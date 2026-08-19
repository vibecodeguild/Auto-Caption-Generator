from __future__ import annotations

import subprocess
import sys
from typing import Any


def hidden_subprocess_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def terminate_process_tree(process: Any, *, timeout_sec: float = 8.0) -> None:
    """Stop a child process and any workers it spawned (Chrome render workers, etc.).

    On Windows, ``terminate()`` on the Node HyperFrames parent leaves headless
    Chrome children running; ``taskkill /T`` kills the whole tree.
    """

    if process is None:
        return
    try:
        if process.poll() is not None:
            return
    except Exception:
        return

    pid = getattr(process, "pid", None)
    if sys.platform == "win32" and pid:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=hidden_subprocess_flags(),
            )
        except OSError:
            try:
                process.kill()
            except OSError:
                pass
        return

    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=max(0.5, float(timeout_sec)))
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
    except OSError:
        pass
