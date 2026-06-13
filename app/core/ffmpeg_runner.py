from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.ffmpeg_locator import find_ffmpeg


def _run(command: list[str], friendly_error: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if details:
            raise RuntimeError(f"{friendly_error}\n\nFFmpeg details:\n{details[-1200:]}")
        raise RuntimeError(friendly_error)


def extract_audio(input_video_path: Path, output_audio_path: Path) -> Path:
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            str(find_ffmpeg()),
            "-y",
            "-i",
            str(input_video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_audio_path),
        ],
        "FFmpeg could not extract audio from this video.",
    )
    return output_audio_path


def _filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def burn_subtitles(
    input_video_path: Path,
    ass_path: Path,
    output_video_path: Path,
    fonts_dir: Path,
) -> Path:
    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    filter_value = f"ass='{_filter_path(ass_path)}':fontsdir='{_filter_path(fonts_dir)}'"
    command_base = [
        str(find_ffmpeg()),
        "-y",
        "-i",
        str(input_video_path),
        "-vf",
        filter_value,
    ]

    try:
        _run(
            command_base + ["-c:a", "copy", str(output_video_path)],
            "FFmpeg could not render the final video.",
        )
    except RuntimeError:
        _run(
            command_base
            + [
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "medium",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(output_video_path),
            ],
            "FFmpeg could not render the final video. Check that the output file is not already open and that you have permission to write to the output folder.",
        )

    return output_video_path
