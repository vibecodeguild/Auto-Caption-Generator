#!/usr/bin/env python3
"""Legacy entrypoint — use scripts/seed_graphics_library.py."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).with_name("seed_graphics_library.py")
    runpy.run_path(str(target), run_name="__main__")
