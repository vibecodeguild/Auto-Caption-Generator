from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.creator_capabilities import inventory_hyperframes_capabilities
from app.core.creator_governance import (
    evaluate_episode_repetition,
    resolve_sequence_selection,
    validate_analysis_ledger,
    validate_semantic_manifest,
    validate_source_evidence,
)
from app.core.creator_evidence import validate_source_layout_classification
from app.core.creator_production import compile_episode_manifest
from tests.test_creator_production import _manifest


SHA = "a" * 64


def _capture_catalog() -> dict:
    return {
        "schemaVersion": 1,
        "id": "creator-obs-capture-layouts",
        "version": 1,
        "frame": {"width": 1920, "height": 1080},
        "source": {
            "authority": "creator-approved-capture-facts",
            "sourceDocumentSha256": "b" * 64,
            "measurementMethod": "fixture",
            "readOnlyLegacyRecovery": True,
            "executionAuthority": False,
        },
        "layouts": {
            layout_id: {
                "obsScene": f"OBS {layout_id}",
                "speakerBounds": (
                    None
                    if layout_id == "computer-screen-only"
                    else {"x": 0, "y": 0, "width": 0.5, "height": 1}
                ),
                "origin": "obs-geometry",
                "evidence": "fixture",
            }
            for layout_id in (
                "full-screen-talking",
                "talking-left",
                "talking-right",
                "talking-bottom-left",
                "talking-top-left",
                "talking-bottom-right",
                "talking-top-right",
                "computer-screen-only",
            )
        },
    }


def _channel() -> dict:
    root = Path(__file__).resolve().parents[1]
    return json.loads(
        (root / "creator-production" / "profiles" / "vcg.v1.json").read_text(encoding="utf-8")
    )


def _catalog() -> dict:
    root = Path(__file__).resolve().parents[1]
    skill_root = Path.home() / ".codex" / "skills" / "hyperframes-animation"
    cli = root / "node_modules" / "hyperframes" / "dist" / "cli.js"
    if not skill_root.is_dir() or not cli.is_file():
        pytest.skip("Pinned local HyperFrames installation is unavailable.")
    return inventory_hyperframes_capabilities(
        skill_root=skill_root,
        hyperframes_cli_path=cli,
        hyperframes_version="0.7.54",
    )


def _candidate(capability_id: str, semantic: float) -> dict:
    return {
        "capabilityId": capability_id,
        "hardExclusions": {
            "globallyBlocked": False,
            "creatorProhibited": False,
            "episodeRestricted": False,
            "semanticallyIncompatible": False,
            "assetUnavailable": False,
            "speakerUnsafe": False,
            "runtimeIncompatible": False,
            "contentCapacityFailure": False,
            "timingInvalid": False,
            "repetitionProhibited": False,
        },
        "criterionValues": {
            "semantic-fitness": semantic,
            "whole-video-contrast": 1,
            "creator-preference": 1,
            "implementation-maturity": 1,
        },
    }


def _analysis_ledger() -> dict:
    return {
        "schemaVersion": 1,
        "episodeId": "episode",
        "lockedCutSha256": SHA,
        "wordTimingSha256": SHA,
        "totalFrames": 100,
        "propositions": [
            {
                "id": "p1",
                "startWordId": "w1",
                "endWordId": "w1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 30,
                "text": "Click Open in PowerPoint then use /plan",
                "semanticBeatKind": "claim",
                "relationshipToPrevious": None,
                "relationshipToNext": None,
                "evidenceRefs": ["word:w1"],
                "assetNeeds": [],
                "uncertainty": 0,
                "unresolvedReasons": [],
            }
        ],
        "semanticUnits": [
            {
                "id": "unit-1",
                "startPropositionId": "p1",
                "endPropositionId": "p1",
                "summary": "Test proposition",
                "relationshipToPrevious": "runtime-start",
                "sourceEventRefs": [],
                "evidenceRefs": ["word:w1"],
                "unresolvedReasons": [],
            }
        ],
        "sourceEvents": [],
        "observedVisualChanges": [],
        "copyEvidence": [],
        "intentionalCarrySpans": [],
        "coverageSpans": [
            {
                "id": "a",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 40,
                "evidenceRefs": [],
            },
            {
                "id": "b",
                "absoluteStartFrame": 40,
                "absoluteEndFrameExclusive": 100,
                "evidenceRefs": [],
            },
        ],
        "unresolvedAmbiguities": [],
    }


def test_whole_runtime_analysis_is_complete_and_channel_neutral(monkeypatch) -> None:
    ledger = _analysis_ledger()
    validate_analysis_ledger(ledger)
    ledger["propositions"][0]["presentationRole"] = "authored"
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    with pytest.raises(ValueError, match="may not make presentation decisions"):
        validate_analysis_ledger(ledger)


def test_exact_ui_copy_evidence_requires_an_exact_locked_frame() -> None:
    ledger = _analysis_ledger()
    ledger["sourceEvents"] = [
        {
            "id": "source-1",
            "absoluteStartFrame": 0,
            "absoluteEndFrameExclusive": 30,
            "eventType": "software-ui",
            "description": "PowerPoint export dialog.",
            "evidenceRefs": ["locked-cut:frames:0-29"],
            "geometryObservations": [],
            "candidateProtectedRegionObservationIds": [],
            "confidence": 1,
            "creatorConfirmationRequired": False,
            "unresolvedReasons": [],
        }
    ]
    ledger["semanticUnits"][0]["sourceEventRefs"] = ["source-1"]
    ledger["copyEvidence"] = [
        {
            "kind": "exact-ui-label",
            "observedText": "Open in PowerPoint",
            "propositionId": "p1",
            "sourceEventId": "source-1",
            "absoluteFrame": 12,
            "observationMethod": "frame-inspection",
            "evidenceRefs": ["locked-cut:frames:0-29"],
            "confidence": 1,
        }
    ]

    with pytest.raises(ValueError, match="exact locked frame"):
        validate_analysis_ledger(ledger)

    ledger["copyEvidence"][0]["evidenceRefs"] = ["locked-cut:frame:12"]
    validate_analysis_ledger(ledger)


def test_verbatim_command_copy_evidence_must_match_transcript_evidence() -> None:
    ledger = _analysis_ledger()
    ledger["copyEvidence"] = [
        {
            "kind": "verbatim-command",
            "observedText": "/plan",
            "propositionId": "p1",
            "sourceEventId": None,
            "absoluteFrame": None,
            "observationMethod": "transcript-verification",
            "evidenceRefs": ["unrelated"],
            "confidence": 1,
        }
    ]

    with pytest.raises(ValueError, match="must cite its proposition"):
        validate_analysis_ledger(ledger)

    ledger["copyEvidence"][0]["evidenceRefs"] = ["word:w1"]
    validate_analysis_ledger(ledger)


def test_source_evidence_requires_contiguous_measured_layout_spans() -> None:
    rect = {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.7}
    artifact_identity = {
        "artifactKind": "fixture",
        "artifactId": "fixture",
        "version": 1,
        "sha256": SHA,
    }
    ledger = {
        "schemaVersion": 1,
        "episodeId": "episode",
        "lockedCutSha256": SHA,
        "captureLayoutCatalogRef": artifact_identity,
        "classificationRef": artifact_identity,
        "sequences": [
            {
                "sequenceId": "s1",
                "layoutSpans": [
                    {
                        "absoluteStartFrame": 0,
                        "absoluteEndFrameExclusive": 10,
                        "layoutId": "full-screen-talking",
                        "subjectBounds": rect,
                        "protectedMasks": [rect],
                        "classificationMethod": "agent-frame-classification",
                        "classificationActor": "codex-subscription-host",
                        "classificationVersion": "1",
                        "confidence": 1,
                        "evidenceFrames": [0, 9],
                        "evidenceRefs": ["frame-0", "frame-9"],
                    }
                ],
                "protectedRegionSamples": [],
                "creatorCorrections": [],
            }
        ],
    }
    validate_source_evidence(ledger, {"s1": (0, 10)})
    ledger["sequences"][0]["layoutSpans"][0]["absoluteStartFrame"] = 1
    with pytest.raises(ValueError, match="not contiguous"):
        validate_source_evidence(ledger, {"s1": (0, 10)})


def test_agent_layout_classification_is_catalog_bounded_and_fail_closed() -> None:
    classification = {
        "schemaVersion": 1,
        "episodeId": "episode",
        "lockedCutSha256": SHA,
        "wordTimingSha256": "c" * 64,
        "totalFrames": 10,
        "catalogId": "creator-obs-capture-layouts",
        "catalogVersion": 1,
        "sequences": [
            {
                "sequenceId": "s1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 10,
                "layoutSpans": [
                    {
                        "absoluteStartFrame": 0,
                        "absoluteEndFrameExclusive": 10,
                        "layoutId": "talking-bottom-right",
                        "candidateLayoutIds": ["talking-bottom-right"],
                        "confidence": 0.99,
                        "evidenceFrames": [0, 9],
                        "evidenceRefs": ["video:frame:0", "video:frame:9"],
                        "unresolvedReasons": [],
                    }
                ],
            }
        ],
    }
    assert validate_source_layout_classification(
        classification,
        expected_ranges={"s1": (0, 10)},
        capture_layout_catalog=_capture_catalog(),
    ) == []

    span = classification["sequences"][0]["layoutSpans"][0]
    span["layoutId"] = None
    span["candidateLayoutIds"] = ["talking-bottom-left", "talking-bottom-right"]
    span["unresolvedReasons"] = ["The inset crosses a transition at the inspected frame."]
    assert validate_source_layout_classification(
        classification,
        expected_ranges={"s1": (0, 10)},
        capture_layout_catalog=_capture_catalog(),
    )[0]["sequenceId"] == "s1"


def test_initial_semantic_manifest_revision_must_be_one(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    with pytest.raises(ValueError, match="revision 1"):
        validate_semantic_manifest({"revision": 2}, {})


def test_vcg_planning_requires_editorial_copy_and_timing_directive(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    manifest = {
        "revision": 1,
        "totalFrames": 30,
        "sequences": [
            {
                "id": "s1",
                "chapterId": "c1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 30,
                "propositionId": "p1",
                "candidateCapabilityIds": [],
                "candidateAssessments": [],
                "presentationRole": "source-led",
            }
        ],
        "transitionIntents": [],
        "chapters": [
            {
                "id": "c1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 30,
            }
        ],
    }
    profile = {
        "selection": {"fullCatalogEvaluationRequired": True},
    }

    with pytest.raises(ValueError, match="missing its editorial directive"):
        validate_semantic_manifest(
            manifest,
            {"capabilities": []},
            {"propositions": [{"id": "p1"}]},
            profile,
        )


def test_semantic_manifest_is_grounded_in_analysis_and_chapter_ranges(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    sequence = {
        "id": "s1",
        "chapterId": "c1",
        "absoluteStartFrame": 0,
        "absoluteEndFrameExclusive": 100,
        "propositionId": "missing",
        "candidateCapabilityIds": ["cap-1"],
        "candidateAssessments": [
            {
                "capabilityId": "cap-1",
                "recipeEvidence": {
                    "sourceResourceId": "cap-source-1",
                    "sourceSha256": SHA,
                    "compatibleRecipeRole": "fixture",
                    "compatibilityRationale": "fixture",
                },
                "hardExclusions": {
                    "runtimeIncompatible": False,
                    "semanticallyIncompatible": False,
                },
            }
        ],
        "presentationRole": "fixture",
    }
    manifest = {
        "revision": 1,
        "totalFrames": 100,
        "sequences": [sequence],
        "transitionIntents": [],
        "chapters": [
            {
                "id": "c1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 100,
            }
        ],
    }
    catalog = {
        "capabilities": [
            {
                "id": "cap-1",
                "sourceAvailability": "source-enabled",
                "implementationMaturity": "source-only",
                "technicalAdmission": "unassessed",
                "source": {"relativePath": "cap-1.md", "sha256": SHA},
            }
        ],
        "sourceResources": [
            {"id": "cap-source-1", "relativePath": "cap-1.md", "sha256": SHA}
        ],
    }
    analysis = {"propositions": [{"id": "p1"}]}

    with pytest.raises(ValueError, match="unknown proposition"):
        validate_semantic_manifest(manifest, catalog, analysis)

    sequence["propositionId"] = "p1"
    manifest["chapters"] = [
        {"id": "c1", "absoluteStartFrame": 0, "absoluteEndFrameExclusive": 50},
        {"id": "c2", "absoluteStartFrame": 50, "absoluteEndFrameExclusive": 100},
    ]
    with pytest.raises(ValueError, match="does not match its assigned sequence range"):
        validate_semantic_manifest(manifest, catalog, analysis)


def test_source_only_unassessed_capability_is_adaptation_debt_not_hard_exclusion(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    manifest = {
        "revision": 1,
        "totalFrames": 100,
        "sequences": [
            {
                "id": "s1",
                "chapterId": "c1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 100,
                "propositionId": "p1",
                "candidateCapabilityIds": ["cap-1"],
                "candidateAssessments": [
                        {
                            "capabilityId": "cap-1",
                            "recipeEvidence": {
                                "sourceResourceId": "cap-source-1",
                                "sourceSha256": SHA,
                                "compatibleRecipeRole": "fixture",
                                "compatibilityRationale": "fixture",
                            },
                            "hardExclusions": {
                                "runtimeIncompatible": True,
                                "semanticallyIncompatible": False,
                            },
                        }
                ],
                "presentationRole": "fixture",
            }
        ],
        "transitionIntents": [],
        "chapters": [
            {
                "id": "c1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 100,
            }
        ],
    }
    catalog = {
        "capabilities": [
            {
                "id": "cap-1",
                "sourceAvailability": "source-enabled",
                "implementationMaturity": "source-only",
                    "technicalAdmission": "unassessed",
                    "source": {"relativePath": "cap-1.md", "sha256": SHA},
                }
            ],
            "sourceResources": [
                {"id": "cap-source-1", "relativePath": "cap-1.md", "sha256": SHA}
            ],
    }
    analysis = {"propositions": [{"id": "p1"}]}

    with pytest.raises(ValueError, match="requires adaptation, not hard exclusion"):
        validate_semantic_manifest(manifest, catalog, analysis)


def test_semantic_manifest_rejects_candidate_evidence_from_another_recipe(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    manifest = {
        "revision": 1,
        "totalFrames": 100,
        "sequences": [
            {
                "id": "s1",
                "chapterId": "c1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 100,
                "propositionId": "p1",
                "candidateCapabilityIds": ["cap-1"],
                "candidateAssessments": [
                    {
                        "capabilityId": "cap-1",
                        "recipeEvidence": {
                            "sourceResourceId": "wrong-source",
                            "sourceSha256": SHA,
                            "compatibleRecipeRole": "fixture",
                            "compatibilityRationale": "fixture",
                        },
                        "hardExclusions": {
                            "runtimeIncompatible": False,
                            "semanticallyIncompatible": False,
                        },
                    }
                ],
                "presentationRole": "fixture",
            }
        ],
        "transitionIntents": [],
        "chapters": [
            {
                "id": "c1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 100,
            }
        ],
    }
    catalog = {
        "capabilities": [
            {
                "id": "cap-1",
                "sourceAvailability": "source-enabled",
                "implementationMaturity": "source-only",
                "technicalAdmission": "unassessed",
                "source": {"relativePath": "cap-1.md", "sha256": SHA},
            }
        ],
        "sourceResources": [
            {"id": "cap-source-1", "relativePath": "cap-1.md", "sha256": SHA}
        ],
    }
    analysis = {"propositions": [{"id": "p1"}]}

    with pytest.raises(ValueError, match="exact frozen recipe"):
        validate_semantic_manifest(manifest, catalog, analysis)


def test_stronger_source_only_fit_blocks_for_adaptation_instead_of_falling_back() -> None:
    catalog = _catalog()
    weaker = next(item for item in catalog["capabilities"] if item["id"] == "hf-rule:spring-pop-entrance")
    weaker["productionSelection"] = "production-selectable"
    weaker["technicalAdmission"] = "library-admitted"
    weaker["implementationMaturity"] = "technically-proven"
    selected, receipt = resolve_sequence_selection(
        sequence_id="s1",
        candidates=[
            _candidate("hf-rule:kinetic-beat-slam", 10),
            _candidate("hf-rule:spring-pop-entrance", 5),
        ],
        resolved_channel_profile=_channel(),
        catalog=catalog,
        semantic_evidence_refs=["p1"],
        actor_model="test",
        prompt_version="1",
    )
    assert selected is None
    assert receipt["disposition"] == "adaptation-required"
    assert receipt["selectedCapabilityId"] == "hf-rule:kinetic-beat-slam"
    assert receipt["unresolvedReasons"]


def test_source_led_sequence_records_no_authored_capability_receipt(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    selected, receipt = resolve_sequence_selection(
        sequence_id="s1",
        candidates=[],
        resolved_channel_profile={
            "selection": {
                "criterionOrder": ["semantic-fitness", "stable-capability-id"],
                "rankingPolicyRef": "fixture",
                "mode": "lexicographic",
            }
        },
        catalog={"capabilities": []},
        semantic_evidence_refs=["p1"],
        actor_model="test",
        prompt_version="1",
        presentation_role="source-led",
    )
    assert selected is None
    assert receipt["disposition"] == "source-led-no-authored-capability"
    assert receipt["evaluatedCandidates"] == []
    assert receipt["selectedCapabilityId"] is None


def test_project_admission_is_selectable_only_for_its_exact_sequence(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.creator_governance.validate_artifact",
        lambda _schema_name, _value: None,
    )
    candidate = _candidate("cap-1", 1)
    selected, receipt = resolve_sequence_selection(
        sequence_id="sequence:02",
        candidates=[candidate],
        resolved_channel_profile={
            "selection": {
                "criterionOrder": ["semantic-fitness", "stable-capability-id"],
                "rankingPolicyRef": "fixture",
                "mode": "lexicographic",
            }
        },
        catalog={
            "capabilities": [
                {
                    "id": "cap-1",
                    "sourceAvailability": "source-enabled",
                    "implementationMaturity": "technically-proven",
                    "technicalAdmission": "project-admitted",
                    "productionSelection": "production-selectable",
                    "projectAdmissions": [{"sequenceId": "sequence:01"}],
                }
            ]
        },
        semantic_evidence_refs=["p1"],
        actor_model="test",
        prompt_version="1",
    )
    assert selected is None
    assert receipt["disposition"] == "adaptation-required"


def test_adjacent_repeated_visual_signature_blocks_unrelated_concepts() -> None:
    manifest = _manifest()
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    result = evaluate_episode_repetition(manifest, compiled)
    assert result["passed"] is False
    assert {item["kind"] for item in result["findings"]} == {"adjacent-topologyHash"}


def test_adjacent_locked_source_pass_through_is_not_authored_repetition() -> None:
    manifest = _manifest()
    for sequence in manifest["sequences"]:
        sequence["presentationRole"] = "source-led"
        sequence["sourceImplementationMode"] = "source-pass-through"
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    result = evaluate_episode_repetition(manifest, compiled)
    assert result["passed"] is True
    assert result["findings"] == []
