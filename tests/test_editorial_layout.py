from __future__ import annotations

from app.core.editorial_layout import (
    LAYOUT_IDS,
    free_zones,
    placement_for_module,
    speaker_bounds_for_layout,
    speaker_safety_payload,
)
from app.core.editorial_visual_plan import build_visual_cues_from_beats
from app.core.file_utils import bounds_intersect


def test_eight_layouts_present() -> None:
    assert len(LAYOUT_IDS) == 8
    for layout_id in LAYOUT_IDS:
        # computer-screen-only has null speaker; others must parse.
        bounds = speaker_bounds_for_layout(layout_id)
        if layout_id == "computer-screen-only":
            assert bounds is None
        else:
            assert bounds is not None
            assert bounds["width"] > 0


def test_full_screen_talking_side_panel_remaps() -> None:
    placement = placement_for_module(
        layout_id="full-screen-talking",
        module_id="speaker-side-panel",
    )
    assert placement.remapped_from == "speaker-side-panel"
    assert placement.module_id != "speaker-side-panel"
    assert placement.safe is True
    speaker = speaker_bounds_for_layout("full-screen-talking")
    assert speaker is not None
    if placement.overlay_bounds is not None:
        assert not bounds_intersect(placement.overlay_bounds, speaker)


def test_talking_right_keeps_left_side_panel() -> None:
    placement = placement_for_module(
        layout_id="talking-right",
        module_id="speaker-side-panel",
        preferred_side="left",
    )
    assert placement.module_id == "speaker-side-panel"
    assert placement.side == "left"
    assert placement.safe is True
    assert placement.remapped_from is None


def test_talking_left_prefers_right_free_zone() -> None:
    zones = free_zones("talking-left")
    # Largest free zone should be the right column.
    assert zones[0]["prefer_side"] == "right"
    placement = placement_for_module(
        layout_id="talking-left",
        module_id="kinetic-word-punctuation",
    )
    assert placement.side == "right"
    speaker = speaker_bounds_for_layout("talking-left")
    assert speaker is not None and placement.overlay_bounds is not None
    assert not bounds_intersect(placement.overlay_bounds, speaker)


def test_speaker_safety_payload_shape() -> None:
    placement = placement_for_module(
        layout_id="full-screen-talking",
        module_id="kinetic-word-punctuation",
        preferred_anchor="top",
    )
    payload = speaker_safety_payload(placement, start_sec=1.0, end_sec=4.0)
    assert payload is not None
    assert payload["checked"] is True
    assert payload["maxSpeakerAbsenceSec"] == 0
    assert len(payload["verifiedAtSec"]) == 3
    assert len(set(payload["verifiedAtSec"])) == 3
    assert payload["speakerBounds"] is not None


def test_build_cues_layout_aware_remaps_open() -> None:
    plan = {
        "schemaVersion": 2,
        "mode": "talking-head",
        "fps": {"numerator": 30, "denominator": 1},
        "totalDurationSec": 12.0,
        "beats": [
            {
                "id": "b1",
                "beatType": "context",
                "treatmentId": "speaker-side-panel",
                "onScreenCopy": "WORKING IN POWERPOINT",
                "motionKind": "treatment-enter",
                "startSec": 0.0,
                "endSec": 4.0,
                "layoutId": "full-screen-talking",
            },
            {
                "id": "b2",
                "beatType": "proof",
                "treatmentId": "tradeoff-meter",
                "onScreenCopy": "JUST START",
                "motionKind": "treatment-enter",
                "startSec": 4.0,
                "endSec": 8.0,
                "layoutId": "full-screen-talking",
            },
            {
                "id": "b3",
                "beatType": "aftershock",
                "treatmentId": "source-punch-zoom",
                "onScreenCopy": None,
                "motionKind": "punch-zoom",
                "startSec": 8.0,
                "endSec": 10.0,
                "layoutId": "full-screen-talking",
            },
            {
                "id": "b4",
                "beatType": "punchline",
                "treatmentId": "ui-callout",
                "onScreenCopy": "WAY EASIER",
                "motionKind": "treatment-enter",
                "startSec": 10.0,
                "endSec": 12.0,
                "layoutId": "full-screen-talking",
            },
        ],
    }
    result = build_visual_cues_from_beats(plan)
    assert result["summary"]["layoutAware"] is True
    # Side panel must not stay as a full-height panel on full-screen talking.
    assert result["cues"][0]["moduleId"] != "speaker-side-panel"
    # Realized modules should rotate — not one shell for every beat.
    graphic_modules = [
        c["moduleId"]
        for c in result["cues"]
        if c["moduleId"] not in {"source-punch-zoom", "source-punch-zoom"}
    ]
    assert len(set(graphic_modules)) >= 2
    safety = result["cues"][0]["parameters"].get("speakerSafety")
    assert safety is not None
    assert safety["checked"] is True