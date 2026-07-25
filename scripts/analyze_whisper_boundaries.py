from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.project_store import load_editor_project
from app.core.splice_generation import generate_splices
from app.core.transcriber import configure_cuda_dll_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Large v3 VAD padding against reviewed IN points.")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--moved", type=int, default=10)
    parser.add_argument("--unchanged", type=int, default=5)
    parser.add_argument("--pads", type=int, nargs="+", default=[400, 200, 100, 0])
    parser.add_argument("--model", default="large-v3")
    args = parser.parse_args()

    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    configure_cuda_dll_paths()
    project, edits = load_editor_project(args.project)
    reviewed = [splice for splice in generate_splices(project, edits).splices if splice.reviewed]
    selected = (
        [splice for splice in reviewed if splice.right_in_adjustment][: args.moved]
        + [splice for splice in reviewed if not splice.right_in_adjustment][: args.unchanged]
    )
    audio = decode_audio(str(args.audio), sampling_rate=16000)
    model = WhisperModel(args.model, device="cuda", compute_type="float16")
    results = []

    for pad_ms in args.pads:
        rows = []
        for splice in selected:
            right_index = project.word_index(splice.right_word_id)
            context = project.words[right_index : right_index + 4]
            clip_start = max(0.0, context[0].start - 2.0)
            clip_end = min(len(audio) / 16000.0, context[-1].end + 2.0)
            clip = audio[round(clip_start * 16000) : round(clip_end * 16000)]
            segments, _ = model.transcribe(
                clip,
                language="en",
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"speech_pad_ms": pad_ms},
            )
            recognized = [word for segment in segments for word in (segment.words or [])]
            matched = _best_match(recognized, [word.text for word in context])
            predicted_frame = (
                round((clip_start + matched.start) * project.fps)
                if matched is not None
                else None
            )
            rows.append(
                {
                    "anchor_key": splice.anchor_key,
                    "manual_delta": splice.right_in_adjustment,
                    "whisper_frame": splice.right_whisper_in_frame,
                    "final_frame": splice.right_in_frame,
                    "predicted_frame": predicted_frame,
                    "predicted_delta": (
                        predicted_frame - splice.right_whisper_in_frame
                        if predicted_frame is not None
                        else None
                    ),
                }
            )
        results.append({"speech_pad_ms": pad_ms, "summary": _summary(rows), "rows": rows})

    print(json.dumps({"model": args.model, "compute": "cuda/float16", "results": results}, indent=2))


def _best_match(recognized, expected: list[str]):
    normalized_expected = [_normalize(word) for word in expected]
    best = None
    best_score = 0
    for index, word in enumerate(recognized):
        if _normalize(word.word) != normalized_expected[0]:
            continue
        score = 0
        for offset, expected_word in enumerate(normalized_expected):
            if index + offset >= len(recognized) or _normalize(recognized[index + offset].word) != expected_word:
                break
            score += 1
        if score > best_score:
            best = word
            best_score = score
    return best


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum() or character == "'")


def _summary(rows: list[dict]) -> dict:
    matched = [row for row in rows if row["predicted_frame"] is not None]
    errors = [abs(row["predicted_frame"] - row["final_frame"]) for row in matched]
    return {
        "cuts": len(rows),
        "matched": len(matched),
        "mean_absolute_error_frames": round(sum(errors) / len(errors), 2) if errors else None,
        "within_3_frames": sum(error <= 3 for error in errors),
        "within_6_frames": sum(error <= 6 for error in errors),
    }


if __name__ == "__main__":
    main()
