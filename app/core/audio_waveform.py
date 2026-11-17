"""Transcription-independent PCM peak cache and bounded visible-window queries."""
from __future__ import annotations

from array import array
import hashlib
import json
import math
from pathlib import Path
import tempfile
from threading import Lock
import wave

from app.core.ffmpeg_runner import extract_audio

WINDOW_SECONDS = 0.01
_lock = Lock()


def source_identity(source: Path) -> dict:
    stat = source.stat()
    return {"path": str(source.resolve()), "size": stat.st_size, "mtimeNs": stat.st_mtime_ns}


def waveform_window(source: Path, cache_dir: Path, start: float, end: float) -> dict:
    """Return at most eight seconds; never couple peak generation to ASR."""
    if not all(math.isfinite(value) for value in (start, end)) or start < 0 or end <= start or end - start > 8.01:
        raise ValueError("Waveform context must be a positive interval of at most eight seconds.")
    identity = source_identity(source)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{key}.json"
    with _lock:
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
        else:
            with tempfile.TemporaryDirectory(dir=cache_dir) as folder:
                audio = extract_audio(source, Path(folder) / "waveform.wav")
                data = peaks_from_wav(audio)
            if source_identity(source) != identity:
                raise ValueError("Source changed during waveform generation. Try again.")
            data["source"] = identity
            staging = target.with_suffix(".tmp")
            staging.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            staging.replace(target)
    first = int(start / WINDOW_SECONDS)
    last = min(len(data["peaks"]), int(end / WINDOW_SECONDS) + 1)
    return {"sourceKey": key, "startSeconds": first * WINDOW_SECONDS,
            "windowSeconds": WINDOW_SECONDS, "durationSeconds": data["durationSeconds"],
            "peaks": data["peaks"][first:last]}


def peaks_from_wav(path: Path) -> dict:
    peaks = []
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("Waveform extraction requires mono PCM16 audio.")
        rate = audio.getframerate()
        duration = audio.getnframes() / rate
        window_size = max(1, round(rate * WINDOW_SECONDS))
        while raw := audio.readframes(window_size):
            samples = array("h")
            samples.frombytes(raw)
            peaks.append([round(min(samples) / 32768, 5), round(max(samples) / 32768, 5)])
    return {"windowSeconds": WINDOW_SECONDS, "durationSeconds": duration, "peaks": peaks}
