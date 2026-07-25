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
        },
        "suggestions": [{
            "id": "b-roll-1", "status": "proposed", "category": "stock", "timelineLane": "b-roll",
            "startSec": 4, "endSec": 9, "editorialPurpose": "Visual relief",
            "stockBrief": {"literalQueries": ["office at night"]},
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
            "reuseAudit": {"reviewed": True, "reusedModuleIds": [], "reusedRecipeIds": [], "creatorLibraryQueries": [], "bespokeRationales": ["No authored graphics needed."]},
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
            "reuseAudit": {"reviewed": True, "reusedModuleIds": [], "reusedRecipeIds": [], "creatorLibraryQueries": [], "bespokeRationales": []},
            "bRollAudit": {"reviewed": True, "decision": "not-suitable", "rationale": "The software demonstration is already the visual."},
        },
        "suggestions": [{
            "id": "graphic-1", "status": "proposed", "category": "graphic", "timelineLane": "graphics",
            "startSec": 4, "endSec": 9, "editorialPurpose": "Explain a result",
        }],
    }

    with pytest.raises(ValueError, match="reused source or a bespoke rationale"):
        story_assets.save_visual_suggestions(plan_path, data)


def _audited_graphic(suggestion_id: str, start_sec: float, end_sec: float, recipe_id: str, family: str) -> dict:
    return {
        "id": suggestion_id,
        "status": "proposed",
        "category": "graphic",
        "timelineLane": "graphics",
        "startSec": start_sec,
        "endSec": end_sec,
        "editorialPurpose": "Explain the spoken beat",
        "recipeId": recipe_id,
        "candidateTreatmentIds": [recipe_id, "speaker-side-panel", "problem-card-triptych"],
        "visualFamily": family,
        "selectionRationale": "This choreography matches the editorial job while varying the surrounding scenes.",
        "intentionalRepeat": False,
        "speakerSafety": {
            "checked": True,
            "mode": "left-container",
            "speakerBounds": {"x": .04, "y": .28, "width": .26, "height": .62},
            "overlayOcclusionBounds": [{"x": .38, "y": .08, "width": .56, "height": .78}],
            "verifiedAtSec": [start_sec, (start_sec + end_sec) / 2, end_sec],
            "maxSpeakerAbsenceSec": 0,
        },
    }


def _audited_coverage(recipe_ids: list[str]) -> dict:
    return {
        "reuseAudit": {
            "contractVersion": 2,
            "reviewed": True,
            "reusedModuleIds": [],
            "reusedRecipeIds": recipe_ids,
            "creatorLibraryQueries": [],
            "bespokeRationales": [],
        },
        "bRollAudit": {
            "reviewed": True,
            "decision": "not-suitable",
            "rationale": "The software demonstration is already the visual.",
        },
    }


def _approval_contract_graphic() -> tuple[dict, dict]:
    graphic = _audited_graphic("graphic-v3", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic.update({
        "meaningfulChanges": [],
        "scenePacket": {
            "layout": "talking-left",
            "screenshotTimeSec": 6,
            "purpose": "Punctuate the spoken conclusion",
            "contentDensity": "low",
            "motionOpportunities": ["Reveal the conclusion on the spoken beat"],
            "spokenBeats": [{"timeSec": 6, "text": "the result"}],
            "protectedRegions": [{"label": "speaker", "bounds": {"x": .04, "y": .28, "width": .26, "height": .62}}],
            "bRollFit": "Direct address is stronger than B-roll.",
        },
        "rankedCandidates": [
            {"treatmentId": "kinetic-word-punctuation", "rank": 1, "fitReason": "Exact emphasis intent."},
            {"treatmentId": "speaker-side-panel", "rank": 2, "fitReason": "Compatible supporting layout."},
            {"treatmentId": "problem-card-triptych", "rank": 3, "fitReason": "Compatible if the beat expands."},
        ],
        "decision": {"status": "pending", "selectedTreatmentId": "kinetic-word-punctuation", "notes": ""},
        "approvalEvidence": {
            "status": "sample-required",
            "selectedTreatmentId": "kinetic-word-punctuation",
            "sourceFrameTimeSec": 6,
            "representativeTimeSec": 6,
            "representativeState": "Resolved kinetic emphasis",
        },
        "rejectionHistory": [],
    })
    coverage = _audited_coverage(["kinetic-word-punctuation"])
    coverage["reuseAudit"]["contractVersion"] = 3
    coverage["variationAudit"] = {
        "reviewed": True,
        "familyCounts": {"kinetic-type": 1},
        "treatmentCounts": {"kinetic-word-punctuation": 1},
        "intentionalSeriesIds": [],
        "warnings": [],
    }
    return graphic, coverage


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


def test_cadence_audit_flags_long_unchanged_interval_and_exempts_intentional_hold() -> None:
    unchanged = {"startSec": 0, "endSec": 12, "meaningfulChanges": []}
    held = {
        **unchanged,
        "category": "clean-speaker",
        "intentionalHold": {"reason": "Strong uninterrupted direct-address beat", "representativeTimeSec": 6},
    }

    assert any("five seconds" in issue["reason"] for issue in story_assets._cadence_audit([unchanged], 12)["violations"])
    assert story_assets._cadence_audit([held], 12)["violations"] == []


def test_graphic_approval_requires_evidence_bound_to_selected_treatment(tmp_path: Path, monkeypatch) -> None:
    plan_path = _visual_project(tmp_path)
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-creator-library")
    graphic, coverage = _approval_contract_graphic()
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "coverage": coverage, "suggestions": [graphic]})

    with pytest.raises(ValueError, match="one-frame sample"):
        story_assets.decide_suggestion(plan_path, graphic["id"], action="approve")

    sample = story_assets.approval_sample_path(plan_path, graphic["id"], "kinetic-word-punctuation")
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"sample")
    approved, _data, _plan = story_assets.decide_suggestion(plan_path, graphic["id"], action="approve")

    assert approved["decision"]["status"] == "approved"
    assert approved["approvalEvidence"]["status"] == "sample-ready"


def test_registered_module_prepares_exact_sample_when_history_is_missing(tmp_path: Path, monkeypatch) -> None:
    plan_path = _visual_project(tmp_path)
    monkeypatch.setattr(story_assets, "default_creator_library", lambda: tmp_path / "empty-creator-library")
    graphic, coverage = _approval_contract_graphic()
    graphic["moduleId"] = "speaker-side-panel"
    graphic.pop("recipeId")
    graphic["candidateTreatmentIds"] = ["speaker-side-panel", "kinetic-word-punctuation", "problem-card-triptych"]
    graphic["rankedCandidates"][0]["treatmentId"] = "speaker-side-panel"
    graphic["rankedCandidates"][1]["treatmentId"] = "kinetic-word-punctuation"
    graphic["decision"]["selectedTreatmentId"] = "speaker-side-panel"
    coverage["reuseAudit"]["reusedModuleIds"] = ["speaker-side-panel"]
    coverage["reuseAudit"]["reusedRecipeIds"] = []
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


def test_numbered_example_treatment_is_five_star_locked_default() -> None:
    recipes = story_assets.load_visual_catalog()["recipes"]
    treatment = next(item for item in recipes if item["id"] == "numbered-example-card")
    superseded = next(item for item in recipes if item["id"] == "numbered-step-intro")

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

    rated, _library = story_assets.update_treatment_metadata("metric-crash-chart", {"creatorRating": 4})
    locked, library = story_assets.update_treatment_metadata("metric-crash-chart", {"lockedDefault": True})

    assert rated["creatorRating"] == 4
    assert rated["lockedDefault"] is False
    assert locked["creatorRating"] == 4
    assert locked["lockedDefault"] is True
    assert len(library["treatments"][0]["history"]) == 2


def test_final_delivery_captures_unique_treatment_previews_and_usage(tmp_path: Path, monkeypatch) -> None:
    plan_path = _visual_project(tmp_path)
    graphic, coverage = _approval_contract_graphic()
    sample = story_assets.approval_sample_path(plan_path, graphic["id"], "kinetic-word-punctuation")
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"sample")
    graphic["status"] = "approved"
    graphic["decision"].update({"status": "approved", "decidedAt": "now"})
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

    recorded = story_assets.record_treatment_usage(plan_path, final_video)

    assert recorded == 1
    assert (library_root / "recipe-previews" / "kinetic-word-punctuation.png").is_file()
    assert (library_root / "motion-previews" / "kinetic-word-punctuation.mp4").is_file()
    treatment = story_assets.load_treatment_library()["treatments"][0]
    assert treatment["usageCount"] == 1
    assert treatment["usage"][0]["suggestionId"] == "graphic-v3"


def test_graphic_suggestion_requires_library_comparison_and_speaker_safety(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic.pop("candidateTreatmentIds")
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="compare at least three"):
        story_assets.save_visual_suggestions(plan_path, data)

    graphic["candidateTreatmentIds"] = ["kinetic-word-punctuation", "speaker-side-panel", "problem-card-triptych"]
    graphic.pop("speakerSafety")
    with pytest.raises(ValueError, match="speakerSafety"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_graphic_suggestion_rejects_overlay_over_speaker(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    graphic = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    graphic["speakerSafety"]["overlayOcclusionBounds"] = [{"x": .2, "y": .4, "width": .5, "height": .4}]
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation"]), "suggestions": [graphic]}

    with pytest.raises(ValueError, match="over the protected speaker bounds"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_graphic_suggestions_reject_consecutive_visual_family(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    first = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    second = _audited_graphic("graphic-2", 10, 15, "three-line-principles", "kinetic-type")
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation", "three-line-principles"]), "suggestions": [first, second]}

    with pytest.raises(ValueError, match="repeats visual family"):
        story_assets.save_visual_suggestions(plan_path, data)


def test_diverse_face_safe_graphic_suggestions_pass_audit(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)
    first = _audited_graphic("graphic-1", 4, 9, "kinetic-word-punctuation", "kinetic-type")
    second = _audited_graphic("graphic-2", 10, 15, "three-line-principles", "structured-list")
    data = {"schemaVersion": 1, "coverage": _audited_coverage(["kinetic-word-punctuation", "three-line-principles"]), "suggestions": [first, second]}

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
            "recipeId": graphic["recipeId"],
            "speakerSafety": graphic["speakerSafety"],
            "visualFamily": graphic["visualFamily"],
            "candidateTreatmentIds": graphic["candidateTreatmentIds"],
            "selectionRationale": graphic["selectionRationale"],
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
    story_assets.save_visual_suggestions(plan_path, {"schemaVersion": 1, "suggestions": [{
        "id": "graphic-1", "status": "proposed", "category": "graphic",
        "startSec": 8, "endSec": 12, "editorialPurpose": "Show progress",
        "moduleId": "progress-scale", "moduleParameters": {"targetLabel": "TOP 1%"},
    }]})

    cue, plan = story_assets.build_nonmedia_suggestion(plan_path, "graphic-1")

    assert cue["moduleId"] == "progress-scale"
    assert cue["parameters"]["targetLabel"] == "TOP 1%"
    assert plan["cues"][0]["id"] == cue["id"]
    assert story_assets.load_visual_suggestions(plan_path)["suggestions"][0]["status"] == "built"


def test_recipe_request_stays_unbuilt_and_appears_on_graphics_lane(tmp_path: Path) -> None:
    plan_path = _visual_project(tmp_path)

    suggestion = story_assets.create_recipe_suggestion(
        plan_path,
        "metric-crash-chart",
        start_sec=16,
        end_sec=22,
    )

    assert suggestion["recipeId"] == "metric-crash-chart"
    assert suggestion["status"] == "needs-alternatives"
    assert suggestion["timelineLane"] == "graphics"
    assert story_assets.load_visual_plan(plan_path)["cues"] == []


def test_recipe_catalog_uses_private_preview_when_available(tmp_path: Path, monkeypatch) -> None:
    library = _library(tmp_path, monkeypatch)
    monkeypatch.setattr(story_assets, "project_root", lambda: Path(__file__).resolve().parents[1])
    preview = library / "recipe-previews" / "metric-crash-chart.png"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"private-preview")

    catalog = story_assets.load_visual_catalog()
    recipe = next(item for item in catalog["recipes"] if item["id"] == "metric-crash-chart")

    assert recipe["previewAvailable"] is True
    assert story_assets.recipe_preview_path("metric-crash-chart") == preview


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
