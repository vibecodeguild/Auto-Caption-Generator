from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import graphics_library as gr
from app.core.editorial_build import (
    TREATMENT_BINDINGS,
    beat_parameters,
    build_editorial_composition,
    build_source_led_graph,
    composition_to_html,
    materialize_beat,
    namespace_graph,
    resolve_binding,
    write_composition_artifacts,
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


def _phase2_plan() -> dict:
    """Plan using only Phase-2 buildable treatments (punchline, example, prompt, list, zoom)."""

    return {
        "schemaVersion": 2,
        "episodeId": "phase2-test",
        "mode": "tutorial",
        "fps": {"numerator": 30, "denominator": 1},
        "totalDurationSec": 24.0,
        "source": {
            "lockedCutPath": "exports/locked-cut.mp4",
            "transcriptPath": "transcripts/final-transcript.json",
        },
        "beats": [
            {
                "id": "beat-punch",
                "beatType": "punchline",
                "graphicId": "punchline-reveal",
                "onScreenCopy": "SOUL-CRUSHING CORPORATE JOBS",
                "motionKind": "treatment-enter",
                "startSec": 0.0,
                "endSec": 4.0,
            },
            {
                "id": "beat-example",
                "beatType": "example",
                "graphicId": "numbered-example-card",
                "onScreenCopy": "01 — TURN ROUGH NOTES INTO A GUIDE",
                "motionKind": "treatment-enter",
                "startSec": 4.0,
                "endSec": 9.0,
            },
            {
                "id": "beat-prompt",
                "beatType": "prompt",
                "graphicId": "windows-prompt-typing",
                "onScreenCopy": "Polish this into onboarding copy",
                "motionKind": "treatment-enter",
                "startSec": 9.0,
                "endSec": 14.0,
            },
            {
                "id": "beat-zoom",
                "beatType": "aftershock",
                "graphicId": "source-punch-zoom",
                "onScreenCopy": None,
                "motionKind": "punch-zoom",
                "startSec": 14.0,
                "endSec": 16.5,
            },
            {
                "id": "beat-list",
                "beatType": "list",
                "graphicId": "problem-card-triptych",
                "onScreenCopy": "WHAT YOU GET",
                "motionKind": "internal-reveal",
                "startSec": 16.5,
                "endSec": 24.0,
                "listRows": [
                    {"id": "r1", "text": "FASTER DECKS", "startSec": 17.0},
                    {"id": "r2", "text": "CLEANER SLIDES", "startSec": 20.0},
                    {"id": "r3", "text": "LESS BUSYWORK", "startSec": 22.5},
                ],
            },
        ],
    }


def test_core_bindings_exist() -> None:
    for treatment_id in (
        "punchline-reveal",
        "numbered-example-card",
        "windows-prompt-typing",
        "problem-card-triptych",
        "source-punch-zoom",
    ):
        binding = resolve_binding(treatment_id)
        assert binding is not None
        assert binding.engine_id == treatment_id
        assert binding.usage_id == treatment_id


def test_seed_only_aliases_removed() -> None:
    """compact-* ids were seed aliases, not engines — deleted for clean library."""
    assert resolve_binding("compact-editorial-emphasis") is None
    assert resolve_binding("compact-prompt-card") is None
    assert "compact-editorial-emphasis" not in TREATMENT_BINDINGS
    assert "compact-prompt-card" not in TREATMENT_BINDINGS


def test_numbered_parameter_parsing() -> None:
    binding = resolve_binding("numbered-example-card")
    assert binding is not None
    params = beat_parameters(
        {
            "onScreenCopy": "01 — TURN ROUGH NOTES INTO A GUIDE",
            "listRows": [],
        },
        binding,
    )
    assert params["number"] == "1"
    assert "ROUGH NOTES" in params["text"]

def test_namespace_graph_prefixes_ids() -> None:
    graph = {
        "elements": [
            {
                "id": "caption",
                "kind": "text",
                "geometry": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.1},
                "properties": {"text": "HI"},
            }
        ],
        "events": [
            {
                "id": "enter",
                "targetElementId": "caption",
                "operation": "enter",
                "absoluteFrame": 0,
                "durationFrames": 8,
                "parameters": {},
            }
        ],
    }
    namespaced = namespace_graph(graph, "beat-1")
    assert namespaced["elements"][0]["id"] == "beat-1__caption"
    assert namespaced["events"][0]["targetElementId"] == "beat-1__caption"
    assert namespaced["events"][0]["id"] == "beat-1__enter"


def test_source_led_graph_valid() -> None:
    """source-punch-zoom is a graphic implementation path, not a beat type."""

    beat = {
        "id": "z1",
        "beatType": "punchline",
        "graphicId": "source-punch-zoom",
        "onScreenCopy": None,
        "motionKind": "punch-zoom",
        "startSec": 0.0,
        "endSec": 2.0,
    }
    graph = build_source_led_graph(beat, {"numerator": 30, "denominator": 1})
    assert graph["elements"]
    assert graph["events"]
    assert graph["events"][0]["operation"] == "scale"


def test_materialize_engine_path() -> None:
    beat = {
        "id": "p1",
        "beatType": "punchline",
        "graphicId": "punchline-reveal",
        "onScreenCopy": "JUST START",
        "motionKind": "treatment-enter",
        "startSec": 1.0,
        "endSec": 4.0,
    }
    result = materialize_beat(beat, {"numerator": 30, "denominator": 1})
    assert result["status"] == "built", result
    assert result["engineId"] == "punchline-reveal"
    assert result["engineId"] == "punchline-reveal"
    assert result["graph"] is not None
    assert any(
        "JUST START" in str((el.get("properties") or {}).get("text") or "")
        for el in result["graph"]["elements"]
    )


def test_build_full_phase2_plan(tmp_path: Path) -> None:
    plan = _phase2_plan()
    result = build_editorial_composition(plan)
    assert result["ok"] is True, json.dumps(result.get("errors"), indent=2)
    assert result["summary"]["built"] == 5
    assert result["summary"]["failed"] == 0
    assert result["summary"]["notBuildable"] == 0
    composition = result["composition"]
    assert composition is not None
    assert composition["elements"]
    assert composition["events"]
    # Base locked source present once.
    assert sum(1 for el in composition["elements"] if el["id"] == "locked-source") == 1
    # HTML uses seed geometry, not a generic white shell only.
    html = composition_to_html(composition, video_name="cut.mp4")
    assert "editorial-composition" in html
    assert "SOUL-CRUSHING" in html or "JUST START" in html or "TURN ROUGH" in html
    assert "1920" in html
    paths = write_composition_artifacts(result, tmp_path, write_html=True)
    assert Path(paths["composition"]).is_file()
    assert Path(paths["html"]).is_file()
    assert Path(paths["report"]).is_file()


def test_invalid_plan_stops_before_build() -> None:
    plan = _phase2_plan()
    plan["beats"][0]["onScreenCopy"] = "and"
    result = build_editorial_composition(plan)
    assert result["ok"] is False
    assert result["stage"] == "validate"
    assert result["composition"] is None


def test_unknown_usage_reports_not_buildable() -> None:
    plan = _phase2_plan()
    plan["beats"][1] = {
        "id": "beat-struct",
        "beatType": "structure",
        "graphicId": "not-a-real-engine-xyz",
        "onScreenCopy": "THE STACK THAT MATTERS",
        "motionKind": "treatment-enter",
        "startSec": 4.0,
        "endSec": 9.0,
    }
    result = build_editorial_composition(plan)
    # Plan validation may fail (not in golden set) or build stage may mark not-buildable.
    if result["stage"] == "validate":
        assert result["ok"] is False
        return
    statuses = {item["beatId"]: item["status"] for item in result["beats"]}
    assert statuses["beat-struct"] == "not-buildable"
    assert statuses["beat-punch"] == "built"

    strict = build_editorial_composition(plan, require_all_buildable=True)
    assert strict["ok"] is False


def test_bindings_cover_phase2_priority_set() -> None:
    # Phase 2 priority set uses real module ids only.
    priority = {
        "punchline-reveal",
        "numbered-example-card",
        "windows-prompt-typing",
        "problem-card-triptych",
        "source-punch-zoom",
    }
    assert priority.issubset(TREATMENT_BINDINGS)
