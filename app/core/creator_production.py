from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from jsonschema import Draft202012Validator

from app.core.file_utils import is_within, sha256_file
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.process_utils import hidden_subprocess_flags


WORKFLOW_ID = "creator-video-production"
WORKFLOW_VERSION = 1
ARTIFACT_SCHEMA_VERSION = 1
FORBIDDEN_WORKFLOW_IDS = frozenset(
    {
        "talking-head-recut",
        "general-video",
        "motion-graphics",
        "hyperframes-creative",
        "hyperframes-animation:auto-select",
        "product-launch-video",
        "faceless-explainer",
        "website-to-video",
        "pr-to-video",
        "music-to-video",
        "embedded-captions",
    }
)
CAPABILITY_SCOPES = frozenset(
    {"atomic-operation", "compiled-capability", "blueprint-macro", "project-composition"}
)
PROJECT_STATES = (
    "INGESTING",
    "ANALYZING",
    "MATERIALIZING",
    "PREFLIGHT",
    "REVIEW_READY",
    "REVISION_REQUESTED",
    "APPROVED",
    "RENDERING",
    "RENDER_BLOCKED",
    "DELIVERED",
    "BLOCKED",
)
_ALLOWED_STATE_TRANSITIONS = {
    "INGESTING": {"ANALYZING", "BLOCKED"},
    "ANALYZING": {"MATERIALIZING", "BLOCKED"},
    "MATERIALIZING": {"PREFLIGHT", "BLOCKED"},
    "PREFLIGHT": {"REVIEW_READY", "BLOCKED"},
    "REVIEW_READY": {"REVISION_REQUESTED", "APPROVED", "BLOCKED"},
    "REVISION_REQUESTED": {"MATERIALIZING", "BLOCKED"},
    "APPROVED": {"RENDERING", "REVISION_REQUESTED", "BLOCKED"},
    "RENDERING": {"RENDER_BLOCKED", "DELIVERED", "BLOCKED"},
    "RENDER_BLOCKED": {"RENDERING", "REVISION_REQUESTED", "BLOCKED"},
    "DELIVERED": {"REVISION_REQUESTED"},
    "BLOCKED": set(PROJECT_STATES) - {"BLOCKED", "DELIVERED"},
}
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "creator-production" / "schemas"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json_bytes(value: object) -> bytes:
    """Return the platform's version-1 canonical JSON representation.

    Objects are key-sorted, arrays preserve order, strings are UTF-8, and
    non-finite numbers are rejected. Hashes never include formatting or a
    platform-dependent newline.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_artifact(schema_name: str, value: object) -> None:
    schema_path = _SCHEMA_ROOT / f"{schema_name}.schema.json"
    if not schema_path.is_file():
        raise RuntimeError(f"Creator Production schema is missing: {schema_path.name}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "document root"
        raise ValueError(f"{schema_name} {location}: {error.message}")


def require_private_root(root: Path) -> Path:
    resolved = root.expanduser().resolve()
    if not (resolved / ".vcg-private").is_file():
        raise ValueError("Creator Production storage must be inside a marked private project.")
    return resolved


def content_addressed_object_path(private_root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Content digest must be lowercase SHA-256.")
    root = require_private_root(private_root)
    return root / "creator-production" / "objects" / "sha256" / digest[:2] / digest


def freeze_bytes(private_root: Path, content: bytes) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    destination = content_addressed_object_path(private_root, digest)
    if destination.is_file():
        if sha256_file(destination) != digest:
            raise RuntimeError(f"Immutable object is corrupt: {digest}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    root = require_private_root(private_root)
    return {
        "sha256": digest,
        "bytes": len(content),
        "path": destination.relative_to(root).as_posix(),
    }


def freeze_file(private_root: Path, source: Path) -> dict:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Snapshot source does not exist: {source}")
    return freeze_bytes(private_root, source.read_bytes())


def read_frozen_bytes(private_root: Path, object_ref: dict) -> bytes:
    root = require_private_root(private_root)
    relative = str(object_ref.get("path") or "")
    source = (root / relative).resolve()
    if not is_within(source, root):
        raise ValueError("Frozen object path escapes private storage.")
    expected = str(object_ref.get("sha256") or "")
    if not source.is_file() or sha256_file(source) != expected:
        raise RuntimeError(f"Frozen object is missing or corrupt: {expected}")
    return source.read_bytes()


def freeze_resource_bundle(
    private_root: Path,
    *,
    bundle_id: str,
    bundle_version: int,
    resources: dict[str, Path],
    license_files: dict[str, Path] | None = None,
) -> dict:
    """Freeze exact workflow/capability bytes without preserving mutable paths."""

    if not bundle_id or bundle_version < 1 or not resources:
        raise ValueError("A versioned resource bundle needs an id and at least one resource.")
    frozen_resources = []
    for resource_id, path in sorted(resources.items()):
        if not resource_id:
            raise ValueError("Every frozen resource needs a stable id.")
        frozen_resources.append({"id": resource_id, "object": freeze_file(private_root, path)})
    frozen_licenses = []
    for license_id, path in sorted((license_files or {}).items()):
        frozen_licenses.append({"id": license_id, "object": freeze_file(private_root, path)})
    payload = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "id": bundle_id,
        "version": bundle_version,
        "resources": frozen_resources,
        "licenses": frozen_licenses,
    }
    payload["bundleHash"] = canonical_hash(payload)
    payload["createdAt"] = utc_now()
    root = require_private_root(private_root)
    manifest_path = (
        root
        / "creator-production"
        / "bundles"
        / bundle_id
        / f"v{bundle_version}-{payload['bundleHash']}.json"
    )
    atomic_write_json(manifest_path, payload)
    return {**payload, "manifestPath": manifest_path.relative_to(root).as_posix()}


def freeze_resource_bytes_bundle(
    private_root: Path,
    *,
    bundle_id: str,
    bundle_version: int,
    resources: dict[str, bytes],
    licenses: dict[str, bytes] | None = None,
) -> dict:
    if not bundle_id or bundle_version < 1 or not resources:
        raise ValueError("A versioned resource bundle needs an id and at least one resource.")
    frozen_resources = [
        {"id": resource_id, "object": freeze_bytes(private_root, content)}
        for resource_id, content in sorted(resources.items())
    ]
    frozen_licenses = [
        {"id": license_id, "object": freeze_bytes(private_root, content)}
        for license_id, content in sorted((licenses or {}).items())
    ]
    payload = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "id": bundle_id,
        "version": bundle_version,
        "resources": frozen_resources,
        "licenses": frozen_licenses,
    }
    payload["bundleHash"] = canonical_hash(payload)
    payload["createdAt"] = utc_now()
    root = require_private_root(private_root)
    manifest_path = (
        root
        / "creator-production"
        / "bundles"
        / bundle_id
        / f"v{bundle_version}-{payload['bundleHash']}.json"
    )
    atomic_write_json(manifest_path, payload)
    return {**payload, "manifestPath": manifest_path.relative_to(root).as_posix()}


def verify_resource_bundle(private_root: Path, bundle: dict) -> None:
    unsigned = {key: value for key, value in bundle.items() if key not in {"bundleHash", "createdAt", "manifestPath"}}
    if canonical_hash(unsigned) != bundle.get("bundleHash"):
        raise RuntimeError(f"Resource bundle hash mismatch: {bundle.get('id')}")
    ids: set[str] = set()
    for entry in [*bundle.get("resources", []), *bundle.get("licenses", [])]:
        resource_id = str(entry.get("id") or "")
        if not resource_id or resource_id in ids:
            raise ValueError("Frozen resource IDs must be nonempty and unique.")
        ids.add(resource_id)
        read_frozen_bytes(private_root, entry.get("object") or {})


def create_workflow_lock(
    *,
    workflow_bundle: dict,
    production_profile: dict,
    channel_profile: dict,
    capability_bundle: dict,
    hyperframes_cli_version: str,
    hyperframes_cli_hash: str,
    compiler_version: str,
    compiler_hash: str,
    producer_adapter_version: str,
    producer_adapter_hash: str,
    allowed_domain_resources: dict[str, str],
    transition_source_hashes: dict[str, str] | None = None,
    transition_runtime_registry_hash: str = "",
) -> dict:
    lock = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "workflowId": WORKFLOW_ID,
        "workflowVersion": int(workflow_bundle["version"]),
        "workflowHash": str(workflow_bundle["bundleHash"]),
        "productionProfileId": str(production_profile["id"]),
        "productionProfileVersion": int(production_profile["version"]),
        "productionProfileHash": canonical_hash(production_profile),
        "channelProfileId": str(channel_profile["id"]),
        "channelProfileVersion": int(channel_profile["version"]),
        "channelProfileHash": canonical_hash(channel_profile),
        "capabilityCatalogSnapshotId": str(capability_bundle["id"]),
        "capabilityCatalogSnapshotHash": str(capability_bundle["bundleHash"]),
        "hyperframesCliVersion": hyperframes_cli_version,
        "hyperframesCliHash": hyperframes_cli_hash,
        "compilerVersion": compiler_version,
        "compilerHash": compiler_hash,
        "producerAdapterVersion": producer_adapter_version,
        "producerAdapterHash": producer_adapter_hash,
        "transitionSourceHashes": dict(sorted((transition_source_hashes or {}).items())),
        "transitionRuntimeRegistryHash": transition_runtime_registry_hash,
        "allowedDomainResources": dict(sorted(allowed_domain_resources.items())),
        "forbiddenWorkflowSkills": sorted(FORBIDDEN_WORKFLOW_IDS),
        "executionHost": {
            "kind": "user-visible-codex-task",
            "handoffProtocol": "immutable-file-packet",
            "monitoringMode": "user-visible",
            "nestedCodexProcessAllowed": False,
            "skillInventoryPolicy": "reject-forbidden-visible-skills",
            "outputPromotionPolicy": "application-validated",
            "openaiApiKeyRequired": False,
        },
        "createdAt": utc_now(),
    }
    validate_artifact("workflow-lock", lock)
    return lock


def build_instruction_context(
    private_root: Path,
    *,
    workflow_lock: dict,
    workflow_bundle: dict,
    capability_bundle: dict,
    requested_resource_ids: Iterable[str],
) -> tuple[dict[str, str], dict]:
    """Load only locked resources and produce a dispatcher-owned receipt."""

    validate_artifact("workflow-lock", workflow_lock)
    verify_resource_bundle(private_root, workflow_bundle)
    verify_resource_bundle(private_root, capability_bundle)
    if workflow_lock["workflowId"] != WORKFLOW_ID:
        raise RuntimeError("The project is not owned by creator-video-production.")
    if workflow_bundle["bundleHash"] != workflow_lock["workflowHash"]:
        raise RuntimeError("Workflow bundle does not match the workflow lock.")
    if capability_bundle["bundleHash"] != workflow_lock["capabilityCatalogSnapshotHash"]:
        raise RuntimeError("Capability snapshot does not match the workflow lock.")

    indexed: dict[str, dict] = {}
    for bundle in (workflow_bundle, capability_bundle):
        for entry in bundle.get("resources", []):
            resource_id = str(entry["id"])
            if resource_id in indexed:
                raise RuntimeError(f"Resource ID appears in multiple locked bundles: {resource_id}")
            indexed[resource_id] = entry

    allowed = workflow_lock["allowedDomainResources"]
    requested = list(dict.fromkeys(str(value) for value in requested_resource_ids))
    forbidden_attempts = sorted(set(requested).intersection(FORBIDDEN_WORKFLOW_IDS))
    if forbidden_attempts:
        raise RuntimeError("Forbidden workflow resource requested: " + ", ".join(forbidden_attempts))

    loaded: dict[str, str] = {}
    load_events = []
    for resource_id in requested:
        if resource_id not in allowed:
            raise RuntimeError(f"Resource is not allowlisted by the workflow lock: {resource_id}")
        entry = indexed.get(resource_id)
        if entry is None:
            raise RuntimeError(f"Allowlisted resource bytes are unavailable: {resource_id}")
        content = read_frozen_bytes(private_root, entry["object"])
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != allowed[resource_id]:
            raise RuntimeError(f"Allowlisted resource hash mismatch: {resource_id}")
        try:
            loaded[resource_id] = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"Instruction resource is not UTF-8 text: {resource_id}") from exc
        load_events.append({"resourceId": resource_id, "sha256": actual_hash, "status": "loaded"})

    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "owningWorkflowId": WORKFLOW_ID,
        "workflowVersion": workflow_lock["workflowVersion"],
        "workflowHash": workflow_lock["workflowHash"],
        "channelProfileId": workflow_lock["channelProfileId"],
        "channelProfileHash": workflow_lock["channelProfileHash"],
        "resourceLoads": load_events,
        "forbiddenWorkflowResources": sorted(FORBIDDEN_WORKFLOW_IDS),
        "forbiddenAttempts": [],
        "nativeWorkflowDiscoveryPerformed": False,
        "fallbackOccurred": False,
        "createdAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    validate_artifact("instruction-receipt", receipt)
    return loaded, receipt


def transcript_word_timing_payload(document: dict) -> dict:
    project = document.get("project") if isinstance(document.get("project"), dict) else document
    words = project.get("words") if isinstance(project, dict) else None
    if not isinstance(words, list) or not words:
        raise ValueError("The final transcript contains no words.")
    normalized = []
    seen: set[str] = set()
    previous_start = -1
    for word in words:
        word_id = str(word.get("id") or "")
        if not word_id or word_id in seen:
            raise ValueError("Final transcript word IDs must be nonempty and unique.")
        seen.add(word_id)
        start_frame = int(word["start_frame"])
        end_frame = int(word["end_frame"])
        if start_frame < previous_start or end_frame < start_frame:
            raise ValueError("Final transcript word frames must be monotonic.")
        previous_start = start_frame
        start = float(word["start"])
        end = float(word["end"])
        if not all(math.isfinite(value) for value in (start, end)) or start < 0 or end < start:
            raise ValueError("Final transcript word times must be finite, nonnegative, and ordered.")
        normalized.append(
            {
                "id": word_id,
                "start": word["start"],
                "end": word["end"],
                "startFrame": start_frame,
                "endFrame": end_frame,
            }
        )
    return {"fps": project.get("fps"), "words": normalized}


def transcript_word_timing_hash(document: dict) -> str:
    return canonical_hash(transcript_word_timing_payload(document))


def create_legacy_locked_transcript_attestation(
    *,
    locked_cut: Path,
    transcript_path: Path,
    actor: str,
    reason: str,
) -> dict:
    """Bind an explicit legacy import decision to immutable source identities."""

    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("Legacy transcript import requires an actor and reason.")
    document = json.loads(transcript_path.read_text(encoding="utf-8"))
    attestation = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "attestationKind": "legacy-final-transcript-import",
        "actor": actor,
        "reason": reason,
        "sourceTranscriptSha256": sha256_file(transcript_path),
        "lockedCutSha256": sha256_file(locked_cut),
        "wordTimingSha256": transcript_word_timing_hash(document),
        "timingAuthority": "final-locked-transcript",
        "timingMutationAllowed": False,
        "createdAt": utc_now(),
    }
    attestation["attestationHash"] = canonical_hash(attestation)
    return attestation


def _verify_legacy_locked_transcript_attestation(
    attestation: dict,
    *,
    locked_cut_hash: str,
    transcript_hash: str,
    word_timing_hash: str,
) -> None:
    if not isinstance(attestation, dict):
        raise RuntimeError("Legacy transcript import requires an explicit attestation.")
    unsigned = {
        key: value for key, value in attestation.items() if key != "attestationHash"
    }
    if canonical_hash(unsigned) != attestation.get("attestationHash"):
        raise RuntimeError("Legacy transcript import attestation was modified.")
    required = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "attestationKind": "legacy-final-transcript-import",
        "sourceTranscriptSha256": transcript_hash,
        "lockedCutSha256": locked_cut_hash,
        "wordTimingSha256": word_timing_hash,
        "timingAuthority": "final-locked-transcript",
        "timingMutationAllowed": False,
    }
    for key, expected in required.items():
        if attestation.get(key) != expected:
            raise RuntimeError(f"Legacy transcript import attestation mismatch: {key}")
    if not str(attestation.get("actor") or "").strip() or not str(
        attestation.get("reason") or ""
    ).strip():
        raise RuntimeError("Legacy transcript import attestation has no actor or reason.")


def create_locked_transcript_receipt(
    *,
    locked_cut: Path,
    transcript_path: Path,
    locked_audio_hash: str | None = None,
    legacy_import_attestation: dict | None = None,
) -> dict:
    document = json.loads(transcript_path.read_text(encoding="utf-8"))
    timing_hash = transcript_word_timing_hash(document)
    project = document.get("project") if isinstance(document.get("project"), dict) else document
    generation = project.get("generation") if isinstance(project, dict) else None
    provenance = generation.get("lockedTranscript") if isinstance(generation, dict) else None
    locked_cut_hash = sha256_file(locked_cut)
    transcript_hash = sha256_file(transcript_path)
    required_provenance = {
        "timingAuthority": "final-locked-transcript",
        "timingMutationAllowed": False,
        "lockedCutSha256": locked_cut_hash,
        "wordTimingSha256": timing_hash,
    }
    if isinstance(provenance, dict):
        if legacy_import_attestation is not None:
            raise RuntimeError(
                "Legacy transcript attestation is not allowed when embedded provenance exists."
            )
        for key, expected in required_provenance.items():
            if provenance.get(key) != expected:
                raise RuntimeError(f"Final transcript provenance mismatch: {key}")
        provenance_mode = "embedded-locked-transcript"
    else:
        if legacy_import_attestation is None:
            raise RuntimeError("Final transcript is missing its locked-transcript provenance.")
        _verify_legacy_locked_transcript_attestation(
            legacy_import_attestation,
            locked_cut_hash=locked_cut_hash,
            transcript_hash=transcript_hash,
            word_timing_hash=timing_hash,
        )
        provenance_mode = "explicit-legacy-import-attestation"
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "lockedCutSha256": locked_cut_hash,
        "lockedAudioSha256": locked_audio_hash or "",
        "transcriptSha256": transcript_hash,
        "wordTimingSha256": timing_hash,
        "wordCount": len(transcript_word_timing_payload(document)["words"]),
        "timingAuthority": "final-locked-transcript",
        "timingMutationAllowed": False,
        "provenanceMode": provenance_mode,
        "legacyImportAttestation": legacy_import_attestation,
        "createdAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    return receipt


def locked_audio_stream_hash(locked_cut: Path) -> str:
    """Hash the exact encoded audio packet stream without decoding or resampling it."""

    result = subprocess.run(
        [
            str(find_ffmpeg()),
            "-v",
            "error",
            "-i",
            str(locked_cut),
            "-map",
            "0:a:0",
            "-c:a",
            "copy",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Locked cut must contain a readable audio stream: "
            + (result.stderr or result.stdout)[-800:]
        )
    match = __import__("re").search(r"SHA256=([a-fA-F0-9]{64})", result.stdout)
    if not match:
        raise RuntimeError("FFmpeg did not return a locked-audio stream hash.")
    return match.group(1).lower()


def verify_locked_transcript_receipt(
    receipt: dict,
    *,
    locked_cut: Path,
    transcript_path: Path,
    locked_audio_hash: str | None = None,
) -> None:
    unsigned = {key: value for key, value in receipt.items() if key != "receiptHash"}
    if canonical_hash(unsigned) != receipt.get("receiptHash"):
        raise RuntimeError("Locked transcript receipt was modified.")
    current = create_locked_transcript_receipt(
        locked_cut=locked_cut,
        transcript_path=transcript_path,
        locked_audio_hash=locked_audio_hash,
        legacy_import_attestation=receipt.get("legacyImportAttestation"),
    )
    for key in ("lockedCutSha256", "lockedAudioSha256", "transcriptSha256", "wordTimingSha256", "wordCount"):
        if current[key] != receipt.get(key):
            raise RuntimeError(f"Locked transcript identity changed: {key}")


def assert_state_transition(current: str, target: str) -> None:
    if current not in _ALLOWED_STATE_TRANSITIONS or target not in _ALLOWED_STATE_TRANSITIONS[current]:
        raise ValueError(f"Illegal Creator Production state transition: {current} -> {target}")


def resolve_channel_profile(profile: dict, parent: dict | None = None) -> dict:
    """Resolve one optional parent with deterministic map/set/array behavior."""

    validate_artifact("channel-profile", profile)
    if parent is None:
        if profile.get("parentProfileRef") is not None:
            raise ValueError("The channel profile names a parent that was not supplied.")
        return json.loads(json.dumps(profile))
    validate_artifact("channel-profile", parent)
    parent_ref = profile.get("parentProfileRef")
    expected_ref = f"{parent['id']}@{parent['version']}"
    if parent_ref != expected_ref:
        raise ValueError(f"Channel profile parent must resolve to {expected_ref}.")
    if parent.get("parentProfileRef") is not None:
        raise ValueError("Channel profile version 1 supports exactly one parent level.")
    resolved = _merge_profile_value(parent, profile, path=())
    resolved["resolvedLineage"] = [
        {"id": parent["id"], "version": parent["version"], "hash": canonical_hash(parent)},
        {"id": profile["id"], "version": profile["version"], "hash": canonical_hash(profile)},
    ]
    resolved["resolvedProfileHash"] = canonical_hash(
        {key: value for key, value in resolved.items() if key != "resolvedProfileHash"}
    )
    return resolved


def _merge_profile_value(parent: object, child: object, *, path: tuple[str, ...]) -> object:
    if isinstance(parent, dict) and isinstance(child, dict):
        result = json.loads(json.dumps(parent))
        for key, value in child.items():
            if key in {"id", "version", "parentProfileRef"}:
                result[key] = value
            elif key in result:
                result[key] = _merge_profile_value(result[key], value, path=(*path, key))
            else:
                result[key] = json.loads(json.dumps(value))
        return result
    if isinstance(parent, list) and isinstance(child, list):
        if path and path[-1] in {"preferred", "discouraged", "disabled", "hard", "warnings", "objectives"}:
            by_key: dict[str, object] = {}
            for item in [*parent, *child]:
                key = str(item.get("id")) if isinstance(item, dict) else str(item)
                if key in by_key and by_key[key] != item:
                    raise ValueError(f"Conflicting inherited value for {'.'.join(path)} id {key}.")
                by_key[key] = json.loads(json.dumps(item))
            return [by_key[key] for key in sorted(by_key)]
        return json.loads(json.dumps(child))
    return json.loads(json.dumps(child))


def validate_episode_manifest(manifest: dict) -> None:
    validate_artifact("episode-manifest", manifest)
    sequences = manifest["sequences"]
    ids = [sequence["id"] for sequence in sequences]
    if len(ids) != len(set(ids)):
        raise ValueError("Episode sequence IDs must be unique.")
    by_id = {sequence["id"]: sequence for sequence in sequences}
    cursor = 0
    for sequence in sequences:
        if sequence["absoluteStartFrame"] != cursor:
            raise ValueError("Episode sequences must cover the complete runtime without gaps or overlaps.")
        if sequence["absoluteEndFrameExclusive"] <= sequence["absoluteStartFrame"]:
            raise ValueError(f"Sequence has an empty frame range: {sequence['id']}")
        cursor = sequence["absoluteEndFrameExclusive"]
        _validate_composition_graph(sequence)
        required_assets = {
            item["id"] for item in sequence["assetRequirements"]
        }
        resolved_assets = {
            item["id"] for item in sequence["resolvedAssetRefs"]
        }
        if required_assets != resolved_assets:
            raise ValueError(
                f"Sequence asset requirements are not exactly resolved: {sequence['id']}"
            )
        for asset in sequence["resolvedAssetRefs"]:
            rights = asset["rightsReceipt"]
            expected_rights_hash = canonical_hash(
                {key: value for key, value in rights.items() if key != "receiptHash"}
            )
            if rights["receiptHash"] != expected_rights_hash:
                raise ValueError(
                    f"Asset rights receipt was modified: {asset['id']}"
                )
    if cursor != manifest["totalFrames"]:
        raise ValueError("Episode sequences do not cover totalFrames.")
    boundaries = manifest["transitionBoundaries"]
    if len(boundaries) != max(0, len(sequences) - 1):
        raise ValueError("Every adjacent sequence pair needs exactly one transition boundary.")
    for index, boundary in enumerate(boundaries):
        if boundary["fromSequenceId"] != ids[index] or boundary["toSequenceId"] != ids[index + 1]:
            raise ValueError("Transition boundaries must match sequence adjacency and order.")
        mode = boundary["mode"]
        if mode in {"none", "hard-cut"} and (
            boundary["durationFrames"] != 0 or boundary["overlapFrames"] != 0
        ):
            raise ValueError(f"{mode} boundaries require zero duration and overlap.")
        if mode == "transition" and not boundary.get("implementationRef"):
            raise ValueError("Transition boundaries require an admitted implementationRef.")
        if mode == "transition" and boundary["durationFrames"] <= 0:
            raise ValueError("Transition boundaries require a positive duration.")
        if boundary["overlapFrames"] > boundary["durationFrames"]:
            raise ValueError("Transition overlap cannot exceed its declared duration.")
        if boundary["fromSequenceId"] not in by_id or boundary["toSequenceId"] not in by_id:
            raise ValueError("Transition boundary references an unknown sequence.")
    _validate_chapters(manifest)


def _validate_composition_graph(sequence: dict) -> None:
    graph = sequence.get("compositionGraph")
    if not isinstance(graph, dict):
        raise ValueError(f"Sequence is not materialized: {sequence['id']}")
    elements = graph.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError(f"Sequence composition graph has no elements: {sequence['id']}")
    element_ids = [str(element.get("id") or "") for element in elements]
    if any(not element_id for element_id in element_ids) or len(element_ids) != len(set(element_ids)):
        raise ValueError(f"Composition graph element IDs must be unique: {sequence['id']}")
    known = set(element_ids)
    for element in elements:
        parent_id = element.get("parentId")
        if parent_id is not None and parent_id not in known:
            raise ValueError(f"Composition graph parent does not exist: {parent_id}")
    for event in graph.get("events", []):
        if event["targetElementId"] not in known:
            raise ValueError("Composition event references an unknown element.")
        if event["contentBearing"] and not event.get("wordId") and not event.get("sourceEventAnchorId"):
            raise ValueError("Content-bearing events need a word or measured source-event anchor.")
        if not (
            sequence["absoluteStartFrame"]
            <= event["absoluteFrame"]
            < sequence["absoluteEndFrameExclusive"]
        ):
            raise ValueError(f"Composition event falls outside its sequence: {event['id']}")


def _validate_chapters(manifest: dict) -> None:
    sequences = manifest["sequences"]
    chapters = manifest["chapters"]
    chapter_ids = [chapter["id"] for chapter in chapters]
    if len(chapter_ids) != len(set(chapter_ids)):
        raise ValueError("Chapter IDs must be unique.")
    sequence_chapters = [sequence["chapterId"] for sequence in sequences]
    if set(sequence_chapters) != set(chapter_ids):
        raise ValueError("Every chapter must own sequences and every sequence must reference a chapter.")
    for chapter in chapters:
        owned = [sequence for sequence in sequences if sequence["chapterId"] == chapter["id"]]
        indexes = [sequences.index(sequence) for sequence in owned]
        if indexes != list(range(min(indexes), max(indexes) + 1)):
            raise ValueError("A completed editorial chapter must own one contiguous sequence range.")
        if chapter["absoluteStartFrame"] != owned[0]["absoluteStartFrame"]:
            raise ValueError("Chapter start must match its first sequence.")
        if chapter["absoluteEndFrameExclusive"] != owned[-1]["absoluteEndFrameExclusive"]:
            raise ValueError("Chapter end must match its final sequence.")
        if not str(chapter.get("editorialSectionId") or "") or not str(chapter.get("completionRationale") or ""):
            raise ValueError("A chapter needs a completed editorial section and completion rationale.")
        if "targetDurationSec" in chapter or "targetFrameCount" in chapter:
            raise ValueError("Duration targets may not determine Creator Production chapters.")


def compile_episode_manifest(manifest: dict, *, compiler_version: str) -> dict:
    """Lower a fully materialized manifest without inventing creative values."""

    validate_episode_manifest(manifest)
    compiled_sequences = []
    for sequence in manifest["sequences"]:
        graph = sequence["compositionGraph"]
        graph_hash = canonical_hash(graph)
        implementation_set = sequence["resolvedImplementationSetRef"]
        compiled_sequences.append(
            {
                "sequenceId": sequence["id"],
                "chapterId": sequence["chapterId"],
                "absoluteStartFrame": sequence["absoluteStartFrame"],
                "absoluteEndFrameExclusive": sequence["absoluteEndFrameExclusive"],
                "compositionGraphHash": graph_hash,
                "topologyHash": canonical_hash(
                    {
                        "elements": [
                            {
                                "kind": element["kind"],
                                "parentId": element.get("parentId"),
                                "geometry": element["geometry"],
                                "zIndex": element["zIndex"],
                            }
                            for element in graph["elements"]
                        ],
                        "states": [event["operation"] for event in graph.get("events", [])],
                    }
                ),
                "visualSignature": canonical_hash(
                    {
                        "semanticForm": sequence["semanticForm"],
                        "topology": sequence["selectedCanvasTopology"],
                        "presentationRole": sequence["presentationRole"],
                        "narrativeStateRole": sequence["narrativeStateRole"],
                        "implementationSet": implementation_set,
                    }
                ),
                "motionSignature": canonical_hash(
                    [
                        {
                            "operation": event["operation"],
                            "easing": event.get("easing"),
                            "durationFrames": event.get("durationFrames"),
                        }
                        for event in graph.get("events", [])
                    ]
                ),
                "implementationSetHash": canonical_hash(implementation_set),
                "compiledGraph": graph,
            }
        )
    compiled = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": manifest["episodeId"],
        "manifestRevision": manifest["revision"],
        "manifestHash": canonical_hash(manifest),
        "compilerVersion": compiler_version,
        "workflowId": WORKFLOW_ID,
        "sequences": compiled_sequences,
        "transitionBoundaries": manifest["transitionBoundaries"],
        "chapters": manifest["chapters"],
    }
    compiled["buildHash"] = canonical_hash(compiled)
    return compiled


def copy_frozen_object(private_root: Path, object_ref: dict, destination: Path) -> None:
    """Materialize a frozen object without trusting mutable source paths."""

    source = content_addressed_object_path(private_root, object_ref["sha256"])
    read_frozen_bytes(private_root, object_ref)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def artifact_id_storage_segment(artifact_id: str) -> str:
    """Encode a logical artifact id as one portable filesystem segment."""

    if not artifact_id:
        raise ValueError("Artifact ids must be nonempty.")
    encoded = quote(artifact_id, safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    if encoded in {".", ".."}:
        encoded = encoded.replace(".", "%2E")
    return encoded


def write_versioned_artifact(
    private_root: Path,
    *,
    artifact_kind: str,
    artifact_id: str,
    version: int,
    value: dict,
    schema_name: str | None = None,
) -> dict:
    """Persist an immutable readable revision plus content-addressed exact bytes."""

    root = require_private_root(private_root)
    if not artifact_kind or not artifact_id or version < 1:
        raise ValueError("Versioned artifacts require a kind, id, and positive version.")
    if schema_name:
        validate_artifact(schema_name, value)
    content = canonical_json_bytes(value)
    object_ref = freeze_bytes(root, content)
    destination = (
        root
        / "creator-production"
        / "artifacts"
        / artifact_kind
        / artifact_id_storage_segment(artifact_id)
        / f"v{version}-{object_ref['sha256']}.json"
    )
    version_directory = destination.parent
    if version_directory.is_dir():
        conflicting = [
            path
            for path in version_directory.glob(f"v{version}-*.json")
            if path.name != destination.name
        ]
        if conflicting:
            raise RuntimeError(
                f"Immutable artifact revision {artifact_kind}/{artifact_id}@{version} already exists."
            )
    if destination.exists():
        if destination.read_bytes() != content:
            raise RuntimeError("An immutable artifact revision cannot be overwritten.")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    return {
        "artifactKind": artifact_kind,
        "artifactId": artifact_id,
        "version": version,
        "sha256": object_ref["sha256"],
        "object": object_ref,
        "path": destination.relative_to(root).as_posix(),
    }


def next_artifact_version(
    private_root: Path,
    artifact_kind: str,
    artifact_id: str,
) -> int:
    root = require_private_root(private_root)
    directory = (
        root
        / "creator-production"
        / "artifacts"
        / artifact_kind
        / artifact_id_storage_segment(artifact_id)
    )
    versions = []
    if directory.is_dir():
        for path in directory.glob("v*-*.json"):
            try:
                versions.append(int(path.name.split("-", 1)[0].removeprefix("v")))
            except ValueError:
                continue
    return max(versions, default=0) + 1


def create_build_lock(
    *,
    manifest: dict,
    compiled: dict,
    resolved_profile_hash: str,
    consumed_profile_dependencies: dict[str, dict],
    capability_implementation_hashes: dict[str, list[str]],
    asset_hashes: dict[str, list[str]],
    generated_source_hashes: dict[str, str],
    compiled_source_hashes: dict[str, str],
    validation_result_ids: dict[str, list[str]],
    workflow_lock: dict,
) -> dict:
    validate_episode_manifest(manifest)
    if compiled.get("manifestHash") != canonical_hash(manifest):
        raise ValueError("Compiled episode does not belong to the supplied manifest.")
    compiled_by_id = {item["sequenceId"]: item for item in compiled["sequences"]}
    sequence_locks = []
    for sequence in manifest["sequences"]:
        sequence_id = sequence["id"]
        compiled_sequence = compiled_by_id.get(sequence_id)
        if compiled_sequence is None:
            raise ValueError(f"Compiled episode is missing sequence {sequence_id}.")
        consumed = consumed_profile_dependencies.get(sequence_id)
        if not isinstance(consumed, dict):
            raise ValueError(f"Sequence is missing consumed profile dependencies: {sequence_id}")
        implementation_hashes = sorted(capability_implementation_hashes.get(sequence_id, []))
        if not implementation_hashes and sequence["presentationRole"] != "source-led":
            raise ValueError(f"Authored sequence has no capability implementation hash: {sequence_id}")
        lock = {
            "sequenceId": sequence_id,
            "chapterId": sequence["chapterId"],
            "manifestEntryHash": canonical_hash(sequence),
            "compositionGraphHash": compiled_sequence["compositionGraphHash"],
            "topologyHash": compiled_sequence["topologyHash"],
            "visualSignature": compiled_sequence["visualSignature"],
            "motionSignature": compiled_sequence["motionSignature"],
            "consumedProfileDependencyHash": canonical_hash(consumed),
            "capabilityImplementationHashes": implementation_hashes,
            "assetHashes": sorted(asset_hashes.get(sequence_id, [])),
            "sourceEventAnchorHashes": sorted(
                canonical_hash(anchor)
                for anchor in manifest.get("sourceEventAnchors", [])
                if anchor["id"]
                in {
                    event.get("sourceEventAnchorId")
                    for event in sequence["compositionGraph"].get("events", [])
                }
            ),
            "generatedSourceHash": generated_source_hashes.get(sequence_id, ""),
            "compiledSourceHash": compiled_source_hashes.get(sequence_id, ""),
            "validationResultIds": sorted(validation_result_ids.get(sequence_id, [])),
        }
        lock["sequenceBuildHash"] = canonical_hash(lock)
        sequence_locks.append(lock)

    chapter_locks = []
    for chapter in manifest["chapters"]:
        owned = [
            item for item in sequence_locks if item["chapterId"] == chapter["id"]
        ]
        dependencies = {
            "chapter": chapter,
            "sequenceBuildHashes": [item["sequenceBuildHash"] for item in owned],
            "transitionBoundaries": [
                boundary
                for boundary in manifest["transitionBoundaries"]
                if boundary["fromSequenceId"] in {item["sequenceId"] for item in owned}
                or boundary["toSequenceId"] in {item["sequenceId"] for item in owned}
            ],
        }
        chapter_locks.append(
            {
                "chapterId": chapter["id"],
                "absoluteStartFrame": chapter["absoluteStartFrame"],
                "absoluteEndFrameExclusive": chapter["absoluteEndFrameExclusive"],
                "chapterInputHash": canonical_hash(dependencies),
            }
        )
    lock = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": manifest["episodeId"],
        "manifestRevision": manifest["revision"],
        "manifestHash": canonical_hash(manifest),
        "workflowLockHash": canonical_hash(workflow_lock),
        "lockedCutSha256": manifest["lockedCutSha256"],
        "lockedAudioSha256": manifest["lockedAudioSha256"],
        "transcriptSha256": manifest["transcriptSha256"],
        "wordTimingSha256": manifest["wordTimingSha256"],
        "resolvedProfileHash": resolved_profile_hash,
        "runtime": {
            "hyperframesCliVersion": workflow_lock["hyperframesCliVersion"],
            "hyperframesCliHash": workflow_lock["hyperframesCliHash"],
            "compilerVersion": workflow_lock["compilerVersion"],
            "compilerHash": workflow_lock["compilerHash"],
            "producerAdapterVersion": workflow_lock["producerAdapterVersion"],
            "producerAdapterHash": workflow_lock["producerAdapterHash"],
            "capabilityCatalogSnapshotHash": workflow_lock["capabilityCatalogSnapshotHash"],
            "transitionSourceHashes": workflow_lock["transitionSourceHashes"],
            "transitionRuntimeRegistryHash": workflow_lock["transitionRuntimeRegistryHash"],
        },
        "sequences": sequence_locks,
        "chapters": chapter_locks,
        "createdAt": utc_now(),
    }
    lock["buildHash"] = canonical_hash(lock)
    validate_artifact("build-lock", lock)
    return lock


def calculate_localized_invalidation(old_build: dict, new_build: dict) -> dict:
    old_sequences = {item["sequenceId"]: item["sequenceBuildHash"] for item in old_build["sequences"]}
    new_sequences = {item["sequenceId"]: item["sequenceBuildHash"] for item in new_build["sequences"]}
    changed_sequences = sorted(
        sequence_id
        for sequence_id in set(old_sequences) | set(new_sequences)
        if old_sequences.get(sequence_id) != new_sequences.get(sequence_id)
    )
    old_chapters = {item["chapterId"]: item["chapterInputHash"] for item in old_build["chapters"]}
    new_chapters = {item["chapterId"]: item["chapterInputHash"] for item in new_build["chapters"]}
    changed_chapters = sorted(
        chapter_id
        for chapter_id in set(old_chapters) | set(new_chapters)
        if old_chapters.get(chapter_id) != new_chapters.get(chapter_id)
    )
    return {
        "changedSequenceIds": changed_sequences,
        "changedChapterIds": changed_chapters,
        "reusableSequenceIds": sorted(
            sequence_id
            for sequence_id in set(old_sequences) & set(new_sequences)
            if old_sequences[sequence_id] == new_sequences[sequence_id]
        ),
        "reusableChapterIds": sorted(
            chapter_id
            for chapter_id in set(old_chapters) & set(new_chapters)
            if old_chapters[chapter_id] == new_chapters[chapter_id]
        ),
    }


def create_review_state(*, episode_id: str, build_lock: dict) -> dict:
    review = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": episode_id,
        "revision": 1,
        "buildHash": build_lock["buildHash"],
        "approvalRecords": [],
        "activeNotes": [],
        "noteHistory": [],
        "autosave": {"status": "saved", "failureReason": None, "updatedAt": utc_now()},
        "localizedInvalidation": {
            "changedSequenceIds": [],
            "changedChapterIds": [],
            "reusableSequenceIds": [],
            "reusableChapterIds": [],
        },
    }
    validate_artifact("review-state", review)
    return review


def save_review_note(review: dict, note: dict) -> dict:
    validate_artifact("review-state", review)
    updated = json.loads(json.dumps(review))
    note_id = str(note.get("id") or "")
    if not note_id:
        raise ValueError("Review notes need a stable id.")
    if note.get("buildHash") != updated["buildHash"]:
        raise ValueError("Review note targets a stale build.")
    matches = [item for item in updated["activeNotes"] if item["id"] == note_id]
    if len(matches) > 1:
        raise RuntimeError("Review state contains duplicate active note IDs.")
    note_copy = json.loads(json.dumps(note))
    note_copy["saveStatus"] = "saved"
    note_copy["savedAt"] = utc_now()
    if matches:
        index = updated["activeNotes"].index(matches[0])
        updated["activeNotes"][index] = note_copy
    else:
        updated["activeNotes"].append(note_copy)
    updated["revision"] += 1
    updated["autosave"] = {"status": "saved", "failureReason": None, "updatedAt": utc_now()}
    validate_artifact("review-state", updated)
    return updated


def accept_review_note(review: dict, note_id: str, *, actor_role: str) -> dict:
    if actor_role != "creator":
        raise PermissionError("Only the creator may accept and archive a review note.")
    validate_artifact("review-state", review)
    updated = json.loads(json.dumps(review))
    matches = [item for item in updated["activeNotes"] if item["id"] == note_id]
    if len(matches) != 1:
        raise ValueError(f"Active review note not found: {note_id}")
    note = matches[0]
    updated["activeNotes"].remove(note)
    updated["noteHistory"].append({**note, "acceptedAt": utc_now(), "acceptedBy": "creator"})
    updated["revision"] += 1
    validate_artifact("review-state", updated)
    return updated


def create_approval_record(review: dict, build_lock: dict, *, actor_role: str) -> dict:
    if actor_role != "creator":
        raise PermissionError("Only the creator may approve a complete revision.")
    validate_artifact("review-state", review)
    validate_artifact("build-lock", build_lock)
    if review["activeNotes"]:
        raise ValueError("Complete revision approval is blocked while active notes remain.")
    if review["buildHash"] != build_lock["buildHash"]:
        raise ValueError("Review state and build lock do not match.")
    record = {
        "id": f"approval-{len(review['approvalRecords']) + 1}",
        "creatorApproved": True,
        "buildHash": build_lock["buildHash"],
        "manifestRevision": build_lock["manifestRevision"],
        "orderedSequenceBuildHashes": [
            item["sequenceBuildHash"] for item in build_lock["sequences"]
        ],
        "orderedChapterInputHashes": [
            item["chapterInputHash"] for item in build_lock["chapters"]
        ],
        "approvedAt": utc_now(),
    }
    updated = json.loads(json.dumps(review))
    updated["approvalRecords"].append(record)
    updated["revision"] += 1
    validate_artifact("review-state", updated)
    return updated
