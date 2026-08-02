from __future__ import annotations

import json
from pathlib import Path

from app.core.creator_production import validate_artifact
from app.core.creator_production_menu import (
    density_errors,
    planning_capability_ids_for_profile,
    scrub_retired_catalog_rows,
    vcg_density_enabled,
)


def _empty_catalog() -> dict:
    return {
        "schemaVersion": 1,
        "id": "test-catalog",
        "version": 1,
        "owner": "creator-video-production",
        "sourceIdentity": {
            "hyperframesVersion": "0.7.54",
            "hyperframesCliSha256": "a" * 64,
            "skillPackageVersion": None,
            "skillSha256": "b" * 64,
            "rulesIndexSha256": "c" * 64,
            "rulesTreeSha256": "d" * 64,
            "blueprintsIndexSha256": "e" * 64,
            "blueprintsTreeSha256": "f" * 64,
            "transitionsTreeSha256": "1" * 64,
        },
        "inventorySummary": {},
        "capabilities": [],
        "sourceResources": [],
        "supportResources": [],
        "selectionPolicy": {
            "nativeWorkflowRoutingEnabled": False,
            "automaticRecipeSelectionEnabled": False,
            "sourceOnlySelectable": False,
            "unknownCapabilityFallbackEnabled": False,
            "unknownTransitionFallbackEnabled": False,
        },
    }


def test_scrub_is_noop() -> None:
    catalog = _empty_catalog()
    catalog["capabilities"].append(
        {
            "id": "hf-blueprint:x",
            "category": "native-source-recipe",
            "scope": "blueprint-macro",
            "source": {"relativePath": "x.md", "sha256": "2" * 64, "sectionAnchor": None},
            "inventoryState": "inventoried",
            "sourceAvailability": "source-enabled",
            "adaptationEligibility": "adaptable",
            "implementationMaturity": "source-only",
            "technicalAdmission": "unassessed",
            "productionSelection": "not-selectable",
            "channelPreference": "allowed",
            "aliases": [],
            "requirements": [],
            "knownIncompatibilities": [],
            "linkedImplementationIds": [],
        }
    )
    scrub_retired_catalog_rows(catalog)
    assert len(catalog["capabilities"]) == 1


def test_vcg_v3_profile_density_from_pacing_only() -> None:
    profile = json.loads(
        Path("creator-production/profiles/vcg.v3.json").read_text(encoding="utf-8")
    )
    validate_artifact("channel-profile", profile)
    assert "graphicsLibraryOnly" not in profile["selection"]
    assert profile["pacing"]["maximumMeaningfulChangeGapSec"] == 5
    assert vcg_density_enabled(profile) is True


def test_planning_ids_use_catalog_not_graphics_library() -> None:
    catalog = _empty_catalog()
    catalog["capabilities"].append(
        {
            "id": "hf-blueprint:some-native",
            "category": "native-source-recipe",
            "scope": "blueprint-macro",
            "source": {"relativePath": "x.md", "sha256": "2" * 64, "sectionAnchor": None},
            "inventoryState": "inventoried",
            "sourceAvailability": "source-enabled",
            "adaptationEligibility": "adaptable",
            "implementationMaturity": "source-only",
            "technicalAdmission": "unassessed",
            "productionSelection": "not-selectable",
            "channelPreference": "allowed",
            "aliases": [],
            "requirements": [],
            "knownIncompatibilities": [],
            "linkedImplementationIds": [],
        }
    )
    profile = {
        "selection": {"fullCatalogEvaluationRequired": False},
        "capabilities": {"preferred": []},
    }
    ids = planning_capability_ids_for_profile(catalog, profile)
    assert ids == ["hf-blueprint:some-native"]


def test_density_rejects_sparse_plan() -> None:
    total_frames = 14 * 60 * 30
    frames = list(range(0, total_frames, 64 * 30))
    errors = density_errors(
        verified_change_frames=frames,
        verified_carries=[],
        total_frames=total_frames,
        fps={"numerator": 30, "denominator": 1},
        channel_profile={
            "pacing": {
                "maximumMeaningfulChangeGapSec": 5,
                "maximumContinuousCarrySec": 45,
            }
        },
    )
    codes = {item["code"] for item in errors}
    assert "under-dense-visual-plan" in codes or "under-dense-visual-plan-count" in codes


def test_density_allows_dense_plan() -> None:
    total_frames = 60 * 30
    frames = list(range(0, total_frames, 5 * 30))
    errors = density_errors(
        verified_change_frames=frames,
        verified_carries=[],
        total_frames=total_frames,
        fps={"numerator": 30, "denominator": 1},
        channel_profile={
            "pacing": {
                "maximumMeaningfulChangeGapSec": 5,
                "maximumContinuousCarrySec": 45,
            }
        },
    )
    assert errors == []
