from __future__ import annotations

import json
from pathlib import Path

from app.core.creator_governance import validate_source_evidence
from app.core.creator_project import promote_creator_artifact, verify_creator_project
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    next_artifact_version,
    require_private_root,
    validate_artifact,
    write_versioned_artifact,
)


CLASSIFICATION_METHOD = "agent-frame-classification"
CLASSIFICATION_ACTOR = "user-visible-codex-task"
CLASSIFICATION_VERSION = "capture-layout-classifier@1"


def _read_artifact(root: Path, reference: dict) -> dict:
    return json.loads((root / reference["path"]).read_text(encoding="utf-8"))


def _artifact_identity(reference: dict) -> dict:
    return {
        "artifactKind": reference["artifactKind"],
        "artifactId": reference["artifactId"],
        "version": reference["version"],
        "sha256": reference["sha256"],
    }


def _expected_sequence_ranges(semantic: dict) -> dict[str, tuple[int, int]]:
    return {
        sequence["id"]: (
            sequence["absoluteStartFrame"],
            sequence["absoluteEndFrameExclusive"],
        )
        for sequence in semantic["sequences"]
    }


def validate_source_layout_classification(
    classification: dict,
    *,
    expected_ranges: dict[str, tuple[int, int]],
    capture_layout_catalog: dict,
) -> list[dict]:
    validate_artifact("source-layout-classification", classification)
    expected_ids = set(expected_ranges)
    actual_ids = {item["sequenceId"] for item in classification["sequences"]}
    if actual_ids != expected_ids or len(actual_ids) != len(classification["sequences"]):
        raise ValueError(
            "Layout classification must contain every semantic sequence exactly once; "
            f"missing={sorted(expected_ids-actual_ids)}, unknown={sorted(actual_ids-expected_ids)}"
        )
    if (
        classification["catalogId"] != capture_layout_catalog["id"]
        or classification["catalogVersion"] != capture_layout_catalog["version"]
    ):
        raise ValueError("Layout classification changed the frozen capture-layout catalog identity.")

    unresolved = []
    allowed_layout_ids = set(capture_layout_catalog["layouts"])
    for sequence in classification["sequences"]:
        sequence_id = sequence["sequenceId"]
        expected_start, expected_end = expected_ranges[sequence_id]
        if (
            sequence["absoluteStartFrame"] != expected_start
            or sequence["absoluteEndFrameExclusive"] != expected_end
        ):
            raise ValueError(f"Layout classification changed sequence timing: {sequence_id}")
        cursor = expected_start
        for span in sequence["layoutSpans"]:
            if span["absoluteStartFrame"] != cursor:
                raise ValueError(
                    f"Layout spans must be contiguous in {sequence_id}; expected frame {cursor}."
                )
            if span["absoluteEndFrameExclusive"] <= span["absoluteStartFrame"]:
                raise ValueError(f"Layout classification contains an empty span in {sequence_id}.")
            if span["absoluteEndFrameExclusive"] > expected_end:
                raise ValueError(f"Layout classification leaves {sequence_id}.")
            for frame in span["evidenceFrames"]:
                if not span["absoluteStartFrame"] <= frame < span["absoluteEndFrameExclusive"]:
                    raise ValueError(
                        f"Layout evidence frame {frame} is outside its span in {sequence_id}."
                    )
            layout_id = span["layoutId"]
            candidate_ids = span["candidateLayoutIds"]
            unknown_candidates = set(candidate_ids) - allowed_layout_ids
            if unknown_candidates:
                raise ValueError(
                    f"Layout classification used unknown catalog IDs: {sorted(unknown_candidates)}"
                )
            if layout_id is None:
                if not candidate_ids or not span["unresolvedReasons"]:
                    raise ValueError(
                        f"Ambiguous layout span in {sequence_id} needs candidates and reasons."
                    )
                unresolved.append(
                    {
                        "sequenceId": sequence_id,
                        "absoluteStartFrame": span["absoluteStartFrame"],
                        "absoluteEndFrameExclusive": span["absoluteEndFrameExclusive"],
                        "candidateLayoutIds": candidate_ids,
                        "reasons": span["unresolvedReasons"],
                    }
                )
            elif (
                layout_id not in allowed_layout_ids
                or layout_id not in candidate_ids
                or span["unresolvedReasons"]
            ):
                raise ValueError(
                    f"Resolved layout span in {sequence_id} must cite its selected catalog ID "
                    "and have no unresolved reason."
                )
            cursor = span["absoluteEndFrameExclusive"]
        if cursor != expected_end:
            raise ValueError(f"Layout spans do not cover the end of {sequence_id}.")
    return unresolved


def create_source_evidence_from_classification(
    private_root: Path,
    *,
    classification: dict,
    classification_reference: dict,
) -> tuple[dict | None, list[dict]]:
    root = require_private_root(private_root)
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    semantic_ref = current["artifacts"].get("semanticManifest")
    catalog_ref = current["artifacts"].get("captureLayoutCatalog")
    if not semantic_ref or not catalog_ref:
        raise ValueError(
            "Layout classification requires the semantic manifest and capture-layout catalog."
        )
    semantic = _read_artifact(root, semantic_ref)
    catalog = _read_artifact(root, catalog_ref)
    unresolved = validate_source_layout_classification(
        classification,
        expected_ranges=_expected_sequence_ranges(semantic),
        capture_layout_catalog=catalog,
    )
    if unresolved:
        return None, unresolved

    sequences = []
    for sequence in classification["sequences"]:
        spans = []
        for span in sequence["layoutSpans"]:
            layout_id = span["layoutId"]
            layout = catalog["layouts"][layout_id]
            spans.append(
                {
                    "absoluteStartFrame": span["absoluteStartFrame"],
                    "absoluteEndFrameExclusive": span["absoluteEndFrameExclusive"],
                    "layoutId": layout_id,
                    "subjectBounds": layout["speakerBounds"],
                    "protectedMasks": [],
                    "classificationMethod": CLASSIFICATION_METHOD,
                    "classificationActor": CLASSIFICATION_ACTOR,
                    "classificationVersion": CLASSIFICATION_VERSION,
                    "confidence": span["confidence"],
                    "evidenceFrames": span["evidenceFrames"],
                    "evidenceRefs": span["evidenceRefs"],
                }
            )
        sequences.append(
            {
                "sequenceId": sequence["sequenceId"],
                "layoutSpans": spans,
                "protectedRegionSamples": [],
                "creatorCorrections": [],
            }
        )
    ledger = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": current["episodeId"],
        "lockedCutSha256": classification["lockedCutSha256"],
        "captureLayoutCatalogRef": _artifact_identity(catalog_ref),
        "classificationRef": _artifact_identity(classification_reference),
        "sequences": sequences,
    }
    validate_source_evidence(ledger, _expected_sequence_ranges(semantic))
    reference = write_versioned_artifact(
        root,
        artifact_kind="source-evidence-ledgers",
        artifact_id=current["episodeId"],
        version=next_artifact_version(
            root, "source-evidence-ledgers", current["episodeId"]
        ),
        value=ledger,
        schema_name="source-evidence-ledger",
    )
    return reference, []


def source_evidence_draft(private_root: Path) -> dict:
    """Describe pending agent classification without inventing sample frames."""

    root = require_private_root(private_root)
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    semantic_ref = current["artifacts"].get("semanticManifest")
    catalog_ref = current["artifacts"].get("captureLayoutCatalog")
    if not semantic_ref:
        raise ValueError("Semantic planning must complete before source layouts are classified.")
    if not catalog_ref:
        raise ValueError("The creator-approved capture-layout catalog has not been frozen.")
    semantic = _read_artifact(root, semantic_ref)
    catalog = _read_artifact(root, catalog_ref)
    return {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": current["episodeId"],
        "availableLayoutIds": sorted(catalog["layouts"]),
        "classificationMethod": CLASSIFICATION_METHOD,
        "sequences": [
            {
                "sequenceId": sequence["id"],
                "absoluteStartFrame": sequence["absoluteStartFrame"],
                "absoluteEndFrameExclusive": sequence["absoluteEndFrameExclusive"],
            }
            for sequence in semantic["sequences"]
        ],
    }


def save_source_evidence(private_root: Path, ledger: dict) -> dict:
    """Persist an explicit correction to already measured agent evidence."""

    root = require_private_root(private_root)
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    semantic_ref = current["artifacts"].get("semanticManifest")
    if not semantic_ref:
        raise ValueError("Semantic planning must complete before source evidence is saved.")
    semantic = _read_artifact(root, semantic_ref)
    validate_source_evidence(ledger, _expected_sequence_ranges(semantic))
    reference = write_versioned_artifact(
        root,
        artifact_kind="source-evidence-ledgers",
        artifact_id=current["episodeId"],
        version=next_artifact_version(
            root, "source-evidence-ledgers", current["episodeId"]
        ),
        value=ledger,
        schema_name="source-evidence-ledger",
    )
    promote_creator_artifact(
        root,
        artifact_key="sourceEvidence",
        artifact_reference=reference,
    )
    return reference
