import base64
from pathlib import Path

from app.core import windows_dialog


def test_choose_video_uses_standalone_sta_windows_dialog(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return windows_dialog.subprocess.CompletedProcess(command, 0, stdout="C:\\Videos\\clip.mp4\r\n", stderr="")

    monkeypatch.setattr(windows_dialog.subprocess, "run", fake_run)

    selected = windows_dialog.choose_video_file()

    assert selected == Path("C:\\Videos\\clip.mp4")
    assert captured["command"][:4] == [
        "powershell.exe",
        "-NoProfile",
        "-STA",
        "-EncodedCommand",
    ]
    script = base64.b64decode(captured["command"][4]).decode("utf-16-le")
    assert "CenterScreen" in script
    assert "-32000" not in script
    assert captured["kwargs"]["timeout"] == 300


def test_choose_output_folder_uses_modern_explorer_dialog(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return windows_dialog.subprocess.CompletedProcess(command, 0, stdout="C:\\Exports\r\n", stderr="")

    monkeypatch.setattr(windows_dialog.subprocess, "run", fake_run)

    selected = windows_dialog.choose_output_folder()

    assert selected == Path("C:\\Exports")
    script = base64.b64decode(captured["command"][4]).decode("utf-16-le")
    assert "FOS_PICKFOLDERS" in script
    assert "IFileOpenDialog" in script
    assert "FolderBrowserDialog" not in script


def test_picker_timeout_is_reported_as_actionable_error(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise windows_dialog.subprocess.TimeoutExpired(args[0], timeout=300)

    monkeypatch.setattr(windows_dialog.subprocess, "run", fake_run)

    try:
        windows_dialog.choose_video_file()
    except RuntimeError as exc:
        assert "started but did not return within 300 seconds" in str(exc)
    else:
        raise AssertionError("Expected the picker timeout to be reported")
