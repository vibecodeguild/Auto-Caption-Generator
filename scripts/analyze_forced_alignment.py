from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.project_store import load_editor_project
from app.core.splice_generation import generate_splices


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare GPU forced alignment against reviewed IN points.")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--moved", type=int, default=40)
    parser.add_argument("--unchanged", type=int, default=40)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--engine", choices=["whisperx-en", "mms"], default="whisperx-en")
    args = parser.parse_args()

    import torch
    import torchaudio
    if args.engine == "whisperx-en":
        from torchaudio.pipelines import WAV2VEC2_ASR_BASE_960H as bundle
    else:
        from torchaudio.pipelines import MMS_FA as bundle

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this calibration.")

    project, edits = load_editor_project(args.project)
    reviewed = [splice for splice in generate_splices(project, edits).splices if splice.reviewed]
    selected = (
        [splice for splice in reviewed if splice.right_in_adjustment][: args.moved]
        + [splice for splice in reviewed if not splice.right_in_adjustment][: args.unchanged]
    )

    waveform, sample_rate = _load_pcm_wave(args.audio, torch)
    if sample_rate != bundle.sample_rate:
        waveform = torchaudio.functional.resample(waveform, sample_rate, bundle.sample_rate)
        sample_rate = bundle.sample_rate

    started = time.perf_counter()
    model = (bundle.get_model(with_star=False) if args.engine == "mms" else bundle.get_model()).to("cuda").eval()
    tokenizer = bundle.get_tokenizer() if args.engine == "mms" else None
    aligner = bundle.get_aligner() if args.engine == "mms" else None
    dictionary = {character.casefold(): index for index, character in enumerate(bundle.get_labels())}
    loaded_seconds = time.perf_counter() - started

    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for splice in selected:
            right_index = project.word_index(splice.right_word_id)
            context = project.words[right_index : right_index + 8]
            normalized = [_normalize(word.text) for word in context]
            normalized = [word for word in normalized if word]
            clip_start = max(0.0, context[0].start - 1.5)
            clip_end = min(waveform.size(1) / sample_rate, context[-1].end + 1.0)
            clip = waveform[:, round(clip_start * sample_rate) : round(clip_end * sample_rate)]

            predicted_frame = None
            score = None
            try:
                with torch.inference_mode():
                    emission, _ = model(clip.to("cuda"))
                    if args.engine == "mms":
                        first_spans = aligner(emission[0], tokenizer(normalized))[0]
                    else:
                        first_spans = _align_first_word(emission, normalized, dictionary, torchaudio, torch)
                ratio = clip.size(1) / emission.size(1) / sample_rate
                predicted_seconds = clip_start + first_spans[0].start * ratio
                predicted_frame = round(predicted_seconds * project.fps)
                score = round(
                    sum(span.score * len(span) for span in first_spans) / sum(len(span) for span in first_spans),
                    4,
                )
            except (IndexError, RuntimeError, ValueError):
                pass

            rows.append(
                {
                    "anchor_key": splice.anchor_key,
                    "text": context[0].text,
                    "manual_delta": splice.right_in_adjustment,
                    "whisper_frame": splice.right_whisper_in_frame,
                    "final_frame": splice.right_in_frame,
                    "aligned_frame": predicted_frame,
                    "aligned_delta": (
                        predicted_frame - splice.right_whisper_in_frame
                        if predicted_frame is not None
                        else None
                    ),
                    "score": score,
                }
            )

    elapsed_seconds = time.perf_counter() - started
    result = {
                "engine": args.engine,
                "device": torch.cuda.get_device_name(0),
                "model_load_seconds": round(loaded_seconds, 2),
                "total_seconds": round(elapsed_seconds, 2),
                "summary": _summary(rows),
                "rows": rows,
    }
    if args.summary_only:
        result.pop("rows")
    print(json.dumps(result, indent=2))


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if "a" <= character <= "z" or character == "'")


def _align_first_word(emission, words: list[str], dictionary: dict[str, int], torchaudio, torch):
    transcript = "|".join(words)
    target = torch.tensor(
        [[dictionary[character] for character in transcript if character in dictionary]],
        dtype=torch.int32,
        device=emission.device,
    )
    aligned_tokens, scores = torchaudio.functional.forced_align(emission, target, blank=0)
    spans = torchaudio.functional.merge_tokens(aligned_tokens[0], scores[0].exp())
    separator = dictionary["|"]
    return [span for span in spans if span.token != separator][: len(words[0])]


def _load_pcm_wave(path: Path, torch):
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"Expected 16-bit PCM WAV audio, found {sample_width * 8}-bit audio.")
    waveform = torch.frombuffer(bytearray(frames), dtype=torch.int16).to(torch.float32) / 32768.0
    waveform = waveform.reshape(-1, channels).mean(dim=1).unsqueeze(0)
    return waveform, sample_rate


def _summary(rows: list[dict]) -> dict:
    matched = [row for row in rows if row["aligned_frame"] is not None]
    aligned_errors = [abs(row["aligned_frame"] - row["final_frame"]) for row in matched]
    whisper_errors = [abs(row["whisper_frame"] - row["final_frame"]) for row in matched]
    return {
        "cuts": len(rows),
        "matched": len(matched),
        "whisper_mean_absolute_error_frames": round(sum(whisper_errors) / len(whisper_errors), 2) if whisper_errors else None,
        "aligned_mean_absolute_error_frames": round(sum(aligned_errors) / len(aligned_errors), 2) if aligned_errors else None,
        "whisper_within_3_frames": sum(error <= 3 for error in whisper_errors),
        "aligned_within_3_frames": sum(error <= 3 for error in aligned_errors),
        "aligned_within_6_frames": sum(error <= 6 for error in aligned_errors),
    }


if __name__ == "__main__":
    main()
