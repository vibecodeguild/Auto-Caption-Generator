from __future__ import annotations

from scripts import dev_web


def test_start_process_inherits_terminal_streams(monkeypatch) -> None:
    captured: dict[str, object] = {}
    process = object()

    def fake_popen(command: list[str], **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(dev_web.subprocess, "Popen", fake_popen)

    managed = dev_web._start_process("api", ["python", "-m", "uvicorn"])

    assert managed.name == "api"
    assert managed.process is process
    assert captured == {
        "command": ["python", "-m", "uvicorn"],
        "kwargs": {"cwd": dev_web.ROOT},
    }
