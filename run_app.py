from __future__ import annotations

import traceback
from pathlib import Path


def _write_startup_error() -> None:
    log_path = Path(__file__).resolve().parent / "app" / "temp" / "startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(traceback.format_exc(), encoding="utf-8")


if __name__ == "__main__":
    try:
        from app.main_window import main

        main()
    except Exception:
        _write_startup_error()
        raise
