from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import story_assets, visual_production


def _library(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "creator-library"
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: root)
    monkeypatch.setattr(story_assets, "project_root", lambda: tmp_path / "public-checkout")
    monkeypatch.setattr(story_assets, "probe_visual_source", lambda path: {"durationSec": 5, "width": 1920, "height": 1080, "fps": 30})
    return root


def _rendered_sample(plan_path: Path, suggestion_id: str, treatment_id: str) -> Path:
    """A sample frame with the receipt the app writes when HyperFrames produced it."""
    sample = story_assets.approval_sample_path(plan_path, suggestion_id, treatment_id)
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"sample")
    story_assets._write_sample_receipt(sample, suggestion_id=suggestion_id, treatment_id=treatment_id)
    return sample


def _visual_project(tmp_path: Path) -> Path:
    root = tmp_path / "private-project"
    for folder in ("source", "assets", "visual-production"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    (root / "source" / "locked-cut.mp4").write_bytes(b"video")
    plan = {
        "schemaVersion": 1,
        "project": {"id": "project-1", "name": "Pilot", "createdAt": "now", "updatedAt": "now"},
        "source": {"video": "source/locked-cut.mp4", "transcript": ""},
        "composition": {"width": 1920, "height": 1080, "fps": 30, "durationSec": 60, "brandId": "vcg-white-editorial"},
        "assets": [], "protectedFootage": [], "cues": [],
    }
    plan_path = root / "visual-production" / "visual-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path


def test_creator_library_import_deduplicates_by_checksum(tmp_path: Path, monkeypatch) -> None:
    _library(tmp_path, monkeypatch)
    source = tmp_path / "falling-knife.mp4"
    source.write_bytes(b"same-ai-video")

    first, _library_data, first_duplicate = story_assets.import_creator_asset(source)
    second, library_data, second_duplicate = story_assets.import_creator_asset(source)

    assert not first_duplicate
    assert second_duplicate
    assert first["id"] == second["id"]
    assert len(library_data["assets"]) == 1
    assert first["tags"] == ["falling", "knife"]


def test_creator_library_asset_is_frozen_into_project_and_usage_recorded(tmp_path: Path, monkeypatch) -> None:
    library_root = _library(tmp_path, monkeypatch)
    source = tmp_path / "callback.mp4"
    source.write_bytes(b"callback")
    asset, _library_data, _duplicate = story_assets.import_creator_asset(source, {"name": "Recurring callback", "series": "Finance Shane"})
    plan_path = _visual_project(tmp_path)

    cue, plan = story_assets.freeze_creator_asset(plan_path, asset["id"], start_sec=10, end_sec=15)

    assert cue["startSec"] == 10
    assert plan["assets"][0]["origin"]["type"] == "creator-library"
    assert (plan_path.parents[1] / plan["assets"][0]["path"]).read_bytes() == b"callback"
    updated = json.loads((library_root / "library.json").read_text(encoding="utf-8"))["assets"][0]
    assert updated["usageCount"] == 1


def test_placed_library_asset_carries_the_receipt_that_authorised_it(tmp_path: Path, monkeypatch) -> None:
    """An asset cue with no authorising suggestion made canDeliver permanently false."""
    _library(tmp_path, monkeypatch)
    source = tmp_path / "callback.mp4"
    source.write_bytes(b"callback")
    asset, _library_data, _duplicate = story_assets.import_creator_asset(source)
    plan_path = _visual_project(tmp_path)

    cue, _plan = story_assets.freeze_creator_asset(plan_path, asset["id"], start_sec=10, end_sec=15)

    suggestion_id = cue["parameters"]["planningSuggestionId"]
    suggestions = story_assets.load_visual_suggestions(plan_path)["suggestions"]
    authorising = next(item for item in suggestions if item["id"] == suggestion_id)
    assert authorising["decision"]["status"] == "approved"
    assert authorising["decision"]["decidedBy"] == "creator-direct-placement"
    assert authorising["cueId"] == cue["id"]


def test_visual_suggestions_validate_status_category_and_timing(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    data = {"schemaVersion": 1, "suggestions": [{"id": "s1", "status": "proposed", "category": "stock", "startSec": 4, "endSec": 9, "editorialPurpose": "visual relief", "stockBrief": {"literalQueries": ["office at night"]}}]}

    saved = story_assets.save_visual_suggestions(plan_path, data)

    assert story_assets.load_visual_suggestions(plan_path) == saved
    data["suggestions"][0]["category"] = "unknown"
    with pytest.raises(ValueError, match="category"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_visual_suggestions_persist_reuse_and_b_roll_coverage(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    data = {
        "schemaVersion": 1,
        "coverage": {
            "reuseAudit": {
                "contractVersion": story_assets.SUGGESTIONS_CONTRACT_VERSION,
                "reviewed": True,
                "reusedModuleIds": ["speaker-side-panel"],
                "reusedRecipeIds": ["windows-prompt-typing"],
                "creatorLibraryQueries": ["excel office workflow"],
                "bespokeRationales": [],
            },
            "bRollAudit": {
                "reviewed": True,
                "decision": "planned",
                "rationale": "One transition benefits from literal office footage.",
            },
            "variationAudit": {"reviewed": True, "familyCounts": {}, "treatmentCounts": {}, "intentionalSeriesIds": [], "warnings": []},
        },
        "suggestions": [{
            "id": "b-roll-1", "status": "proposed", "category": "stock", "timelineLane": "b-roll",
            "startSec": 4, "endSec": 9, "editorialPurpose": "Visual relief",
            "stockBrief": {"literalQueries": ["office at night"]},
            "scenePacket": {
                "screenshotTimeSec": 6, "purpose": "Visual relief", "contentDensity": "low",
                "bRollFit": "Literal office footage carries the transition.",
                "motionOpportunities": [], "spokenBeats": [], "protectedRegions": [],
            },
            "meaningfulChanges": [],
            "decision": {"status": "pending", "selectedTreatmentId": None, "notes": ""},
        }],
    }

    saved = story_assets.save_visual_suggestions(plan_path, data)

    assert saved["coverage"]["reuseAudit"]["reusedRecipeIds"] == ["windows-prompt-typing"]
    assert story_assets.load_visual_suggestions(plan_path)["coverage"]["bRollAudit"]["decision"] == "planned"


def test_planned_b_roll_coverage_requires_a_timeline_suggestion(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    data = {
        "schemaVersion": 1,
        "coverage": {
            "reuseAudit": {"contractVersion": story_assets.SUGGESTIONS_CONTRACT_VERSION, "reviewed": True, "reusedModuleIds": [], "reusedRecipeIds": [], "creatorLibraryQueries": [], "bespokeRationales": ["No authored graphics needed."]},
            "bRollAudit": {"reviewed": True, "decision": "planned", "rationale": "Use B-roll."},
        },
        "suggestions": [],
    }

    with pytest.raises(ValueError, match="requires at least one B-roll suggestion"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_reuse_audit_requires_source_or_bespoke_reason_for_graphics(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    data = {
        "schemaVersion": 1,
        "coverage": {
            "reuseAudit": {"contractVersion": story_assets.SUGGESTIONS_CONTRACT_VERSION, "reviewed": True, "reusedModuleIds": [], "reusedRecipeIds": [], "creatorLibraryQueries": [], "bespokeRationales": []},
            "bRollAudit": {"reviewed": True, "decision": "not-suitable", "rationale": "The software demonstration is already the visual."},
        },
        "suggestions": [{
            "id": "graphic-1", "status": "proposed", "category": "graphic", "timelineLane": "graphics",
            "startSec": 4, "endSec": 9, "editorialPurpose": "Explain a result",
        }],
    }

    with pytest.raises(ValueError, match="reused source or a bespoke rationale"):
        story_assets.save_visual_suggestions(plan_path, data)


TEST_LAYOUT = "talking-left"
# The speaker rectangle is measured from the recording setup, not chosen. Fixtures read the same
# source the validator does, so a geometry change updates both instead of silently diverging.
LAYOUT_SPEAKER_BOUNDS = story_assets.measured_speaker_bounds(TEST_LAYOUT)
# talking-left occupies the left half, so a safe overlay lives clear of its right edge.
SAFE_OVERLAY_BOUNDS = {"x": .52, "y": .08, "width": .44, "height": .78}


def _scene_packet(screenshot_time: float) -> dict:
    return {
        "layout": TEST_LAYOUT,
        "screenshotTimeSec": screenshot_time,
        "purpose": "Punctuate the spoken conclusion",
        "contentDensity": "low",
        "motionOpportunities": ["Reveal the conclusion on the spoken beat"],
        "spokenBeats": [{"timeSec": screenshot_time, "text": "the result"}],
        "protectedRegions": [{"label": "speaker", "bounds": dict(LAYOUT_SPEAKER_BOUNDS)}],
        "bRollFit": "Direct address is stronger than B-roll.",
    }


def _audited_graphic(suggestion_id: str, start_sec: float, end_sec: float, recipe_id: str, family: str) -> dict:
    """A complete graphic suggestion. There is one contract, so there is one fixture."""
    middle = (start_sec + end_sec) / 2
    candidates = [recipe_id, "speaker-side-panel", "problem-card-triptych"]
    return {
        "id": suggestion_id,
        "status": "proposed",
        "category": "graphic",
        "timelineLane": "graphics",
        "startSec": start_sec,
        "endSec": end_sec,
        "editorialPurpose": "Explain the spoken beat",
        "moduleId": recipe_id,
        "candidateTreatmentIds": candidates,
        "rankedCandidates": [
            {"treatmentId": treatment, "rank": rank, "fitReason": "Compatible with the recorded layout."}
            for rank, treatment in enumerate(candidates, 1)
        ],
        "visualFamily": family,
        "selectionRationale": "This choreography matches the editorial job while varying the surrounding scenes.",
        "intentionalRepeat": False,
        "meaningfulChanges": [],
        "scenePacket": _scene_packet(middle),
        "speakerSafety": {
            "checked": True,
            "mode": "left-container",
            "speakerBounds": dict(LAYOUT_SPEAKER_BOUNDS),
            "overlayOcclusionBounds": [dict(SAFE_OVERLAY_BOUNDS)],
            "verifiedAtSec": [start_sec, middle, end_sec],
            "maxSpeakerAbsenceSec": 0,
        },
        "approvalEvidence": {
            "status": "sample-required",
            "selectedTreatmentId": recipe_id,
            "sourceFrameTimeSec": middle,
            "representativeTimeSec": middle,
            "representativeState": "Resolved treatment state",
        },
        "decision": {"status": "pending", "selectedTreatmentId": recipe_id, "notes": ""},
        "rejectionHistory": [],
    }


def _audited_coverage(treatment_ids: list[str]) -> dict:
    return {
        "reuseAudit": {
            "contractVersion": story_assets.SUGGESTIONS_CONTRACT_VERSION,
            "reviewed": True,
            "reusedModuleIds": treatment_ids,
            "reusedRecipeIds": [],
            "creatorLibraryQueries": [],
            "bespokeRationales": [],
        },
        "bRollAudit": {
            "reviewed": True,
            "decision": "not-suitable",
            "rationale": "The software demonstration is already the visual.",
        },
        "variationAudit": {
            "reviewed": True,
            "familyCounts": {},
            "treatmentCounts": {},
            "intentionalSeriesIds": [],
            "warnings": [],
        },
    }


def _approval_contract_graphic() -> tuple[dict, dict]:
    graphic = _audited_graphic("graphic-v3", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    return graphic, _audited_coverage(["kinetic-word-punctuation"])


def test_approval_contract_requires_scene_packet_ranked_candidates_and_decision(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    data = {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]}

    saved = story_assets.save_visual_suggestions(plan_path, data)

    assert saved["suggestions"][0]["scenePacket"]["layout"] == "talking-left"
    assert saved["suggestions"][0]["decision"]["status"] == "pending"
    graphic.pop("scenePacket")
    with pytest.raises(ValueError, match="scenePacket"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_swapping_a_treatment_in_loop_b_cannot_inherit_the_earlier_approval(tmp_path: Path, monkeypatch) -> None:
    """A Loop B note may replace the treatment entirely; that swap needs its own approval."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    sample = _rendered_sample(plan_path, graphic["id"], "kinetic-word-punctuation")
    graphic["decision"].update({"status": "approved", "decidedAt": "now"})
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    graphic["moduleId"] = "problem-card-triptych"
    coverage["reuseAudit"]["reusedModuleIds"] = ["problem-card-triptych"]

    with pytest.raises(ValueError, match="Re-approve the scene after swapping its treatment"):
        story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})


def test_rejected_planning_choice_keeps_history_and_routes_review_note(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    suggestion, _data, plan = story_assets.decide_suggestion(
        plan_path,
        graphic["id"],
        action="request-another",
        notes="This treatment covers the spreadsheet controls.",
    )

    assert suggestion["decision"]["status"] == "revision-requested"
    assert suggestion["rejectionHistory"][0]["selectedTreatmentId"] == "kinetic-word-punctuation"
    assert plan["reviews"][0]["note"] == "This treatment covers the spreadsheet controls."
    assert plan["reviews"][0]["directive"] == "replace-all"


def test_production_gate_blocks_pending_scene_choice(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})
    plan = story_assets.load_visual_plan(plan_path)

    report = visual_production.visual_production_gate_report(plan_path, plan)

    assert report["planningApprovalPassed"] is False
    assert report["canExportFinal"] is False
    assert any("pre-render scene review" in issue for issue in report["planningApprovalIssues"])


def test_cadence_audit_allows_long_graphic_with_timed_internal_reveals() -> None:
    suggestion = {
        "startSec": 0,
        "endSec": 14,
        "category": "graphic",
        "moduleId": "speaker-side-panel",
        "meaningfulChanges": [
            {"timeSec": 4, "kind": "internal-reveal", "description": "Reveal first point"},
            {"timeSec": 8, "kind": "internal-reveal", "description": "Reveal second point"},
            {"timeSec": 12, "kind": "emphasis-change", "description": "Emphasize conclusion"},
        ],
    }

    audit = story_assets._cadence_audit([suggestion], 14)

    assert audit["completeCoverage"] is True
    assert audit["maxObservedGapSec"] == 4
    assert audit["violations"] == []


def test_the_five_second_cadence_applies_everywhere_with_no_exemption() -> None:
    """There is no hold concept. Protected footage still earns motion every five seconds."""
    unchanged = {"startSec": 0, "endSec": 12, "meaningfulChanges": []}
    held = {
        **unchanged,
        "category": "clean-speaker",
    }

    assert any("five seconds" in issue["reason"] for issue in story_assets._cadence_audit([unchanged], 12)["violations"])
    assert any("five seconds" in issue["reason"] for issue in story_assets._cadence_audit([held], 12)["violations"])


def test_a_protected_span_needs_real_cues_not_notes_about_movement() -> None:
    """Writing {"kind": "punch-zoom"} on bare footage renders nothing. Only cues count."""
    promised = {
        "id": "h1", "startSec": 0, "endSec": 12, "category": "protected-footage",
        "meaningfulChanges": [
            {"timeSec": 4.0, "kind": "punch-zoom", "description": "Push in on the prompt field."},
            {"timeSec": 8.0, "kind": "ui-action", "description": "Generation completes."},
        ],
    }

    assert any("five seconds" in issue["reason"] for issue in story_assets._cadence_audit([promised], 12)["violations"])


def test_a_protected_span_passes_when_real_punch_zooms_and_callouts_cover_it() -> None:
    """The same intent, expressed as treatments the renderer executes."""
    scenes = [
        {"id": "h1", "startSec": 0, "endSec": 12, "category": "protected-footage", "meaningfulChanges": []},
        {
            "id": "z1", "startSec": 3, "endSec": 7, "category": "graphic", "moduleId": "source-punch-zoom",
            "meaningfulChanges": [{"timeSec": 5.0, "kind": "punch-zoom", "description": "Settle on the prompt field."}],
        },
        {
            "id": "c1", "startSec": 7, "endSec": 11, "category": "graphic", "moduleId": "ui-callout",
            "meaningfulChanges": [{"timeSec": 9.0, "kind": "callout-change", "description": "Name the generated slide."}],
        },
    ]

    assert story_assets._cadence_audit(scenes, 12)["violations"] == []


def test_a_long_protected_span_with_no_motion_is_reported() -> None:
    """The 101-second unbroken stretch that made a 15-minute video feel empty."""
    marathon = {
        "id": "h06", "startSec": 0, "endSec": 101.6, "meaningfulChanges": [],
        "category": "protected-footage",
    }

    violations = story_assets._cadence_audit([marathon], 101.6)["violations"]

    assert len(violations) >= 1
    assert story_assets._cadence_audit([marathon], 101.6)["maxObservedGapSec"] > 100


def test_graphic_approval_requires_evidence_bound_to_selected_treatment(tmp_path: Path, monkeypatch) -> None:
    plan_path = _visual_project(tmp_path)
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-creator-library")
    graphic, coverage = _approval_contract_graphic()
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    with pytest.raises(ValueError, match="one-frame sample"):
        story_assets.decide_suggestion(plan_path, graphic["id"], action="approve")

    sample = _rendered_sample(plan_path, graphic["id"], "kinetic-word-punctuation")
    approved, _data, _plan = story_assets.decide_suggestion(plan_path, graphic["id"], action="approve")

    assert approved["decision"]["status"] == "approved"
    assert approved["approvalEvidence"]["status"] == "sample-ready"


def test_registered_module_prepares_exact_sample_when_history_is_missing(tmp_path: Path, monkeypatch) -> None:
    plan_path = _visual_project(tmp_path)
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-creator-library")
    graphic, coverage = _approval_contract_graphic()
    graphic["moduleId"] = "speaker-side-panel"
    graphic["candidateTreatmentIds"] = ["speaker-side-panel", "kinetic-word-punctuation", "problem-card-triptych"]
    graphic["rankedCandidates"][0]["treatmentId"] = "speaker-side-panel"
    graphic["rankedCandidates"][1]["treatmentId"] = "kinetic-word-punctuation"
    graphic["decision"]["selectedTreatmentId"] = "speaker-side-panel"
    coverage["reuseAudit"]["reusedModuleIds"] = ["speaker-side-panel"]
    expected = story_assets.approval_sample_path(plan_path, graphic["id"], "speaker-side-panel")

    def fake_render(_plan_path: Path, _suggestion: dict) -> Path:
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(b"exact-sample")
        return expected

    monkeypatch.setattr(story_assets, "_render_registered_module_sample", fake_render)
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    prepared, data = story_assets.prepare_suggestion_approval_evidence(plan_path, graphic["id"])

    assert prepared["approvalEvidence"]["status"] == "sample-ready"
    assert prepared["approvalEvidence"]["selectedTreatmentId"] == "speaker-side-panel"
    assert data["coverage"]["decisionCounts"]["graphicTreatments"] == 1


def test_numbered_example_treatment_is_a_five_star_locked_default_module() -> None:
    """It is used ten times in one video, so it is registered rather than left as a design note."""
    catalog = story_assets.load_visual_catalog()
    treatment = next(item for item in catalog["modules"] if item["id"] == "numbered-example-card")
    superseded = next(item for item in catalog["modules"] if item["id"] == "numbered-step-intro")

    assert treatment["kind"] == "module"
    assert treatment["id"] in visual_production.MODULE_IDS
    assert treatment["creatorRating"] == 5
    assert treatment["lockedDefault"] is True
    assert treatment["reusePolicy"] == "intentional-series"
    assert "example number and title" in treatment["intents"]
    assert superseded["lockedDefault"] is False
    assert superseded["supersededBy"] == "numbered-example-card"


def test_treatment_rating_and_lock_are_saved_separately(tmp_path: Path, monkeypatch) -> None:
    library_root = tmp_path / "creator-library"
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: library_root)
    monkeypatch.setattr(story_assets, "_inside", lambda _path, _parent: False)

    rated, _library = story_assets.update_treatment_metadata("tradeoff-meter", {"creatorRating": 4})
    locked, library = story_assets.update_treatment_metadata("tradeoff-meter", {"lockedDefault": True})

    assert rated["creatorRating"] == 4
    assert rated["lockedDefault"] is False
    assert locked["creatorRating"] == 4
    assert locked["lockedDefault"] is True
    assert len(library["treatments"][0]["history"]) == 2


def _delivered_project(tmp_path: Path, monkeypatch, *, reviews: list[dict] | None = None) -> tuple[Path, Path, Path]:
    """A project where the approved graphic actually rendered as an enabled cue."""
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    sample = _rendered_sample(plan_path, graphic["id"], "kinetic-word-punctuation")
    graphic["status"] = "built"
    graphic["cueId"] = "cue-1"
    graphic["decision"].update({"status": "approved", "decidedAt": "now"})
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "speaker-side-panel",
        "startSec": graphic["startSec"], "endSec": graphic["endSec"], "enabled": True,
        "parameters": {"planningSuggestionId": graphic["id"]}, "semanticItems": [],
    }]
    plan["reviews"] = reviews or []
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})
    final_video = tmp_path / "final.mp4"
    final_video.write_bytes(b"video")
    library_root = tmp_path / "creator-library"
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: library_root)
    monkeypatch.setattr(story_assets, "_inside", lambda _path, _parent: False)
    monkeypatch.setattr(story_assets, "find_ffmpeg", lambda: Path("ffmpeg"))

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"preview")
        return story_assets.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(story_assets.subprocess, "run", fake_run)
    return plan_path, final_video, library_root


def test_final_delivery_captures_unique_treatment_previews_and_usage(tmp_path: Path, monkeypatch) -> None:
    plan_path, final_video, library_root = _delivered_project(tmp_path, monkeypatch)

    report = story_assets.record_treatment_usage(plan_path, final_video)

    assert report["treatmentsRecorded"] == 1
    assert report["introducedTreatmentIds"] == ["kinetic-word-punctuation"]
    assert (library_root / "recipe-previews" / "kinetic-word-punctuation.png").is_file()
    assert (library_root / "motion-previews" / "kinetic-word-punctuation.mp4").is_file()
    treatment = story_assets.load_treatment_library()["treatments"][0]
    assert treatment["usageCount"] == 1
    assert treatment["usage"][0]["suggestionId"] == "graphic-v3"


def test_harvest_skips_a_treatment_the_full_review_still_has_notes_on(tmp_path: Path, monkeypatch) -> None:
    """Loop A approved the frame; Loop B left a note. The library must not learn from it."""
    plan_path, final_video, _library_root = _delivered_project(tmp_path, monkeypatch, reviews=[{
        "id": "review-1", "itemType": "cue", "itemId": "cue-1",
        "startSec": 4, "endSec": 9, "note": "The panel lands a beat late.",
        "directive": "targeted", "status": "changes-requested",
        "createdAt": "now", "updatedAt": "now",
    }])

    report = story_assets.record_treatment_usage(plan_path, final_video)

    assert report["treatmentsRecorded"] == 0
    assert report["candidates"] == 0


def test_harvest_reports_a_failure_instead_of_recording_zero(tmp_path: Path, monkeypatch) -> None:
    plan_path, final_video, _library_root = _delivered_project(tmp_path, monkeypatch)
    monkeypatch.setattr(
        story_assets.subprocess,
        "run",
        lambda command, **_kwargs: story_assets.subprocess.CompletedProcess(command, 1, "", "no such frame"),
    )

    with pytest.raises(RuntimeError, match="could not capture a still frame"):
        story_assets.record_treatment_usage(plan_path, final_video)


def test_a_rated_preview_is_not_replaced_by_a_later_unrated_use(tmp_path: Path, monkeypatch) -> None:
    """The canonical example Cook ranks against should be the best use, not the most recent."""
    plan_path, final_video, library_root = _delivered_project(tmp_path, monkeypatch)
    preview = library_root / "recipe-previews" / "kinetic-word-punctuation.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"the-rated-frame")
    library = story_assets.load_treatment_library()
    library["treatments"].append({"id": "kinetic-word-punctuation", "creatorRating": 5, "createdAt": "then", "history": [], "usage": []})
    story_assets.save_treatment_library(library)

    story_assets.record_treatment_usage(plan_path, final_video)

    assert preview.read_bytes() == b"the-rated-frame"
    history = list((library_root / "treatment-preview-history").rglob("*.png"))
    assert history, "the new use is still recorded in the per-use history"


def test_an_unrated_preview_is_refreshed_by_a_later_use(tmp_path: Path, monkeypatch) -> None:
    plan_path, final_video, library_root = _delivered_project(tmp_path, monkeypatch)
    preview = library_root / "recipe-previews" / "kinetic-word-punctuation.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"the-old-frame")

    story_assets.record_treatment_usage(plan_path, final_video)

    assert preview.read_bytes() == b"preview"


def test_lowering_the_contract_version_is_rejected_outright(tmp_path: Path, monkeypatch) -> None:
    """It was the single field that disabled the approval contract, the gate, and the harvest."""
    plan_path, final_video, _library_root = _delivered_project(tmp_path, monkeypatch)
    data = story_assets.load_visual_suggestions(plan_path)
    data["coverage"]["reuseAudit"]["contractVersion"] = 2
    story_assets._write_visual_suggestions(story_assets.suggestions_path(plan_path), data, refreshed=True)

    with pytest.raises(ValueError, match="contractVersion must be 3"):
        story_assets.record_treatment_usage(plan_path, final_video)


def test_graphic_suggestion_requires_library_comparison_and_speaker_safety(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic.pop("candidateTreatmentIds")
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="compare at least three"):
        story_assets.save_visual_suggestions(plan_path, data)

    graphic["candidateTreatmentIds"] = ["kinetic-word-punctuation", "speaker-side-panel", "problem-card-triptych"]
    graphic.pop("speakerSafety")
    with pytest.raises(ValueError, match="speaker-safety audit"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_graphic_suggestion_rejects_overlay_over_speaker(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic["speakerSafety"]["overlayOcclusionBounds"] = [{"x": .2, "y": .4, "width": .5, "height": .4}]
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="places an overlay over the speaker"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_speaker_bounds_come_from_measured_geometry_not_the_suggestion(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    # A plausible but invented speaker rectangle. Previously this was believed and validated against.
    graphic["speakerSafety"]["speakerBounds"] = {"x": .04, "y": .28, "width": .26, "height": .62}
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="do not match the measured geometry"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_overlay_is_checked_against_the_layout_the_scene_was_recorded_in(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    # An overlay on the right half is safe in talking-left and unsafe in talking-right. The only
    # thing that changes between these two cases is which scene the speaker was recorded in.
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}
    assert story_assets.save_visual_suggestions(plan_path, data)["suggestions"][0]["id"] == "graphic-1"

    mirrored = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    mirrored["scenePacket"]["layout"] = "talking-right"
    mirrored["scenePacket"]["protectedRegions"] = [
        {"label": "speaker", "bounds": dict(story_assets.measured_speaker_bounds("talking-right"))}
    ]
    mirrored["speakerSafety"]["speakerBounds"] = dict(story_assets.measured_speaker_bounds("talking-right"))
    data["suggestions"] = [mirrored]

    with pytest.raises(ValueError, match="places an overlay over the speaker"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_graphic_without_a_known_layout_cannot_claim_speaker_safety(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic["scenePacket"]["layout"] = "talking-diagonal"
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="layout"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_full_frame_speaker_mode_is_not_available(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic["speakerSafety"]["mode"] = "brief-full-frame-hit"
    graphic["speakerSafety"]["maxSpeakerAbsenceSec"] = 2
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="unknown speakerSafety mode"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_graphic_may_not_hide_the_speaker_at_all(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic["speakerSafety"]["maxSpeakerAbsenceSec"] = 1.5
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="may not hide the speaker"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_graphic_suggestions_reject_consecutive_visual_family(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    first = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    second = _audited_graphic("graphic-2", 10, 15, "list-reveal-pinned-thesis", "kinetic-type")
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation", "list-reveal-pinned-thesis"]), "suggestions": [first, second]}

    with pytest.raises(ValueError, match="repeats visual family"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_diverse_face_safe_graphic_suggestions_pass_audit(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    first = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    second = _audited_graphic("graphic-2", 10, 15, "list-reveal-pinned-thesis", "structured-list")
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation", "list-reveal-pinned-thesis"]), "suggestions": [first, second]}

    saved = story_assets.save_visual_suggestions(plan_path, data)

    assert len(saved["suggestions"]) == 2


def test_visual_safety_gate_requires_built_cue_to_preserve_audit(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic.update({"status": "built", "cueId": "cue-graphic-1"})
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}
    story_assets.save_visual_suggestions(plan_path, data)
    plan = story_assets.load_visual_plan(plan_path)

    assert visual_production.visual_safety_gate_issues(plan_path, plan) == ["graphic-1 has not been realized as its registered plan cue."]

    plan["cues"] = [{
        "id": "cue-graphic-1",
        "kind": "composition",
        "compositionId": "test-composition",
        "sceneId": "scene-graphic-1",
        "startSec": 4,
        "endSec": 9,
        "enabled": True,
        "parameters": {
            "recipeId": graphic["moduleId"],
            "speakerSafety": graphic["speakerSafety"],
            "visualFamily": graphic["visualFamily"],
            "candidateTreatmentIds": graphic["candidateTreatmentIds"],
            "selectionRationale": graphic["selectionRationale"],
            "meaningfulChanges": graphic["meaningfulChanges"],
            "approvalEvidence": story_assets.load_visual_suggestions(plan_path)["suggestions"][0]["approvalEvidence"],
            "planningSuggestionId": "graphic-1",
            "approvedTreatmentId": graphic["decision"]["selectedTreatmentId"],
        },
        "semanticItems": [],
    }]

    assert visual_production.visual_safety_gate_issues(plan_path, plan) == []


def test_creator_library_search_matches_callback_metadata(tmp_path: Path, monkeypatch) -> None:
    _library(tmp_path, monkeypatch)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    story_assets.import_creator_asset(source, {"name": "Shane catches a falling knife", "tags": ["investing", "risk"], "series": "Finance Shane"})

    assert story_assets.search_creator_library("falling knife")[0]["name"] == "Shane catches a falling knife"
    assert story_assets.search_creator_library("finance")[0]["series"] == "Finance Shane"


def test_untrusted_stock_download_url_is_rejected(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    with pytest.raises(ValueError, match="not trusted"):
        story_assets.select_pexels_candidate(
            plan_path, "s1",
            {"id": "123", "provider": "pexels", "downloadUrl": "https://attacker.example/video.mp4"},
            start_sec=1, end_sec=3,
        )


def test_approved_graphic_suggestion_builds_editable_timeline_cue(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    # punchline-reveal is a registered module that is compatible with the fixture layout.
    graphic = _audited_graphic("graphic-1", 8, 12, "punchline-reveal", "punchline")
    graphic["moduleParameters"] = {
        "accentColor": "#FF00CE",
        "text": "Approved exact copy",
        "kicker": "APPROVED KICKER",
    }
    graphic["approvalEvidence"]["selectedTreatmentId"] = "punchline-reveal"
    graphic["decision"] = {"status": "approved", "selectedTreatmentId": "punchline-reveal", "notes": "", "decidedAt": "now"}
    coverage = _audited_coverage([])
    coverage["reuseAudit"]["reusedModuleIds"] = ["punchline-reveal"]
    sample = _rendered_sample(plan_path, "graphic-1", "punchline-reveal")
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    cue, plan = story_assets.build_nonmedia_suggestion(plan_path, "graphic-1")

    assert cue["moduleId"] == "punchline-reveal"
    assert cue["parameters"]["accentColor"] == "#FF00CE"
    assert cue["parameters"]["text"] == "Approved exact copy"
    assert cue["parameters"]["kicker"] == "APPROVED KICKER"
    assert plan["cues"][0]["id"] == cue["id"]
    assert story_assets.load_visual_suggestions(plan_path)["suggestions"][0]["status"] == "built"


def test_writing_around_the_public_api_is_refused(tmp_path: Path) -> None:
    """Cook called the private writer directly, skipping the approval-evidence refresh."""
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()

    with pytest.raises(RuntimeError, match="Use save_visual_suggestions"):
        story_assets._write_visual_suggestions(
            story_assets.suggestions_path(plan_path),
            {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]},
        )


def test_a_hand_set_evidence_status_is_corrected_on_the_next_read(tmp_path: Path, monkeypatch) -> None:
    """Even a file written outside the app is re-derived, so the claim cannot survive."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    graphic["approvalEvidence"]["status"] = "sample-ready"
    graphic["approvalEvidence"]["sampleFramePath"] = "previews/visual/approval-samples/invented.png"
    story_assets.suggestions_path(plan_path).parent.mkdir(parents=True, exist_ok=True)
    story_assets.suggestions_path(plan_path).write_text(
        json.dumps({"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]}), encoding="utf-8"
    )

    reloaded = story_assets.load_visual_suggestions(plan_path)

    assert reloaded["suggestions"][0]["approvalEvidence"]["status"] == "sample-required"


def test_a_hand_drawn_sample_frame_is_not_accepted_as_approval_evidence(tmp_path: Path, monkeypatch) -> None:
    """Cook drew the graphic in PIL and dropped it at the expected path. That approves nothing."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    drawing = story_assets.approval_sample_path(plan_path, graphic["id"], "kinetic-word-punctuation")
    drawing.parent.mkdir(parents=True, exist_ok=True)
    drawing.write_bytes(b"a picture drawn by hand, not rendered")

    saved = story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    evidence = saved["suggestions"][0]["approvalEvidence"]
    assert evidence["status"] == "sample-required"
    assert "no render receipt" in evidence["blockedReason"]
    with pytest.raises(ValueError, match="Prepare the exact one-frame sample"):
        story_assets.decide_suggestion(plan_path, graphic["id"], action="approve")


def test_a_signed_sample_frame_is_accepted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    _rendered_sample(plan_path, graphic["id"], "kinetic-word-punctuation")

    saved = story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    assert saved["suggestions"][0]["approvalEvidence"]["status"] == "sample-ready"


def test_editing_a_signed_sample_after_the_fact_invalidates_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    sample = _rendered_sample(plan_path, graphic["id"], "kinetic-word-punctuation")
    sample.write_bytes(b"retouched after rendering")

    saved = story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    assert saved["suggestions"][0]["approvalEvidence"]["blockedReason"] == "the sample frame changed after it was rendered"


def test_a_sample_rendered_for_another_treatment_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    sample = story_assets.approval_sample_path(plan_path, graphic["id"], "kinetic-word-punctuation")
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"sample")
    story_assets._write_sample_receipt(sample, suggestion_id=graphic["id"], treatment_id="speaker-side-panel")

    saved = story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    assert "rendered for speaker-side-panel" in saved["suggestions"][0]["approvalEvidence"]["blockedReason"]


def test_an_unregistered_treatment_cannot_produce_a_sample_at_all(tmp_path: Path, monkeypatch) -> None:
    """The old message told Cook to 'create' a frame, which is what invited the drawing."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})
    data = story_assets.load_visual_suggestions(plan_path)
    data["suggestions"][0]["moduleId"] = "a-treatment-nobody-built"
    story_assets._write_visual_suggestions(story_assets.suggestions_path(plan_path), data, refreshed=True)

    with pytest.raises(ValueError, match="Unknown visual treatment"):
        story_assets.prepare_suggestion_approval_evidence(plan_path, graphic["id"])


def test_one_treatment_may_not_carry_the_plan(tmp_path: Path) -> None:
    """A pass marked 154 of 165 graphics intentionalRepeat and became 46% punch zooms."""
    counts = {"source-punch-zoom": 76, "ui-callout": 63, "numbered-example-card": 10, "dual-comparison": 9}
    families = {"camera-move": 76, "callout": 63, "numbered-example-card": 10, "comparison": 9}

    with pytest.raises(ValueError, match="No treatment may exceed 25% of the plan"):
        story_assets._validate_treatment_variety(counts, families)


def test_two_treatments_may_not_carry_the_plan_between_them(tmp_path: Path) -> None:
    # Each device stays under the single-treatment ceiling; together they still dominate.
    counts = {"source-punch-zoom": 24, "ui-callout": 24, "side-list-panel": 13,
              "result-badge": 13, "tradeoff-meter": 13, "link-chip": 13}
    families = {"camera-move": 24, "callout": 24, "structured-list": 13,
                "outcome": 13, "data-motion": 13, "chip": 13}

    with pytest.raises(ValueError, match="Two devices may not exceed 45%"):
        story_assets._validate_treatment_variety(counts, families)


def test_renaming_the_treatment_does_not_create_variety(tmp_path: Path) -> None:
    """Same device under four names is still the same beat repeating."""
    # No treatment and no pair breaches its ceiling, but one family is three of them.
    counts = {"zoom-a": 12, "zoom-b": 12, "zoom-c": 12, "callout": 18,
              "card": 18, "panel": 14, "badge": 14}
    families = {"camera-move": 36, "callout": 18, "card": 18, "panel": 14, "badge": 14}

    with pytest.raises(ValueError, match="no visual family may exceed 25%"):
        story_assets._validate_treatment_variety(counts, families)


def test_a_varied_plan_passes(tmp_path: Path) -> None:
    counts = {"source-punch-zoom": 10, "ui-callout": 10, "side-list-panel": 8,
              "numbered-example-card": 10, "result-badge": 6, "tradeoff-meter": 6}
    families = {"camera-move": 10, "callout": 10, "structured-list": 8,
                "numbered-example-card": 10, "outcome": 6, "data-motion": 6}

    story_assets._validate_treatment_variety(counts, families)


def test_a_small_plan_is_not_held_to_proportions(tmp_path: Path) -> None:
    """Proportions are meaningless below a handful of graphics."""
    story_assets._validate_treatment_variety({"punchline-reveal": 3}, {"punchline": 3})


def test_a_graphic_that_flashes_for_a_tenth_of_a_second_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4.0, 4.1, "side-list-panel", "structured-list")
    graphic["speakerSafety"]["verifiedAtSec"] = [4.0, 4.05, 4.1]
    coverage = _audited_coverage(["side-list-panel"])

    with pytest.raises(ValueError, match="reads as a glitch, not a visual event"):
        story_assets.save_visual_suggestions(plan_path, {
            "schemaVersion": 1, "coverage": coverage, "suggestions": [graphic],
        })


def _protected_scene(start: float, end: float) -> dict:
    return {
        "id": "h1", "status": "proposed", "category": "protected-footage", "startSec": start, "endSec": end,
        "editorialPurpose": "The click has to be readable.",
        "scenePacket": {
            "layout": "talking-bottom-left", "screenshotTimeSec": (start + end) / 2,
            "purpose": "Software demonstration", "contentDensity": "dense UI",
            "bRollFit": "Not suitable.", "motionOpportunities": [], "spokenBeats": [],
            "protectedRegions": [{"label": "slide canvas", "bounds": {"x": .2, "y": .18, "width": .78, "height": .68}}],
        },
        "meaningfulChanges": [],
        "decision": {"status": "pending", "selectedTreatmentId": None, "notes": ""},
        "rejectionHistory": [],
    }


def test_a_protected_moment_may_not_take_a_whole_chapter_off_the_board(tmp_path: Path) -> None:
    """One video declared 547 seconds protected, which rendered nothing at all."""
    plan_path = _visual_project(tmp_path)
    coverage = _audited_coverage([])
    coverage["reuseAudit"]["bespokeRationales"] = ["Demonstration carries this section."]

    with pytest.raises(ValueError, match="leaves 42.5s of the video with nothing on screen"):
        story_assets.save_visual_suggestions(plan_path, {
            "schemaVersion": 1, "coverage": coverage, "suggestions": [_protected_scene(95.1, 137.6)],
        })


def test_a_short_protected_moment_is_fine(tmp_path: Path) -> None:
    """A punchline or a click still gets to breathe."""
    plan_path = _visual_project(tmp_path)
    coverage = _audited_coverage([])
    coverage["reuseAudit"]["bespokeRationales"] = ["The click has to be readable."]

    saved = story_assets.save_visual_suggestions(plan_path, {
        "schemaVersion": 1, "coverage": coverage, "suggestions": [_protected_scene(95.1, 101.0)],
    })

    assert saved["suggestions"][0]["category"] == "protected-footage"


def test_a_long_protected_scene_is_fine_when_a_treatment_covers_it(tmp_path: Path, monkeypatch) -> None:
    """Protection preserves source geometry; it does not force the whole interval to stay bare."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 20, "side-list-panel", "structured-list")
    coverage = _audited_coverage(["side-list-panel"])

    saved = story_assets.save_visual_suggestions(plan_path, {
        "schemaVersion": 1,
        "coverage": coverage,
        "suggestions": [_protected_scene(4, 20), graphic],
    })

    assert len(saved["suggestions"]) == 2


def test_change_request_keeps_protected_interval_in_timeline_contract(tmp_path: Path, monkeypatch) -> None:
    """Rejecting a treatment must save the note without inventing a protected-footage gap."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-13", 4, 20, "side-list-panel", "structured-list")
    coverage = _audited_coverage(["side-list-panel"])
    story_assets.save_visual_suggestions(plan_path, {
        "schemaVersion": 1,
        "coverage": coverage,
        "suggestions": [_protected_scene(4, 20), graphic],
    })

    suggestion, data, plan = story_assets.decide_suggestion(
        plan_path,
        graphic["id"],
        action="reject",
        notes="Use a different comparison treatment.",
    )

    assert suggestion["status"] == "needs-alternatives"
    assert suggestion["decision"]["status"] == "revision-requested"
    assert suggestion["decision"]["notes"] == "Use a different comparison treatment."
    assert data["coverage"]["decisionCounts"]["timelineDecisions"] == 2
    assert data["coverage"]["decisionCounts"]["graphicTreatments"] == 1
    assert story_assets.load_visual_suggestions(plan_path)["suggestions"][1]["decision"]["notes"] == (
        "Use a different comparison treatment."
    )
    gate = visual_production.visual_production_gate_report(plan_path, plan)
    assert gate["planningApprovalPassed"] is False
    assert gate["canRenderReview"] is False
    assert any("graphic-13 has not been approved" in issue for issue in gate["planningApprovalIssues"])


def test_signed_exact_sample_takes_priority_over_generic_historical_preview(tmp_path: Path, monkeypatch) -> None:
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    historical = tmp_path / "historical.png"
    historical.write_bytes(b"generic-history")
    monkeypatch.setattr(story_assets, "recipe_preview_path", lambda *_args, **_kwargs: historical)
    sample = _rendered_sample(plan_path, graphic["id"], "kinetic-word-punctuation")
    graphic["approvalEvidence"]["sampleFramePath"] = sample.relative_to(
        story_assets.find_visual_root(plan_path)
    ).as_posix()

    story_assets.save_visual_suggestions(
        plan_path,
        {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]},
    )
    saved = story_assets.load_visual_suggestions(plan_path)["suggestions"][0]

    assert saved["approvalEvidence"]["status"] == "sample-ready"
    assert saved["approvalEvidence"]["sampleFramePath"].endswith(".png")


def test_a_long_uncovered_part_of_a_protected_scene_is_still_rejected(tmp_path: Path, monkeypatch) -> None:
    """An overlapping treatment must cover the interval, not merely touch it."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 13, 25, "side-list-panel", "structured-list")
    coverage = _audited_coverage(["side-list-panel"])

    with pytest.raises(ValueError, match="leaves 9.0s of the video with nothing on screen"):
        story_assets.save_visual_suggestions(plan_path, {
            "schemaVersion": 1,
            "coverage": coverage,
            "suggestions": [_protected_scene(4, 25), graphic],
        })


def test_a_graphic_over_a_screen_share_layout_must_name_the_readable_region(tmp_path: Path, monkeypatch) -> None:
    """The precise tool is a rectangle. Requiring it stops whole spans being declared off-limits."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "side-list-panel", "structured-list")
    graphic["scenePacket"]["layout"] = "computer-screen-only"
    graphic["scenePacket"]["protectedRegions"] = []
    graphic["speakerSafety"]["speakerBounds"] = None
    coverage = _audited_coverage(["side-list-panel"])

    with pytest.raises(ValueError, match="List the screen area that must stay readable"):
        story_assets.save_visual_suggestions(plan_path, {
            "schemaVersion": 1, "coverage": coverage, "suggestions": [graphic],
        })


def test_a_graphic_on_a_speaker_led_layout_does_not_need_a_region(tmp_path: Path, monkeypatch) -> None:
    """talking-left is mostly the speaker, so there is no application to keep readable."""
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-library")
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "side-list-panel", "structured-list")
    graphic["scenePacket"]["protectedRegions"] = []
    coverage = _audited_coverage(["side-list-panel"])

    saved = story_assets.save_visual_suggestions(plan_path, {
        "schemaVersion": 1, "coverage": coverage, "suggestions": [graphic],
    })

    assert saved["suggestions"][0]["scenePacket"]["layout"] == "talking-left"


def test_screen_share_layouts_are_the_corner_and_screen_only_ones() -> None:
    assert visual_production.is_screen_share_layout("computer-screen-only") is True
    assert visual_production.is_screen_share_layout("talking-bottom-left") is True
    assert visual_production.is_screen_share_layout("talking-top-right") is True
    assert visual_production.is_screen_share_layout("talking-left") is False
    assert visual_production.is_screen_share_layout("full-screen-talking") is False


def test_a_fabricated_treatment_errors_instead_of_becoming_a_side_panel(tmp_path: Path) -> None:
    """The substitution turned an invented treatment id into a rendered generic graphic."""
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 8, 12, "punchline-reveal", "punchline")
    graphic["decision"] = {"status": "approved", "selectedTreatmentId": "punchline-reveal", "notes": "", "decidedAt": "now"}
    graphic["approvalEvidence"]["selectedTreatmentId"] = "punchline-reveal"
    coverage = _audited_coverage([])
    coverage["reuseAudit"]["reusedModuleIds"] = ["punchline-reveal"]
    sample = _rendered_sample(plan_path, "graphic-1", "punchline-reveal")
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})
    data = story_assets.load_visual_suggestions(plan_path)
    data["suggestions"][0]["moduleId"] = "invented-module"
    story_assets._write_visual_suggestions(story_assets.suggestions_path(plan_path), data, refreshed=True)

    with pytest.raises(ValueError, match="invented-module"):
        story_assets.build_nonmedia_suggestion(plan_path, "graphic-1")


def test_a_recipe_id_holding_a_module_is_rejected(tmp_path: Path) -> None:
    """Crossing the namespaces made an unbuildable recipe look renderable."""
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "speaker-side-panel", "side-panel")
    graphic.pop("moduleId")
    graphic["recipeId"] = "speaker-side-panel"
    coverage = _audited_coverage([])
    coverage["reuseAudit"]["reusedRecipeIds"] = ["speaker-side-panel"]

    with pytest.raises(ValueError, match="modules belong in moduleId"):
        story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})


def test_authored_graphics_cannot_be_saved_without_a_coverage_audit(tmp_path: Path) -> None:
    """Omitting coverage used to skip every reuse, variety and speaker-safety check."""
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")

    with pytest.raises(ValueError, match="needs a coverage block"):
        story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "suggestions": [graphic]})


def test_an_unreviewed_reuse_audit_is_rejected(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    coverage = _audited_coverage(["kinetic-word-punctuation"])
    coverage["reuseAudit"]["reviewed"] = False

    with pytest.raises(ValueError, match="must be completed before the plan is saved"):
        story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})


def test_creator_requested_treatment_lands_on_the_graphics_lane(tmp_path: Path) -> None:
    """The creator can ask for a specific treatment; Cook still has to flesh it out."""
    plan_path = _visual_project(tmp_path)

    suggestion = story_assets.create_recipe_suggestion(
        plan_path, "tradeoff-meter", start_sec=4, end_sec=9
    )

    assert suggestion["timelineLane"] == "graphics"
    assert suggestion["status"] == "needs-alternatives"
    assert suggestion["moduleId"] == "tradeoff-meter"



def test_treatment_catalog_uses_private_preview_when_available(tmp_path: Path, monkeypatch) -> None:
    library = _library(tmp_path, monkeypatch)
    monkeypatch.setattr(story_assets, "project_root", lambda: Path(__file__).resolve().parents[1])
    preview = library / "recipe-previews" / "tradeoff-meter.png"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"private-preview")

    catalog = story_assets.load_visual_catalog()
    recipe = next(item for item in catalog["modules"] if item["id"] == "tradeoff-meter")

    assert recipe["previewAvailable"] is True
    assert story_assets.recipe_preview_path("tradeoff-meter") == preview


def test_review_prompt_includes_only_nonempty_active_notes_and_marks_them_copied(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    plan = story_assets.load_visual_plan(plan_path)
    plan["cues"] = [{
        "id": "cue-1", "kind": "module", "moduleId": "speaker-side-panel",
        "startSec": 10, "endSec": 15, "enabled": True, "parameters": {"reviewLabel": "07 · APPROVED V5 SCENE"},
    }]
    plan["reviews"] = [
        {
            "id": "review-1", "itemId": "cue-1", "itemType": "cue", "startSec": 10, "endSec": 15,
            "note": "Move me to the bottom left.", "directive": "leave-everything-else",
            "status": "changes-requested", "createdAt": "now", "updatedAt": "now",
        },
        {
            "id": "review-empty", "itemId": "suggestion-empty", "itemType": "suggestion", "startSec": 20, "endSec": 25,
            "note": "", "directive": "targeted", "status": "changes-requested", "createdAt": "now", "updatedAt": "now",
        },
    ]
    story_assets.save_visual_plan(plan_path, plan)

    prompt, saved, count = story_assets.build_review_prompt(plan_path, {"review-1"})

    assert count == 1
    assert "cue cue-1 (10.000s-15.000s)" in prompt
    assert "Move me to the bottom left." in prompt
    assert "Treatment: 07 · APPROVED V5 SCENE" in prompt
    assert "leave every other part of this item exactly as it is" in prompt
    assert "review-empty" not in prompt
    assert saved["reviews"][0]["copiedAt"]
    assert "copiedAt" not in saved["reviews"][1]
