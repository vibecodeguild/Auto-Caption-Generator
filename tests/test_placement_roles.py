"""Placement role specs cover all engines; no kickers; adapter maps lines."""

from __future__ import annotations

from app.core.placement_roles import (
    ENGINE_PLACEMENT_SPECS,
    all_placement_interfaces,
    assert_specs_cover_all_engines,
    empty_line,
    lines_to_engine_parameters,
    placement_interface_summary,
    slot_to_parameter_path,
)
from app.core.visual_production import MODULE_IDS


def test_specs_cover_all_module_ids() -> None:
    assert_specs_cover_all_engines()
    assert set(ENGINE_PLACEMENT_SPECS) == MODULE_IDS
    assert len(ENGINE_PLACEMENT_SPECS) == len(MODULE_IDS)
    assert "speaker-side-panel" not in MODULE_IDS


def test_no_kicker_in_any_spec_or_adapter() -> None:
    for eid, spec in ENGINE_PLACEMENT_SPECS.items():
        fixed = spec.get("fixed_line_slots") or []
        assert "kicker" not in fixed, eid
        assert "kicker" not in (spec.get("meta_keys") or []), eid
        params = lines_to_engine_parameters(
            eid,
            [empty_line("text", text="HELLO", reveal_frame=10)],
            meta={"kicker": "SHOULD_DROP"},
        )
        assert "kicker" not in params, eid


def test_dependency_stack_lines_expand_nodes() -> None:
    params = lines_to_engine_parameters(
        "dependency-stack",
        [
            empty_line("text", text="TITLE", reveal_frame=0),
            empty_line("nodes.0", text="One", reveal_frame=10),
            empty_line("nodes.1", text="Two", reveal_frame=20),
        ],
    )
    assert params["text"] == "TITLE"
    assert params["nodes"] == ["One", "Two"]
    assert "kicker" not in params


def test_punchline_and_kinetic_slots() -> None:
    p = lines_to_engine_parameters(
        "punchline-reveal",
        [empty_line("text", text="JOKE", reveal_frame=5)],
        assets={"imageAssetId": "img1"},
    )
    assert p["text"] == "JOKE"
    assert p.get("imageAssetId") == "img1"

    k = lines_to_engine_parameters(
        "kinetic-word-punctuation",
        [empty_line("phrase", text="HIT", reveal_frame=1)],
        motion={"side": "left", "anchor": "top"},
    )
    assert k["phrase"] == "HIT"
    assert k["side"] == "left"


def test_source_punch_zoom_has_no_lines() -> None:
    spec = placement_interface_summary("source-punch-zoom")
    assert spec["fixedLineSlots"] == []
    assert spec["listSlot"] is None
    assert "zoomInFrame" in (spec.get("motionKeys") or [])
    assert "zoomOutFrame" in (spec.get("motionKeys") or [])
    params = lines_to_engine_parameters(
        "source-punch-zoom",
        [],
        motion={
            "focusX": 0.5,
            "focusY": 0.4,
            "zoom": 1.4,
            "zoomInFrame": 120,
            "zoomOutFrame": 200,
        },
    )
    assert params["focusX"] == 0.5
    assert params["zoom"] == 1.4
    assert params["zoomInFrame"] == 120
    assert params["zoomOutFrame"] == 200


def test_all_interfaces_export() -> None:
    rows = all_placement_interfaces()
    assert len(rows) == len(MODULE_IDS)
    assert all(row["kicker"] is False for row in rows)
    assert not any(row["engineId"] == "speaker-side-panel" for row in rows)


def test_slot_paths() -> None:
    assert slot_to_parameter_path("text") == "parameters.text"
    assert slot_to_parameter_path("items.2") == "parameters.items.2"
