from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core import audio_normalizer
from app.core.audio_normalizer import (
    LoudnessMeasurement,
    analyze_audio,
    create_audio_preview,
    find_loudness_hotspots,
    normalize_video_audio,
    parse_momentary_loudness,
    parse_loudnorm_measurement,
)


LOUDNORM_OUTPUT = """
[Parsed_loudnorm_0 @ 000001] {
    "input_i" : "-21.45",
    "input_tp" : "-3.12",
    "input_lra" : "8.30",
    "input_thresh" : "-31.20",
    "output_i" : "-13.95",
    "output_tp" : "-1.50",
    "output_lra" : "6.90",
    "output_thresh" : "-24.10",
    "normalization_type" : "dynamic",
    "target_offset" : "-0.05"
}
"""


def test_parses_loudnorm_json_measurement() -> None:
    measurement = parse_loudnorm_measurement(LOUDNORM_OUTPUT)

    assert measurement.input_i == -21.45
    assert measurement.input_tp == -3.12
    assert measurement.input_lra == 8.3
    assert measurement.target_offset == -0.05


def test_gentle_analysis_levels_audio_before_measuring(monkeypatch) -> None:
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        return SimpleNamespace(returncode=0, stderr=LOUDNORM_OUTPUT, stdout="")

    monkeypatch.setattr(audio_normalizer.subprocess, "run", fake_run)

    measurement = analyze_audio(
        ffmpeg=Path("ffmpeg.exe"),
        input_video=Path("source.mp4"),
        preset_id="gentle",
    )

    audio_filter = captured[captured.index("-af") + 1]
    assert audio_filter.startswith("dynaudnorm=f=500:g=31:p=0.90:m=4,loudnorm=")
    assert "I=-14.0" in audio_filter
    assert measurement.input_i == -21.45


def test_second_pass_preserves_video_and_encodes_normalized_aac(monkeypatch, tmp_path: Path) -> None:
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(audio_normalizer.subprocess, "run", fake_run)
    output = tmp_path / "normalized.mp4"

    normalize_video_audio(
        ffmpeg=Path("ffmpeg.exe"),
        input_video=Path("source.mp4"),
        output_video=output,
        preset_id="normalize",
        measurement=LoudnessMeasurement(
            input_i=-21.45,
            input_tp=-3.12,
            input_lra=8.3,
            input_thresh=-31.2,
            target_offset=-0.05,
        ),
    )

    assert captured[captured.index("-c:v") : captured.index("-c:v") + 2] == ["-c:v", "copy"]
    assert captured[captured.index("-c:a") : captured.index("-c:a") + 4] == ["-c:a", "aac", "-b:a", "256k"]
    assert captured[captured.index("-ar") : captured.index("-ar") + 2] == ["-ar", "48000"]
    audio_filter = captured[captured.index("-af") + 1]
    assert audio_filter.startswith("loudnorm=I=-14.0:LRA=7.0:TP=-1.5")
    assert "measured_I=-21.45" in audio_filter
    assert captured[-1] == str(output)


def test_preview_creates_matching_original_and_corrected_clips(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(audio_normalizer.subprocess, "run", fake_run)
    original = tmp_path / "original.mp4"
    corrected = tmp_path / "corrected.mp4"

    create_audio_preview(
        ffmpeg=Path("ffmpeg.exe"),
        input_video=Path("source.mp4"),
        original_preview=original,
        corrected_preview=corrected,
        start_seconds=42.5,
        duration_seconds=20,
        preset_id="gentle",
        measurement=LoudnessMeasurement(
            input_i=-20.0,
            input_tp=-3.0,
            input_lra=8.0,
            input_thresh=-30.0,
            target_offset=0.1,
        ),
    )

    assert len(commands) == 2
    for command in commands:
        assert command[command.index("-ss") : command.index("-ss") + 2] == ["-ss", "42.500"]
        assert command[command.index("-t") : command.index("-t") + 2] == ["-t", "20.000"]
        assert command[command.index("-c:v") : command.index("-c:v") + 2] == ["-c:v", "libx264"]
    assert "-af" not in commands[0]
    assert commands[0][-1] == str(original)
    assert commands[1][commands[1].index("-af") + 1].startswith("dynaudnorm=")
    assert "measured_I=-20.0" in commands[1][commands[1].index("-af") + 1]
    assert commands[1][-1] == str(corrected)


def test_parses_momentary_loudness_timeline() -> None:
    output = """
frame:0 pts:0 pts_time:0
lavfi.r128.M=-120.691
frame:1 pts:4800 pts_time:0.1
lavfi.r128.M=-31.250
"""

    assert parse_momentary_loudness(output) == [(0.0, -120.691), (0.1, -31.25)]


def test_hotspots_ignore_silence_and_select_quiet_and_loud_speech() -> None:
    samples: list[tuple[float, float]] = []
    for index in range(160):
        time = index / 10
        if time < 2 or 7 <= time < 9 or time >= 14:
            loudness = -25.0
        elif time < 7:
            loudness = -39.0
        else:
            loudness = -16.0
        samples.append((time, loudness))

    hotspots = find_loudness_hotspots(
        samples,
        preview_duration=4,
        focus_duration=2,
        speech_ranges=[(2.0, 7.0), (9.0, 14.0)],
    )

    assert 2 <= hotspots.quietest_speech.focus_seconds < 7
    assert 9 <= hotspots.loudest.focus_seconds < 14
    assert hotspots.quietest_speech.loudness_lufs < hotspots.loudest.loudness_lufs
