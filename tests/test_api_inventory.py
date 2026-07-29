"""The documented API inventory must match the routes that exist.

It had fallen 55 routes behind, which is how a document stops being usable as a reference.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_api_inventory  # noqa: E402


def test_the_api_inventory_matches_the_route_table() -> None:
    current = (ROOT / "docs" / "current-system.md").read_text(encoding="utf-8")

    assert generate_api_inventory.markdown().strip() in current, (
        "The API inventory is stale. Run: python scripts/generate_api_inventory.py"
    )


def test_every_route_appears_in_the_inventory() -> None:
    current = (ROOT / "docs" / "current-system.md").read_text(encoding="utf-8")

    missing = [
        f"{method} {path}"
        for method, path, _purpose in generate_api_inventory.routes()
        if f"| {method} | `{path}` |" not in current
    ]

    assert missing == []
