from pathlib import Path

from app.core import ffmpeg_runner


def test_burn_subtitles_forces_windows_compatible_h264(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(ffmpeg_runner, "find_ffmpeg", lambda: Path("ffmpeg.exe"))
    monkeypatch.setattr(
        ffmpeg_runner,
        "_run",
        lambda command, friendly_error: commands.append(command),
    )

    ffmpeg_runner.burn_subtitles(
        tmp_path / "source.mp4",
        tmp_path / "captions.ass",
        tmp_path / "captioned.mp4",
        tmp_path / "fonts",
    )

    command = commands[0]
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-profile:v") + 1] == "high"
    assert command[command.index("-movflags") + 1] == "+faststart"
