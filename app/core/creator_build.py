from __future__ import annotations

import json
from pathlib import Path

from app.core.creator_capability_runtime import execute_materialized_capability
from app.core.creator_preflight import run_structural_preflight
from app.core.creator_project import verify_creator_project
from app.core.creator_production import (
    artifact_id_storage_segment,
    canonical_hash,
    compile_episode_manifest,
    freeze_bytes,
    create_build_lock,
    next_artifact_version,
    require_private_root,
    write_versioned_artifact,
    transcript_word_timing_payload,
)
from app.core.file_utils import is_within, sha256_file


def _profile_value(profile: dict, path: str) -> object:
    value: object = profile
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"Consumed profile path does not exist: {path}")
        value = value[part]
    return value


def _profile_references(profile: object, reference_ids: set[str]) -> dict[str, object]:
    resolved: dict[str, object] = {}

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            identifier = value.get("id")
            if isinstance(identifier, str) and identifier in reference_ids:
                resolved[path or identifier] = value
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if str(key) in reference_ids:
                    resolved[child_path] = child
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(profile, "")
    return dict(sorted(resolved.items()))


def _resolved_profile_dependencies(profile: dict, declared: dict) -> dict:
    paths = declared.get("tokenPaths", [])
    reference_ids = {
        str(value)
        for key in ("fontIds", "policyIds", "thresholdIds", "preferenceIds")
        for value in declared.get(key, [])
    }
    return {
        "declared": json.loads(json.dumps(declared)),
        "tokenValues": {
            path: _profile_value(profile, path)
            for path in sorted(paths)
        },
        "referencedValues": _profile_references(profile, reference_ids),
        "referenceGrammarIdentity": (
            profile.get("referenceGrammarRef")
            if declared.get("referenceGrammarFields")
            else None
        ),
    }


def _validate_implementation_materialization(
    root: Path,
    *,
    manifest: dict,
    catalog: dict,
    profile: dict,
    transcript: dict,
    evidence: dict,
) -> None:
    capabilities = {item["id"]: item for item in catalog["capabilities"]}
    evidence_by_sequence = {item["sequenceId"]: item for item in evidence["sequences"]}
    words = transcript_word_timing_payload(transcript)["words"]
    for sequence in manifest["sequences"]:
        if sequence["presentationRole"] == "source-led":
            continue
        if sequence.get("sourceOverrideRef"):
            override_hash = sequence["sourceOverrideRef"]
            matches = []
            override_root = (
                root
                / "creator-production"
                / "artifacts"
                / "source-overrides"
                / artifact_id_storage_segment(sequence["id"])
            )
            for path in override_root.glob("v*-*.json") if override_root.is_dir() else []:
                try:
                    candidate = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if candidate.get("overrideHash") == override_hash:
                    matches.append(candidate)
            if len(matches) != 1:
                raise ValueError(f"Sequence {sequence['id']} source override is unavailable.")
            if matches[0].get("compositionGraphHash") != canonical_hash(
                sequence["compositionGraph"]
            ):
                raise ValueError(f"Sequence {sequence['id']} source override graph changed.")
            continue
        merged_elements: dict[str, dict] = {}
        merged_events: dict[str, dict] = {}
        consumed_paths = sequence["consumedProfileDependencies"]["tokenPaths"]
        tokens = {path: _profile_value(profile, path) for path in consumed_paths}
        timing_words = [
            word
            for word in words
            if sequence["absoluteStartFrame"]
            <= word["startFrame"]
            < sequence["absoluteEndFrameExclusive"]
        ]
        for binding in sequence["selectedCapabilityBindings"]:
            capability = capabilities[binding["capabilityId"]]
            admissions = [
                item
                for item in capability.get("projectAdmissions", [])
                if item.get("implementationId") == binding.get("implementationId")
                and item.get("sequenceId") == sequence["id"]
                and item.get("episodeId") == manifest["episodeId"]
            ]
            if len(admissions) != 1:
                raise ValueError(f"Sequence {sequence['id']} lacks one exact project admission.")
            admission = admissions[0]
            if binding.get("implementationSourceHash") != admission["implementationSourceHash"]:
                raise ValueError(f"Sequence {sequence['id']} changed implementation source hash.")
            graph = execute_materialized_capability(
                root,
                adaptation_id=admission["adaptationId"],
                implementation_source_hash=admission["implementationSourceHash"],
                context={
                    "parameters": binding.get("parameters", {}),
                    "tokens": tokens,
                    "timing": {
                        "words": timing_words,
                        "sourceEventAnchors": manifest["sourceEventAnchors"],
                    },
                    "canvas": manifest["canvas"],
                    "sourceEvidence": evidence_by_sequence[sequence["id"]],
                },
            )
            for element in graph["elements"]:
                existing = merged_elements.get(element["id"])
                if existing is not None and existing != element:
                    raise ValueError("Capability implementations produced conflicting elements.")
                merged_elements[element["id"]] = element
            for event in graph["events"]:
                if event["id"] in merged_events:
                    raise ValueError("Capability implementations produced duplicate event ids.")
                merged_events[event["id"]] = event
        actual = sequence["compositionGraph"]
        expected = {
            "elements": sorted(merged_elements.values(), key=lambda item: item["id"]),
            "events": sorted(merged_events.values(), key=lambda item: item["id"]),
        }
        normalized_actual = {
            "elements": sorted(actual["elements"], key=lambda item: item["id"]),
            "events": sorted(actual["events"], key=lambda item: item["id"]),
        }
        if canonical_hash(expected) != canonical_hash(normalized_actual):
            raise ValueError(
                f"Materialized graph for {sequence['id']} is not the exact output "
                "of its admitted capability implementations."
            )


def _freeze_resolved_assets(root: Path, manifest: dict) -> None:
    for sequence in manifest["sequences"]:
        for asset in sequence["resolvedAssetRefs"]:
            source = (root / asset["path"]).resolve()
            if (
                not is_within(source, root)
                or not source.is_file()
                or sha256_file(source) != asset["sha256"]
            ):
                raise ValueError(
                    f"Resolved asset bytes are unavailable or changed: {asset['id']}"
                )
            object_ref = freeze_bytes(root, source.read_bytes())
            if object_ref["sha256"] != asset["sha256"]:
                raise RuntimeError(
                    f"Content-addressed asset identity changed: {asset['id']}"
                )


def finalize_materialized_build(private_root: Path, manifest: dict) -> dict:
    """Compile and run deterministic non-browser gates without creative reinterpretation."""

    root = require_private_root(private_root)
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    transcript = json.loads(
        (root / current["finalTranscriptPath"]).read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (root / current["artifacts"]["sourceEvidence"]["path"]).read_text(encoding="utf-8")
    )
    catalog = json.loads(
        (root / current["artifacts"]["capabilityCatalog"]["path"]).read_text(encoding="utf-8")
    )
    profile = json.loads(
        (root / current["artifacts"]["channelProfile"]["path"]).read_text(encoding="utf-8")
    )
    workflow_lock = json.loads(
        (root / current["artifacts"]["workflowLock"]["path"]).read_text(encoding="utf-8")
    )
    decision_index = json.loads(
        (root / current["artifacts"]["sequenceDecisionIndex"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    semantic_manifest = json.loads(
        (root / current["artifacts"]["semanticManifest"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    semantic_sequences = {
        item["id"]: item for item in semantic_manifest["sequences"]
    }
    if [item["id"] for item in manifest["sequences"]] != [
        item["id"] for item in semantic_manifest["sequences"]
    ]:
        raise ValueError(
            "Materialization changed the ordered semantic sequence structure."
        )
    protected_sequence_fields = (
        "id",
        "chapterId",
        "absoluteStartFrame",
        "absoluteEndFrameExclusive",
        "startWordId",
        "endWordId",
        "conceptId",
        "seriesId",
        "callbackTo",
        "propositionId",
        "semanticBeatKind",
        "editorialJob",
        "semanticForm",
        "presentationRole",
        "narrativeStateRole",
        "editorialDirective",
    )
    for sequence in manifest["sequences"]:
        semantic_sequence = semantic_sequences[sequence["id"]]
        changed = [
            field
            for field in protected_sequence_fields
            if sequence.get(field) != semantic_sequence.get(field)
        ]
        if changed:
            raise ValueError(
                f"Sequence {sequence['id']} changed protected semantic fields "
                "during materialization: "
                + ", ".join(changed)
            )
    protected_chapter_fields = (
        "id",
        "editorialSectionId",
        "title",
        "completionRationale",
        "absoluteStartFrame",
        "absoluteEndFrameExclusive",
    )
    if len(manifest["chapters"]) != len(semantic_manifest["chapters"]):
        raise ValueError("Materialization changed the semantic chapter count.")
    for chapter, semantic_chapter in zip(
        manifest["chapters"], semantic_manifest["chapters"]
    ):
        changed = [
            field
            for field in protected_chapter_fields
            if chapter.get(field) != semantic_chapter.get(field)
        ]
        if changed:
            raise ValueError(
                f"Chapter {chapter.get('id')} changed protected semantic fields "
                "during materialization: "
                + ", ".join(changed)
            )
    _freeze_resolved_assets(root, manifest)
    decisions = {item["sequenceId"]: item for item in decision_index["items"]}
    for sequence in manifest["sequences"]:
        semantic_sequence = semantic_sequences.get(sequence["id"])
        if semantic_sequence is None:
            raise ValueError(f"Unknown materialized sequence {sequence['id']}.")
        if profile.get("id") == "vcg" and int(profile.get("version", 0)) >= 2:
            if sequence.get("editorialDirective") != semantic_sequence.get(
                "editorialDirective"
            ):
                raise ValueError(
                    f"Sequence {sequence['id']} changed its approved editorial "
                    "copy or timing during materialization."
                )
        decision = decisions.get(sequence["id"])
        if not decision or sequence["sequenceDecisionReceiptId"] != decision["receiptId"]:
            raise ValueError(
                f"Sequence {sequence['id']} does not cite the current deterministic decision receipt."
            )
        if sequence["presentationRole"] != "source-led":
            selected = {
                binding.get("capabilityId")
                for binding in sequence["selectedCapabilityBindings"]
            }
            if selected != {decision["selectedCapabilityId"]}:
                raise ValueError(
                    f"Sequence {sequence['id']} changed the selected capability after ranking."
                )
            if (
                profile.get("id") == "vcg"
                and int(profile.get("version", 0)) >= 2
                and sequence.get("selectedVisualFamilyId")
                != decision["selectedCapabilityId"]
            ):
                raise ValueError(
                    f"Sequence {sequence['id']} must identify its selected "
                    "HyperFrames capability as the visual family."
                )
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    _validate_implementation_materialization(
        root,
        manifest=manifest,
        catalog=catalog,
        profile=profile,
        transcript=transcript,
        evidence=evidence,
    )
    preflight = run_structural_preflight(
        manifest=manifest,
        compiled=compiled,
        transcript_document=transcript,
        source_evidence=evidence,
        capability_catalog=catalog,
        channel_profile=profile,
    )
    compiled_ref = write_versioned_artifact(
        root,
        artifact_kind="compiled-episodes",
        artifact_id=current["episodeId"],
        version=next_artifact_version(
            root, "compiled-episodes", current["episodeId"]
        ),
        value=compiled,
    )
    preflight_ref = write_versioned_artifact(
        root,
        artifact_kind="preflight-receipts",
        artifact_id=current["episodeId"],
        version=next_artifact_version(
            root, "preflight-receipts", current["episodeId"]
        ),
        value=preflight,
    )
    if not preflight["passed"]:
        return {
            "compiledEpisodeRef": compiled_ref,
            "preflightRef": preflight_ref,
            "buildLockRef": None,
            "passed": False,
        }

    capabilities = {item["id"]: item for item in catalog["capabilities"]}
    implementation_hashes: dict[str, list[str]] = {}
    asset_hashes: dict[str, list[str]] = {}
    validation_ids: dict[str, list[str]] = {}
    consumed: dict[str, dict] = {}
    generated_hashes: dict[str, str] = {}
    compiled_hashes: dict[str, str] = {}
    for sequence in manifest["sequences"]:
        sequence_id = sequence["id"]
        hashes = []
        for binding in sequence["selectedCapabilityBindings"]:
            capability = capabilities[binding["capabilityId"]]
            implementation_id = binding.get("implementationId")
            admissions = [
                item
                for item in capability.get("projectAdmissions", [])
                if item.get("implementationId") == implementation_id
                and item.get("episodeId") == manifest["episodeId"]
                and item.get("sequenceId") == sequence_id
            ]
            if capability["technicalAdmission"] == "project-admitted":
                if len(admissions) != 1:
                    raise ValueError(
                        f"Cannot resolve exact implementation hash for {sequence_id}."
                    )
                hashes.append(admissions[0]["implementationSourceHash"])
            else:
                hashes.append(binding["implementationSourceHash"])
        implementation_hashes[sequence_id] = hashes
        if sequence.get("sourceOverrideRef"):
            implementation_hashes[sequence_id].append(sequence["sourceOverrideRef"])
        asset_hashes[sequence_id] = [
            item["sha256"] for item in sequence["resolvedAssetRefs"]
        ]
        validation_ids[sequence_id] = [preflight["receiptHash"]]
        consumed[sequence_id] = _resolved_profile_dependencies(
            profile,
            sequence["consumedProfileDependencies"],
        )
        graph_hash = canonical_hash(sequence["compositionGraph"])
        generated_hashes[sequence_id] = graph_hash
        compiled_hashes[sequence_id] = graph_hash
    build_lock = create_build_lock(
        manifest=manifest,
        compiled=compiled,
        resolved_profile_hash=canonical_hash(profile),
        consumed_profile_dependencies=consumed,
        capability_implementation_hashes=implementation_hashes,
        asset_hashes=asset_hashes,
        generated_source_hashes=generated_hashes,
        compiled_source_hashes=compiled_hashes,
        validation_result_ids=validation_ids,
        workflow_lock=workflow_lock,
    )
    build_ref = write_versioned_artifact(
        root,
        artifact_kind="build-locks",
        artifact_id=current["episodeId"],
        version=next_artifact_version(root, "build-locks", current["episodeId"]),
        value=build_lock,
        schema_name="build-lock",
    )
    return {
        "compiledEpisodeRef": compiled_ref,
        "preflightRef": preflight_ref,
        "buildLockRef": build_ref,
        "passed": True,
    }
