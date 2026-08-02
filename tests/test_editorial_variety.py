from __future__ import annotations

from pathlib import Path

import pytest

from app.core import graphics_library as gr
from app.core.editorial_beats import validate_editorial_plan
from app.core.editorial_variety import (
    pick_variety_remap,
    validate_variety,
)
from app.core.visual_production import MODULE_IDS


@pytest.fixture(autouse=True)
def _temp_golden_production_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "graphics-library"
    library = tmp_path / "creator-library"
    library.mkdir()
    monkeypatch.setenv("VCG_GRAPHICS_LIBRARY", str(root))
    monkeypatch.setenv("VCG_CREATOR_LIBRARY", str(library))
    gr.create_graphics_library(root)
    gr.ensure_candidate_usages_from_engines(root)
    document = gr.load_graphics_library(root)
    for entry in document["entries"]:
        if entry.get("buildable") or entry.get("id") in MODULE_IDS:
            entry["status"] = "golden"
            entry["buildable"] = True
    gr.save_graphics_library(document, root)


def test_consecutive_same_graphic_fails() -> None:
    items = [
        {"graphicId": "kinetic-word-punctuation"},
        {"graphicId": "kinetic-word-punctuation"},
    ]
    errors = validate_variety(items, id_key="graphicId")
    assert any(e["code"] == "variety-consecutive-graphic" for e in errors)


def test_different_graphics_ok_back_to_back() -> None:
    """Flat model: different graphic ids may follow each other freely."""

    items = [
        {"graphicId": "kinetic-word-punctuation"},
        {"graphicId": "brand-cta-lockup"},
    ]
    errors = validate_variety(items, id_key="graphicId")
    assert not any(e["code"] == "variety-consecutive-graphic" for e in errors)


def test_intentional_series_allows_same_graphic_repeat() -> None:
    items = [
        {
            "graphicId": "kinetic-word-punctuation",
            "intentionalSeriesId": "series-a",
        },
        {
            "graphicId": "kinetic-word-punctuation",
            "intentionalSeriesId": "series-a",
        },
    ]
    errors = validate_variety(items, id_key="graphicId")
    assert not any(e["code"] == "variety-consecutive-graphic" for e in errors)


def test_share_cap_fails() -> None:
    items = [{"graphicId": "kinetic-word-punctuation"} for _ in range(5)]
    items.append({"graphicId": "speaker-side-panel"})
    items.append({"graphicId": "brand-cta-lockup"})
    items.append({"graphicId": "tradeoff-meter"})
    errors = validate_variety(items, id_key="graphicId")
    assert any(e["code"] == "variety-graphic-share" for e in errors)


def test_pick_variety_remap_avoids_last_graphic() -> None:
    chosen = pick_variety_remap(
        preferred_module_id="kinetic-word-punctuation",
        recent_module_ids=["kinetic-word-punctuation"],
        candidates=[
            "kinetic-word-punctuation",
            "brand-cta-lockup",
            "numbered-step-intro",
        ],
    )
    assert chosen != "kinetic-word-punctuation"


def test_plan_variety_rejects_same_graphic_spam() -> None:
    plan = {
        "schemaVersion": 2,
        "mode": "tutorial",
        "fps": {"numerator": 30, "denominator": 1},
        "totalDurationSec": 20.0,
        "beats": [
            {
                "id": f"b{i}",
                "beatType": "punchline",
                "graphicId": "kinetic-word-punctuation",
                "onScreenCopy": f"LINE NUMBER {i}",
                "motionKind": "kinetic-hit",
                "startSec": float(i * 2),
                "endSec": float(i * 2 + 1.5),
            }
            for i in range(8)
        ],
    }
    result = validate_editorial_plan(plan)
    assert result["ok"] is False
    assert any(
        e["code"]
        in {
            "variety-consecutive-graphic",
            "variety-graphic-share",
            "variety-top-two-share",
        }
        for e in result["errors"]
    )


