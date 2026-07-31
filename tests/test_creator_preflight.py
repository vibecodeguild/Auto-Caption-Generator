from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.creator_capabilities import inventory_hyperframes_capabilities
from app.core.creator_preflight import run_structural_preflight
from app.core.creator_production import compile_episode_manifest, transcript_word_timing_hash
from tests.test_creator_production import _manifest


def _catalog() -> dict:
    root = Path(__file__).resolve().parents[1]
    skill = Path.home() / ".codex" / "skills" / "hyperframes-animation"
    cli = root / "node_modules" / "hyperframes" / "dist" / "cli.js"
    if not skill.is_dir() or not cli.is_file():
        pytest.skip("Pinned local HyperFrames installation is unavailable.")
    return inventory_hyperframes_capabilities(
        skill_root=skill,
        hyperframes_cli_path=cli,
        hyperframes_version="0.7.54",
    )


def _inputs() -> tuple[dict, dict, dict]:
    manifest = _manifest()
    manifest["sequences"][1]["selectedCanvasTopology"] = "speaker-right-information-left"
    manifest["sequences"][1]["compositionGraph"]["elements"][1]["geometry"]["x"] = 0.05
    for sequence in manifest["sequences"]:
        sequence["compositionGraph"]["elements"][0]["properties"]["role"] = "speaker-source"
        sequence["compositionGraph"]["elements"][1]["properties"]["initiallyVisible"] = False
    transcript = {
        "project": {
            "fps": 30,
            "words": [
                {"id": "w1", "start": 1, "end": 1.2, "start_frame": 30, "end_frame": 36},
                {"id": "w2", "start": 5, "end": 5.2, "start_frame": 150, "end_frame": 156},
            ],
        }
    }
    manifest["wordTimingSha256"] = transcript_word_timing_hash(transcript)
    rect = {"x": 0.55, "y": 0.05, "width": 0.4, "height": 0.9}
    evidence = {
        "schemaVersion": 1,
        "episodeId": "episode-1",
        "lockedCutSha256": "a" * 64,
        "captureLayoutCatalogRef": {
            "artifactKind": "fixture",
            "artifactId": "catalog",
            "version": 1,
            "sha256": "b" * 64,
        },
        "classificationRef": {
            "artifactKind": "fixture",
            "artifactId": "classification",
            "version": 1,
            "sha256": "c" * 64,
        },
        "sequences": [
            {
                "sequenceId": sequence["id"],
                "layoutSpans": [
                    {
                        "absoluteStartFrame": sequence["absoluteStartFrame"],
                        "absoluteEndFrameExclusive": sequence["absoluteEndFrameExclusive"],
                        "layoutId": "talking-right",
                        "subjectBounds": rect,
                        "protectedMasks": [rect],
                        "classificationMethod": "agent-frame-classification",
                        "classificationActor": "codex-subscription-host",
                        "classificationVersion": "1",
                        "confidence": 1,
                        "evidenceFrames": [
                            sequence["absoluteStartFrame"],
                            sequence["absoluteEndFrameExclusive"] - 1,
                        ],
                        "evidenceRefs": [
                            f"{sequence['id']}-entry",
                            f"{sequence['id']}-exit",
                        ],
                    }
                ],
                "protectedRegionSamples": [],
                "creatorCorrections": [],
            }
            for sequence in manifest["sequences"]
        ],
    }
    return manifest, transcript, evidence


def _apply_vcg_contract(manifest: dict) -> dict:
    for index, sequence in enumerate(manifest["sequences"]):
        event = sequence["compositionGraph"]["events"][0]
        element = sequence["compositionGraph"]["elements"][1]
        beat_id = f"beat-{index + 1}"
        capability_id = f"family-{index + 1}"
        element["properties"]["editorialBeatId"] = beat_id
        element["properties"]["text"] = f"Exact label {index + 1}"
        sequence["selectedCapabilityBindings"][0]["capabilityId"] = capability_id
        sequence["selectedVisualFamilyId"] = capability_id
        event["parameters"]["meaningfulChangeId"] = f"change-{index + 1}"
        sequence["editorialDirective"] = {
            "visualPurpose": "Explain the spoken idea.",
            "sourceStrategy": "hybrid-emphasis",
            "spokenBeats": [
                {
                    "id": beat_id,
                    "sourceWordIds": [event["wordId"]],
                    "spokenPhrase": f"Spoken phrase {index + 1}",
                    "onScreenText": element["properties"]["text"],
                    "copyMode": "concise-editorial-label",
                    "revealFrame": event["absoluteFrame"],
                    "fullyVisibleFrame": event["absoluteFrame"] + event["durationFrames"],
                    "exitFrameExclusive": sequence["absoluteEndFrameExclusive"],
                    "editorialPurpose": "Emphasis",
                    "copyEvidenceRef": None,
                }
            ],
            "meaningfulChanges": [
                {
                    "id": f"change-{index + 1}",
                    "absoluteFrame": event["absoluteFrame"],
                    "kind": "treatment-enter",
                    "description": "A meaningful treatment change.",
                    "spokenBeatId": beat_id,
                    "sourceVisualChangeRef": None,
                    "verificationKind": "spoken-beat",
                }
            ],
            "intentionalVisualCarry": None,
            "copyReview": {
                "spellingPassed": True,
                "punctuationPassed": True,
                "grammarPassed": True,
            },
        }
    return {
        "id": "vcg",
        "version": 2,
        "speaker": {
            "visibilityPolicy": {
                "continuousAbsenceMaximumSeconds": 5,
                "absenceAllowedLayoutIds": ["full-screen-talking"],
            }
        },
        "pacing": {"maximumMeaningfulChangeGapSec": 5},
        "reuse": {"maximumUsesPerVisualFamily": 3},
    }


def test_preflight_passes_exact_word_timing_and_measured_safe_layout() -> None:
    manifest, transcript, evidence = _inputs()
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    receipt = run_structural_preflight(
        manifest=manifest,
        compiled=compiled,
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog=_catalog(),
    )
    assert receipt["passed"] is True


def test_preflight_blocks_early_graphic_and_protected_region_overlap() -> None:
    manifest, transcript, evidence = _inputs()
    manifest["sequences"][0]["compositionGraph"]["events"][0]["absoluteFrame"] = 29
    manifest["sequences"][0]["compositionGraph"]["elements"][1]["geometry"]["x"] = 0.6
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    receipt = run_structural_preflight(
        manifest=manifest,
        compiled=compiled,
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog=_catalog(),
    )
    gates = {item["gate"] for item in receipt["findings"]}
    assert "invented-timing-offset" in gates
    assert "protected-region-intersection" in gates
    assert receipt["passed"] is False


def test_vcg_preflight_binds_planned_copy_and_timing_to_graph() -> None:
    manifest, transcript, evidence = _inputs()
    profile = _apply_vcg_contract(manifest)
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    receipt = run_structural_preflight(
        manifest=manifest,
        compiled=compiled,
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog={"capabilities": []},
        channel_profile=profile,
    )
    assert receipt["passed"] is True

    first_event = manifest["sequences"][0]["compositionGraph"]["events"][0]
    first_change_id = first_event["parameters"].pop("meaningfulChangeId")
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    receipt = run_structural_preflight(
        manifest=manifest,
        compiled=compiled,
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog={"capabilities": []},
        channel_profile=profile,
    )
    assert "meaningful-change-not-materialized" in {
        finding["gate"] for finding in receipt["findings"]
    }
    first_event["parameters"]["meaningfulChangeId"] = first_change_id

    manifest["sequences"][0]["compositionGraph"]["elements"][1]["properties"][
        "text"
    ] = "Recipe default"
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    receipt = run_structural_preflight(
        manifest=manifest,
        compiled=compiled,
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog={"capabilities": []},
        channel_profile=profile,
    )
    assert "semantic-copy-binding" in {
        finding["gate"] for finding in receipt["findings"]
    }


def test_vcg_preflight_allows_one_verified_carry_across_adjacent_sequences() -> None:
    manifest, transcript, evidence = _inputs()
    profile = _apply_vcg_contract(manifest)
    for sequence in manifest["sequences"]:
        sequence["editorialDirective"]["meaningfulChanges"] = []
        sequence["editorialDirective"]["intentionalVisualCarry"] = {
            "carrySpanRef": "carry-screen-demonstration",
            "sourceEventId": "screen-demonstration",
            "evidenceRefs": ["frame-entry", "frame-exit"],
            "absoluteStartFrame": sequence["absoluteStartFrame"],
            "absoluteEndFrameExclusive": sequence["absoluteEndFrameExclusive"],
        }

    receipt = run_structural_preflight(
        manifest=manifest,
        compiled=compile_episode_manifest(manifest, compiler_version="1"),
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog={"capabilities": []},
        channel_profile=profile,
    )

    assert "intentional-carry-not-evidenced" not in {
        finding["gate"] for finding in receipt["findings"]
    }
    assert "meaningful-change-cadence" not in {
        finding["gate"] for finding in receipt["findings"]
    }


def test_vcg_preflight_rejects_reused_carry_with_changed_evidence() -> None:
    manifest, transcript, evidence = _inputs()
    profile = _apply_vcg_contract(manifest)
    for sequence in manifest["sequences"]:
        sequence["editorialDirective"]["intentionalVisualCarry"] = {
            "carrySpanRef": "carry-screen-demonstration",
            "sourceEventId": "screen-demonstration",
            "evidenceRefs": ["frame-entry", "frame-exit"],
            "absoluteStartFrame": sequence["absoluteStartFrame"],
            "absoluteEndFrameExclusive": sequence["absoluteEndFrameExclusive"],
        }
    manifest["sequences"][1]["editorialDirective"]["intentionalVisualCarry"][
        "evidenceRefs"
    ] = ["different-evidence"]

    receipt = run_structural_preflight(
        manifest=manifest,
        compiled=compile_episode_manifest(manifest, compiler_version="1"),
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog={"capabilities": []},
        channel_profile=profile,
    )

    assert "intentional-carry-not-evidenced" in {
        finding["gate"] for finding in receipt["findings"]
    }
