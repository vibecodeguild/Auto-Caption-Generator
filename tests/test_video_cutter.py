from __future__ import annotations

from pathlib import Path

from app.core.video_cutter import (
    build_cut_filter,
    build_cut_command,
    frame_intervals_to_seconds,
)


def test_converts_inclusive_frame_intervals_to_ffmpeg_seconds() -> None:
    assert frame_intervals_to_seconds([(0, 29), (60, 89)], fps=30.0) == [
        (0.0, 1.0),
        (2.0, 3.0),
    ]


def test_builds_trim_concat_filter_for_multiple_ranges() -> None:
    filter_complex = build_cut_filter([(0.0, 1.0), (2.0, 3.0)])

    assert "[0:v]trim=start=0.000000:end=1.000000,setpts=PTS-STARTPTS[v0]" in filter_complex
    assert "[0:a]atrim=start=2.000000:end=3.000000,asetpts=PTS-STARTPTS[a1]" in filter_complex
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]" in filter_complex


def test_builds_ffmpeg_command_with_quality_settings() -> None:
    command = build_cut_command(
        ffmpeg=Path("ffmpeg.exe"),
        input_video=Path("input.mp4"),
        output_video=Path("output.mp4"),
        intervals=[(0.0, 1.0)],
        crf=20,
        preset="slow",
    )

    assert command[:4] == ["ffmpeg.exe", "-y", "-i", "input.mp4"]
    assert "-filter_complex" in command
    assert command[command.index("-c:v") : command.index("-c:v") + 6] == [
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-preset",
        "slow",
    ]
    assert command[command.index("-c:a") : command.index("-c:a") + 4] == ["-c:a", "aac", "-b:a", "192k"]
    assert command[command.index("-movflags") : command.index("-movflags") + 2] == ["-movflags", "+faststart"]
    assert command[-1] == "output.mp4"
