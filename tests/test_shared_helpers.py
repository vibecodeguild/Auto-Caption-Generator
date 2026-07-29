"""Keep the helpers that drifted defined exactly once.

Four modules carried their own copy of the same path, hash, slug and bounds helpers, and two
modules carried independent implementations of the speaker-safety rules. A safety check that
exists twice can disagree with itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core import file_utils, story_assets, visual_production


ROOT = Path(__file__).resolve().parents[1]
SOURCES = [*sorted((ROOT / "app").rglob("*.py")), *sorted((ROOT / "scripts").glob("*.py"))]
SHARED = ("sha256_file", "is_within", "_is_within", "_inside", "slug", "_slug", "bounds_intersect")


def _definitions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]


@pytest.mark.parametrize("name", SHARED)
def test_each_shared_helper_is_defined_once(name: str) -> None:
    homes = [
        path.relative_to(ROOT).as_posix()
        for path in SOURCES
        if "temp" not in path.parts and name in _definitions(path)
    ]

    assert homes in ([], ["app/core/file_utils.py"]), f"{name} is defined in {homes}"


def test_the_shared_aliases_are_the_shared_functions() -> None:
    assert visual_production.sha256_file is file_utils.sha256_file
    assert story_assets.sha256_file is file_utils.sha256_file
    assert visual_production._is_within is file_utils.is_within
    assert story_assets._inside is file_utils.is_within
    assert story_assets.slug is file_utils.slug


def test_the_speaker_safety_rules_have_one_implementation() -> None:
    """story_assets raises the first issue; the gate lists them all. Same rules either way."""
    unsafe = {
        "checked": True,
        "mode": "left-container",
        "maxSpeakerAbsenceSec": 0,
        "speakerBounds": dict(visual_production.measured_speaker_bounds("talking-left")),
        "overlayOcclusionBounds": [{"x": 0.0, "y": 0.1, "width": 0.4, "height": 0.5}],
        "verifiedAtSec": [4, 6, 9],
    }
    suggestion = {"id": "graphic-1", "startSec": 4, "endSec": 9, "speakerSafety": unsafe, "scenePacket": {"layout": "talking-left"}}

    gate_issues = visual_production.speaker_safety_issues(
        "Graphic suggestion graphic-1", unsafe, "talking-left", start_sec=4, end_sec=9
    )
    with pytest.raises(ValueError) as raised:
        story_assets._validate_speaker_safety(suggestion)

    assert gate_issues, "the overlay covers the speaker, so the gate must object"
    assert str(raised.value) == gate_issues[0]
