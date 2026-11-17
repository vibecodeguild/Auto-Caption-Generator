"""Application-level Parakeet adapter; Whisper routing lives in transcriber.py."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Lock, Timer

from app.core.settings import WordTimestamp, project_root

MODEL_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
_inference_lock = Lock()


class TranscribedWords(list):
    def __init__(self, words=(), *, metadata=None):
        super().__init__(words)
        self.metadata = metadata or {}


def words_from_tokens(tokens, timestamps, durations, *, offset=0.0, duration=float("inf")):
    """Approved last-lexical-token + 80 ms estimates, capped at the next word.

    Native TDT durations can include long silence and remain raw evidence only.
    """
    if len(tokens) != len(timestamps) or len(tokens) != len(durations):
        raise ValueError("Parakeet token, timestamp and duration counts differ.")
    words = []
    text = ""
    spoken = False
    start = end = previous = 0.0
    for token, timestamp, length in zip(tokens, timestamps, durations):
        if not isinstance(token, str) or not all(math.isfinite(v) for v in (timestamp, length)):
            raise ValueError("Invalid Parakeet token timing.")
        if timestamp < previous or timestamp < 0 or length < 0:
            raise ValueError("Unordered Parakeet token timing.")
        previous = timestamp
        piece = token.replace("▁", " ")
        lexical = any(character.isalnum() for character in piece)
        if piece.startswith(" ") and lexical and spoken:
            words.append(WordTimestamp(text.strip(), start, end))
            text = ""
            spoken = False
        if lexical:
            if not spoken:
                start = offset + timestamp
            # Punctuation is preserved in text but has no acoustic duration.
            # Its emission can be delayed across a long silence.
            end = min(duration, offset + timestamp + .08)
            spoken = True
        text += piece
    if spoken:
        words.append(WordTimestamp(text.strip(), start, end))
    result = []
    for index, word in enumerate(words):
        end = min(word.end, words[index + 1].start if index + 1 < len(words) else duration)
        if end <= word.start:
            raise ValueError("Parakeet word timing has no positive interval after next-word capping.")
        # Preserve the application's positive word-interval invariant. GPU
        # timing failures retry on CPU; no word is silently removed or stretched.
        result.append(WordTimestamp(word.text, word.start, end))
    return result


def reconcile_chunks(previous, incoming, seam):
    """Join overlapping decodes using matching words AND matching source times.

    Text alone is never a duplicate test: repeated speech at different times
    remains repeated. Prefer the alignment with the closest timing agreement.
    If neither a shared anchor nor a clean temporal gap exists, reject the seam
    rather than silently losing speech or inventing timestamps.
    """
    if not previous:
        return list(incoming)
    if not incoming:
        return previous
    candidates = []
    for i, left in enumerate(previous):
        if abs(left.start - seam) > 2:
            continue
        for j, right in enumerate(incoming):
            if abs(right.start - seam) > 2:
                continue
            if i < 1 or j < 1:
                continue
            pairs = [(previous[i - 1], incoming[j - 1]), (left, right)]
            if all(a.text.casefold() == b.text.casefold() and abs(a.start - b.start) <= .24
                   and abs(a.end - b.end) <= .24 for a, b in pairs):
                difference = sum(abs(a.start - b.start) + abs(a.end - b.end) for a, b in pairs)
                candidates.append((difference, abs(left.end - seam), i, j))
    if candidates:
        _, _, i, j = min(candidates)
        merged = [*previous[:i + 1], *incoming[j + 1:]]
    else:
        left = [word for word in previous if (word.start + word.end) / 2 < seam]
        right = [word for word in incoming if (word.start + word.end) / 2 >= seam]
        # A clean gap must be present in both decodes to choose a seam without
        # a linguistic anchor. Never splice through a disagreeing word.
        if any(word.start < seam < word.end for word in [*previous, *incoming]):
            raise ValueError("Parakeet could not reconcile speech at a chunk boundary. Previous transcript was preserved.")
        merged = [*left, *right]
    if any(a.end > b.start for a, b in zip(merged, merged[1:])):
        raise ValueError("Parakeet chunk boundary timing overlaps. Previous transcript was preserved.")
    return merged


def transcribe_parakeet(audio_path: Path, compute_mode: str, progress_callback=None):
    root = project_root()
    python = root / ".venv-parakeet" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    model = Path(os.environ.get("VCG_PARAKEET_MODEL", root / "models" / MODEL_NAME))
    if not python.is_file() or not (model / "tokens.txt").is_file():
        raise RuntimeError("Parakeet is not installed. Run scripts/setup_parakeet.ps1, or explicitly choose a Whisper model.")
    providers = ["cuda", "cpu"] if compute_mode == "NVIDIA GPU" else ["cpu"]
    reason = None
    with _inference_lock:
        for provider in providers:
            words = []
            metadata = {"engine": "parakeet", "model_id": "parakeet-tdt-0.6b-v3", "device": provider,
                        "fallback_reason": reason, "chunks": [],
                        "word_end_method": "last_lexical_token_plus_80ms_capped"}
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as diagnostics:
                process = subprocess.Popen(
                    [str(python), str(root / "app/core/parakeet_worker.py"), str(model), str(audio_path), "--provider", provider],
                    stdout=subprocess.PIPE, stderr=diagnostics, text=True, encoding="utf-8",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                complete = False
                validation_failure = None
                timer = Timer(600, process.kill)
                timer.start()
                try:
                    for line in process.stdout:
                        timer.cancel()
                        timer = Timer(600, process.kill)
                        timer.start()
                        event = json.loads(line)
                        if event["event"] == "device":
                            metadata.update({key: value for key, value in event.items() if key != "event"})
                        elif event["event"] == "chunk":
                            assembled = words_from_tokens(event["tokens"], event["timestamps"], event["durations"],
                                                          offset=event["offset"], duration=event["duration"])
                            words = reconcile_chunks(words, assembled, event["core_start"])
                            metadata["chunks"].append(event)
                            if progress_callback:
                                progress_callback(len(words), event["core_end"], event["duration"])
                        elif event["event"] == "complete":
                            metadata.update({"decode_seconds": event["decode_seconds"]})
                            complete = True
                    returncode = process.wait()
                except ValueError as exc:
                    # Invalid GPU timing is an inference failure too. Retry the
                    # complete recording on CPU; never drop spoken words or
                    # invent repair timing beyond the approved estimate.
                    validation_failure = str(exc)
                    process.kill()
                    returncode = process.wait()
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
                finally:
                    timer.cancel()
                    process.stdout.close()
                diagnostics.seek(0)
                details = diagnostics.read()
            if returncode == 0 and complete and not (provider == "cuda" and "fallback to cpu" in details.lower()):
                if not words:
                    raise RuntimeError("No speech was detected in this video.")
                return TranscribedWords(words, metadata=metadata)
            reason = validation_failure or details.strip()[-2500:] or f"Parakeet worker exited with code {returncode}."
        raise RuntimeError(f"Parakeet transcription failed on CPU. {reason}")


def transcription_notice(words) -> str:
    metadata = getattr(words, "metadata", {})
    if not metadata:
        return ""
    notice = f"{metadata.get('engine', 'Transcription')} · {metadata.get('device', 'unknown device').upper()}"
    if metadata.get("fallback_reason"):
        reason = metadata["fallback_reason"].splitlines()[-1][:300]
        notice += f" · GPU unavailable; CPU fallback: {reason}"
    return notice
