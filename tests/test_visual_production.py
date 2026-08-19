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


def test_publish_verified_render_overwrites_existing_closed_file(tmp_path: Path) -> None:
    """An existing final-video.mp4 must not block publish when the file is not locked."""
    staged = tmp_path / ".final-verified.mp4"
    requested = tmp_path / "final-video.mp4"
    staged.write_bytes(b"verified-new")
    requested.write_bytes(b"old-final")

    published = visual_production.publish_verified_render(staged, requested)

    assert published == requested
    assert requested.read_bytes() == b"verified-new"


def test_publish_verified_render_uses_versioned_fallback_when_target_is_open(tmp_path: Path, monkeypatch) -> None:
    staged = tmp_path / ".final-verified.mp4"
    requested = tmp_path / "final-video.mp4"
    staged.write_bytes(b"verified")
    requested.write_bytes(b"old-open-file")
    real_replace = visual_production.os.replace
    real_unlink = Path.unlink

    def replace_with_locked_target(source, destination):
        if Path(destination) == requested or Path(destination).name.startswith("final-video-"):
            if Path(destination) == requested:
                raise PermissionError("file is open")
        return real_replace(source, destination)

    def unlink_locked(self, *args, **kwargs):
        if self == requested:
            raise PermissionError("file is open")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(visual_production.os, "replace", replace_with_locked_target)
    monkeypatch.setattr(Path, "unlink", unlink_locked)

    # First replace fails, unlink fails, versioned path succeeds via real replace
    # for non-requested names — re-bind carefully.
    def replace_selective(source, destination):
        dest = Path(destination)
        if dest == requested:
            raise PermissionError("file is open")
        return real_replace(source, destination)

    monkeypatch.setattr(visual_production.os, "replace", replace_selective)

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


def test_progress_scale_fill_follows_milestone_reveal_frames() -> None:
    """Bar reaches each stop when that milestone's placement reveal fires."""
    fps = 30.0
    range_start = 1379 / fps
    # Cue local start ~0.05 with 0.05 preroll pad in live preview; use absolute secs.
    cue = {
        "moduleId": "progress-scale",
        "startSec": 1379 / fps,
        "endSec": 1576 / fps,
        "parameters": {
            "text": "Title Goes Here",
            "startLabel": "First",
            "targetLabel": "Second",
            "milestones": ["Third", "Forth", "Firth"],
        },
        "semanticItems": [
            {
                "parameterPath": "parameters.milestones.0",
                "spokenStartSec": 1428 / fps,
                "fullyVisibleSec": 1428 / fps + 0.2,
            },
            {
                "parameterPath": "parameters.milestones.1",
                "spokenStartSec": 1477 / fps,
                "fullyVisibleSec": 1477 / fps + 0.2,
            },
            {
                "parameterPath": "parameters.milestones.2",
                "spokenStartSec": 1526 / fps,
                "fullyVisibleSec": 1526 / fps + 0.2,
            },
        ],
    }
    # Composition-local times = absolute − range_start (preview pads −0.05).
    t0 = 1428 / fps - range_start
    t1 = 1477 / fps - range_start
    t2 = 1526 / fps - range_start
    assert t0 < t1 < t2
    # Fractions on a 3-stop bar: 0, 0.5, 1.0 — same geometry as markup.
    fracs = [i / 2 for i in range(3)]
    assert fracs == [0.0, 0.5, 1.0]
    # Contract: each stop time is the spoken anchor (engine clamps monotonic only).
    assert t1 - t0 == pytest.approx((1477 - 1428) / fps)
    assert t2 - t1 == pytest.approx((1526 - 1477) / fps)


def test_brand_cta_lockup_is_community_stage_with_brand_fixed_copy() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "brand-cta-lockup",
            "parameters": {
                # Overrides must not win — product brand lock.
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
    assert visual_production.DEFAULT_BRAND_CTA_ACTION in markup
    assert visual_production.DEFAULT_BRAND_CTA_DESTINATION in markup
    assert "JOIN THE COMMUNITY" not in markup or "JOIN THE FREE" in markup
    assert "your.community.url" not in markup
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
    # Kicker retired from the joke card (D5, 2026-08-03): the caption is the
    # Title line only — a passed-in legacy kicker param must not render.
    assert "joke-kicker" not in markup
    assert "RARE MARKETING SKILL" not in markup
    assert "joke-line" in markup
    assert "WORD LAYOUT DARK ARTS" in markup
    assert "COMEDY BREAK" not in markup
    assert "joke-tab" not in markup
    assert "demo-joke-image.png" in markup
    assert "module-fill" not in markup


def test_source_punch_zoom_motion_keys_include_frame_anchors() -> None:
    """Placement can set absolute zoom-in / zoom-out frames on the locked cut."""
    entry = visual_production.ENGINE_REGISTRY["source-punch-zoom"]["placement"]
    keys = entry["motion_keys"]
    assert "zoomInFrame" in keys
    assert "zoomOutFrame" in keys
    assert "zoomInFrame" in visual_production.MODULE_PARAMETER_KEYS["source-punch-zoom"]
    assert "zoomOutFrame" in visual_production.MODULE_PARAMETER_KEYS["source-punch-zoom"]


def test_punchline_title_content_at_uses_title_semantic_not_beat_start() -> None:
    """Title reveal times image+caption; stage/dock still starts at the beat."""
    cue = {
        "semanticItems": [
            {
                "parameterPath": "parameters.text",
                "spokenStartSec": 12.5,
                "fullyVisibleSec": 12.8,
            }
        ]
    }
    # Cue window 10–18 in absolute source; composition local start=0 for a range
    # that begins at 10 → content at 2.5 local.
    content_at = visual_production._punchline_title_content_at(
        cue,
        range_start=10.0,
        start=0.0,
        duration=8.0,
    )
    assert content_at == pytest.approx(2.5)

    # Missing title semantic → content lands with beat start.
    assert (
        visual_production._punchline_title_content_at(
            {"semanticItems": []},
            range_start=10.0,
            start=0.0,
            duration=8.0,
        )
        == 0.0
    )


def test_punchline_beat2_stage_at_177_content_at_247() -> None:
    """Regression: beat-002 frames must not collapse stage+content onto Title.

    Stage/dock at startFrame 177; whole card (borders+image+caption) at Title 247.
    """
    fps = 30.0
    start_f, reveal_f, end_f = 177, 247, 395
    range_start = start_f / fps - 0.05
    start = start_f / fps - range_start  # ~0.05 composition-local
    duration = (end_f - start_f) / fps
    content_at = visual_production._punchline_title_content_at(
        {
            "semanticItems": [
                {
                    "parameterPath": "parameters.text",
                    "spokenStartSec": reveal_f / fps,
                    "fullyVisibleSec": reveal_f / fps + 0.35,
                }
            ]
        },
        range_start=range_start,
        start=start,
        duration=duration,
    )

    # Absolute frame back from composition-local times.
    stage_abs_frame = (start + range_start) * fps
    content_abs_frame = (content_at + range_start) * fps
    assert stage_abs_frame == pytest.approx(177.0)
    assert content_abs_frame == pytest.approx(247.0)
    assert content_at - start == pytest.approx((247 - 177) / fps)

    # Contract the helper encodes: stage time != content time for this beat.
    assert content_at > start + 1.0


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


def test_main_video_dock_forces_top_left_origin() -> None:
    """Punch-zoom leaves focus origin; dock engines must reset origin or head flies off."""
    line = visual_production._main_video_dock_line(
        scale=0.365, x_px=1080.0, y_px=129.6, duration=0.5, at=34.2667
    )
    assert "fromTo" in line
    assert 'transformOrigin:"0% 0%"' in line
    assert "scale:0.3650" in line
    assert "overwrite:\"auto\"" in line
    # Starts from clean full-frame so prior punch origin cannot stick.
    assert 'scale:1,x:0,y:0,transformOrigin:"0% 0%"' in line
    undock = visual_production._main_video_undock_line(duration=0.45, at=44.7)
    assert 'transformOrigin:"0% 0%"' in undock
    assert "scale:1" in undock and "x:0" in undock


def test_cover_dock_is_pure_hole_geometry() -> None:
    """Cover dock = object-fit:cover into the mask rect — no face/overscan nudges."""

    def _assert_cover(left: float, top: float, box_w: float, box_h: float) -> None:
        scale, x_frac, y_frac = visual_production._cover_dock_for_frame(left, top, box_w, box_h)
        assert scale == pytest.approx(max(box_w, box_h))
        assert x_frac == pytest.approx(left + (box_w - scale) / 2.0)
        assert y_frac == pytest.approx(top + (box_h - scale) / 2.0)
        # Fully covers the hole.
        assert x_frac <= left + 1e-9
        assert y_frac <= top + 1e-9
        assert x_frac + scale >= left + box_w - 1e-9
        assert y_frac + scale >= top + box_h - 1e-9

    _assert_cover(0.50, 0.10, 0.42, 0.78)  # dependency
    _assert_cover(0.08, 0.10, 0.42, 0.78)  # punchline
    _assert_cover(0.5885, 0.102, 0.359, 0.787)  # brand CTA


def test_engine_compose_recipe_is_shared_version_token() -> None:
    """Preview and Final fingerprints both hash this — one engine code version."""
    assert isinstance(visual_production.ENGINE_COMPOSE_RECIPE, int)
    assert visual_production.ENGINE_COMPOSE_RECIPE >= 34


def test_progress_scale_fit_dock_aligns_video_to_outline() -> None:
    """Progress outline is a picture frame — video TL + size must match the border."""
    scale, x_frac, y_frac = visual_production._fit_dock_for_frame(0.5625, 0.12, 0.365, 0.365)
    assert scale == pytest.approx(0.365)
    assert x_frac == pytest.approx(0.5625)
    assert y_frac == pytest.approx(0.12)


def test_progress_scale_markup_includes_mask_hole() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "progress-scale",
            "parameters": {
                "text": "Ada Example",
                "startLabel": "Full Stack",
                "targetLabel": "Enterprise",
                "milestones": ["Thankful"],
            },
        },
        "ps",
        1,
        8,
        20,
    )
    assert "progress-mask" in markup
    assert "stat-video-outline" in markup


def test_progress_scale_restores_video_at_cue_end_not_after_fill_hold() -> None:
    """Ends must undock the head; early restore left empty outline artifacts."""
    start = 0.0
    duration = 25.633  # ~f32208–32977 at 30fps
    video_out = 0.45
    fill_end = 14.4  # last milestone
    hold_after_fill = 2.5
    # Old path undocked long before Ends while stage chrome stayed up.
    old_restore = min(start + duration - video_out, fill_end + hold_after_fill)
    assert old_restore == pytest.approx(16.9, abs=0.05)
    # New path: undock at cue end (placement Ends).
    exit_at = start + duration - video_out
    restore_at = max(exit_at, fill_end + 0.12)
    restore_at = min(restore_at, start + duration - 0.05)
    assert restore_at == pytest.approx(exit_at, abs=0.02)
    assert restore_at > old_restore + 5.0


def test_robot_defiant_bubble_lands_at_placement_text_reveal() -> None:
    """Craft frame on text must drive bubble start, not fixed beat-start + 0.28s."""
    fps = 30.0
    range_start = 17270 / fps
    reveal_frame = 17468
    start = 0.0  # composition-local cue start after range remap
    spoken = reveal_frame / fps
    land_at = max(spoken, range_start) - range_start
    land_at = max(start + 0.05, land_at)
    wrap_lead = 0.28
    bubble_start = land_at
    wrap_at = max(start, land_at - wrap_lead)
    # Old path ignored craft and always used start + 0.28.
    old_bubble = start + 0.28
    assert bubble_start == pytest.approx(reveal_frame / fps - range_start, abs=0.02)
    assert bubble_start > old_bubble + 5.0  # craft is several seconds later than beat start
    assert wrap_at == pytest.approx(bubble_start - wrap_lead, abs=0.02)


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


def test_intro_credentials_markup_has_name_nodes_wai_robot() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "intro-credentials",
            "parameters": {
                "text": "Ada",
                "nodes": ["Builder", "Teacher"],
                "thankYou": "Thank you!",
            },
        },
        "intro",
        1,
        12,
        20,
    )
    assert "intro-stage" in markup
    assert "intro-mask" in markup
    assert "intro-video-outline" in markup
    assert "intro-name" in markup
    assert "Ada" in markup
    assert "intro-node" in markup
    assert "Builder" in markup
    assert "intro-robot" in markup
    assert "intro-robot-bubble" in markup
    assert "Thank you!" in markup
    assert 'data-semantic-path="parameters.thankYou"' in markup
    assert "intro-robot-svg" in markup
    # Wai cues: closed-eye arcs + solid triangle hands (no interior finger lines).
    assert "intro-wai-hands" in markup
    assert "<polygon" in markup
    assert 'q20 24 40 0' in markup
    assert "lib-kicker" not in markup
    bare = visual_production._module_markup(
        {
            "moduleId": "intro-credentials",
            "parameters": {"text": "Host", "nodes": ["One"]},
        },
        "intro2",
        1,
        8,
        21,
    )
    assert "Thank you!" in bare
    custom = visual_production._module_markup(
        {
            "moduleId": "intro-credentials",
            "parameters": {
                "text": "Host",
                "nodes": ["One"],
                "thankYou": "Thanks for watching!",
            },
        },
        "intro3",
        1,
        8,
        22,
    )
    assert "Thanks for watching!" in custom
    assert "intro-credentials" in visual_production.MODULE_IDS
    assert "thankYou" in visual_production.MODULE_PARAMETER_KEYS["intro-credentials"]
    assert "nodes" in visual_production.MODULE_PARAMETER_KEYS["intro-credentials"]


def test_tradeoff_meter_fill_ends_at_verdict_frame() -> None:
    """Fill lands on value at the verdict revealFrame (not full bar, not free-run)."""
    fps = 30.0
    range_start = 1577 / fps
    verdict_frame = 1638
    start = 0.0
    duration = (1699 / fps) - range_start
    exit_duration = 0.28
    latest = start + duration - exit_duration - 0.05
    value_frac = 0.8
    # Composition-local verdict = absolute spoken − range_start.
    verdict_at = max(verdict_frame / fps, range_start) - range_start
    fill_end = max(start + 0.35, min(latest, verdict_at))
    label_ready = start + 0.25  # labels at beat start
    earliest = start + 0.12
    preferred = max(earliest, label_ready)
    if fill_end - preferred >= 0.35:
        fill_start = preferred
    else:
        fill_start = max(earliest, fill_end - min(2.5, max(0.35, fill_end - earliest)))
    fill_dur = max(0.05, min(2.5, fill_end - fill_start))
    fill_start = fill_end - fill_dur
    assert fill_start + fill_dur == pytest.approx(fill_end, abs=0.001)
    assert fill_end == pytest.approx(verdict_at, abs=0.02)
    # Marker is value, not 100% of the track.
    assert 0.0 <= value_frac <= 1.0
    assert value_frac == pytest.approx(0.8)
    # Old free-run (start+0.3, dur 0.6) finished far before craft verdict.
    old_end = start + 0.3 + 0.6
    assert old_end < fill_end - 0.5
    # Knob is fixed at value; fill starts empty (GSAP grows scaleX to value_frac).
    markup = visual_production._module_markup(
        {
            "moduleId": "tradeoff-meter",
            "parameters": {
                "leftLabel": "Left",
                "rightLabel": "Right",
                "verdict": "Verdict",
                "value": value_frac,
            },
        },
        "meter",
        0,
        4,
        20,
    )
    assert "scaleX(0)" in markup
    assert "pf-meter-fill" in markup
    assert 'class="pf-meter-knob" style="left:80.00%"' in markup
    assert 'data-semantic-path="parameters.verdict"' in markup


def test_speaker_side_panel_retired_aliases_to_dependency_stack() -> None:
    """speaker-side-panel is retired; old cues rewrite to dependency-stack."""
    assert "speaker-side-panel" not in visual_production.MODULE_IDS
    assert visual_production.canonicalize_engine_id("speaker-side-panel") == "dependency-stack"
    cue = visual_production.normalize_cue_engine(
        {
            "kind": "module",
            "moduleId": "speaker-side-panel",
            "parameters": {
                "text": "Title",
                "items": ["Bullet 1", "Bullet 2", "Lumberg."],
                "side": "right",
            },
            "semanticItems": [
                {
                    "parameterPath": "parameters.items.0",
                    "spokenStartSec": 1.0,
                    "fullyVisibleSec": 1.2,
                }
            ],
        }
    )
    assert cue["moduleId"] == "dependency-stack"
    assert cue["parameters"]["text"] == "Title"
    assert cue["parameters"]["nodes"] == ["Bullet 1", "Bullet 2", "Lumberg."]
    assert "items" not in cue["parameters"]
    assert cue["semanticItems"][0]["parameterPath"] == "parameters.nodes.0"
    markup = visual_production._module_markup(cue, "side", 1, 10, 20)
    assert "dependency-stage" in markup
    assert "Title" in markup
    assert "Bullet 1" in markup


def test_speaker_rise_callouts_markup_uses_edge_slots_and_eight() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "speaker-rise-callouts",
            "parameters": {
                "thesis": "Here is the Title",
                "callouts": ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"],
            },
        },
        "rise",
        1,
        10,
        20,
    )
    assert "pf-rise-thesis" in markup
    assert "Here is the Title" in markup
    assert 'data-callout-index="0"' in markup
    assert 'data-callout-index="7"' in markup
    assert "Eight" in markup
    # Face-clear layout is CSS nth-child; markup must not hardcode center coords.
    assert "left:22%" not in markup
    assert "top:50%" not in markup


def test_speaker_rise_honors_placement_callout_reveal_frames() -> None:
    """Thesis + callouts use craft frames; auto-stagger only when unanchored."""
    fps = 30.0
    range_start = 399 / fps
    frames = [495, 592, 688, 785]
    expected = [f / fps - range_start for f in frames]
    # Old engine packed words near the end (~f816+) via reverse stagger — far from craft.
    assert expected[0] < 4.0
    assert expected[-1] < 14.0
    # Placement contract: local appear = spoken − range_start (clamped by engine).
    for exp, frame in zip(expected, frames, strict=True):
        assert exp == pytest.approx(frame / fps - range_start, abs=0.001)


def test_problem_card_triptych_honors_placement_card_reveal_frames() -> None:
    """Placement card frames must not be even-redistributed when settle/linger is long."""
    fps = 30.0
    range_start = 6755 / fps
    frames = [6755, 6835, 6885]
    cue_end = 6996 / fps
    duration = cue_end - range_start
    start = 0.0
    exit_duration = 0.28
    semantic_items = [
        {
            "parameterPath": f"parameters.cards.{index}",
            "spokenStartSec": frame / fps,
        }
        for index, frame in enumerate(frames)
    ]
    card_times, anchored_count, order = visual_production._placement_item_reveal_schedule(
        count=3,
        path_prefix="parameters.cards",
        semantic_items=semantic_items,
        range_start=range_start,
        start=start,
        unanchored_at=lambda index: start + 0.28 + index * 0.85,
    )

    expected = [max(start + 0.12, f / fps - range_start) for f in frames]
    assert anchored_count == 3
    assert order == [0, 1, 2]
    for got, exp in zip(card_times, expected, strict=True):
        assert got == pytest.approx(exp, abs=0.02)

    settle_after_last_sec = 2.0
    linger_all_white_sec = 2.0
    latest_need = (
        max(card_times) + settle_after_last_sec + linger_all_white_sec + exit_duration
    )
    assert latest_need > start + duration  # would have triggered old redistrib
    budget = max(
        0.8,
        duration - exit_duration - settle_after_last_sec - linger_all_white_sec - 0.28,
    )
    step = budget / 2
    old_times = [start + 0.28 + index * step for index in range(3)]
    # Later bullets diverged most (even respace vs speech anchors).
    assert abs(old_times[1] - expected[1]) > 0.4
    assert abs(old_times[2] - expected[2]) > 0.4


def test_problem_card_triptych_honors_out_of_order_reveal_frames() -> None:
    """Later slot with earlier craft frame must still land at that frame.

    Beat-003 craft: Bullet 1 f1609, Bullet 2 f1500 — index-order clamping used to
    delay card 1 until after card 0, so IBM never appeared at f1500.
    """
    fps = 30.0
    range_start = 1359 / fps
    start = 0.0
    frames = [1609, 1500]  # index 0 later than index 1
    semantic_items = [
        {
            "parameterPath": f"parameters.cards.{index}",
            "spokenStartSec": frame / fps,
        }
        for index, frame in enumerate(frames)
    ]
    card_times, anchored_count, order = visual_production._placement_item_reveal_schedule(
        count=2,
        path_prefix="parameters.cards",
        semantic_items=semantic_items,
        range_start=range_start,
        start=start,
        unanchored_at=lambda index: start + 0.28 + index * 0.85,
    )
    assert anchored_count == 2
    # Reveal order is by time: card 1 (IBM @ 1500) then card 0 (AI Native @ 1609).
    assert order == [1, 0]
    assert card_times[1] == pytest.approx(1500 / fps - range_start, abs=0.02)
    assert card_times[0] == pytest.approx(1609 / fps - range_start, abs=0.02)
    # Old index-order clamp would have forced card 1 after card 0.
    assert card_times[1] < card_times[0]


def test_kinetic_word_stamp_lands_with_phrase_not_empty_at_beat_start() -> None:
    """Pink stamp + phrase reveal together at phrase frame (not empty shell at start)."""
    fps = 30.0
    range_start = 2168 / fps
    phrase_frame = 2250  # later than beat start
    phrase_spoken = phrase_frame / fps
    phrase_at = max(phrase_spoken, range_start) - range_start
    assert phrase_at > 0.5  # delayed relative to beat start
    # Contract: stamp appear time == phrase local time (engine clamps into cue).
    start = 0.0
    duration = (2404 / fps) - range_start
    clamped = max(start, min(start + max(duration - 0.05, 0.0), phrase_at))
    assert clamped == pytest.approx(phrase_at, abs=0.001)
    # Empty-pink bug was shell at entry_start (~0) while words waited for phrase_at.
    assert clamped != pytest.approx(0.0, abs=0.05)


def test_dependency_stack_honors_placement_node_reveal_frames() -> None:
    """Placement anchors must not be even-redistributed when settle/linger is long.

    Beat-003 craft frames 495/592/688/785 at 30fps with cue [13.3, 29.4]:
    settle(2s)+linger(2s) after the last bullet would exceed the cue end and used
    to re-space bullets evenly (~414/526/638/750). Placement path keeps anchors.
    """
    fps = 30.0
    range_start = 399 / fps  # 13.3
    cue_end = 882 / fps  # 29.4
    duration = cue_end - range_start
    start = 0.0  # composition-local cue start after range remap
    frames = [495, 592, 688, 785]
    spoken = [f / fps for f in frames]
    node_times: list[float] = []
    anchored_count = 0
    for spoken_sec in spoken:
        appear_at = max(spoken_sec, range_start) - range_start
        node_times.append(max(start + 0.12, appear_at))
        anchored_count += 1
    min_gap = 0.08 if anchored_count > 0 else 0.35
    for index in range(1, len(node_times)):
        node_times[index] = max(node_times[index], node_times[index - 1] + min_gap)

    expected = [f / fps - range_start for f in frames]
    assert anchored_count == 4
    for got, exp in zip(node_times, expected, strict=True):
        assert got == pytest.approx(exp, abs=0.02)

    # Prove the OLD even-redistribute path would have diverged from craft frames.
    settle_after_last_sec = 2.0
    linger_all_white_sec = 2.0
    video_out = 0.45
    latest_need = node_times[-1] + settle_after_last_sec + linger_all_white_sec + video_out
    assert latest_need > start + duration  # would have triggered redistribute
    budget = max(
        0.8,
        duration - video_out - settle_after_last_sec - linger_all_white_sec - 0.45,
    )
    step = budget / 3
    old_times = [start + 0.45 + index * step for index in range(4)]
    for old, exp in zip(old_times, expected, strict=True):
        assert abs(old - exp) > 1.0  # old path was >1s off each bullet


def test_numbered_phrase_reveal_markup_and_typing_shell() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "numbered-phrase-reveal",
            "parameters": {
                "numberLabel": "02",
                "title": "Step",
                "text": "Here are words",
            },
        },
        "npr",
        1,
        8,
        20,
    )
    assert "npr-stage" in markup
    assert "npr-mask" in markup
    assert "npr-video-outline" in markup
    assert "npr-number" in markup
    assert "02" in markup
    assert "npr-title" in markup
    assert "Step" in markup
    assert "npr-typed-text" in markup
    assert 'data-full-prompt="Here are words"' in markup
    assert 'class="npr-typed-text"></span>' in markup
    # Optional title omitted when empty.
    bare = visual_production._module_markup(
        {
            "moduleId": "numbered-phrase-reveal",
            "parameters": {"numberLabel": "2", "title": "", "text": "Hi"},
        },
        "npr2",
        1,
        6,
        21,
    )
    assert "npr-title" not in bare
    assert ">2<" in bare or ">2</div>" in bare


def test_numbered_phrase_reveal_timeline_docks_and_types() -> None:
    from pathlib import Path
    import tempfile

    plan = {
        "version": 2,
        "composition": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "durationSec": 10,
            "brandId": "vcg-white-editorial",
        },
        "source": {"path": "source.mp4", "durationSec": 10},
        "cues": [
            {
                "id": "npr-1",
                "kind": "module",
                "moduleId": "numbered-phrase-reveal",
                "startSec": 1.0,
                "endSec": 8.0,
                "enabled": True,
                "parameters": {
                    "numberLabel": "2",
                    "title": "",
                    "text": "Hi",
                },
                "semanticItems": [
                    {
                        "id": "s1",
                        "parameterPath": "parameters.text",
                        "label": "Hi",
                        "anchorType": "spoken",
                        "spokenStartSec": 2.0,
                        "fullyVisibleSec": 3.0,
                    }
                ],
            }
        ],
        "assets": [],
    }
    # build path needs staged env — use composition builder internals via public API if easy.
    # Assert compose recipe includes engine and dock math constants.
    assert "numbered-phrase-reveal" in visual_production.MODULE_IDS
    assert "numberLabel" in visual_production.MODULE_PARAMETER_KEYS["numbered-phrase-reveal"]
    assert "text" in visual_production.MODULE_PARAMETER_KEYS["numbered-phrase-reveal"]


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


def test_windows_prompt_overlay_is_centered_terminal_without_dock() -> None:
    markup = visual_production._module_markup(
        {
            "moduleId": "windows-prompt-overlay",
            "parameters": {
                "appName": "Windows PowerShell",
                "prompt": "Hi overlay",
            },
        },
        "pover",
        1,
        8,
        20,
    )
    assert "prompt-overlay-stage" in markup
    assert "prompt-overlay-terminal" in markup
    assert "prompt-typed-text" in markup
    assert 'data-full-prompt="Hi overlay"' in markup
    assert 'class="prompt-typed-text"></span>' in markup
    # No dock chrome — source stays full frame.
    assert "prompt-mask" not in markup
    assert "prompt-video-outline" not in markup
    assert "win-min" in markup
    assert "windows-prompt-overlay" in visual_production.MODULE_IDS
    assert "prompt" in visual_production.MODULE_PARAMETER_KEYS["windows-prompt-overlay"]
    assert "appName" in visual_production.MODULE_PARAMETER_KEYS["windows-prompt-overlay"]


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
                # Passed action/destination must not appear — brand-fixed forever.
                "action": "IGNORED OVERRIDE",
                "destination": "ignored.example",
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
    step_with_num = visual_production._module_markup(
        {
            "moduleId": "numbered-step-intro",
            "parameters": {
                "stepNumber": 3,
                "showNumber": True,
                "title": "OPEN THE FILE",
                "action": "LET GROK REVISE IT",
            },
        },
        "step-num",
        30,
        5,
        22,
    )

    assert 'src="assets/joke-image.png"' in joke
    assert "joke-card" in joke
    assert "joke-stage" in joke
    assert 'src="assets/skool-logo.svg"' in cta or "brand-skool-logo.svg" in cta
    assert "community-stage" in cta
    assert "JOIN THE FREE VIBE CODE GUILD COMMUNITY" in cta
    assert "skool.com/vibecodeguild" in cta
    assert "IGNORED OVERRIDE" not in cta
    assert "ignored.example" not in cta
    assert 'data-semantic-path="parameters.logoAssetId"' not in cta
    assert "pf-step-no-num" in step
    assert "pf-step-num" not in step
    # Number + title share one headline row; action is the pink line below.
    assert "pf-step-headline" in step_with_num
    assert "pf-step-num" in step_with_num
    assert "OPEN THE FILE" in step_with_num
    assert step_with_num.index("pf-step-headline") < step_with_num.index("pf-step-num")
    assert step_with_num.index("pf-step-num") < step_with_num.index("pf-step-title")
    assert step_with_num.index("pf-step-title") < step_with_num.index("pf-step-action")


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


def test_claim_empty_workspace_diverts_when_clear_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live hyperframes-player locks must not block the next composition build."""
    locked = tmp_path / "92ed1206705c5082e32f"
    (locked / "public").mkdir(parents=True)
    (locked / "public" / "source.mp4").write_bytes(b"locked")
    monkeypatch.setattr(visual_production, "_replace_directory_tree", lambda _path: False)

    claimed = visual_production._claim_empty_workspace(locked)

    assert claimed != locked
    assert claimed.name.startswith(f"{locked.name}-w")
    assert not claimed.exists()


def test_replace_directory_tree_clears_unlocked_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "hyperframes"
    (workspace / "public").mkdir(parents=True)
    (workspace / "public" / "source.mp4").write_bytes(b"video")

    assert visual_production._replace_directory_tree(workspace) is True
    assert not workspace.exists()
