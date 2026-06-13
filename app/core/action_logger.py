from __future__ import annotations

from datetime import datetime
from pathlib import Path


class ActionLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str, details: str | None = None) -> None:
        self._write("INFO", message, details)

    def error(self, message: str, details: str | None = None) -> None:
        self._write("ERROR", message, details)

    def _write(self, level: str, message: str, details: str | None) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        line = f"{timestamp} [{level}] {message}\n"
        if details:
            line += f"{details.rstrip()}\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
