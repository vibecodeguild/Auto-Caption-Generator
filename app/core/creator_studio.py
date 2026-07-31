from __future__ import annotations

import json
from pathlib import Path

from app.core.creator_build import finalize_materialized_build
from app.core.creator_project import (
    promote_creator_artifacts,
    transition_creator_project,
    verify_creator_project,
)
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    canonical_hash,
    next_artifact_version,
    utc_now,
    validate_episode_manifest,
    require_private_root,
    write_versioned_artifact,
)


ALLOWED_STUDIO_EDIT_KINDS = frozenset(
    {
        "element-geometry",
        "element-property",
        "element-token-binding",
        "event-easing",
        "event-duration",
        "event-parameter",
    }
)


def create_studio_handoff(
    *,
    manifest: dict,
    build_lock: dict,
    sequence_id: str,
    element_id: str | None,
    absolute_frame: int,
    studio_context: dict | None = None,
) -> dict:
    validate_episode_manifest(manifest)
    if build_lock["manifestHash"] != canonical_hash(manifest):
        raise ValueError("Studio handoff requires the exact manifest represented by the build lock.")
    sequence = next((item for item in manifest["sequences"] if item["id"] == sequence_id), None)
    if sequence is None:
        raise ValueError(f"Studio sequence does not exist: {sequence_id}")
    if not sequence["absoluteStartFrame"] <= absolute_frame < sequence["absoluteEndFrameExclusive"]:
        raise ValueError("Studio playhead must be inside the selected sequence.")
    if element_id is not None and element_id not in {
        item["id"] for item in sequence["compositionGraph"]["elements"]
    }:
        raise ValueError(f"Studio element does not exist: {element_id}")
    handoff = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": manifest["episodeId"],
        "manifestRevision": manifest["revision"],
        "manifestHash": canonical_hash(manifest),
        "buildHash": build_lock["buildHash"],
        "sequenceId": sequence_id,
        "elementId": element_id,
        "absoluteFrame": absolute_frame,
        "wordContext": {
            "startWordId": sequence["startWordId"],
            "endWordId": sequence["endWordId"],
        },
        "editAuthority": "manifest-aware-production-adapter",
        "directSourceMutationAllowed": False,
        "studioContext": studio_context,
        "createdAt": utc_now(),
    }
    handoff["handoffHash"] = canonical_hash(handoff)
    return handoff


def apply_studio_edits(
    *,
    manifest: dict,
    build_lock: dict,
    handoff: dict,
    edits: list[dict],
) -> tuple[dict, dict]:
    if handoff.get("buildHash") != build_lock.get("buildHash"):
        raise ValueError("Studio handoff targets a stale build.")
    if handoff.get("manifestHash") != canonical_hash(manifest):
        raise ValueError("Studio handoff targets a stale manifest.")
    if not edits:
        raise ValueError("Studio edit submission is empty.")
    updated = json.loads(json.dumps(manifest))
    sequence = next(item for item in updated["sequences"] if item["id"] == handoff["sequenceId"])
    elements = {item["id"]: item for item in sequence["compositionGraph"]["elements"]}
    events = {item["id"]: item for item in sequence["compositionGraph"]["events"]}
    applied = []
    for edit in edits:
        kind = edit.get("kind")
        if kind not in ALLOWED_STUDIO_EDIT_KINDS:
            raise ValueError(f"Studio edit is outside the manifest-aware allowlist: {kind}")
        target_id = str(edit.get("targetId") or "")
        path = str(edit.get("path") or "")
        value = json.loads(json.dumps(edit.get("value")))
        if kind.startswith("element-"):
            target = elements.get(target_id)
            if target is None:
                raise ValueError(f"Studio edit targets an unknown element: {target_id}")
            root_key = {
                "element-geometry": "geometry",
                "element-property": "properties",
                "element-token-binding": "tokenBindings",
            }[kind]
        else:
            target = events.get(target_id)
            if target is None:
                raise ValueError(f"Studio edit targets an unknown event: {target_id}")
            root_key = {
                "event-easing": "easing",
                "event-duration": "durationFrames",
                "event-parameter": "parameters",
            }[kind]
        if root_key in {"easing", "durationFrames"}:
            if path:
                raise ValueError(f"{kind} does not accept a nested path.")
            target[root_key] = value
        else:
            if not path or "." in path or path in {
                "semanticForm",
                "selectedCapabilityBindings",
                "absoluteFrame",
                "wordId",
            }:
                raise ValueError("Studio edits require one allowed leaf field.")
            target[root_key][path] = value
        applied.append({"kind": kind, "targetId": target_id, "path": path})
    updated["revision"] += 1
    updated["state"] = "MATERIALIZING"
    validate_episode_manifest(updated)
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": updated["episodeId"],
        "fromManifestHash": canonical_hash(manifest),
        "toManifestHash": canonical_hash(updated),
        "fromBuildHash": build_lock["buildHash"],
        "handoffHash": handoff["handoffHash"],
        "sequenceId": handoff["sequenceId"],
        "appliedEdits": applied,
        "semanticSelectionChanged": False,
        "timingAuthorityChanged": False,
        "requiresRecompile": True,
        "createdAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    return updated, receipt


def persist_studio_edits(
    private_root: Path,
    *,
    handoff: dict,
    edits: list[dict],
) -> dict:
    root = require_private_root(private_root)
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    if current["state"] not in {"REVIEW_READY", "APPROVED", "DELIVERED"}:
        raise ValueError(
            "Studio edits require a current review-ready or delivered build."
        )
    manifest = json.loads(
        (root / current["artifacts"]["episodeManifest"]["path"]).read_text(encoding="utf-8")
    )
    build_lock = json.loads(
        (root / current["artifacts"]["buildLock"]["path"]).read_text(encoding="utf-8")
    )
    updated, receipt = apply_studio_edits(
        manifest=manifest,
        build_lock=build_lock,
        handoff=handoff,
        edits=edits,
    )
    sequence = next(
        item for item in updated["sequences"] if item["id"] == handoff["sequenceId"]
    )
    override = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": updated["episodeId"],
        "sequenceId": sequence["id"],
        "fromBuildHash": build_lock["buildHash"],
        "handoffHash": handoff["handoffHash"],
        "compositionGraphHash": canonical_hash(sequence["compositionGraph"]),
        "appliedEdits": receipt["appliedEdits"],
        "createdAt": utc_now(),
    }
    override["overrideHash"] = canonical_hash(override)
    sequence["sourceOverrideRef"] = override["overrideHash"]
    receipt["toManifestHash"] = canonical_hash(updated)
    receipt["receiptHash"] = canonical_hash(
        {key: value for key, value in receipt.items() if key != "receiptHash"}
    )
    override_ref = write_versioned_artifact(
        root,
        artifact_kind="source-overrides",
        artifact_id=sequence["id"],
        version=next_artifact_version(root, "source-overrides", sequence["id"]),
        value=override,
    )
    manifest_ref = write_versioned_artifact(
        root,
        artifact_kind="episode-manifests",
        artifact_id=updated["episodeId"],
        version=next_artifact_version(
            root, "episode-manifests", updated["episodeId"]
        ),
        value=updated,
        schema_name="episode-manifest",
    )
    receipt_ref = write_versioned_artifact(
        root,
        artifact_kind="studio-edit-receipts",
        artifact_id=sequence["id"],
        version=next_artifact_version(
            root, "studio-edit-receipts", sequence["id"]
        ),
        value=receipt,
    )
    if current["state"] in {"REVIEW_READY", "DELIVERED", "APPROVED"}:
        current = transition_creator_project(
            root,
            target_state="REVISION_REQUESTED",
            gate_receipt_refs=[receipt_ref["sha256"]],
            actor="creator",
        )
    if current["state"] == "REVISION_REQUESTED":
        transition_creator_project(
            root,
            target_state="MATERIALIZING",
            gate_receipt_refs=[receipt_ref["sha256"], override_ref["sha256"]],
            actor="production",
        )
    build = finalize_materialized_build(root, updated)
    if not build["passed"]:
        raise ValueError("Studio revision failed deterministic preflight.")
    promote_creator_artifacts(
        root,
        artifact_references={
            "episodeManifest": manifest_ref,
            "compiledEpisode": build["compiledEpisodeRef"],
            "structuralPreflight": build["preflightRef"],
            "buildLock": build["buildLockRef"],
            "studioEditReceipt": receipt_ref,
            "sourceOverride": override_ref,
        },
    )
    transition_creator_project(
        root,
        target_state="PREFLIGHT",
        gate_receipt_refs=[build["preflightRef"]["sha256"], build["buildLockRef"]["sha256"]],
    )
    return {
        "manifestRef": manifest_ref,
        "buildLockRef": build["buildLockRef"],
        "receiptRef": receipt_ref,
        "overrideRef": override_ref,
    }
