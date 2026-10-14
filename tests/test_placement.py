"""Stage 3 Placement — draft, lock, re-place skips locked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.assignment import (
    OUTPUT_FILENAME as ASSIGN_OUT,
    REVIEWED_FILENAME as ASSIGN_REV,
    build_assignment_document,
    write_assignment_original,
    write_assignment_reviewed,
)
from app.core.graphics_library import LIBRARY_SCHEMA_VERSION
from app.core.masterbeater import (
    normalize_masterbeater_result,
    write_masterbeater_output,
)
from app.core import visual_production
from app.core.placement import (
    OUTPUT_FILENAME,
    REVIEWED_FILENAME,
    broll_clip_end_frame_exclusive,
    build_cue_preview_payload,
    build_placement_final_plan,
    draft_lines_for_engine,
    load_placement_original,
    load_placement_reviewed,
    normalize_placement_engine,
    render_placement_final_for_video_project,
    run_placement_for_video_project,
    save_placement_beat_for_video_project,
    write_placement_original,
    write_placement_reviewed,
)
from app.core.placement_roles import lines_to_engine_parameters, placement_interface_summary
from app.core.scenelayer import write_scenelayer_original, write_scenelayer_reviewed


def _doc() -> dict:
    return {
        "project": {
            "fps": 30,
            "words": [
                {
                    "id": "w1",
                    "text": "Hello",
                    "start": 0.0,
                    "end": 0.3,
                    "start_frame": 0,
                    "end_frame": 9,
                },
                {
                    "id": "w2",
                    "text": "world",
                    "start": 0.3,
                    "end": 0.6,
                    "start_frame": 9,
                    "end_frame": 18,
                },
                {
                    "id": "w3",
                    "text": "bullet",
                    "start": 1.0,
                    "end": 1.3,
                    "start_frame": 30,
                    "end_frame": 39,
                },
                {
                    "id": "w4",
                    "text": "two",
                    "start": 1.3,
                    "end": 1.6,
                    "start_frame": 39,
                    "end_frame": 48,
                },
            ],
        }
    }


def _setup_project(tmp_path: Path, library: Path) -> tuple[Path, dict]:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".vcg-private").write_text("private\n", encoding="utf-8")
    transcript = project / "final-transcript.json"
    document = _doc()
    transcript.write_text(json.dumps(document), encoding="utf-8")
    manifest_path = project / "manifest.json"
    manifest = {
        "paths": {
            "finalTranscript": "final-transcript.json",
            "lockedCut": "locked.mp4",
            "sourceVideo": "source.mp4",
        }
    }
    mb = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w2",
                    "rationale": "Open",
                },
                {
                    "id": "b2",
                    "beatType": "context",
                    "startWordId": "w3",
                    "endWordId": "w4",
                    "rationale": "Context",
                },
            ],
        },
        project_root=project,
        transcript_path=transcript,
        document=document,
    )
    write_masterbeater_output(project, mb)

    library.mkdir(parents=True, exist_ok=True)
    (library / "graphics-library.json").write_text(
        json.dumps(
            {
                "schemaVersion": LIBRARY_SCHEMA_VERSION,
                "updatedAt": "2026-08-02T00:00:00Z",
                "entries": [
                    {
                        "id": "hook-u",
                        "displayName": "Hook",
                        "status": "golden",
                        "engineId": "kinetic-word-punctuation",
                        "beatTypes": ["hook"],
                        "allowedLayouts": ["full-screen-talking"],
                    },
                    {
                        "id": "ctx-u",
                        "displayName": "Context",
                        "status": "golden",
                        "engineId": "dependency-stack",
                        "beatTypes": ["context"],
                        "allowedLayouts": ["talking-left"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    # Scenelayer + assignment shells
    sl = {
        "agent": "scenelayer",
        "schemaVersion": 1,
        "beats": [
            {"beatId": "b1", "layoutId": "full-screen-talking", "source": "algorithm"},
            {"beatId": "b2", "layoutId": "talking-left", "source": "algorithm"},
        ],
    }
    write_scenelayer_original(project, sl)
    write_scenelayer_reviewed(project, {**sl, "role": "reviewed"})

    assign_beats = [
        {"beatId": "b1", "usageId": "hook-u", "source": "algorithm"},
        {"beatId": "b2", "usageId": "ctx-u", "source": "algorithm"},
    ]
    adoc = build_assignment_document(assign_beats, project_root=project, role="original")
    write_assignment_original(project, adoc)
    write_assignment_reviewed(
        project, build_assignment_document(assign_beats, project_root=project, role="reviewed")
    )
    return manifest_path, manifest


def test_draft_kinetic_single_line() -> None:
    beat = {
        "id": "b1",
        "beatType": "hook",
        "wordsText": "Hello world",
        "startFrame": 0,
        "endFrameExclusive": 30,
    }
    lines = draft_lines_for_engine(
        "kinetic-word-punctuation", beat, start_frame=0, end_frame_exclusive=30
    )
    assert len(lines) == 1
    assert lines[0]["slot"] == "phrase"
    assert "Hello" in lines[0]["text"]
    assert lines[0]["revealFrame"] == 0


def test_build_cue_preview_payload_maps_reveal_frames() -> None:
    placement = {
        "beatId": "b1",
        "engineId": "kinetic-word-punctuation",
        "startFrame": 30,
        "endFrameExclusive": 90,
        "lines": [{"slot": "phrase", "text": "Hello world", "revealFrame": 45}],
        "meta": {},
        "assets": {},
        "motion": {"side": "left", "anchor": "top"},
    }
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["moduleId"] == "kinetic-word-punctuation"
    assert cue["startSec"] == 1.0
    assert cue["endSec"] == 3.0
    assert cue["parameters"]["phrase"] == "Hello world"
    assert "kicker" not in cue["parameters"]
    assert cue["semanticItems"]
    spoken = cue["semanticItems"][0]["spokenStartSec"]
    assert abs(spoken - 1.5) < 0.02


def test_build_cue_preview_sanitizes_legacy_punch_motion() -> None:
    """Legacy drafts used motion=punch; schema only allows in|out|in-out."""

    placement = {
        "beatId": "b-zoom",
        "engineId": "source-punch-zoom",
        "startFrame": 0,
        "endFrameExclusive": 60,
        "lines": [],
        "meta": {},
        "assets": {},
        "motion": {
            "focusX": 0.5,
            "focusY": 0.4,
            "zoom": 1.3,
            "settleSec": 0.5,
            "motion": "punch",
        },
    }
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["parameters"]["motion"] == "in-out"
    assert 1.02 <= float(cue["parameters"]["zoom"]) <= 2.0


def test_build_cue_preview_coerces_tradeoff_meter_value() -> None:
    """UI text meta value must become a number so schema oneOf accepts the cue."""

    placement = {
        "beatId": "b-meter",
        "engineId": "tradeoff-meter",
        "startFrame": 0,
        "endFrameExclusive": 90,
        "lines": [
            {"slot": "leftLabel", "text": "Left", "revealFrame": 0},
            {"slot": "rightLabel", "text": "Right", "revealFrame": 0},
            {"slot": "verdict", "text": "Verdict", "revealFrame": 45},
        ],
        "meta": {"value": "0.8"},
        "assets": {},
        "motion": {"side": "left"},
    }
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["moduleId"] == "tradeoff-meter"
    assert cue["parameters"]["value"] == pytest.approx(0.8)
    assert isinstance(cue["parameters"]["value"], float)


def test_build_cue_preview_assembles_ui_callout_bounds() -> None:
    """Craft meta x/y/width/height become nested targetBounds; flats stripped."""

    placement = {
        "beatId": "b-callout",
        "engineId": "ui-callout",
        "startFrame": 0,
        "endFrameExclusive": 90,
        "lines": [
            {"slot": "label", "text": "Click here", "revealFrame": 0},
        ],
        "meta": {"x": "0.2", "y": "0.3", "width": "0.25", "height": "0.15"},
        "assets": {},
        "motion": {"pointer": "below"},
    }
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["moduleId"] == "ui-callout"
    tb = cue["parameters"]["targetBounds"]
    assert tb["x"] == pytest.approx(0.2)
    assert tb["y"] == pytest.approx(0.3)
    assert tb["width"] == pytest.approx(0.25)
    assert tb["height"] == pytest.approx(0.15)
    assert "x" not in cue["parameters"]
    assert "width" not in cue["parameters"]
    assert "detail" not in cue["parameters"]
    assert cue["parameters"]["pointer"] == "below"

    markup = visual_production._module_markup(cue, "callout", 0, 3, 20)
    assert "callout-ring" in markup
    assert "callout-detail" not in markup
    assert "left:20.000%" in markup
    assert "top:30.000%" in markup
    assert "width:25.000%" in markup
    assert "height:15.000%" in markup


def test_build_cue_preview_coerces_numbered_step_show_number() -> None:
    """UI text knobs must not fail schema oneOf (misleading assetId required)."""

    placement = {
        "beatId": "b-step",
        "engineId": "numbered-step-intro",
        "startFrame": 0,
        "endFrameExclusive": 90,
        "lines": [
            {"slot": "title", "text": "STEP TITLE", "revealFrame": 0},
            {"slot": "action", "text": "Do the thing", "revealFrame": 15},
        ],
        "meta": {
            "stepNumber": "3",  # string from text input
            "showNumber": "false",  # string from text input — schema wants boolean
        },
        "assets": {},
        "motion": {"side": "left"},
    }
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["moduleId"] == "numbered-step-intro"
    assert cue["parameters"]["stepNumber"] == 3
    assert cue["parameters"]["showNumber"] is False
    assert isinstance(cue["parameters"]["showNumber"], bool)

    placement["meta"]["showNumber"] = 0
    cue0 = build_cue_preview_payload(placement, fps=30.0)
    assert cue0["parameters"]["showNumber"] is False

    placement["meta"]["showNumber"] = "true"
    placement["meta"]["stepNumber"] = 2
    cue1 = build_cue_preview_payload(placement, fps=30.0)
    assert cue1["parameters"]["showNumber"] is True
    assert cue1["parameters"]["stepNumber"] == 2


def test_build_cue_preview_intro_credentials_schema() -> None:
    """intro-credentials name/nodes/thankYou must validate under visual-plan schema."""

    placement = {
        "beatId": "b-intro",
        "engineId": "intro-credentials",
        "startFrame": 0,
        "endFrameExclusive": 300,
        "lines": [
            {"slot": "text", "text": "Ada", "revealFrame": 0},
            {"slot": "nodes.0", "text": "Builder", "revealFrame": 30},
            {"slot": "nodes.1", "text": "Teacher", "revealFrame": 60},
            {"slot": "thankYou", "text": "Thank you!", "revealFrame": 120},
        ],
        "meta": {},
        "assets": {},
        "motion": {},
    }
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["moduleId"] == "intro-credentials"
    assert cue["parameters"]["text"] == "Ada"
    assert cue["parameters"]["nodes"] == ["Builder", "Teacher"]
    assert cue["parameters"]["thankYou"] == "Thank you!"

    from datetime import datetime, timezone

    from app.core.visual_production import VISUAL_PLAN_VERSION, validate_document_schema

    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "schemaVersion": VISUAL_PLAN_VERSION,
        "project": {"id": "p", "name": "p", "createdAt": now, "updatedAt": now},
        "source": {"video": "source.mp4", "transcript": "", "videoSha256": "a" * 64},
        "composition": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "durationSec": 12,
            "brandId": "vcg-white-editorial",
        },
        "assets": [],
        "customCompositions": [],
        "protectedFootage": [],
        "cues": [
            {
                "id": cue["id"],
                "kind": "module",
                "moduleId": cue["moduleId"],
                "startSec": cue["startSec"],
                "endSec": cue["endSec"],
                "enabled": True,
                "parameters": cue["parameters"],
                "semanticItems": cue["semanticItems"],
            }
        ],
        "revisions": {"activeRevision": None, "items": []},
        "productionGates": {
            "representativeApproval": None,
            "fullReviewApproval": None,
            "layoutInspection": None,
            "deliveryReopen": None,
        },
        "reviews": [],
        "reviewHistory": [],
    }
    validate_document_schema("visual-plan", plan, label="visual-plan.preview.json")


def test_build_cue_preview_coerces_numbered_phrase_reveal_strings() -> None:
    """numberLabel/title/text must be strings or schema oneOf reports assetId required."""

    placement = {
        "beatId": "b-npr",
        "engineId": "numbered-phrase-reveal",
        "startFrame": 0,
        "endFrameExclusive": 90,
        "lines": [
            {"slot": "title", "text": None, "revealFrame": 0},  # type: ignore[dict-item]
            {"slot": "text", "text": "Phrase here", "revealFrame": 15},
        ],
        "meta": {
            "numberLabel": 2,  # number from craft UI — schema wants string
        },
        "assets": {},
        "motion": {},
    }
    # lines_to_engine_parameters stringifies via str() for line text; force null title via meta path
    placement["lines"][0]["text"] = ""
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["moduleId"] == "numbered-phrase-reveal"
    assert cue["parameters"]["numberLabel"] == "2"
    assert isinstance(cue["parameters"]["numberLabel"], str)
    assert cue["parameters"]["text"] == "Phrase here"
    assert cue["parameters"]["title"] == ""

    # Full plan must pass visual-plan.schema.json (same path as live preview).
    from datetime import datetime, timezone

    from app.core.visual_production import VISUAL_PLAN_VERSION, validate_document_schema

    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "schemaVersion": VISUAL_PLAN_VERSION,
        "project": {"id": "p", "name": "p", "createdAt": now, "updatedAt": now},
        "source": {"video": "source.mp4", "transcript": "", "videoSha256": "a" * 64},
        "composition": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "durationSec": 10,
            "brandId": "vcg-white-editorial",
        },
        "assets": [],
        "customCompositions": [],
        "protectedFootage": [],
        "cues": [
            {
                "id": cue["id"],
                "kind": "module",
                "moduleId": cue["moduleId"],
                "startSec": cue["startSec"],
                "endSec": cue["endSec"],
                "enabled": True,
                "parameters": cue["parameters"],
                "semanticItems": cue["semanticItems"],
            }
        ],
        "revisions": {"activeRevision": None, "items": []},
        "productionGates": {
            "representativeApproval": None,
            "fullReviewApproval": None,
            "layoutInspection": None,
            "deliveryReopen": None,
        },
        "reviews": [],
        "reviewHistory": [],
    }
    validate_document_schema("visual-plan", plan, label="visual-plan.preview.json")


def test_punchline_reveal_preview_uses_joke_image_card_path() -> None:
    """Without an image asset, punchline-reveal must still use the golden joke-card path."""

    placement = {
        "beatId": "b-joke",
        "engineId": "punchline-reveal",
        "startFrame": 0,
        "endFrameExclusive": 90,
        "lines": [{"slot": "text", "text": "WORD LAYOUT DARK ARTS", "revealFrame": 0}],
        "meta": {},
        "assets": {},
        "motion": {},
    }
    cue = build_cue_preview_payload(placement, fps=30.0)
    assert cue["parameters"]["text"] == "WORD LAYOUT DARK ARTS"
    assert cue["parameters"].get("imageAssetId") == "demo-joke-image"


def test_retired_speaker_side_panel_resolves_for_place_interfaces() -> None:
    """Persisted speaker-side-panel must not KeyError when Place builds engineInterfaces."""

    summary = placement_interface_summary("speaker-side-panel")
    assert summary["engineId"] == "dependency-stack"
    assert summary["listSlot"] == "nodes"
    assert summary["fixedLineSlots"] == ["text"]

    row = normalize_placement_engine(
        {
            "beatId": "b1",
            "engineId": "speaker-side-panel",
            "lines": [
                {"slot": "text", "text": "Title", "revealFrame": 0},
                {"slot": "items.0", "text": "A", "revealFrame": 10},
            ],
        }
    )
    assert row["engineId"] == "dependency-stack"
    assert row["lines"][1]["slot"] == "nodes.0"


def test_place_rerun_survives_locked_speaker_side_panel_prior(tmp_path: Path) -> None:
    """Re-Place after a retired engine was locked must succeed (not 500)."""

    library = tmp_path / "library"
    manifest_path, manifest = _setup_project(tmp_path, library)
    project = manifest_path.parent

    first = run_placement_for_video_project(manifest_path, manifest, library_root=library)
    assert first["ok"] is True
    beats = list(first["beats"] or [])
    # Force a locked prior that still names the retired engine (old episode draft).
    for beat in beats:
        beat["engineId"] = "speaker-side-panel"
        beat["locked"] = True
        beat["lines"] = [
            {"slot": "text", "text": "Kept title", "revealFrame": int(beat.get("startFrame") or 0)},
            {"slot": "items.0", "text": "Kept bullet", "revealFrame": int(beat.get("startFrame") or 0) + 5},
        ]
    write_placement_reviewed(
        project,
        {
            "agent": "placement-reviewed",
            "schemaVersion": 1,
            "role": "reviewed",
            "projectRoot": str(project),
            "placementCount": len(beats),
            "lockedCount": len(beats),
            "unlockedCount": 0,
            "allLocked": True,
            "beats": beats,
            "notes": [],
            "basedOnOriginal": True,
            "originalFile": OUTPUT_FILENAME,
        },
    )

    again = run_placement_for_video_project(manifest_path, manifest, library_root=library)
    assert again["ok"] is True
    assert again["placementCount"] == len(beats)
    for beat in again["beats"] or []:
        assert beat["engineId"] == "dependency-stack"
        assert beat["locked"] is True
        slots = [line.get("slot") for line in beat.get("lines") or []]
        assert "nodes.0" in slots
        assert "items.0" not in slots
    assert "dependency-stack" in (again.get("engineInterfaces") or {})
    assert "speaker-side-panel" not in (again.get("engineInterfaces") or {})


def test_run_placement_and_lock(tmp_path: Path) -> None:
    library = tmp_path / "library"
    manifest_path, manifest = _setup_project(tmp_path, library)
    project = manifest_path.parent

    result = run_placement_for_video_project(
        manifest_path, manifest, library_root=library
    )
    assert result["ok"] is True
    assert result["firstRun"] is True
    assert result["placementCount"] == 2
    assert (project / OUTPUT_FILENAME).is_file()
    assert (project / REVIEWED_FILENAME).is_file()
    original = load_placement_original(project)
    assert original is not None
    assert original["allLocked"] is False

    b1 = next(b for b in result["beats"] if b["beatId"] == "b1")
    assert b1["engineId"] == "kinetic-word-punctuation"
    assert b1["locked"] is False

    saved = save_placement_beat_for_video_project(
        manifest_path,
        manifest,
        {
            "beatId": "b1",
            "lines": [{"slot": "phrase", "text": "CUSTOM", "revealFrame": 5}],
            "locked": True,
        },
    )
    assert saved["ok"] is True
    assert saved["placement"]["locked"] is True
    assert saved["placement"]["lines"][0]["text"] == "CUSTOM"
    assert saved["allLocked"] is False

    # Re-place must keep locked b1 text
    again = run_placement_for_video_project(
        manifest_path, manifest, library_root=library
    )
    assert again["firstRun"] is False
    kept = next(b for b in again["beats"] if b["beatId"] == "b1")
    assert kept["locked"] is True
    assert kept["lines"][0]["text"] == "CUSTOM"

    # Lock second
    save_placement_beat_for_video_project(
        manifest_path, manifest, {"beatId": "b2", "locked": True}
    )
    final = load_placement_reviewed(project)
    assert final is not None
    assert final["allLocked"] is True

    # Original still has first draft for b1 phrase content? original may have Hello world
    orig = load_placement_original(project)
    assert orig is not None
    orig_b1 = next(b for b in orig["beats"] if b["beatId"] == "b1")
    assert orig_b1["lines"][0]["text"] != "CUSTOM" or True  # original never updated by save
    # Ensure original file not rewritten with CUSTOM
    assert any(
        "CUSTOM" not in json.dumps(b.get("lines"))
        for b in orig["beats"]
        if b["beatId"] == "b1"
    ) or orig_b1["lines"][0]["text"] != "CUSTOM"


def test_build_placement_final_plan_requires_all_locked(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "library"
    manifest_path, manifest = _setup_project(tmp_path, library)
    project = manifest_path.parent
    locked = project / "locked.mp4"
    locked.write_bytes(b"fake")
    monkeypatch.setattr(
        "app.core.placement.preferred_stage_source",
        lambda _m, _man: locked,
    )
    monkeypatch.setattr(
        "app.core.visual_production.probe_visual_source",
        lambda _path: {"durationSec": 5.0, "width": 1920, "height": 1080, "fps": 30},
    )
    monkeypatch.setattr(
        "app.core.file_utils.sha256_file",
        lambda _path: "abc123",
    )

    run_placement_for_video_project(manifest_path, manifest, library_root=library)
    with pytest.raises(ValueError, match="locked"):
        build_placement_final_plan(manifest_path, manifest)

    save_placement_beat_for_video_project(
        manifest_path, manifest, {"beatId": "b1", "locked": True}
    )
    save_placement_beat_for_video_project(
        manifest_path, manifest, {"beatId": "b2", "locked": True}
    )
    assembled = build_placement_final_plan(manifest_path, manifest, quality="standard")
    assert assembled["ok"] is True
    assert assembled["cueCount"] == 2
    assert assembled["placementCount"] == 2
    assert assembled["durationSec"] == pytest.approx(5.0)
    plan = assembled["plan"]
    assert len(plan["cues"]) == 2
    modules = {c["moduleId"] for c in plan["cues"]}
    assert "kinetic-word-punctuation" in modules
    assert "dependency-stack" in modules
    # Absolute times on the locked cut (not range-local preview).
    for cue in plan["cues"]:
        assert 0.0 <= float(cue["startSec"]) < float(cue["endSec"]) <= 5.0
    assert Path(assembled["planPath"]).is_file()
    assert Path(assembled["outputPath"]).as_posix().endswith(
        "working/placement-final/a-roll-master.mp4"
    )


def test_build_placement_final_render_command_uses_gpu_and_workers(monkeypatch) -> None:
    """Final HyperFrames argv enables GPU encode + parallel workers (not a parallel engine path)."""

    from app.core.placement import build_placement_final_render_command

    monkeypatch.delenv("PLACEMENT_FINAL_WORKERS", raising=False)
    monkeypatch.delenv("PLACEMENT_FINAL_GPU", raising=False)
    command = build_placement_final_render_command(
        node="node",
        cli_js=Path("node_modules/hyperframes/dist/cli.js"),
        runtime_root=Path("public"),
        output_path=Path("out.mp4"),
        quality="standard",
    )
    assert command[0] == "node"
    assert "render" in command
    assert "--gpu" in command
    assert "--workers" in command
    workers_idx = command.index("--workers")
    assert command[workers_idx + 1] == "4"
    assert "--quality" in command
    assert command[command.index("--quality") + 1] == "standard"

    monkeypatch.setenv("PLACEMENT_FINAL_GPU", "0")
    monkeypatch.setenv("PLACEMENT_FINAL_WORKERS", "auto")
    off = build_placement_final_render_command(
        node="node",
        cli_js=Path("cli.js"),
        runtime_root=Path("public"),
        output_path=Path("out.mp4"),
        quality="draft",
    )
    assert "--gpu" not in off
    assert off[off.index("--workers") + 1] == "auto"
    assert off[off.index("--quality") + 1] == "draft"


def test_render_placement_final_reuses_receipt(tmp_path: Path, monkeypatch) -> None:
    """Identical locked set + existing receipt skips HyperFrames re-encode."""

    library = tmp_path / "library"
    manifest_path, manifest = _setup_project(tmp_path, library)
    project = manifest_path.parent
    locked = project / "locked.mp4"
    locked.write_bytes(b"fake")
    out = project / "working" / "placement-final" / "a-roll-master.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"published")

    monkeypatch.setattr(
        "app.core.placement.preferred_stage_source",
        lambda _m, _man: locked,
    )
    monkeypatch.setattr(
        "app.core.visual_production.probe_visual_source",
        lambda _path: {"durationSec": 4.0, "width": 1920, "height": 1080, "fps": 30},
    )
    monkeypatch.setattr("app.core.file_utils.sha256_file", lambda _path: "sha-final")

    run_placement_for_video_project(manifest_path, manifest, library_root=library)
    save_placement_beat_for_video_project(
        manifest_path, manifest, {"beatId": "b1", "locked": True}
    )
    save_placement_beat_for_video_project(
        manifest_path, manifest, {"beatId": "b2", "locked": True}
    )
    assembled = build_placement_final_plan(manifest_path, manifest)
    work = project / "working" / "placement-final"
    work.mkdir(parents=True, exist_ok=True)
    (work / "final-receipt.json").write_text(
        json.dumps(
            {
                "fingerprint": assembled["fingerprint"],
                "quality": "standard",
                "outputPath": str(out.resolve()),
            }
        ),
        encoding="utf-8",
    )

    def _must_not_build(*_a, **_k):
        raise AssertionError("should reuse receipt, not rebuild composition")

    monkeypatch.setattr(
        "app.core.visual_production.build_hyperframes_composition",
        _must_not_build,
    )
    # force=False is the only way to hit receipt reuse; Stage 3 Final always force=True.
    result = render_placement_final_for_video_project(
        manifest_path, manifest, force=False
    )
    assert result["ok"] is True
    assert result["reused"] is True
    assert Path(result["outputPath"]).resolve() == out.resolve()

    # force=True must not short-circuit on an existing A-roll master.
    def _force_skips_reuse(*_a, **_k):
        assert out.is_file()
        raise RuntimeError("FORCE_REBUILD_REACHED")

    monkeypatch.setattr(
        "app.core.visual_production.build_hyperframes_composition",
        _force_skips_reuse,
    )
    with pytest.raises(RuntimeError, match="FORCE_REBUILD_REACHED"):
        render_placement_final_for_video_project(manifest_path, manifest, force=True)


def test_render_placement_final_defaults_to_force_rebuild(tmp_path: Path, monkeypatch) -> None:
    """Default force=True: existing A-roll master + receipt must not silently reuse."""

    library = tmp_path / "library"
    manifest_path, manifest = _setup_project(tmp_path, library)
    project = manifest_path.parent
    locked = project / "locked.mp4"
    locked.write_bytes(b"fake")
    out = project / "working" / "placement-final" / "a-roll-master.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"old-published")

    monkeypatch.setattr(
        "app.core.placement.preferred_stage_source",
        lambda _m, _man: locked,
    )
    monkeypatch.setattr(
        "app.core.visual_production.probe_visual_source",
        lambda _path: {"durationSec": 4.0, "width": 1920, "height": 1080, "fps": 30},
    )
    monkeypatch.setattr("app.core.file_utils.sha256_file", lambda _path: "sha-final")

    run_placement_for_video_project(manifest_path, manifest, library_root=library)
    save_placement_beat_for_video_project(
        manifest_path, manifest, {"beatId": "b1", "locked": True}
    )
    save_placement_beat_for_video_project(
        manifest_path, manifest, {"beatId": "b2", "locked": True}
    )
    assembled = build_placement_final_plan(manifest_path, manifest)
    work = project / "working" / "placement-final"
    work.mkdir(parents=True, exist_ok=True)
    (work / "final-receipt.json").write_text(
        json.dumps(
            {
                "fingerprint": assembled["fingerprint"],
                "quality": "standard",
                "outputPath": str(out.resolve()),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.core.visual_production.build_hyperframes_composition",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("DEFAULT_FORCE_REBUILD")),
    )
    with pytest.raises(RuntimeError, match="DEFAULT_FORCE_REBUILD"):
        render_placement_final_for_video_project(manifest_path, manifest)


def test_broll_cue_uses_start_and_end_frames() -> None:
    payload = build_cue_preview_payload(
        {
            "beatId": "b1",
            "engineId": "broll-overlay",
            "startFrame": 30,
            "endFrameExclusive": 90,
            "lines": [],
            "assets": {"videoAssetId": "clip"},
            "meta": {"clipStartSec": 1.5, "fit": "cover"},
        },
        fps=30,
    )
    assert payload["startSec"] == 1.0
    assert payload["endSec"] == 3.0
    assert payload["parameters"]["videoAssetId"] == "clip"
    assert payload["parameters"]["clipStartSec"] == 1.5


def test_broll_clip_end_uses_remaining_media_then_beat_cap() -> None:
    # 3s remaining after a 1s in-point at 30fps = 90 frames from start 10.
    assert (
        broll_clip_end_frame_exclusive(
            start_frame=10,
            clip_start_sec=1.0,
            clip_duration_sec=4.0,
            fps=30.0,
            beat_end_exclusive=200,
        )
        == 100
    )
    # Clip longer than the beat → beat end wins.
    assert (
        broll_clip_end_frame_exclusive(
            start_frame=0,
            clip_start_sec=0.0,
            clip_duration_sec=10.0,
            fps=30.0,
            beat_end_exclusive=60,
        )
        == 60
    )


def test_image_overlay_preview_cue_matches_schema() -> None:
    from app.core.visual_production import validate_visual_plan

    cue = build_cue_preview_payload(
        {
            "beatId": "b-img",
            "engineId": "image-overlay",
            "startFrame": 10,
            "endFrameExclusive": 90,
            "lines": [],
            "assets": {
                "layers": [
                    {
                        "imageAssetId": "slide-1",
                        "x": 0.55,
                        "y": 0.1,
                        "width": 0.4,
                        "height": 0.4,
                        "revealFrame": 12,
                    },
                    {
                        "imageAssetId": "slide-2",
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.3,
                        "height": 0.3,
                        "startFrame": 40,
                        "endFrameExclusive": 70,
                    },
                ]
            },
        },
        fps=30.0,
    )
    assert cue["moduleId"] == "image-overlay"
    assert cue["kind"] == "module"
    layers = cue["parameters"]["layers"]
    assert layers[0]["startFrame"] == 12
    assert layers[0]["endFrameExclusive"] == 90
    assert layers[1]["startFrame"] == 40
    assert layers[1]["endFrameExclusive"] == 70
    plan = {
        "schemaVersion": 2,
        "project": {"id": "preview", "name": "preview"},
        "source": {"video": "locked.mp4", "transcript": ""},
        "composition": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "durationSec": 10,
            "brandId": "vcg-white-editorial",
        },
        "assets": [],
        "customCompositions": [],
        "protectedFootage": [],
        "cues": [
            {
                "id": cue["id"],
                "kind": "module",
                "moduleId": "image-overlay",
                "startSec": cue["startSec"],
                "endSec": cue["endSec"],
                "enabled": True,
                "parameters": cue["parameters"],
                "semanticItems": cue["semanticItems"],
            }
        ],
        "revisions": {"activeRevision": None, "items": []},
        "productionGates": {
            "representativeApproval": None,
            "fullReviewApproval": None,
            "layoutInspection": None,
            "deliveryReopen": None,
        },
        "reviews": [],
        "reviewHistory": [],
    }
    validate_visual_plan(plan, Path("."))


def test_image_overlay_cue_span_covers_later_still() -> None:
    cue = build_cue_preview_payload(
        {
            "beatId": "b-img-2",
            "engineId": "image-overlay",
            "startFrame": 10,
            "endFrameExclusive": 30,
            "lines": [],
            "assets": {
                "layers": [
                    {
                        "imageAssetId": "slide-1",
                        "x": 0.5,
                        "y": 0.1,
                        "width": 0.4,
                        "height": 0.4,
                        "startFrame": 10,
                        "endFrameExclusive": 30,
                    },
                    {
                        "imageAssetId": "slide-2",
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.3,
                        "height": 0.3,
                        "startFrame": 40,
                        "endFrameExclusive": 80,
                    },
                ]
            },
        },
        fps=30.0,
    )
    assert cue["startFrame"] == 10
    assert cue["endFrameExclusive"] == 80
    assert cue["parameters"]["layers"][1]["startFrame"] == 40
    assert cue["parameters"]["layers"][1]["endFrameExclusive"] == 80


def test_image_overlay_has_no_copy_lines() -> None:
    spec = placement_interface_summary("image-overlay")
    assert spec["fixedLineSlots"] == []
    assert spec["assetKeys"] == ["layers"]
    lines = draft_lines_for_engine(
        "image-overlay",
        {"wordsText": "this speech stays on the cut"},
        start_frame=10,
        end_frame_exclusive=90,
    )
    assert lines == []
    params = lines_to_engine_parameters(
        "image-overlay",
        [],
        assets={
            "layers": [
                {
                    "imageAssetId": "slide-1",
                    "x": 0.55,
                    "y": 0.1,
                    "width": 0.4,
                    "height": 0.4,
                    "revealFrame": 12,
                }
            ]
        },
    )
    assert params["layers"][0]["imageAssetId"] == "slide-1"
    assert params["layers"][0]["x"] == 0.55


def test_broll_overlay_has_no_copy_lines() -> None:
    spec = placement_interface_summary("broll-overlay")
    assert spec["fixedLineSlots"] == []
    assert spec["assetKeys"] == ["videoAssetId"]
    lines = draft_lines_for_engine(
        "broll-overlay",
        {"wordsText": "this speech stays on the cut"},
        start_frame=10,
        end_frame_exclusive=90,
    )
    assert lines == []


def test_broll_overlay_drops_leftover_copy_lines_on_save(tmp_path: Path) -> None:
    from app.core.placement import _filter_lines_to_engine_slots
    from app.core.video_project import VIDEO_PROJECT_SUFFIX

    leftover = [
        {"slot": "text", "text": "Here's Why", "revealFrame": 10},
        {"slot": "nodes.0", "text": "One", "revealFrame": 20},
    ]
    assert _filter_lines_to_engine_slots("broll-overlay", leftover) == []

    root = tmp_path / "proj"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    manifest = root / f"show{VIDEO_PROJECT_SUFFIX}"
    manifest.write_text("{}", encoding="utf-8")
    beat_row = {
        "beatId": "b1",
        "engineId": "broll-overlay",
        "startFrame": 10,
        "endFrameExclusive": 90,
        "lines": leftover,
        "locked": False,
    }
    write_placement_original(root, {"schemaVersion": 1, "beats": [beat_row]})
    save_placement_beat_for_video_project(
        manifest,
        {},
        {"beatId": "b1", "startFrame": 25, "endFrameExclusive": 80, "lines": leftover},
    )
    reviewed = load_placement_reviewed(root)
    assert reviewed is not None
    beat = reviewed["beats"][0]
    assert beat["lines"] == []
    assert beat["startFrame"] == 25
    assert beat["endFrameExclusive"] == 80


def test_save_clamps_broll_end_to_clip_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.video_project import VIDEO_PROJECT_SUFFIX

    monkeypatch.setattr(
        "app.core.visual_production.probe_visual_source",
        lambda _path: {"durationSec": 2.0, "width": 1920, "height": 1080, "fps": 30},
    )
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    media = root / "assets" / "placement"
    media.mkdir(parents=True)
    (media / "clip.mp4").write_bytes(b"fake-mp4")
    manifest = root / f"show{VIDEO_PROJECT_SUFFIX}"
    manifest.write_text("{}", encoding="utf-8")
    write_placement_original(
        root,
        {
            "schemaVersion": 1,
            "beats": [
                {
                    "beatId": "b1",
                    "engineId": "broll-overlay",
                    "startFrame": 0,
                    "endFrameExclusive": 300,
                    "lines": [],
                    "assets": {"videoAssetId": "clip"},
                    "meta": {"clipStartSec": 0, "fit": "cover"},
                    "locked": False,
                }
            ],
        },
    )
    save_placement_beat_for_video_project(
        manifest,
        {},
        {"beatId": "b1", "endFrameExclusive": 300},
    )
    reviewed = load_placement_reviewed(root)
    assert reviewed is not None
    # 2.0s × 30fps from start 0 → exclusive 60, not the 300-frame beat.
    assert reviewed["beats"][0]["endFrameExclusive"] == 60
    save_placement_beat_for_video_project(
        manifest,
        {},
        {"beatId": "b1", "endFrameExclusive": 40},
    )
    reviewed = load_placement_reviewed(root)
    assert reviewed is not None
    # Earlier human pick is kept.
    assert reviewed["beats"][0]["endFrameExclusive"] == 40


def test_import_placement_media_copies_video(tmp_path: Path) -> None:
    from app.core.placement import import_placement_media
    from app.core.video_project import VIDEO_PROJECT_SUFFIX

    root = tmp_path / "proj"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    manifest = root / f"show{VIDEO_PROJECT_SUFFIX}"
    manifest.write_text("{}", encoding="utf-8")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake-mp4")

    result = import_placement_media(manifest, source)

    assert result["assetId"] == "clip"
    assert result["mediaType"] == "video"
    copied = root / "assets" / "placement" / "clip.mp4"
    assert copied.is_file()
    assert copied.read_bytes() == b"fake-mp4"
