from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.core.creator_capabilities import inventory_hyperframes_capabilities
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    WORKFLOW_ID,
    atomic_write_json,
    canonical_hash,
    canonical_json_bytes,
    create_locked_transcript_receipt,
    create_workflow_lock,
    freeze_resource_bytes_bundle,
    locked_audio_stream_hash,
    require_private_root,
    assert_state_transition,
    utc_now,
    validate_artifact,
    verify_locked_transcript_receipt,
    verify_resource_bundle,
    write_versioned_artifact,
)
from app.core.file_utils import is_within, sha256_file
from app.core.settings import user_data_root


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "creator-production"
CAPTURE_LAYOUT_CATALOG_ID = "creator-obs-capture-layouts"
CAPTURE_LAYOUT_IDS = (
    "full-screen-talking",
    "talking-left",
    "talking-right",
    "talking-bottom-left",
    "talking-top-left",
    "talking-bottom-right",
    "talking-top-right",
    "computer-screen-only",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _capture_layout_catalog_document(private_root: Path) -> dict:
    """Load creator-approved capture facts without granting legacy workflow authority."""

    root = require_private_root(private_root)
    private_catalog = (
        root
        / "creator-production-inputs"
        / "capture-layout-catalog.v1.json"
    )
    if private_catalog.is_file():
        catalog = _load_json(private_catalog)
        validate_artifact("capture-layout-catalog", catalog)
        return catalog

    legacy_facts = REPOSITORY_ROOT / "visual-production" / "layouts" / "scene-geometry.json"
    if not legacy_facts.is_file():
        raise ValueError(
            "Creator Production requires the creator-approved eight-layout capture catalog "
            "under creator-production-inputs/capture-layout-catalog.v1.json."
        )
    document = _load_json(legacy_facts)
    layouts = document.get("layouts")
    if not isinstance(layouts, dict) or set(layouts) != set(CAPTURE_LAYOUT_IDS):
        raise ValueError("The creator-approved capture facts do not define exactly eight OBS layouts.")
    normalized_layouts = {}
    for layout_id in CAPTURE_LAYOUT_IDS:
        source = layouts[layout_id]
        evidence = str(
            source.get("verifiedAgainst")
            or source.get("note")
            or f"OBS scene geometry: {source.get('obsScene')}"
        ).strip()
        normalized_layouts[layout_id] = {
            "obsScene": str(source.get("obsScene") or "").strip(),
            "speakerBounds": source.get("speakerBounds"),
            "origin": source.get("origin"),
            "evidence": evidence,
        }
    catalog = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "id": CAPTURE_LAYOUT_CATALOG_ID,
        "version": 1,
        "frame": document.get("frame"),
        "source": {
            "authority": "creator-approved-capture-facts",
            "sourceDocumentSha256": sha256_file(legacy_facts),
            "measurementMethod": str(
                (document.get("source") or {}).get("method") or "documented OBS geometry"
            ),
            "readOnlyLegacyRecovery": True,
            "executionAuthority": False,
        },
        "layouts": normalized_layouts,
    }
    validate_artifact("capture-layout-catalog", catalog)
    return catalog


def resolve_hyperframes_animation_source(
    *,
    private_root: Path,
    hyperframes_version: str,
) -> Path:
    root = require_private_root(private_root)
    candidates = [
        root / "creator-production-inputs" / "hyperframes-animation",
    ]
    cache_root = user_data_root() / "private-capability-snapshots"
    if cache_root.is_dir():
        for metadata_path in sorted(cache_root.glob("*/snapshot.json"), reverse=True):
            try:
                metadata = _load_json(metadata_path)
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("hyperframesVersion") == hyperframes_version:
                candidates.append(metadata_path.parent / "hyperframes-animation")
    candidates.extend(
        [
            Path.home() / ".codex" / "skills" / "hyperframes-animation",
            Path.home() / ".agents" / "skills" / "hyperframes-animation",
        ]
    )
    for candidate in candidates:
        if all(
            (candidate / relative).is_file()
            for relative in ("SKILL.md", "rules-index.md", "blueprints-index.md")
        ):
            return candidate.resolve()
    raise ValueError(
        "No preserved HyperFrames animation source matches the pinned runtime. "
        "Place the exact source under creator-production-inputs/hyperframes-animation."
    )


def preserve_hyperframes_animation_source(
    *,
    skill_root: Path,
    catalog: dict,
) -> Path:
    snapshot_root = (
        user_data_root()
        / "private-capability-snapshots"
        / catalog["catalogHash"]
    )
    destination_root = snapshot_root / "hyperframes-animation"
    for source in sorted(path for path in skill_root.rglob("*") if path.is_file()):
        relative = source.relative_to(skill_root)
        destination = destination_root / relative
        content = source.read_bytes()
        if destination.is_file():
            if destination.read_bytes() != content:
                raise RuntimeError("Private native capability snapshot bytes changed.")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix(destination.suffix + ".pending")
        pending.write_bytes(content)
        pending.replace(destination)
    metadata = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "catalogHash": catalog["catalogHash"],
        "hyperframesVersion": catalog["sourceIdentity"]["hyperframesVersion"],
        "sourceIdentity": catalog["sourceIdentity"],
        "createdAt": utc_now(),
    }
    metadata_path = snapshot_root / "snapshot.json"
    if metadata_path.is_file():
        existing = _load_json(metadata_path)
        if (
            existing.get("catalogHash") != catalog["catalogHash"]
            or existing.get("sourceIdentity") != catalog["sourceIdentity"]
        ):
            raise RuntimeError("Private native capability snapshot metadata changed.")
    else:
        atomic_write_json(metadata_path, metadata)
    return destination_root


def available_channel_profiles(private_root: Path | None = None) -> list[dict]:
    profiles = []
    roots = [(PACKAGE_ROOT / "profiles", PACKAGE_ROOT / "reference-grammars")]
    if private_root is not None:
        root = require_private_root(private_root)
        inputs = root / "creator-production-inputs"
        roots.append((inputs / "profiles", inputs / "reference-grammars"))
    for profile_root, grammar_root in roots:
        if not profile_root.is_dir():
            continue
        for path in sorted(profile_root.glob("*.v*.json")):
            if path.name == "creator-default.v1.json":
                continue
            value = _load_json(path)
            validate_artifact("channel-profile", value)
            grammar_name = value["referenceGrammarRef"].replace("@", ".v") + ".md"
            grammar_path = grammar_root / grammar_name
            if not grammar_path.is_file():
                raise ValueError(
                    f"Channel profile {value['id']} has no versioned reference grammar."
                )
            profiles.append(
                {
                    "id": value["id"],
                    "version": value["version"],
                    "referenceGrammarRef": value["referenceGrammarRef"],
                    "fileName": path.name,
                    "profilePath": str(path.resolve()),
                    "grammarPath": str(grammar_path.resolve()),
                }
            )
    references = [f"{item['id']}@{item['version']}" for item in profiles]
    if len(references) != len(set(references)):
        raise ValueError(
            "Channel profile id/version references must be unique across registries."
        )
    # Historical versions remain frozen with existing projects, but only the
    # newest version of each channel is offered for a new project.
    latest: dict[str, dict] = {}
    for profile in profiles:
        current = latest.get(profile["id"])
        if current is None or profile["version"] > current["version"]:
            latest[profile["id"]] = profile
    return sorted(latest.values(), key=lambda item: item["id"])


def _resource_bytes(skill_root: Path, catalog: dict) -> dict[str, bytes]:
    resources = {"capability:catalog": canonical_json_bytes(catalog)}
    skill_root = skill_root.resolve()
    for resource in [*catalog["sourceResources"], *catalog["supportResources"]]:
        relative = str(resource["relativePath"])
        # All catalog resources freeze from the HyperFrames skill tree.
        path = (skill_root / relative).resolve()
        if not is_within(path, skill_root) or not path.is_file():
            raise RuntimeError(f"Capability resource cannot be frozen: {resource['id']}")
        if sha256_file(path) != resource["sha256"]:
            raise RuntimeError(f"Capability source changed during bootstrap: {resource['id']}")
        resources[resource["id"]] = path.read_bytes()
    return resources


def _workflow_resource_bytes(
    *,
    additional_reference_grammar: Path | None = None,
) -> dict[str, bytes]:
    resources: dict[str, bytes] = {}
    for folder in ("workflow", "tasks", "schemas", "profiles", "reference-grammars"):
        root = PACKAGE_ROOT / folder
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            resources[f"workflow:package:{relative}"] = path.read_bytes()
    resources["workflow:main"] = (PACKAGE_ROOT / "workflow" / "WORKFLOW.md").read_bytes()
    for task_path in sorted((PACKAGE_ROOT / "tasks").glob("*.md")):
        resources[f"workflow:task:{task_path.stem}"] = task_path.read_bytes()
    for path in sorted((REPOSITORY_ROOT / "app" / "core").glob("creator_*.py")):
        resources[f"workflow:implementation:{path.name}"] = path.read_bytes()
    probe = REPOSITORY_ROOT / "scripts" / "probe-creator-capability.mjs"
    resources["workflow:implementation:probe-creator-capability.mjs"] = probe.read_bytes()
    handoff = REPOSITORY_ROOT / "scripts" / "creator_task_handoff.py"
    resources["workflow:implementation:creator-task-handoff-cli.py"] = handoff.read_bytes()
    if additional_reference_grammar is not None:
        resource_id = (
            f"workflow:package:reference-grammars/"
            f"{additional_reference_grammar.name}"
        )
        existing = resources.get(resource_id)
        content = additional_reference_grammar.read_bytes()
        if existing is not None and existing != content:
            raise ValueError("Private reference grammar conflicts with a packaged resource ID.")
        resources[resource_id] = content
    return resources


def _additional_reference_grammar(
    private_root: Path,
    channel_profile: dict,
) -> Path | None:
    grammar_name = channel_profile["referenceGrammarRef"].replace("@", ".v") + ".md"
    if (PACKAGE_ROOT / "reference-grammars" / grammar_name).is_file():
        return None
    private = (
        require_private_root(private_root)
        / "creator-production-inputs"
        / "reference-grammars"
        / grammar_name
    )
    if not private.is_file():
        raise RuntimeError(
            f"Locked channel profile reference grammar is unavailable: {grammar_name}"
        )
    return private


def _bundle_resource_hashes(bundle: dict) -> dict[str, str]:
    return {
        str(entry["id"]): str(entry["object"]["sha256"])
        for entry in bundle.get("resources", [])
    }


def verify_live_workflow_package_matches_lock(
    private_root: Path,
    current: dict | None = None,
) -> None:
    """Block execution when mutable dispatcher bytes differ from the project lock."""

    root = require_private_root(private_root)
    current = current or _load_json(root / "creator-production" / "current.json")
    verify_creator_project(root, current)
    channel_profile = _load_json(root / current["artifacts"]["channelProfile"]["path"])
    live_resources = _workflow_resource_bytes(
        additional_reference_grammar=_additional_reference_grammar(root, channel_profile)
    )
    live_hashes = {
        resource_id: hashlib.sha256(content).hexdigest()
        for resource_id, content in live_resources.items()
    }
    locked_hashes = _bundle_resource_hashes(current["workflowBundle"])
    if live_hashes != locked_hashes:
        changed = sorted(
            resource_id
            for resource_id in set(live_hashes).union(locked_hashes)
            if live_hashes.get(resource_id) != locked_hashes.get(resource_id)
        )
        preview = ", ".join(changed[:8])
        suffix = "" if len(changed) <= 8 else f" (+{len(changed) - 8} more)"
        raise RuntimeError(
            "Live Creator Production workflow package differs from the immutable "
            f"project lock; an explicit workflow upgrade is required: {preview}{suffix}"
        )


def upgrade_creator_workflow_package(
    private_root: Path,
    *,
    actor: str,
    reason: str,
) -> dict:
    """Explicitly supersede a workflow lock while preserving the prior authority."""

    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("Workflow upgrades require a nonempty actor and reason.")
    root = require_private_root(private_root)
    current_path = root / "creator-production" / "current.json"
    current = _load_json(current_path)
    verify_creator_project(root, current)
    production_profile = _load_json(root / current["artifacts"]["productionProfile"]["path"])
    channel_profile = _load_json(root / current["artifacts"]["channelProfile"]["path"])
    workflow_resources = _workflow_resource_bytes(
        additional_reference_grammar=_additional_reference_grammar(root, channel_profile)
    )
    live_resource_hashes = {
        resource_id: hashlib.sha256(content).hexdigest()
        for resource_id, content in workflow_resources.items()
    }
    locked_resource_hashes = _bundle_resource_hashes(current["workflowBundle"])
    changed_resource_ids = {
        resource_id
        for resource_id in set(live_resource_hashes).union(locked_resource_hashes)
        if live_resource_hashes.get(resource_id) != locked_resource_hashes.get(resource_id)
    }
    promoted_authority = {
        "episodeManifest",
        "compiledEpisode",
        "buildLock",
    }.intersection(current["artifacts"])
    render_boundary_resources = {
        "workflow:implementation:creator_project.py",
        "workflow:implementation:creator_rendering.py",
    }
    render_boundary_rebuild = (
        current["state"] == "PREFLIGHT"
        and bool(promoted_authority)
        and "workflow:implementation:creator_rendering.py" in changed_resource_ids
        and changed_resource_ids.issubset(render_boundary_resources)
    )
    materialization_runtime_resources = {
        "workflow:implementation:creator_build.py",
        "workflow:implementation:creator_capability_runtime.py",
        "workflow:implementation:creator_project.py",
    }
    materialization_runtime_rebuild = (
        current["state"] == "MATERIALIZING"
        and not promoted_authority
        and "workflow:implementation:creator_capability_runtime.py" in changed_resource_ids
        and changed_resource_ids.issubset(materialization_runtime_resources)
    )
    if current["state"] not in {"INGESTING", "ANALYZING", "MATERIALIZING"} and not (
        render_boundary_rebuild
    ):
        raise ValueError(
            "Workflow upgrades are allowed only before successful materialization, "
            "except for a renderer-boundary rebuild from PREFLIGHT."
        )
    if promoted_authority and not render_boundary_rebuild:
        raise ValueError(
            "Workflow upgrade is blocked after editorial authority was promoted: "
            + ", ".join(sorted(promoted_authority))
        )
    capability_catalog = _load_json(root / current["artifacts"]["capabilityCatalog"]["path"])
    admitted_capabilities = sorted(
        {
            str(capability.get("id"))
            for capability in capability_catalog.get("capabilities", [])
            if capability.get("projectAdmissions")
        }
    )
    admission_contract_resources = {
        "workflow:task:adapt",
        "workflow:package:tasks/adapt.md",
        "workflow:package:schemas/capability-adaptation.schema.json",
        "workflow:implementation:creator_adaptation.py",
        "workflow:implementation:probe-creator-capability.mjs",
    }
    changed_admission_contract = sorted(
        admission_contract_resources.intersection(changed_resource_ids)
    )
    if admitted_capabilities and changed_admission_contract:
        raise ValueError(
            "Workflow upgrade is blocked because the capability-admission contract "
            "changed after project code was admitted: "
            + ", ".join(changed_admission_contract)
        )
    active_jobs = []
    for job_path in (root / "creator-production" / "jobs").glob("*/job.json"):
        try:
            job = _load_json(job_path)
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("status") in {"queued", "running", "canceling"}:
            active_jobs.append(str(job.get("id") or job_path.parent.name))
    if active_jobs:
        raise ValueError(
            "Workflow upgrade is blocked while Creator Production jobs are active: "
            + ", ".join(sorted(active_jobs))
        )

    old_bundle = current["workflowBundle"]
    old_lock_ref = current["artifacts"]["workflowLock"]
    old_lock = _load_json(root / old_lock_ref["path"])
    invalidated_artifact_keys = (
        ()
        if materialization_runtime_rebuild
        else (
            "episodeManifest",
            "compiledEpisode",
            "structuralPreflight",
            "buildLock",
        )
        if render_boundary_rebuild
        else (
            "analysisLedger",
            "editorialPlanDecisions",
            "semanticManifest",
            "semanticPlanMaterialization",
            "sequenceDecisionIndex",
            "sourceLayoutClassification",
            "sourceEvidence",
            "structuralPreflight",
        )
    )
    invalidated_artifact_refs = {
        key: current["artifacts"][key]
        for key in invalidated_artifact_keys
        if key in current["artifacts"]
    }
    new_version = int(old_bundle["version"]) + 1
    workflow_bundle = freeze_resource_bytes_bundle(
        root,
        bundle_id=str(old_bundle["id"]),
        bundle_version=new_version,
        resources=workflow_resources,
    )
    allowed_resources = {
        **_bundle_resource_hashes(workflow_bundle),
        **_bundle_resource_hashes(current["capabilityBundle"]),
    }
    compiler_hash = canonical_hash(
        {
            resource_id: hashlib.sha256(content).hexdigest()
            for resource_id, content in sorted(workflow_resources.items())
            if resource_id.startswith("workflow:implementation:")
        }
    )
    workflow_lock = create_workflow_lock(
        workflow_bundle=workflow_bundle,
        production_profile=production_profile,
        channel_profile=channel_profile,
        capability_bundle=current["capabilityBundle"],
        hyperframes_cli_version=old_lock["hyperframesCliVersion"],
        hyperframes_cli_hash=old_lock["hyperframesCliHash"],
        compiler_version=str(new_version),
        compiler_hash=compiler_hash,
        producer_adapter_version=str(new_version),
        producer_adapter_hash=compiler_hash,
        allowed_domain_resources=allowed_resources,
        transition_source_hashes=old_lock["transitionSourceHashes"],
        transition_runtime_registry_hash=old_lock["transitionRuntimeRegistryHash"],
    )
    new_lock_ref = write_versioned_artifact(
        root,
        artifact_kind="workflow-locks",
        artifact_id=current["episodeId"],
        version=int(old_lock_ref["version"]) + 1,
        value=workflow_lock,
        schema_name="workflow-lock",
    )
    upgrade_receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": current["episodeId"],
        "actor": actor,
        "reason": reason,
        "supersededWorkflowVersion": int(old_bundle["version"]),
        "supersededWorkflowHash": old_bundle["bundleHash"],
        "supersededWorkflowLockRef": old_lock_ref,
        "workflowVersion": new_version,
        "workflowHash": workflow_bundle["bundleHash"],
        "workflowLockRef": new_lock_ref,
        "invalidatedArtifactRefs": invalidated_artifact_refs,
        "preservedProjectAdmissions": admitted_capabilities,
        "changedResourceIds": sorted(changed_resource_ids),
        "resultingState": (
            "MATERIALIZING"
            if render_boundary_rebuild or materialization_runtime_rebuild
            else ("ANALYZING" if current["state"] == "MATERIALIZING" else current["state"])
        ),
        "createdAt": utc_now(),
    }
    upgrade_ref = write_versioned_artifact(
        root,
        artifact_kind="workflow-upgrade-receipts",
        artifact_id=current["episodeId"],
        version=new_version - 1,
        value=upgrade_receipt,
    )
    current.setdefault("workflowBundleHistory", []).append(old_bundle)
    current.setdefault("workflowLockHistory", []).append(old_lock_ref)
    current.setdefault("workflowUpgradeHistory", []).append(upgrade_ref)
    for artifact_key, artifact_ref in invalidated_artifact_refs.items():
        current.setdefault("supersededArtifactHistory", []).append(
            {
                "artifactKey": artifact_key,
                "artifactRef": artifact_ref,
                "supersededByWorkflowUpgradeRef": upgrade_ref,
                "reason": (
                    "Workflow implementation bytes changed; rerun the stage under "
                    "the new lock before downstream promotion."
                ),
                "createdAt": utc_now(),
            }
        )
        current["artifacts"].pop(artifact_key, None)
    current["workflowBundle"] = workflow_bundle
    current["artifacts"]["workflowLock"] = new_lock_ref
    current["artifacts"]["workflowUpgrade"] = upgrade_ref
    if current["state"] == "MATERIALIZING" or render_boundary_rebuild:
        prior_state = current["state"]
        resulting_state = (
            "MATERIALIZING"
            if render_boundary_rebuild or materialization_runtime_rebuild
            else "ANALYZING"
        )
        state_revision = int(current["stateRevision"]) + 1
        state_record = {
            "schemaVersion": ARTIFACT_SCHEMA_VERSION,
            "episodeId": current["episodeId"],
            "revision": state_revision,
            "fromState": prior_state,
            "state": resulting_state,
            "gateReceiptRefs": [upgrade_ref["sha256"]],
            "actor": "workflow-upgrade",
            "createdAt": utc_now(),
        }
        state_ref = write_versioned_artifact(
            root,
            artifact_kind="project-states",
            artifact_id=current["episodeId"],
            version=state_revision,
            value=state_record,
        )
        current["state"] = resulting_state
        current["stateRevision"] = state_revision
        current["stateHistory"].append(state_ref)
        current["artifacts"]["projectState"] = state_ref
    current["updatedAt"] = utc_now()
    current["currentHash"] = canonical_hash(
        {key: value for key, value in current.items() if key != "currentHash"}
    )
    atomic_write_json(current_path, current)
    verify_creator_project(root, current)
    verify_live_workflow_package_matches_lock(root, current)
    return current


def initialize_creator_project(
    private_root: Path,
    *,
    episode_id: str,
    locked_cut: Path,
    final_transcript: Path,
    hyperframes_skill_root: Path,
    hyperframes_cli_path: Path,
    hyperframes_version: str,
    channel_profile_id: str,
    preserve_capability_source_cache: bool = False,
    legacy_transcript_attestation: dict | None = None,
) -> dict:
    """Create the immutable Production authority for a new post-cut project."""

    root = require_private_root(private_root)
    locked_cut = locked_cut.expanduser().resolve()
    final_transcript = final_transcript.expanduser().resolve()
    if not is_within(locked_cut, root) or not is_within(final_transcript, root):
        raise ValueError("Locked cut and final transcript must be inside the private project.")
    current_path = root / "creator-production" / "current.json"
    if current_path.exists():
        current = _load_json(current_path)
        verify_creator_project(root, current)
        return current

    private_production_profile = (
        root
        / "creator-production-inputs"
        / "profiles"
        / "creator-default.v1.json"
    )
    production_profile = _load_json(
        private_production_profile
        if private_production_profile.is_file()
        else PACKAGE_ROOT / "profiles" / "creator-default.v1.json"
    )
    capture_layout_catalog = _capture_layout_catalog_document(root)
    profiles = available_channel_profiles(root)
    available = {
        f"{item['id']}@{item['version']}": item for item in profiles
    }
    profile_entry = available.get(channel_profile_id)
    if profile_entry is None:
        id_matches = [item for item in profiles if item["id"] == channel_profile_id]
        if len(id_matches) == 1:
            profile_entry = id_matches[0]
        elif len(id_matches) > 1:
            raise ValueError(
                f"Channel profile requires an exact id@version reference: {channel_profile_id}"
            )
    if profile_entry is None:
        raise ValueError(f"Unknown Creator Production channel profile: {channel_profile_id}")
    channel_profile = _load_json(
        Path(profile_entry["profilePath"])
    )
    validate_artifact("production-profile", production_profile)
    validate_artifact("channel-profile", channel_profile)
    transcript_receipt = create_locked_transcript_receipt(
        locked_cut=locked_cut,
        transcript_path=final_transcript,
        locked_audio_hash=locked_audio_stream_hash(locked_cut),
        legacy_import_attestation=legacy_transcript_attestation,
    )
    catalog = inventory_hyperframes_capabilities(
        skill_root=hyperframes_skill_root,
        hyperframes_cli_path=hyperframes_cli_path,
        hyperframes_version=hyperframes_version,
    )
    if preserve_capability_source_cache:
        preserve_hyperframes_animation_source(
            skill_root=hyperframes_skill_root.resolve(),
            catalog=catalog,
        )

    grammar_path = Path(profile_entry["grammarPath"])
    workflow_resources = _workflow_resource_bytes(
        additional_reference_grammar=(
            grammar_path
            if not is_within(grammar_path, PACKAGE_ROOT)
            else None
        )
    )
    workflow_bundle = freeze_resource_bytes_bundle(
        root,
        bundle_id="creator-video-production-workflow",
        bundle_version=1,
        resources=workflow_resources,
    )
    license_path = REPOSITORY_ROOT / "node_modules" / "hyperframes" / "LICENSE"
    capability_bundle = freeze_resource_bytes_bundle(
        root,
        bundle_id="hyperframes-native-capability-snapshot",
        bundle_version=1,
        resources=_resource_bytes(hyperframes_skill_root.resolve(), catalog),
        licenses={"hyperframes-license": license_path.read_bytes()} if license_path.is_file() else {},
    )
    allowed_resources = {}
    for bundle in (workflow_bundle, capability_bundle):
        for entry in bundle["resources"]:
            allowed_resources[entry["id"]] = entry["object"]["sha256"]
    compiler_hash = canonical_hash(
        {
            resource_id: __import__("hashlib").sha256(content).hexdigest()
            for resource_id, content in sorted(workflow_resources.items())
            if resource_id.startswith("workflow:implementation:")
        }
    )
    workflow_lock = create_workflow_lock(
        workflow_bundle=workflow_bundle,
        production_profile=production_profile,
        channel_profile=channel_profile,
        capability_bundle=capability_bundle,
        hyperframes_cli_version=hyperframes_version,
        hyperframes_cli_hash=sha256_file(hyperframes_cli_path),
        compiler_version="1",
        compiler_hash=compiler_hash,
        producer_adapter_version="1",
        producer_adapter_hash=compiler_hash,
        allowed_domain_resources=allowed_resources,
        transition_source_hashes={
            "transitionTree": catalog["sourceIdentity"]["transitionsTreeSha256"]
        },
        transition_runtime_registry_hash=catalog["sourceIdentity"]["hyperframesCliSha256"],
    )
    artifacts = {
        "productionProfile": write_versioned_artifact(
            root,
            artifact_kind="production-profiles",
            artifact_id=production_profile["id"],
            version=production_profile["version"],
            value=production_profile,
            schema_name="production-profile",
        ),
        "channelProfile": write_versioned_artifact(
            root,
            artifact_kind="channel-profiles",
            artifact_id=channel_profile["id"],
            version=channel_profile["version"],
            value=channel_profile,
            schema_name="channel-profile",
        ),
        "capabilityCatalog": write_versioned_artifact(
            root,
            artifact_kind="capability-catalogs",
            artifact_id=catalog["id"],
            version=catalog["version"],
            value=catalog,
            schema_name="capability-catalog",
        ),
        "captureLayoutCatalog": write_versioned_artifact(
            root,
            artifact_kind="capture-layout-catalogs",
            artifact_id=capture_layout_catalog["id"],
            version=capture_layout_catalog["version"],
            value=capture_layout_catalog,
            schema_name="capture-layout-catalog",
        ),
        "workflowLock": write_versioned_artifact(
            root,
            artifact_kind="workflow-locks",
            artifact_id=episode_id,
            version=1,
            value=workflow_lock,
            schema_name="workflow-lock",
        ),
        "transcriptReceipt": write_versioned_artifact(
            root,
            artifact_kind="transcript-receipts",
            artifact_id=episode_id,
            version=1,
            value=transcript_receipt,
        ),
    }
    initial_state = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": episode_id,
        "revision": 1,
        "fromState": None,
        "state": "INGESTING",
        "gateReceiptRefs": [],
        "actor": "production",
        "createdAt": utc_now(),
    }
    artifacts["projectState"] = write_versioned_artifact(
        root,
        artifact_kind="project-states",
        artifact_id=episode_id,
        version=1,
        value=initial_state,
    )
    current = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "workflowId": WORKFLOW_ID,
        "episodeId": episode_id,
        "state": "INGESTING",
        "stateRevision": 1,
        "lockedCutPath": locked_cut.relative_to(root).as_posix(),
        "finalTranscriptPath": final_transcript.relative_to(root).as_posix(),
        "workflowBundle": workflow_bundle,
        "capabilityBundle": capability_bundle,
        "artifacts": artifacts,
        "stateHistory": [artifacts["projectState"]],
        "createdAt": utc_now(),
        "updatedAt": utc_now(),
    }
    current["currentHash"] = canonical_hash(current)
    atomic_write_json(current_path, current)
    return current


def verify_creator_project(private_root: Path, current: dict | None = None) -> None:
    root = require_private_root(private_root)
    current = current or _load_json(root / "creator-production" / "current.json")
    unsigned = {key: value for key, value in current.items() if key != "currentHash"}
    if canonical_hash(unsigned) != current.get("currentHash"):
        raise RuntimeError("Creator Production current state was modified.")
    if current.get("workflowId") != WORKFLOW_ID:
        raise RuntimeError("Creator Production workflow ownership changed.")
    verify_resource_bundle(root, current["workflowBundle"])
    verify_resource_bundle(root, current["capabilityBundle"])
    workflow_lock = _load_json(root / current["artifacts"]["workflowLock"]["path"])
    validate_artifact("workflow-lock", workflow_lock)
    if workflow_lock["workflowHash"] != current["workflowBundle"]["bundleHash"]:
        raise RuntimeError("Current workflow bytes do not match the workflow lock.")
    if workflow_lock["capabilityCatalogSnapshotHash"] != current["capabilityBundle"]["bundleHash"]:
        raise RuntimeError("Current capability bytes do not match the workflow lock.")
    receipt = _load_json(root / current["artifacts"]["transcriptReceipt"]["path"])
    verify_locked_transcript_receipt(
        receipt,
        locked_cut=root / current["lockedCutPath"],
        transcript_path=root / current["finalTranscriptPath"],
        locked_audio_hash=locked_audio_stream_hash(root / current["lockedCutPath"]),
    )
    if not current.get("stateHistory") or current["stateHistory"][-1]["version"] != current.get(
        "stateRevision"
    ):
        raise RuntimeError("Creator Production state history is incomplete.")
    state_record = _load_json(root / current["stateHistory"][-1]["path"])
    if state_record["state"] != current["state"]:
        raise RuntimeError("Creator Production current state does not match its immutable record.")


def transition_creator_project(
    private_root: Path,
    *,
    target_state: str,
    gate_receipt_refs: list[str],
    actor: str = "production",
) -> dict:
    root = require_private_root(private_root)
    current_path = root / "creator-production" / "current.json"
    current = _load_json(current_path)
    verify_creator_project(root, current)
    assert_state_transition(current["state"], target_state)
    revision = int(current["stateRevision"]) + 1
    state_record = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": current["episodeId"],
        "revision": revision,
        "fromState": current["state"],
        "state": target_state,
        "gateReceiptRefs": sorted(gate_receipt_refs),
        "actor": actor,
        "createdAt": utc_now(),
    }
    state_ref = write_versioned_artifact(
        root,
        artifact_kind="project-states",
        artifact_id=current["episodeId"],
        version=revision,
        value=state_record,
    )
    current["state"] = target_state
    current["stateRevision"] = revision
    current["stateHistory"].append(state_ref)
    current["artifacts"]["projectState"] = state_ref
    current["updatedAt"] = utc_now()
    current["currentHash"] = canonical_hash(
        {key: value for key, value in current.items() if key != "currentHash"}
    )
    atomic_write_json(current_path, current)
    return current


def promote_creator_artifact(
    private_root: Path,
    *,
    artifact_key: str,
    artifact_reference: dict,
) -> dict:
    return promote_creator_artifacts(
        private_root,
        artifact_references={artifact_key: artifact_reference},
    )


def ensure_capture_layout_catalog(private_root: Path) -> dict:
    """Freeze the documented creator capture facts for an already initialized project."""

    root = require_private_root(private_root)
    current = _load_json(root / "creator-production" / "current.json")
    verify_creator_project(root, current)
    existing = current["artifacts"].get("captureLayoutCatalog")
    if existing:
        validate_artifact(
            "capture-layout-catalog",
            _load_json(root / existing["path"]),
        )
        return existing
    catalog = _capture_layout_catalog_document(root)
    reference = write_versioned_artifact(
        root,
        artifact_kind="capture-layout-catalogs",
        artifact_id=catalog["id"],
        version=catalog["version"],
        value=catalog,
        schema_name="capture-layout-catalog",
    )
    promote_creator_artifact(
        root,
        artifact_key="captureLayoutCatalog",
        artifact_reference=reference,
    )
    return reference


def promote_creator_artifacts(
    private_root: Path,
    *,
    artifact_references: dict[str, dict],
) -> dict:
    """Atomically move one validated immutable output into the current pointer."""

    root = require_private_root(private_root)
    current_path = root / "creator-production" / "current.json"
    current = _load_json(current_path)
    verify_creator_project(root, current)
    for artifact_key, artifact_reference in artifact_references.items():
        if not artifact_key or not artifact_key[0].isalpha():
            raise ValueError("Creator Production artifact keys must begin with a letter.")
        artifact_path = (root / artifact_reference["path"]).resolve()
        if not is_within(artifact_path, root) or not artifact_path.is_file():
            raise ValueError("Promoted artifact is not inside the private project.")
        if sha256_file(artifact_path) != artifact_reference["sha256"]:
            raise ValueError("Promoted artifact bytes do not match their immutable reference.")
    current["artifacts"].update(artifact_references)
    current["updatedAt"] = utc_now()
    current["currentHash"] = canonical_hash(
        {key: value for key, value in current.items() if key != "currentHash"}
    )
    atomic_write_json(current_path, current)
    return current
