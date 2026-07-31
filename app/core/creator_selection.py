from __future__ import annotations

import json
from pathlib import Path

from app.core.creator_governance import resolve_sequence_selection
from app.core.creator_project import promote_creator_artifact, verify_creator_project
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    canonical_hash,
    next_artifact_version,
    require_private_root,
    utc_now,
    write_versioned_artifact,
)


def _next_version(root: Path, artifact_kind: str, artifact_id: str) -> int:
    return next_artifact_version(root, artifact_kind, artifact_id)


def refresh_sequence_decisions(
    private_root: Path,
    semantic: dict | None = None,
    *,
    catalog: dict | None = None,
    promote: bool = True,
) -> tuple[dict, dict]:
    root = require_private_root(private_root)
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    if semantic is None:
        reference = current["artifacts"].get("semanticManifest")
        if not reference:
            raise ValueError("Sequence decisions require a semantic manifest.")
        semantic = json.loads((root / reference["path"]).read_text(encoding="utf-8"))
    if catalog is None:
        catalog = json.loads(
            (root / current["artifacts"]["capabilityCatalog"]["path"]).read_text(
                encoding="utf-8"
            )
        )
    profile = json.loads(
        (root / current["artifacts"]["channelProfile"]["path"]).read_text(encoding="utf-8")
    )
    items = []
    for sequence in semantic["sequences"]:
        selected, receipt = resolve_sequence_selection(
            sequence_id=sequence["id"],
            candidates=sequence["candidateAssessments"],
            resolved_channel_profile=profile,
            catalog=catalog,
            semantic_evidence_refs=sequence["semanticEvidenceRefs"],
            actor_model="user-visible-codex-task",
            prompt_version="semantic-plan@1",
            presentation_role=sequence["presentationRole"],
        )
        version = _next_version(root, "sequence-decision-receipts", sequence["id"])
        receipt["id"] = f"decision:{sequence['id']}:v{version}"
        receipt["receiptHash"] = canonical_hash(
            {key: value for key, value in receipt.items() if key != "receiptHash"}
        )
        reference = write_versioned_artifact(
            root,
            artifact_kind="sequence-decision-receipts",
            artifact_id=sequence["id"],
            version=version,
            value=receipt,
            schema_name="sequence-decision-receipt",
        )
        items.append(
            {
                "sequenceId": sequence["id"],
                "receiptId": receipt["id"],
                "receiptRef": reference,
                "disposition": receipt["disposition"],
                "selectedCapabilityId": (
                    selected["capabilityId"] if selected is not None else None
                ),
                "topRankedCapabilityId": (
                    receipt["rankedHardValidCapabilityIds"][0]
                    if receipt["rankedHardValidCapabilityIds"]
                    else None
                ),
                "unresolvedReasons": receipt["unresolvedReasons"],
            }
        )
    index = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": current["episodeId"],
        "semanticManifestHash": canonical_hash(semantic),
        "catalogHash": catalog["catalogHash"],
        "items": items,
        "createdAt": utc_now(),
    }
    index["indexHash"] = canonical_hash(index)
    version = _next_version(root, "sequence-decision-indexes", current["episodeId"])
    index_ref = write_versioned_artifact(
        root,
        artifact_kind="sequence-decision-indexes",
        artifact_id=current["episodeId"],
        version=version,
        value=index,
    )
    if promote:
        promote_creator_artifact(
            root,
            artifact_key="sequenceDecisionIndex",
            artifact_reference=index_ref,
        )
    return index, index_ref
