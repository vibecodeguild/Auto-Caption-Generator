from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import visual_production


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


def test_module_motion_wrapper_keeps_animation_off_framework_clip() -> None:
    markup = (
        '<section id="cue-1" class="clip module" data-start="1" data-duration="2">'
        '<div class="card">Approved graphic</div></section>'
    )

    wrapped = visual_production._wrap_module_motion(markup)

    assert wrapped.startswith('<section id="cue-1" class="clip module"')
    assert '<div class="cue-motion"><div class="card">Approved graphic</div></div>' in wrapped
    assert wrapped.endswith("</section>")


def test_entry_preroll_advances_motion_one_frame_without_crossing_zero() -> None:
    assert visual_production._entry_preroll_time(10, 30) == pytest.approx(10 - (1 / 30))
    assert visual_production._entry_preroll_time(0, 30) == 0
    assert visual_production._entry_preroll_time(0.01, 30) == 0


def test_final_export_is_blocked_until_the_full_review_is_approved(tmp_path: Path) -> None:
    """Loop B is the production pass. There is no route to a delivered render that skips it."""
    plan_path, plan = _private_project(tmp_path)
    saved = visual_production.save_visual_plan(plan_path, plan)

    report = visual_production.visual_production_gate_report(plan_path, saved)

    assert report["fullReviewApproved"] is False
    assert report["reviewRenderAvailable"] is False
    assert report["canRenderReview"] is True
    assert report["canExportFinal"] is False
    assert report["canDeliver"] is False
    assert any("review" in message for message in report["messages"])


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
    assert "comparison-speaker-outline" not in markup


@pytest.mark.parametrize("module_id", ["punchline-reveal", "progress-scale", "dual-comparison"])
def test_sustained_modules_render_only_inside_the_audited_speaker_safe_region(module_id: str) -> None:
    cue = {
        "moduleId": module_id,
        "parameters": {
            "text": "Keep the speaker visible",
            "speakerSafety": {
                "overlayOcclusionBounds": [
                    {"x": .18, "y": .02, "width": .78, "height": .62},
                ],
            },
        },
    }

    markup = visual_production._module_markup(cue, "safe-overlay", 10, 8, 20)

    assert "left:18.000%;top:2.000%;width:78.000%;height:62.000%" in markup
    assert 'class="module-fill"' not in markup or 'style="left:18.000%' in markup


def test_progress_scale_renders_its_planned_milestones() -> None:
    cue = {
        "moduleId": "progress-scale",
        "parameters": {
            "text": "Working result",
            "milestones": ["Prompt again", "Add detail", "Verify"],
        },
    }

    markup = visual_production._module_markup(cue, "progress", 10, 8, 20)

    assert "scale-milestones" in markup
    assert "Prompt again" in markup
    assert "Add detail" in markup
    assert "Verify" in markup
    semantic_paths = [
        item["parameterPath"]
        for item in visual_production._unanchored_semantic_items({
            "kind": "module",
            "moduleId": "progress-scale",
            "startSec": 10,
            "endSec": 18,
            "parameters": cue["parameters"],
        })
    ]
    assert "parameters.milestones.0" in semantic_paths
    assert "parameters.milestones.2" in semantic_paths


def test_pinned_list_rows_mark_structural_parent_child_overlap_as_intentional() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "list-reveal-pinned-thesis",
            "parameters": {
                "kicker": "RULES",
                "thesis": "Keep it readable",
                "rows": ["First point", "Second point"],
            },
        },
        "pinned-list",
        10,
        8,
        20,
    )

    assert markup.count("data-layout-allow-overlap") == 2


def test_approved_reuse_variants_render_frozen_media_and_can_hide_step_number() -> None:
    joke = visual_production._module_markup(
        {
            "moduleId": "punchline-reveal",
            "parameters": {
                "imageAssetId": "joke-image",
                "kicker": "THE PAYOFF",
                "text": "GO PLAY PICKLEBALL",
            },
        },
        "joke",
        10,
        5,
        20,
        {"joke-image": "joke-image.png"},
    )
    cta = visual_production._module_markup(
        {
            "moduleId": "brand-cta-lockup",
            "parameters": {
                "logoAssetId": "skool-logo",
                "logoText": "SKOOL",
                "action": "JOIN THE VIBE CODE GUILD",
                "destination": "SKOOL.COM/VIBECODEGUILD",
                "side": "left",
            },
        },
        "cta",
        20,
        5,
        21,
        {"skool-logo": "skool-logo.svg"},
    )
    step = visual_production._module_markup(
        {
            "moduleId": "numbered-step-intro",
            "parameters": {
                "stepNumber": 2,
                "showNumber": False,
                "title": "TAKE THE CHANGES",
                "action": "LET GROK REVISE IT",
            },
        },
        "step",
        30,
        5,
        22,
    )

    assert 'src="assets/joke-image.png"' in joke
    assert "joke-card-approved" in joke
    assert 'src="assets/skool-logo.svg"' in cta
    assert "pf-community" in cta
    assert 'data-semantic-path="parameters.logoText"' in cta
    assert 'data-semantic-path="parameters.logoAssetId"' not in cta
    assert "pf-step-no-num" in step
    assert "pf-step-num" not in step


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


def _contract_suggestions(root: Path, suggestions: list[dict], **coverage_overrides) -> None:
    (root / "visual-production").mkdir(exist_ok=True)
    coverage = {
        "reuseAudit": {
            "contractVersion": 3, "reviewed": True, "reusedModuleIds": [], "reusedRecipeIds": [],
            "creatorLibraryQueries": [], "bespokeRationales": [],
        },
        "bRollAudit": {"reviewed": True, "decision": "planned", "rationale": "One cutaway."},
        "cadenceAudit": {"completeCoverage": True, "violations": []},
        **coverage_overrides,
    }
    (root / "visual-production" / "visual-suggestions.json").write_text(
        json.dumps({"schemaVersion": 1, "coverage": coverage, "suggestions": suggestions}), encoding="utf-8"
    )


def test_asset_cue_backed_by_an_approved_placement_passes_the_planning_gate(tmp_path: Path) -> None:
    """B-roll and library assets used to make canDeliver permanently false (F5)."""
    plan_path, plan = _private_project(tmp_path)
    root = plan_path.parents[1]
    (root / "assets" / "clip.mp4").write_bytes(b"clip")
    plan["assets"] = [{"id": "pexels-1", "name": "Clip", "path": "assets/clip.mp4", "mediaType": "video", "durationSec": 5, "hasTransparency": False}]
    plan["source"]["videoSha256"] = visual_production.sha256_file(root / "source" / "locked-cut.mp4")
    plan["cues"] = [{
        "id": "asset-1", "kind": "asset", "assetId": "pexels-1", "startSec": 4, "endSec": 9,
        "enabled": True, "semanticItems": [],
        "parameters": {"planningSuggestionId": "placed-1", "approvedTreatmentId": "pexels-1"},
    }]
    saved = visual_production.save_visual_plan(plan_path, plan)
    _contract_suggestions(root, [{
        "id": "placed-1", "status": "built", "cueId": "asset-1", "category": "stock",
        "timelineLane": "b-roll", "startSec": 4, "endSec": 9,
        "decision": {"status": "approved", "selectedTreatmentId": "pexels-1", "decidedAt": "now"},
    }])

    report = visual_production.visual_production_gate_report(plan_path, saved)

    assert report["planningApprovalIssues"] == []
    assert report["canRenderReview"] is True


def test_a_plan_with_cues_and_no_decision_record_cannot_be_delivered(tmp_path: Path) -> None:
    """Absence of visual-suggestions.json used to mean every gate silently passed."""
    plan_path, plan = _private_project(tmp_path)
    plan["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "source-footage-hold",
        "startSec": 1, "endSec": 4, "enabled": True, "parameters": {}, "semanticItems": [],
    }]
    saved = visual_production.save_visual_plan(plan_path, plan)

    report = visual_production.visual_production_gate_report(plan_path, saved)

    assert report["planningApprovalPassed"] is False
    assert report["speakerSafetyPassed"] is False
    assert report["canRenderReview"] is False
    assert report["canDeliver"] is False
    assert any("visual-suggestions.json is missing" in issue for issue in report["planningApprovalIssues"])


def test_review_render_then_approval_unblocks_the_final_export(tmp_path: Path) -> None:
    """The whole Loop B cycle: render for review, approve it, then delivery opens."""
    plan_path, plan = _private_project(tmp_path)
    root = plan_path.parents[1]
    runtime = root / "working" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "index.html").write_text("<div></div>", encoding="utf-8")
    review_render = root / "renders" / "review.mp4"
    review_render.write_bytes(b"review")
    saved = visual_production.save_visual_plan(plan_path, plan)
    assert visual_production.visual_production_gate_report(plan_path, saved)["canDeliver"] is False

    visual_production.record_review_revision(plan_path, runtime, review_render)
    approved = visual_production.approve_full_review(plan_path)

    report = visual_production.visual_production_gate_report(plan_path, approved)
    assert report["reviewRenderAvailable"] is True
    assert report["fullReviewApproved"] is True
    assert report["canDeliver"] is True


def test_editing_a_cue_after_approval_reopens_the_full_review(tmp_path: Path) -> None:
    """A fix made in response to a Loop B note must be reviewed again, not inherit the sign-off."""
    plan_path, plan = _private_project(tmp_path)
    root = plan_path.parents[1]
    runtime = root / "working" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "index.html").write_text("<div></div>", encoding="utf-8")
    (root / "renders" / "review.mp4").write_bytes(b"review")
    visual_production.save_visual_plan(plan_path, plan)
    visual_production.record_review_revision(plan_path, runtime, root / "renders" / "review.mp4")
    approved = visual_production.approve_full_review(plan_path)

    approved["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "source-footage-hold",
        "startSec": 1, "endSec": 4, "enabled": True, "parameters": {}, "semanticItems": [],
    }]
    edited = visual_production.save_visual_plan(plan_path, approved)

    assert visual_production.visual_production_gate_report(plan_path, edited)["fullReviewApproved"] is False


def test_recutting_the_locked_cut_names_the_cues_that_must_be_retimed(tmp_path: Path) -> None:
    """Cue times are seconds into a specific file; a re-cut used to drift silently."""
    plan_path, plan = _private_project(tmp_path)
    locked = plan_path.parents[1] / "source" / "locked-cut.mp4"
    plan["source"]["videoSha256"] = visual_production.sha256_file(locked)
    plan["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "source-footage-hold",
        "startSec": 1, "endSec": 4, "enabled": True, "parameters": {}, "semanticItems": [],
    }]
    saved = visual_production.save_visual_plan(plan_path, plan)
    assert visual_production.locked_cut_drift_issues(plan_path, saved) == []

    locked.write_bytes(b"a completely different cut")

    issues = visual_production.locked_cut_drift_issues(plan_path, saved)
    assert len(issues) == 1
    assert "All 1 cue time(s) refer to the previous cut" in issues[0]
    assert visual_production.visual_production_gate_report(plan_path, saved)["canRenderReview"] is False


def test_a_custom_composition_cannot_declare_a_source_hash_it_does_not_have(tmp_path: Path) -> None:
    """Realizing a recipe means registering real files; the hash must match what is there."""
    plan_path, plan = _private_project(tmp_path)
    root = plan_path.parents[1]
    source = root / "working" / "recipe-build" / "public"
    source.mkdir(parents=True)
    (source / "index.html").write_text('<div data-composition-id="root"></div>', encoding="utf-8")
    plan["customCompositions"] = [{
        "id": "composition-1", "runtime": "hyperframes", "name": "Numbered example card",
        "rootCompositionId": "root", "projectPath": "working/recipe-build/public",
        "entryFile": "index.html", "sourceHash": "0" * 64,
    }]

    with pytest.raises(ValueError, match="Register the hash of the files that are actually there"):
        visual_production.save_visual_plan(plan_path, plan)

    plan["customCompositions"][0]["sourceHash"] = visual_production.sha256_directory(source)
    assert visual_production.save_visual_plan(plan_path, plan)["customCompositions"][0]["id"] == "composition-1"


def test_a_plan_that_does_not_record_its_locked_cut_cannot_render(tmp_path: Path) -> None:
    plan_path, plan = _private_project(tmp_path)
    plan["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "source-footage-hold",
        "startSec": 1, "endSec": 4, "enabled": True, "parameters": {}, "semanticItems": [],
    }]
    saved = visual_production.save_visual_plan(plan_path, plan)

    report = visual_production.visual_production_gate_report(plan_path, saved)

    assert report["lockedCutMatches"] is False
    assert "does not record which locked cut" in report["lockedCutIssues"][0]


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
