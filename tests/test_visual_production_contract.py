import json
from pathlib import Path

import pytest

from app.core import story_assets, visual_production


ROOT = Path(__file__).resolve().parents[1]
VISUAL_ROOT = ROOT / "visual-production"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_module_catalog_matches_visual_plan_schema() -> None:
    catalog = _json(VISUAL_ROOT / "modules" / "catalog.json")
    schema = _json(VISUAL_ROOT / "schemas" / "visual-plan.schema.json")

    catalog_ids = [module["id"] for module in catalog["modules"]]
    module_definitions = [
        "punchlineCue", "sourceHoldCue", "sidePanelCue", "progressCue",
        "dependencyCue", "comparisonCue", "numberedExampleCardCue", "punchZoomCue", "uiCalloutCue",
        "sideListPanelCue", "resultBadgeCue", "linkChipCue", "milestonePathCue", "beforeAfterGradeCue", "lowerThirdFlowCue",
        "threeStepCelebrationCue",
        "careerPathwayCue",
        "listRevealPinnedThesisCue",
        "kineticWordPunctuationCue",
        "numberedStepIntroCue",
        "problemCardTriptychCue",
        "speakerRiseCalloutsCue",
        "conversationBubbleSequenceCue",
        "tradeoffMeterCue",
        "rankMedalHitCue",
        "brandCtaLockupCue",
        "commandPopupStackCue",
        "windowsPromptTypingCue",
        "upliftingSunriseFinaleCue",
    ]
    schema_ids = [schema["$defs"][name]["allOf"][1]["properties"]["moduleId"]["const"] for name in module_definitions]

    assert len(catalog_ids) == len(set(catalog_ids))
    assert set(catalog_ids) == set(schema_ids)


def test_brand_contract_matches_visual_plan_schema() -> None:
    brand = _json(VISUAL_ROOT / "brand" / "vcg-white-editorial.json")
    schema = _json(VISUAL_ROOT / "schemas" / "visual-plan.schema.json")

    assert schema["properties"]["composition"]["properties"]["brandId"]["const"] == brand["id"]


def test_public_css_contains_every_brand_color() -> None:
    brand = _json(VISUAL_ROOT / "brand" / "vcg-white-editorial.json")
    css = (VISUAL_ROOT / "styles" / "vcg-white-editorial.css").read_text(encoding="utf-8").lower()

    assert all(color.lower() in css for color in brand["colors"].values())


def test_recipe_catalog_is_content_neutral_and_not_registered_as_runtime_modules() -> None:
    modules = _json(VISUAL_ROOT / "modules" / "catalog.json")["modules"]
    recipes = _json(VISUAL_ROOT / "recipes" / "catalog.json")["recipes"]

    module_ids = {item["id"] for item in modules}
    recipe_ids = [item["id"] for item in recipes]
    # Every catalog family has been built, so nothing is left in the unrealized-recipe list.
    # A recipe here means a design note with no renderer, which is what starved earlier plans.
    assert len(recipe_ids) == len(set(recipe_ids))
    assert module_ids.isdisjoint(recipe_ids)
    # Archived entries had no implementation in any prior project. They must not be offered to Cook.
    archived = {item["id"] for item in _json(VISUAL_ROOT / "recipes" / "archive-never-built.json")["recipes"]}
    assert archived.isdisjoint(recipe_ids)
    assert all(item["name"] and item["description"] and item["speakerMode"] for item in recipes)
    assert len(module_ids) >= 29
    supported = {
        "full-screen-talking", "talking-left", "talking-right", "talking-bottom-left",
        "talking-top-left", "talking-bottom-right", "talking-top-right", "computer-screen-only",
    }
    assert all(item["allowedLayouts"] and set(item["allowedLayouts"]) <= supported for item in [*modules, *recipes])


# A schema that has never rejected a document is documentation, not a contract. These tests run
# the schema: one known-good document that must validate, and one mutation per rule that must be
# rejected. Asserting on the schema's own text proved nothing about what it accepts.


def _good_suggestions() -> dict:
    return {
        "schemaVersion": 1,
        "coverage": {
            "reuseAudit": {
                "reviewed": True, "contractVersion": 3,
                "reusedModuleIds": ["kinetic-word-punctuation"], "reusedRecipeIds": [],
                "creatorLibraryQueries": [], "bespokeRationales": [],
            },
            "bRollAudit": {"reviewed": True, "decision": "not-suitable", "rationale": "Authored graphics carry it."},
            "variationAudit": {"reviewed": True, "familyCounts": {"kinetic-type": 1}, "treatmentCounts": {"kinetic-word-punctuation": 1}, "intentionalSeriesIds": [], "warnings": []},
            "decisionCounts": {"timelineDecisions": 1, "graphicTreatments": 1, "cleanPerformanceHolds": 0, "protectedFootageDecisions": 0, "bRollDecisions": 0, "unresolvedApprovals": 1},
            "cadenceAudit": {"maxAllowedGapSec": 5, "maxObservedGapSec": 4, "meaningfulChangeCount": 2, "completeCoverage": True, "violations": []},
        },
        "suggestions": [{
            "id": "graphic-1", "status": "proposed", "category": "graphic", "timelineLane": "graphics",
            "startSec": 4, "endSec": 9, "editorialPurpose": "Land the emphasis beat.",
            "moduleId": "kinetic-word-punctuation", "visualFamily": "kinetic-type",
            "selectionRationale": "Matches the spoken emphasis.",
            "candidateTreatmentIds": ["kinetic-word-punctuation", "speaker-side-panel", "problem-card-triptych"],
            "rankedCandidates": [
                {"treatmentId": "kinetic-word-punctuation", "rank": 1, "fitReason": "Exact emphasis intent."},
                {"treatmentId": "speaker-side-panel", "rank": 2, "fitReason": "Compatible supporting layout."},
                {"treatmentId": "problem-card-triptych", "rank": 3, "fitReason": "Compatible if the beat expands."},
            ],
            "speakerSafety": {
                "checked": True, "mode": "right-container", "maxSpeakerAbsenceSec": 0,
                "speakerBounds": {"x": 0, "y": 0.019, "width": 0.504, "height": 0.981},
                "overlayOcclusionBounds": [{"x": 0.52, "y": 0.08, "width": 0.44, "height": 0.78}],
                "verifiedAtSec": [4.5, 6, 8.5],
            },
            "scenePacket": {
                "layout": "talking-left", "screenshotTimeSec": 6, "purpose": "Emphasis",
                "contentDensity": "single phrase", "bRollFit": "Not suitable.",
                "motionOpportunities": [], "spokenBeats": [], "protectedRegions": [],
            },
            "meaningfulChanges": [],
            "approvalEvidence": {
                "status": "sample-required", "selectedTreatmentId": "kinetic-word-punctuation",
                "sourceFrameTimeSec": 6, "representativeTimeSec": 6, "representativeState": "Resolved emphasis",
            },
            "decision": {"status": "pending", "selectedTreatmentId": "kinetic-word-punctuation", "notes": ""},
            "rejectionHistory": [],
        }],
    }


def test_the_published_schema_accepts_a_complete_suggestions_document() -> None:
    visual_production.validate_document_schema("visual-suggestions", _good_suggestions(), label="fixture")


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda doc: doc["suggestions"][0].pop("speakerSafety"), "speakerSafety"),
        (lambda doc: doc["suggestions"][0].pop("visualFamily"), "visualFamily"),
        (lambda doc: doc["suggestions"][0].pop("selectionRationale"), "selectionRationale"),
        (lambda doc: doc["suggestions"][0].update(inventedField="anything"), "invented"),
        (lambda doc: doc["suggestions"][0]["rankedCandidates"].pop(), "rankedCandidates"),
        (lambda doc: doc["suggestions"][0]["candidateTreatmentIds"].pop(), "candidateTreatmentIds"),
        (lambda doc: doc["suggestions"][0]["speakerSafety"].update(mode="brief-full-frame-hit"), "brief-full-frame-hit"),
        (lambda doc: doc["suggestions"][0]["scenePacket"].update(layout="big-face-middle"), "big-face-middle"),
        (lambda doc: doc["coverage"].pop("reuseAudit"), "reuseAudit"),
        (lambda doc: doc["coverage"]["bRollAudit"].update(decision="maybe"), "maybe"),
    ],
)
def test_the_published_schema_rejects_each_broken_rule(mutation, expected: str) -> None:
    document = _good_suggestions()
    mutation(document)

    with pytest.raises(ValueError, match="visual-suggestions.schema.json") as error:
        visual_production.validate_document_schema("visual-suggestions", document, label="fixture")

    assert expected in str(error.value)


def test_a_graphic_stripped_to_the_bare_minimum_is_rejected_by_the_schema_alone() -> None:
    """The audit trail is required of graphics by the schema, not only by the Python validator."""
    document = _good_suggestions()
    document["suggestions"][0] = {
        key: value
        for key, value in document["suggestions"][0].items()
        if key in {"id", "status", "category", "timelineLane", "startSec", "endSec", "editorialPurpose"}
    }

    with pytest.raises(ValueError, match="visual-suggestions.schema.json"):
        visual_production.validate_document_schema("visual-suggestions", document, label="fixture")


@pytest.mark.parametrize("missing", ["scenePacket", "decision", "rankedCandidates"])
def test_the_approval_contract_rejects_a_graphic_missing_its_approval_record(tmp_path: Path, missing: str) -> None:
    """These live in the approval contract rather than the base schema, so prove they still bite."""
    document = _good_suggestions()
    document["suggestions"][0].pop(missing)
    project = tmp_path / "private-project"
    (project / "visual-production").mkdir(parents=True)
    (project / "source").mkdir()
    (project / ".vcg-private").write_text("private\n", encoding="utf-8")
    (project / "source" / "locked-cut.mp4").write_bytes(b"video")
    plan_path = project / "visual-production" / "visual-plan.json"
    plan_path.write_text(json.dumps({
        "schemaVersion": 1,
        "project": {"id": "p", "name": "Pilot", "createdAt": "now", "updatedAt": "now"},
        "source": {"video": "source/locked-cut.mp4", "transcript": ""},
        "composition": {"width": 1920, "height": 1080, "fps": 30, "durationSec": 60, "brandId": "vcg-white-editorial"},
        "assets": [], "protectedFootage": [], "cues": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match=missing if missing != "decision" else "planning decision"):
        story_assets.save_visual_suggestions(plan_path, document)


def test_a_graphic_awaiting_alternatives_is_not_yet_held_to_the_audit_trail() -> None:
    """A recipe the creator requested is a placeholder until Cook fills it in."""
    document = _good_suggestions()
    document["suggestions"][0] = {
        "id": "recipe-1", "status": "needs-alternatives", "category": "graphic", "timelineLane": "graphics",
        "startSec": 4, "endSec": 9, "editorialPurpose": "Requested by the creator",
        "moduleId": "kinetic-word-punctuation",
    }

    visual_production.validate_document_schema("visual-suggestions", document, label="fixture")


def test_a_media_suggestion_does_not_need_the_graphic_audit_trail() -> None:
    """B-roll and library placements carry no speaker geometry to audit."""
    document = _good_suggestions()
    document["coverage"]["bRollAudit"] = {"reviewed": True, "decision": "planned", "rationale": "One cutaway."}
    document["suggestions"] = [{
        "id": "placed-1", "status": "built", "category": "creator-library", "timelineLane": "b-roll",
        "startSec": 4, "endSec": 9, "editorialPurpose": "Recurring callback clip",
        "decision": {"status": "approved", "selectedTreatmentId": "library-creator-1", "decidedBy": "creator-direct-placement", "decidedAt": "now"},
        "rejectionHistory": [],
    }]

    visual_production.validate_document_schema("visual-suggestions", document, label="fixture")
