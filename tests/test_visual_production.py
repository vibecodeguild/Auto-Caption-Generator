from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import visual_production
from scripts import promote_frozen_visual_revision


def _private_project(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "private-project"
    for name in ("source", "assets", "plans", "renders", "working"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    (root / "source" / "locked-cut.mp4").write_bytes(b"video")
    plan = {
        "schemaVersion": 1,
        "project": {"id": "project-1", "name": "Pilot", "createdAt": "now", "updatedAt": "now"},
        "source": {"video": "source/locked-cut.mp4", "transcript": ""},
        "composition": {"width": 1920, "height": 1080, "fps": 30, "durationSec": 60, "brandId": "vcg-white-editorial"},
        "assets": [],
        "protectedFootage": [],
        "cues": [],
    }
    plan_path = root / "plans" / "visual-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path, plan


def test_visual_plan_round_trip_stays_inside_marked_private_project(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    plan["cues"].append({
        "id": "cue-1",
        "kind": "module",
        "moduleId": "punchline-reveal",
        "startSec": 4,
        "endSec": 6,
        "enabled": True,
        "parameters": {"text": "Reveal after delivery"},
    })

    saved = visual_production.save_visual_plan(plan_path, plan)

    assert visual_production.find_visual_root(plan_path) == plan_path.parents[1]
    assert visual_production.load_visual_plan(plan_path)["cues"] == saved["cues"]
    assert saved["project"]["updatedAt"] != "now"


def test_visual_plan_rejects_paths_that_escape_private_project(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    plan["source"]["video"] = "../../public-video.mp4"

    with pytest.raises(ValueError, match="escapes its private project"):
        visual_production.save_visual_plan(plan_path, plan)


def test_import_visual_asset_copies_media_and_updates_plan(tmp_path: Path) -> None:
    plan_path, _plan = _private_project(tmp_path)
    source = tmp_path / "generated-overlay.png"
    source.write_bytes(b"png")

    asset, plan = visual_production.import_visual_asset(plan_path, source)

    copied = plan_path.parents[1] / asset["path"]
    assert copied.read_bytes() == b"png"
    assert asset["mediaType"] == "image"
    assert plan["assets"] == [asset]


def test_create_visual_project_refuses_public_checkout_workspace(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "cut.mp4"
    source.write_bytes(b"video")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(visual_production, "project_root", lambda: checkout)

    with pytest.raises(ValueError, match="outside the public Git checkout"):
        visual_production.create_visual_project(source, workspace_root=checkout / "internal")


def test_probe_visual_source_falls_back_to_ffmpeg_without_ffprobe(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "cut.mp4"
    source.write_bytes(b"video")
    completed = visual_production.subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="Duration: 00:01:02.50\nStream #0:0: Video: h264, yuv420p, 1920x1080, 29.97 fps"
    )
    monkeypatch.setattr(visual_production, "find_ffprobe", lambda: None)
    monkeypatch.setattr(visual_production, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(visual_production.subprocess, "run", lambda *args, **kwargs: completed)

    metadata = visual_production.probe_visual_source(source)

    assert metadata == {"width": 1920, "height": 1080, "fps": 29.97, "durationSec": 62.5}


def test_remux_locked_audio_copies_video_and_audio_then_verifies_hashes(tmp_path: Path, monkeypatch) -> None:
    rendered = tmp_path / "video-only.mp4"
    locked = tmp_path / "locked-cut.mp4"
    output = tmp_path / "final.mp4"
    rendered.write_bytes(b"video")
    locked.write_bytes(b"audio")
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if "-f" in command and "hash" in command:
            return visual_production.subprocess.CompletedProcess(command, 0, "SHA256=" + "a" * 64, "")
        Path(command[-1]).write_bytes(b"muxed")
        return visual_production.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(visual_production, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(visual_production.subprocess, "run", fake_run)

    visual_production.remux_locked_audio(rendered, locked, output)

    assert output.read_bytes() == b"muxed"
    assert commands[0][commands[0].index("-map") + 1] == "0:v:0"
    assert commands[0][commands[0].index("-map", commands[0].index("-map") + 1) + 1] == "1:a:0"
    assert commands[0][commands[0].index("-c:v") + 1] == "copy"
    assert commands[0][commands[0].index("-c:a") + 1] == "copy"
    assert len(commands) == 3


def test_remux_locked_audio_rejects_changed_mastered_audio(tmp_path: Path, monkeypatch) -> None:
    rendered = tmp_path / "video-only.mp4"
    locked = tmp_path / "locked-cut.mp4"
    output = tmp_path / "final.mp4"
    rendered.write_bytes(b"video")
    locked.write_bytes(b"audio")
    hashes = iter(("a" * 64, "b" * 64))

    def fake_run(command, **_kwargs):
        if "-f" in command and "hash" in command:
            return visual_production.subprocess.CompletedProcess(command, 0, "SHA256=" + next(hashes), "")
        Path(command[-1]).write_bytes(b"muxed")
        return visual_production.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(visual_production, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(visual_production.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="does not match the locked cut"):
        visual_production.remux_locked_audio(rendered, locked, output)


def test_hyperframes_progress_parser_supports_percent_and_frame_counts() -> None:
    assert visual_production._hyperframes_progress_percent("render progress 42.5%") == 42.5
    assert visual_production._hyperframes_progress_percent("Rendered 225 / 900 frames") == 25
    assert visual_production._hyperframes_progress_percent("Preparing browser") is None


def test_direct_final_export_does_not_require_legacy_review_gates(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    saved = visual_production.save_visual_plan(plan_path, plan)

    report = visual_production.visual_production_gate_report(plan_path, saved)

    assert report["representativeApproved"] is False
    assert report["fullReviewApproved"] is False
    assert report["reviewRenderAvailable"] is False
    assert report["canExportFinal"] is True
    assert report["canDeliver"] is True


def test_direct_final_export_blocks_active_review_notes(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    plan["reviews"] = [{
        "id": "review-1", "itemId": "cue-1", "itemType": "cue",
        "startSec": 1, "endSec": 2, "note": "Move this away from my face.",
        "directive": "targeted", "status": "changes-requested",
        "createdAt": "now", "updatedAt": "now",
    }]
    saved = visual_production.save_visual_plan(plan_path, plan)

    report = visual_production.visual_production_gate_report(plan_path, saved)

    assert report["activeReviewCount"] == 1
    assert report["canExportFinal"] is False
    assert "active review note" in report["messages"][0]


def test_delivery_verification_rejects_missing_audio(tmp_path: Path, monkeypatch) -> None:
    delivered = tmp_path / "final.mp4"
    locked = tmp_path / "locked.mp4"
    metadata = {
        "streams": [{
            "codec_type": "video", "width": 1920, "height": 1080,
            "avg_frame_rate": "30/1", "duration": "60", "nb_frames": "1800",
        }],
        "format": {"duration": "60"},
    }
    monkeypatch.setattr(visual_production, "probe_delivery_media", lambda _path: metadata)

    with pytest.raises(RuntimeError, match="no audio stream"):
        visual_production.verify_delivered_media(
            delivered,
            locked,
            {"width": 1920, "height": 1080, "fps": 30, "durationSec": 60},
            full_length=True,
        )


def test_publish_verified_render_uses_versioned_fallback_when_target_is_open(tmp_path: Path, monkeypatch) -> None:
    staged = tmp_path / ".final-verified.mp4"
    requested = tmp_path / "final-video.mp4"
    staged.write_bytes(b"verified")
    requested.write_bytes(b"old-open-file")
    real_replace = visual_production.os.replace

    def replace_with_locked_target(source, destination):
        if Path(destination) == requested:
            raise PermissionError("file is open")
        return real_replace(source, destination)

    monkeypatch.setattr(visual_production.os, "replace", replace_with_locked_target)

    published = visual_production.publish_verified_render(staged, requested)

    assert published != requested
    assert published.name.startswith("final-video-")
    assert published.read_bytes() == b"verified"
    assert requested.read_bytes() == b"old-open-file"


def test_validate_visual_plan_rejects_unknown_module(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    plan["cues"] = [{
        "id": "cue-1",
        "kind": "module",
        "moduleId": "invented-module",
        "startSec": 1,
        "endSec": 2,
        "enabled": True,
        "parameters": {},
    }]

    with pytest.raises(ValueError, match="Unknown visual module"):
        visual_production.save_visual_plan(plan_path, plan)


def test_dual_comparison_module_renders_two_colored_sides() -> None:
    cue = {
        "moduleId": "dual-comparison",
        "parameters": {
            "kicker": "Choose the result",
            "leftTitle": "Work",
            "rightTitle": "Codex",
            "leftItems": ["Business artifact"],
            "rightItems": ["Technical change"],
            "leftColor": "#4D7CFE",
            "rightColor": "#6E56CF",
        },
    }

    markup = visual_production._module_markup(cue, "comparison", 10, 8, 20)

    assert "module-dual-comparison" in markup
    assert "Business artifact" in markup
    assert "Technical change" in markup
    assert "--left-accent:#4D7CFE" in markup
    assert "--right-accent:#6E56CF" in markup


def test_visual_plan_response_keeps_legacy_frozen_master_compatible_until_migration(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    root = plan_path.parents[1]
    final_path = root / "exports" / "final-video.mp4"
    final_path.parent.mkdir()
    final_path.write_bytes(b"verified-master")
    plan["assets"] = [{
        "id": "frozen-v5-master",
        "name": "V5 Final frozen master",
        "path": "exports/final-video.mp4",
        "mediaType": "video",
        "durationSec": 60,
        "hasTransparency": False,
        "origin": {
            "kind": "frozen-visual-revision",
            "active": True,
            "revisionId": "v5-final",
            "revisionName": "V5 Final",
        },
    }]

    response = visual_production.visual_plan_response(plan_path, plan)
    master_path, revision = visual_production.active_visual_master(plan_path, plan)

    assert master_path == final_path.resolve()
    assert revision is not None and revision["id"] == "v5-final"
    assert response["finalVideo"]["available"] is True
    assert response["finalVideo"]["revisionName"] == "V5 Final"
    assert response["finalVideo"]["cacheKey"]


def test_promote_revision_registers_custom_composition_and_voice_timed_scene_cues(tmp_path: Path, monkeypatch) -> None:
    plan_path, plan = _private_project(tmp_path)
    root = plan_path.parents[1]
    manifest = {
        "paths": {
            "visualPlan": plan_path.relative_to(root).as_posix(),
            "finalVideo": "exports/final-video.mp4",
        },
    }
    (root / "project.vcg-project.json").write_text(json.dumps(manifest), encoding="utf-8")
    master = root / "visual-production" / "renders" / "approved-v5.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"approved-v5")
    project_directory = root / "working" / "hyperframes-v5" / "public"
    project_directory.mkdir(parents=True)
    (project_directory / "index.html").write_text('<div data-composition-id="v5-root"></div>', encoding="utf-8")
    storyboard = root / "working" / "hyperframes-v5" / "storyboard.json"
    storyboard.write_text(json.dumps({"representativeApprovalSet": ["scene-one"], "scenes": [
        {"id": "scene-one", "startSec": 0, "renderEndSec": 30, "purpose": "First", "recipe": "one", "copy": {"kicker": "FIRST SCENE"}},
        {"id": "scene-two", "startSec": 30, "renderEndSec": 60, "purpose": "Second", "recipe": "two", "copy": {"kicker": "SECOND SCENE"}},
    ]}), encoding="utf-8")
    timing_ledger = storyboard.parent / "timing-ledger.json"
    timing_ledger.write_text(json.dumps({"fps": 30, "scenes": [
        {"sceneId": "scene-one", "reveals": [{"label": "First reveal", "phrase": "first words", "absoluteSec": 2, "settledFrame": 75}]},
        {"sceneId": "scene-two", "reveals": [{"label": "Second reveal", "phrase": "scene-relative", "absoluteSec": 30.1, "settledFrame": 918}]},
    ]}), encoding="utf-8")
    monkeypatch.setattr(promote_frozen_visual_revision, "probe_visual_source", lambda _path: {"width": 1920, "height": 1080, "fps": 30, "durationSec": 60})

    result = promote_frozen_visual_revision.promote(
        root,
        master,
        storyboard,
        revision_id="v5-final",
        revision_name="V5 Final",
        superseded_id="v1-generic",
        skip_production_checks=True,
    )
    promoted = visual_production.load_visual_plan(plan_path)

    assert result["sceneCount"] == 2
    assert (root / "exports" / "final-video.mp4").read_bytes() == b"approved-v5"
    assert len(list(plan_path.parent.glob("visual-plan.superseded-v1-generic-*.json"))) == 1
    assert [cue["parameters"]["reviewLabel"] for cue in promoted["cues"]] == ["01 · FIRST SCENE", "02 · SECOND SCENE"]
    assert all(cue["kind"] == "composition" for cue in promoted["cues"])
    assert promoted["cues"][0]["semanticItems"][0]["spokenStartSec"] == 2
    assert promoted["cues"][1]["semanticItems"][0]["anchorType"] == "scene-relative"
    assert promoted["assets"] == []
    assert promoted["customCompositions"][0]["projectPath"] == "working/hyperframes-v5/public"
    assert promoted["revisions"]["activeRevision"] == 5
    assert promoted["revisions"]["items"][0]["status"] == "delivered"
    report = visual_production.visual_production_gate_report(plan_path, promoted)
    assert report["timingAnchored"] is True
    assert report["canDeliver"] is True
    assert report["deliveryReopenVerified"] is False


def test_semantic_layout_inspection_times_use_fully_visible_voice_anchors() -> None:
    plan = {"cues": [
        {"enabled": True, "semanticItems": [
            {"fullyVisibleSec": 2.5},
            {"fullyVisibleSec": 4},
        ]},
        {"enabled": False, "semanticItems": [{"fullyVisibleSec": 9}]},
        {"enabled": True, "semanticItems": [{"fullyVisibleSec": 2.5}]},
    ]}

    assert visual_production.semantic_layout_inspection_times(plan) == [2.5, 4.0]


def test_custom_composition_tail_hold_can_have_no_visible_semantic_items() -> None:
    assert promote_frozen_visual_revision._semantic_items(
        {"id": "tail-hold"},
        {"sceneId": "tail-hold", "reveals": []},
        30,
        57.4,
        60,
    ) == []


def test_production_gate_blocks_unanchored_visible_text(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    plan["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "punchline-reveal", "startSec": 1, "endSec": 4,
        "enabled": True, "parameters": {"text": "SYNC THIS", "kicker": "VOICE"},
    }]
    saved = visual_production.save_visual_plan(plan_path, plan)

    report = visual_production.visual_production_gate_report(plan_path, saved)

    assert report["timingAnchored"] is False
    assert report["unanchoredCount"] == 2
    assert report["canRenderReview"] is False


def test_visual_plan_rejects_module_parameters_outside_the_module_contract(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    plan["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "punchline-reveal", "startSec": 1, "endSec": 4,
        "enabled": True, "parameters": {"text": "SYNC THIS", "leftItems": ["not allowed"]},
    }]

    with pytest.raises(ValueError, match="unsupported parameters: leftItems"):
        visual_production.save_visual_plan(plan_path, plan)
