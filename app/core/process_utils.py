from __future__ import annotations

import subprocess
import sys


def hidden_subprocess_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
