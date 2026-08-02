from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.core import graphics_library as gr
from app.core.editorial_beats import (
    BEAT_TYPES,
    MAX_MOTION_GAP_SEC,
    SCHEMA_VERSION,
    SUPERSEDED_BEAT_TYPES,
    copy_lacks_substance,
    production_graphic_ids,
    validate_editorial_plan,
)
from app.core.visual_production import MODULE_IDS


@pytest.fixture(autouse=True)
def _temp_golden_production_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Editorial validation reads GR production set — provide goldens for tests."""

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
    return root


def _good_plan() -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "episodeId": "test",
        "mode": "tutorial",
        "fps": {"numerator": 30, "denominator": 1},
        "totalDurationSec": 20.0,
        "beats": [
            {
                "id": "b1",
                "beatType": "hook",
                "graphicId": "kinetic-word-punctuation",
                "onScreenCopy": "SOUL-CRUSHING CORPORATE JOBS",
                "motionKind": "treatment-enter",
                "startSec": 0.0,
                "endSec": 4.0,
            },
            {
                "id": "b2",
                "beatType": "context",
                "graphicId": "speaker-side-panel",
                "onScreenCopy": "WORKING IN POWERPOINT",
                "motionKind": "treatment-enter",
                "startSec": 4.0,
                "endSec": 8.0,
            },
            {
                "id": "b3",
                "beatType": "punchline",
                "graphicId": "source-punch-zoom",
                "onScreenCopy": None,
                "motionKind": "punch-zoom",
                "startSec": 8.0,
                "endSec": 10.0,
            },
            {
                "id": "b4",
                "beatType": "list",
                "graphicId": "problem-card-triptych",
                "onScreenCopy": "WHAT YOU GET",
                "motionKind": "internal-reveal",
                "startSec": 10.0,
                "endSec": 20.0,
                "listRows": [
                    {"id": "r1", "text": "FASTER DECKS", "startSec": 10.5},
                    {"id": "r2", "text": "CLEANER SLIDES", "startSec": 14.0},
                    {"id": "r3", "text": "LESS BUSYWORK", "startSec": 17.5},
                ],
            },
        ],
    }


def test_good_plan_passes() -> None:
    result = validate_editorial_plan(_good_plan())
    assert result["ok"] is True
    assert result["errorCount"] == 0


def test_function_word_copy_fails() -> None:
    plan = _good_plan()
    plan["beats"][0]["onScreenCopy"] = "and"
    result = validate_editorial_plan(plan)
    assert result["ok"] is False
    assert any(error["code"] == "weak-copy" for error in result["errors"])


def test_copy_helpers() -> None:
    assert copy_lacks_substance("if")
    assert copy_lacks_substance("to the")
    assert not copy_lacks_substance("SOUL-CRUSHING CORPORATE JOBS")
    assert not copy_lacks_substance("10 WAYS")


def test_unknown_graphic_fails() -> None:
    plan = _good_plan()
    plan["beats"][0]["graphicId"] = "vibe-white-card"
    result = validate_editorial_plan(plan)
    assert result["ok"] is False
    assert any(error["code"] == "unknown-graphic" for error in result["errors"])


def test_empty_production_set_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty_root = tmp_path / "empty-gr"
    monkeypatch.setenv("VCG_GRAPHICS_LIBRARY", str(empty_root))
    gr.create_graphics_library(empty_root)
    # Candidates only — nothing golden.
    gr.ensure_candidate_usages_from_engines(empty_root)
    result = validate_editorial_plan(_good_plan())
    assert result["ok"] is False
    assert any(error["code"] == "empty-production-set" for error in result["errors"])
    assert result["productionSet"]["empty"] is True


def test_motion_gap_fails() -> None:
    plan = _good_plan()
    # Remove middle beats so 0 -> 10 is a 10s gap if only first and last remain wrong —
    # instead set second beat late.
    plan["beats"] = [
        plan["beats"][0],
        {
            "id": "late",
            "beatType": "cta",
            "graphicId": "brand-cta-lockup",
            "onScreenCopy": "INSTALL THE ADD-IN",
            "motionKind": "treatment-enter",
            "startSec": 12.0,
            "endSec": 20.0,
        },
    ]
    result = validate_editorial_plan(plan)
    assert result["ok"] is False
    assert any(error["code"] == "motion-gap" for error in result["errors"])
    assert MAX_MOTION_GAP_SEC == 5.0


def test_superseded_beat_types_rejected() -> None:
    plan = _good_plan()
    plan["beats"][0]["beatType"] = "source-led-motion"
    result = validate_editorial_plan(plan)
    assert result["ok"] is False
    assert any(error["code"] == "schema" for error in result["errors"])

    plan2 = _good_plan()
    plan2["beats"][0]["beatType"] = "section-label"
    result2 = validate_editorial_plan(plan2)
    assert result2["ok"] is False


def test_schema_version_and_universe() -> None:
    assert SCHEMA_VERSION == 2
    assert len(BEAT_TYPES) == 13
    assert SUPERSEDED_BEAT_TYPES.isdisjoint(BEAT_TYPES)
    plan = _good_plan()
    plan["schemaVersion"] = 1
    result = validate_editorial_plan(plan)
    assert result["ok"] is False


def test_production_set_contains_proven_graphics() -> None:
    ids, _snap = production_graphic_ids()
    for graphic_id in (
        "punchline-reveal",
        "numbered-example-card",
        "kinetic-word-punctuation",
        "source-punch-zoom",
    ):
        assert graphic_id in ids


def test_transcript_word_binding() -> None:
    plan = _good_plan()
    plan["beats"][0]["wordSpan"] = {
        "startWordId": "w1",
        "endWordId": "w2",
    }
    transcript = {
        "project": {
            "words": [
                {"id": "w1", "text": "Hello", "start_frame": 0, "end_frame": 10},
                {"id": "w2", "text": "world", "start_frame": 11, "end_frame": 20},
            ]
        }
    }
    ok = validate_editorial_plan(plan, transcript_document=transcript)
    assert ok["ok"] is True

    bad = copy.deepcopy(plan)
    bad["beats"][0]["wordSpan"] = {"startWordId": "missing", "endWordId": "w2"}
    result = validate_editorial_plan(bad, transcript_document=transcript)
    assert result["ok"] is False
    assert any(error["code"] == "unknown-word-id" for error in result["errors"])


def test_schema_file_exists() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "visual-production"
        / "schemas"
        / "editorial-beats.v1.schema.json"
    )
    assert path.is_file()
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["properties"]["schemaVersion"]["const"] == SCHEMA_VERSION
    enum = set(schema["$defs"]["beatType"]["enum"])
    assert enum == set(BEAT_TYPES)
    assert enum.isdisjoint(SUPERSEDED_BEAT_TYPES)
