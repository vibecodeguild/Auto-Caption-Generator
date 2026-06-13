from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from app.core.process_utils import hidden_subprocess_flags


ProgressCallback = Callable[[float], None]


def frame_intervals_to_seconds(intervals: list[tuple[int, int]], fps: float) -> list[tuple[float, float]]:
    if fps <= 0:
        raise ValueError("FPS must be greater than zero.")
    return [(round(start / fps, 6), round((end + 1) / fps, 6)) for start, end in intervals if end >= start]


def build_cut_filter(intervals: list[tuple[float, float]]) -> str:
    if not intervals:
        raise ValueError("At least one cut interval is required.")

    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, (start, end) in enumerate(intervals):
        if end <= start:
            raise ValueError(f"Invalid cut interval: {start}..{end}")
        filters.append(f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]")
        filters.append(f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]")
        concat_inputs.extend([f"[v{index}]", f"[a{index}]"])
    filters.append(f"{''.join(concat_inputs)}concat=n={len(intervals)}:v=1:a=1[outv][outa]")
    return ";".join(filters)


def build_cut_command(
    *,
    ffmpeg: Path,
    input_video: Path,
    output_video: Path,
    intervals: list[tuple[float, float]],
    crf: int = 18,
    preset: str = "veryfast",
) -> list[str]:
    return [
        str(ffmpeg),
        "-y",
        "-i",
        str(input_video),
        "-filter_complex",
        build_cut_filter(intervals),
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_video),
    ]


def run_cut(
    *,
    ffmpeg: Path,
    input_video: Path,
    output_video: Path,
    intervals: list[tuple[float, float]],
    crf: int = 18,
    preset: str = "veryfast",
    progress_callback: ProgressCallback | None = None,
) -> None:
    total_duration = sum(end - start for start, end in intervals)
    command = build_cut_command(
        ffmpeg=ffmpeg,
        input_video=input_video,
        output_video=output_video,
        intervals=intervals,
        crf=crf,
        preset=preset,
    )
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            creationflags=hidden_subprocess_flags(),
        )
        assert process.stdout is not None
        for line in process.stdout:
            if progress_callback and line.startswith("out_time_ms="):
                try:
                    seconds = int(line.split("=", 1)[1].strip()) / 1_000_000
                except ValueError:
                    continue
                progress_callback(min(1.0, seconds / total_duration) if total_duration else 0.0)
        process.wait()
        if process.returncode != 0:
            stderr_file.seek(0)
            stderr = stderr_file.read()
            raise RuntimeError(stderr.strip() or f"ffmpeg exited {process.returncode}")
