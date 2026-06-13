from __future__ import annotations

import shutil
from pathlib import Path

from app.core.settings import resource_root, runtime_root


def find_executable(name: str) -> Path | None:
    candidates = [
        runtime_root() / "tools" / "ffmpeg" / f"{name}.exe",
        resource_root() / "tools" / "ffmpeg" / f"{name}.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    found = shutil.which(name)
    if found:
        return Path(found)

    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
        except ImportError:
            pass
        else:
            packaged = Path(imageio_ffmpeg.get_ffmpeg_exe())
            if packaged.exists():
                return packaged

    return None


def find_ffmpeg() -> Path:
    ffmpeg = find_executable("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg was not found. Please install FFmpeg or place ffmpeg.exe in tools/ffmpeg/.")
    return ffmpeg


def find_ffprobe() -> Path | None:
    return find_executable("ffprobe")
