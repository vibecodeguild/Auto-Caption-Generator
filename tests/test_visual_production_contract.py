import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VISUAL_ROOT = ROOT / "visual-production"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_module_catalog_matches_visual_plan_schema() -> None:
    catalog = _json(VISUAL_ROOT / "modules" / "catalog.json")
    schema = _json(VISUAL_ROOT / "schemas" / "visual-plan.schema.json")

    catalog_ids = [module["id"] for module in catalog["modules"]]
    module_definitions = ["punchlineCue", "sourceHoldCue", "sidePanelCue", "progressCue", "dependencyCue", "comparisonCue"]
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
    assert len(recipe_ids) == 33
    assert len(recipe_ids) == len(set(recipe_ids))
    assert module_ids.isdisjoint(recipe_ids)
    assert all(item["name"] and item["description"] and item["speakerMode"] for item in recipes)
    supported = {
        "full-screen-talking", "talking-left", "talking-right", "talking-bottom-left",
        "talking-top-left", "talking-bottom-right", "talking-top-right", "computer-screen-only",
    }
    assert all(item["allowedLayouts"] and set(item["allowedLayouts"]) <= supported for item in [*modules, *recipes])


def test_suggestions_schema_records_reuse_and_b_roll_audits() -> None:
    schema = _json(VISUAL_ROOT / "schemas" / "visual-suggestions.schema.json")
    coverage = schema["properties"]["coverage"]

    assert coverage["required"] == ["reuseAudit", "bRollAudit"]
    assert "reusedRecipeIds" in coverage["properties"]["reuseAudit"]["required"]
    assert coverage["properties"]["bRollAudit"]["properties"]["decision"]["enum"] == ["planned", "not-suitable"]


def test_suggestions_schema_records_per_graphic_variety_and_speaker_safety() -> None:
    schema = _json(VISUAL_ROOT / "schemas" / "visual-suggestions.schema.json")
    suggestion = schema["properties"]["suggestions"]["items"]["properties"]

    assert suggestion["candidateTreatmentIds"]["minItems"] == 3
    assert "visualFamily" in suggestion
    assert suggestion["speakerSafety"]["$ref"] == "#/$defs/speakerSafety"
    assert schema["$defs"]["speakerSafety"]["properties"]["maxSpeakerAbsenceSec"]["maximum"] == 2

    plan_schema = _json(VISUAL_ROOT / "schemas" / "visual-plan.schema.json")
    assert plan_schema["$defs"]["compositionParameters"]["properties"]["speakerSafety"]["$ref"] == "#/$defs/speakerSafety"


def test_suggestions_schema_records_scene_approval_and_library_ranking() -> None:
    schema = _json(VISUAL_ROOT / "schemas" / "visual-suggestions.schema.json")
    suggestion = schema["properties"]["suggestions"]["items"]["properties"]

    assert suggestion["scenePacket"]["$ref"] == "#/$defs/scenePacket"
    assert suggestion["rankedCandidates"]["minItems"] == 3
    assert suggestion["decision"]["properties"]["status"]["enum"] == ["pending", "approved", "revision-requested"]
    assert len(schema["$defs"]["sceneLayout"]["enum"]) == 8


def test_suggestions_schema_records_fixed_counts_cadence_and_bound_evidence() -> None:
    schema = _json(VISUAL_ROOT / "schemas" / "visual-suggestions.schema.json")
    coverage = schema["properties"]["coverage"]["properties"]
    suggestion = schema["properties"]["suggestions"]["items"]["properties"]

    assert coverage["decisionCounts"]["$ref"] == "#/$defs/decisionCounts"
    assert coverage["cadenceAudit"]["$ref"] == "#/$defs/cadenceAudit"
    assert schema["$defs"]["cadenceAudit"]["properties"]["maxAllowedGapSec"]["const"] == 5
    assert suggestion["meaningfulChanges"]["items"]["$ref"] == "#/$defs/meaningfulChange"
    assert suggestion["approvalEvidence"]["$ref"] == "#/$defs/approvalEvidence"
