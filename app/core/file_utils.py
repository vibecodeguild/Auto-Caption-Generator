from __future__ import annotations

from pathlib import Path

from app.core.settings import SUPPORTED_VIDEO_EXTENSIONS


def validate_input_video(path: Path) -> None:
    if not path.exists():
        raise RuntimeError("Please choose a video file first.")
    if path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        raise RuntimeError("Please choose a supported video file: MP4, MOV, MKV, AVI, or WEBM.")


def ensure_output_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    probe = path.parent / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("The output folder is not writable.") from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
