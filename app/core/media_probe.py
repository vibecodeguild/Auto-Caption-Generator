from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core.ffmpeg_locator import find_ffprobe


def probe_video_size(input_video_path: Path) -> tuple[int, int]:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        return 1080, 1920

    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(input_video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 1080, 1920

    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return 1080, 1920


def ass_play_resolution_for_video(input_video_path: Path) -> tuple[int, int, int]:
    width, height = probe_video_size(input_video_path)
    if width >= height:
        return 1920, 1080, 120
    return 1080, 1920, 220
