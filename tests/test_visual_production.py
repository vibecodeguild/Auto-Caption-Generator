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
        "parameters": {
            "text": "Reveal after delivery",
            "imageAssetId": "demo-joke-image",
        },
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


def test_punchline_reveal_is_full_joke_stage_not_overlay_bounds() -> None:
    """Joke card docks video left — not a speaker-safe overlay fill."""

    markup = visual_production._module_markup(
        {
            "moduleId": "punchline-reveal",
            "parameters": {
                "text": "Keep the speaker visible",
                "imageAssetId": "demo-joke-image",
            },
        },
        "safe-overlay",
        10,
        8,
        20,
        staged_assets={"demo-joke-image": "demo-joke-image.png"},
    )

    assert "joke-stage" in markup
    assert "joke-video-outline" in markup
    assert "module-fill" not in markup


def test_progress_scale_renders_full_white_stage_with_video_window() -> None:
    cue = {
        "moduleId": "progress-scale",
        "parameters": {
            "kicker": "PROGRESS",
            "text": "Working result",
            "milestones": ["Prompt again", "Add detail", "Verify"],
            "startLabel": "IDEA",
            "targetLabel": "SHIPPED",
        },
    }

    markup = visual_production._module_markup(cue, "progress", 10, 8, 20)

    assert "progress-stage" in markup
    assert "progress-track-block" in markup
    assert "stat-video-outline" in markup
    assert "module-fill" not in markup
    assert "scale-milestones" in markup
    assert "scale-marker" not in markup
    assert "Prompt again" in markup
    assert "Add detail" in markup
    assert "Verify" in markup
    assert "Working result" in markup
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


def test_progress_scale_milestone_hits_track_linear_bar_fill() -> None:
    """Stops sit at 0/50/100% of fill; bar finishes before a multi-second linger."""
    start, duration = 1.0, 10.0
    hold_after_fill = 2.5
    video_out = 0.45
    fill_lead = 0.45
    min_fill = 1.2
    fill_duration = max(min_fill, duration - fill_lead - hold_after_fill - video_out)
    fill_start = start + fill_lead
    fill_end = fill_start + fill_duration
    milestone_count = 3
    appears = [
        fill_start + (index / max(milestone_count - 1, 1)) * fill_duration
        for index in range(milestone_count)
    ]
    assert appears[0] == pytest.approx(fill_start)
    assert appears[1] == pytest.approx(fill_start + fill_duration * 0.5)
    assert appears[2] == pytest.approx(fill_end)
    # Linger after last stop, before video restore / cue end.
    restore_at = min(start + duration - video_out, fill_end + hold_after_fill)
    assert restore_at - fill_end == pytest.approx(hold_after_fill)
    assert appears[0] < appears[1] < appears[2]


def test_brand_cta_lockup_is_community_stage_with_generic_defaults() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "brand-cta-lockup",
            "parameters": {
                "action": "JOIN THE COMMUNITY",
                "destination": "your.community.url",
            },
        },
        "cta",
        1,
        8,
        20,
    )
    assert "community-stage" in markup
    assert "community-mask" in markup
    assert "community-bg" not in markup  # solid bg under the hole paints the video white
    assert "community-logo" in markup
    assert "community-copy" in markup
    assert "community-url" in markup
    assert "community-video-outline" in markup
    assert "JOIN THE COMMUNITY" in markup
    assert "your.community.url" in markup
    assert "brand-skool-logo.svg" in markup
    assert "pf-card" not in markup
    assert visual_production.brand_skool_logo_path().is_file()


def test_punchline_reveal_with_image_is_joke_card() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "punchline-reveal",
            "parameters": {
                "kicker": "RARE MARKETING SKILL",
                "text": "WORD LAYOUT DARK ARTS",
                "imageAssetId": "demo-joke-image",
            },
        },
        "joke",
        1,
        8,
        20,
        staged_assets={"demo-joke-image": "demo-joke-image.png"},
    )
    assert "joke-stage" in markup
    assert "joke-mask" in markup
    assert "joke-video-outline" in markup
    assert "joke-panel" in markup
    assert "joke-card" in markup
    assert "joke-image" in markup
    assert "joke-copy" in markup
    assert "joke-kicker" in markup
    assert "joke-line" in markup
    assert "WORD LAYOUT DARK ARTS" in markup
    assert "COMEDY BREAK" not in markup
    assert "joke-tab" not in markup
    assert "demo-joke-image.png" in markup
    assert "module-fill" not in markup


def test_punchline_reveal_requires_image_no_text_only_mode() -> None:
    """One engine, one look — missing imageAssetId is an error, not a second mode."""

    try:
        visual_production._module_markup(
            {
                "moduleId": "punchline-reveal",
                "parameters": {"kicker": "PUNCH", "text": "JUST START"},
            },
            "punch",
            1,
            4,
            20,
        )
        raise AssertionError("expected ValueError for punchline-reveal without imageAssetId")
    except ValueError as exc:
        assert "imageAssetId" in str(exc)
        assert "kinetic-word-punctuation" in str(exc)


def test_robot_rocket_sign_markup_has_rig_and_sign() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "robot-rocket-sign",
            "parameters": {"text": "LINK IN DESCRIPTION"},
        },
        "rocket",
        1,
        6,
        20,
    )
    assert "rocket-stage" in markup
    assert "rocket-rig" in markup
    assert "rocket-smoke" in markup
    assert "rocket-fist" in markup
    assert "rocket-sign-board" in markup
    assert "LINK IN DESCRIPTION" in markup
    assert "robot-bubble" not in markup


def test_robot_hold_after_drawn_is_three_seconds() -> None:
    """Long cues still exit ~3s after the bubble is drawn (engine-fixed)."""
    assert visual_production.ROBOT_HOLD_AFTER_DRAWN_SEC == 3.0
    # drawn_at (cheer) = start + 0.28 + 0.45 = start + 0.73 → exit at start + 3.73
    start = 2.0
    duration = 20.0  # deliberately long
    drawn_at = start + 0.28 + 0.45
    expected_exit = drawn_at + visual_production.ROBOT_HOLD_AFTER_DRAWN_SEC
    # Reconstruct the same math the timeline uses.
    exit_d = 0.28
    exit_at = min(start + duration - exit_d, expected_exit)
    assert exit_at == pytest.approx(expected_exit)
    assert exit_at - drawn_at == pytest.approx(3.0)


def test_robot_cheer_markup_has_bubble_and_svg() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "robot-cheer",
            "parameters": {"text": "Vibe coding", "tagline": "FOR THE WIN!"},
        },
        "cheer",
        1,
        6,
        20,
    )
    assert "robot-stage-left" in markup
    assert "robot-bubble" in markup
    assert "Vibe coding" in markup
    assert "FOR THE WIN!" in markup
    assert "robot-body" in markup
    assert 'data-semantic-path="parameters.text"' in markup


def test_robot_defiant_and_roast_markup_sides() -> None:
    defiant = visual_production._module_markup(
        {"moduleId": "robot-defiant", "parameters": {"text": "Stand firm"}},
        "def",
        1,
        6,
        20,
    )
    roast = visual_production._module_markup(
        {"moduleId": "robot-roast", "parameters": {"text": "He's lowkey cheap"}},
        "roast",
        1,
        8,
        20,
    )
    assert "robot-stage-left" in defiant
    assert "robot-fist" in defiant
    assert "Stand firm" in defiant
    assert "robot-stage-right" in roast
    assert "robot-point" in roast
    assert "lowkey cheap" in roast
    assert "robot-bubble-roast" in roast


def test_dependency_stack_markup_has_title_nodes_and_video_frame() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "dependency-stack",
            "parameters": {
                "text": "WHAT YOU NEED",
                "nodes": ["Transcript", "Locked cut", "Graphics kit"],
            },
        },
        "dep",
        1,
        10,
        20,
    )
    assert "dependency-stage" in markup
    assert "dependency-video-outline" in markup
    assert "dependency-title" in markup
    assert "WHAT YOU NEED" in markup
    assert "STACK" not in markup
    assert 'data-node-index="0"' in markup
    assert "Transcript" in markup
    assert "lib-kicker" not in markup
    assert 'class="kicker"' not in markup


def test_windows_prompt_typing_docks_head_and_types_chars() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "windows-prompt-typing",
            "parameters": {
                "appName": "Windows PowerShell",
                "prompt": "Hi there",
            },
        },
        "prompt",
        1,
        8,
        20,
    )
    assert "prompt-stage" in markup
    assert "prompt-terminal" in markup
    assert "prompt-video-outline" in markup
    assert "prompt-mask" in markup
    assert "Windows PowerShell" in markup
    assert "PS C:\\&gt;" in markup or "PS C:\\>" in markup
    assert "prompt-typed-text" in markup
    assert 'data-full-prompt="Hi there"' in markup
    # Live text starts empty; GSAP fills textContent letter-by-letter.
    # Caret is CSS ::after on .prompt-typed-text (not a sibling that fails on wrap).
    assert 'class="prompt-typed-text"></span>' in markup
    assert "prompt-cursor" not in markup
    assert "pf-window" not in markup
    # Windows caption buttons, not Mac traffic-light dots.
    assert "win-min" in markup
    assert "win-max" in markup
    assert "win-close" in markup
    assert "prompt-win-controls" in markup


def test_problem_card_triptych_markup_is_sequential_not_static_accent() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "problem-card-triptych",
            "parameters": {
                "cards": ["Too slow", "Too generic", "Too risky"],
            },
        },
        "tri",
        1,
        10,
        20,
    )
    assert "pf-triptych" in markup
    assert 'data-card-index="0"' in markup
    assert 'data-card-index="2"' in markup
    assert "Too slow" in markup
    assert "lib-accent" not in markup
    assert "lib-kicker" not in markup
    assert "PROBLEMS" not in markup


def test_progress_scale_markup_places_stops_on_bar_fractions() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "progress-scale",
            "parameters": {
                "text": "JOURNEY",
                "milestones": ["Brief", "Build", "Ship"],
            },
        },
        "progress",
        1,
        8,
        20,
    )
    assert 'data-milestone-index="0"' in markup
    assert "left:0.0000%" in markup
    assert "left:50.0000%" in markup
    assert "left:100.0000%" in markup
    assert "scale-milestone" in markup


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
                "action": "JOIN THE CREATOR COMMUNITY",
                "destination": "COMMUNITY.EXAMPLE/JOIN",
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
    assert "joke-card" in joke
    assert "joke-stage" in joke
    assert 'src="assets/skool-logo.svg"' in cta or "brand-skool-logo.svg" in cta
    assert "community-stage" in cta
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
        "id": "cue-1", "kind": "module", "moduleId": "source-punch-zoom",
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
        "id": "cue-1", "kind": "module", "moduleId": "source-punch-zoom",
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
        "id": "cue-1", "kind": "module", "moduleId": "source-punch-zoom",
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
        "id": "cue-1", "kind": "module", "moduleId": "source-punch-zoom",
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
        "enabled": True,
        "parameters": {
            "text": "SYNC THIS",
            "kicker": "VOICE",
            "imageAssetId": "demo-joke-image",
        },
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
        "enabled": True,
        "parameters": {
            "text": "SYNC THIS",
            "imageAssetId": "demo-joke-image",
            "leftItems": ["not allowed"],
        },
    }]

    with pytest.raises(ValueError, match="unsupported parameters: leftItems"):
        visual_production.save_visual_plan(plan_path, plan)
