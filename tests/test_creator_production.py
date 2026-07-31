from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.creator_production import (
    build_instruction_context,
    calculate_localized_invalidation,
    canonical_hash,
    compile_episode_manifest,
    create_approval_record,
    create_build_lock,
    create_locked_transcript_receipt,
    create_legacy_locked_transcript_attestation,
    create_review_state,
    create_workflow_lock,
    accept_review_note,
    freeze_resource_bundle,
    next_artifact_version,
    resolve_channel_profile,
    save_review_note,
    transcript_word_timing_hash,
    validate_episode_manifest,
    verify_locked_transcript_receipt,
    write_versioned_artifact,
)
from app.core.creator_capabilities import (
    assert_capability_selectable,
    inventory_hyperframes_capabilities,
    required_capability_resource_ids,
)
from app.core.creator_project import (
    available_channel_profiles,
    initialize_creator_project,
    promote_creator_artifact,
    promote_creator_artifacts,
    upgrade_creator_workflow_package,
    verify_creator_project,
    verify_live_workflow_package_matches_lock,
)


SHA = "a" * 64


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    return root


def test_private_channel_profiles_are_discovered_by_version_without_code_branch(
    tmp_path: Path,
) -> None:
    root = _private_root(tmp_path)
    profile_root = root / "creator-production-inputs" / "profiles"
    grammar_root = root / "creator-production-inputs" / "reference-grammars"
    profile_root.mkdir(parents=True)
    grammar_root.mkdir(parents=True)
    source = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "creator-production"
            / "profiles"
            / "vcg.v1.json"
        ).read_text(encoding="utf-8")
    )
    source["id"] = "private-channel"
    source["version"] = 7
    source["referenceGrammarRef"] = "private-channel-grammar@7"
    (profile_root / "private-channel.v7.json").write_text(
        json.dumps(source),
        encoding="utf-8",
    )
    (grammar_root / "private-channel-grammar.v7.md").write_text(
        "# Private channel grammar\n",
        encoding="utf-8",
    )

    profiles = available_channel_profiles(root)

    assert any(
        item["id"] == "private-channel" and item["version"] == 7
        for item in profiles
    )


def test_new_vcg_projects_only_offer_latest_channel_contract() -> None:
    profiles = available_channel_profiles()
    vcg_profiles = [item for item in profiles if item["id"] == "vcg"]

    assert [(item["id"], item["version"]) for item in vcg_profiles] == [
        ("vcg", 2)
    ]


def _profile(profile_id: str = "sample", *, parent: str | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "id": profile_id,
        "version": 1,
        "parentProfileRef": parent,
        "designTokenContractVersion": 1,
        "referenceGrammarRef": "grammar@1",
        "brand": {
            "fonts": ["Example Sans"],
            "colors": {"canvas": "#ffffff"},
            "typographyScale": {},
            "lineBreaking": {},
            "spacing": {},
            "strokeWeights": {},
            "borders": {},
            "shadows": {},
            "speakerFrames": {},
        },
        "editorial": {},
        "selection": {
            "rankingPolicyRef": "ranking@1",
            "mode": "lexicographic",
            "criterionOrder": ["semantic-fitness"],
            "criterionWeights": {},
            "tieBreaker": "stable-capability-id",
        },
        "pacing": {},
        "capabilities": {
            "defaultPreference": "allowed",
            "preferred": [],
            "discouraged": [],
            "disabled": [],
            "overrides": {},
        },
        "reuse": {},
        "policies": {"hard": [], "warnings": [], "objectives": []},
        "speaker": {},
        "assets": {},
    }


def _manifest() -> dict:
    graph = {
        "elements": [
            {
                "id": "source",
                "kind": "video",
                "parentId": None,
                "zIndex": 0,
                "geometry": {"x": 0, "y": 0, "width": 1, "height": 1},
                "tokenBindings": {},
                "properties": {"sourceRef": "locked-cut"},
            },
            {
                "id": "headline",
                "kind": "text",
                "parentId": None,
                "zIndex": 1,
                "geometry": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2},
                "tokenBindings": {"color": "color.ink"},
                "properties": {"text": "Example"},
            },
        ],
        "events": [
            {
                "id": "reveal",
                "targetElementId": "headline",
                "operation": "reveal",
                "absoluteFrame": 30,
                "wordId": "w1",
                "sourceEventAnchorId": None,
                "durationFrames": 8,
                "easing": "power2.out",
                "parameters": {},
                "contentBearing": True,
            }
        ],
    }
    sequences = []
    for index, (start, end) in enumerate(((0, 90), (90, 180)), start=1):
        sequence_graph = json.loads(json.dumps(graph))
        if index == 2:
            sequence_graph["events"][0]["absoluteFrame"] = 150
            sequence_graph["events"][0]["wordId"] = "w2"
        sequences.append(
            {
                "id": f"s{index}",
                "chapterId": "chapter-complete-idea",
                "absoluteStartFrame": start,
                "absoluteEndFrameExclusive": end,
                "startWordId": "w1",
                "endWordId": "w2",
                "conceptId": f"concept-{index}",
                "propositionId": f"proposition-{index}",
                "semanticBeatKind": "claim",
                "editorialJob": "explain",
                "semanticForm": "kinetic-type",
                "presentationRole": "hybrid",
                "narrativeStateRole": "establish" if index == 1 else "payoff",
                "sourceImplementationMode": "compiled-capability",
                "selectedCanvasTopology": "speaker-left-information-right",
                "selectedCapabilityBindings": [{"id": "binding-1"}],
                "assetRequirements": [],
                "resolvedAssetRefs": [],
                "resolvedImplementationSetRef": {"binding-1": {"scope": "atomic-operation"}},
                "consumedProfileDependencies": {
                    "tokenPaths": [],
                    "fontIds": [],
                    "policyIds": [],
                    "thresholdIds": [],
                    "preferenceIds": [],
                    "referenceGrammarFields": [],
                },
                "compositionGraph": sequence_graph,
                "policyExceptionRefs": [],
                "policyReceiptIds": [],
                "sequenceDecisionReceiptId": f"decision-{index}",
                "routingConfidence": 1,
                "unresolvedReasons": [],
            }
        )
    return {
        "schemaVersion": 1,
        "episodeId": "episode-1",
        "revision": 1,
        "state": "PREFLIGHT",
        "workflowLockHash": SHA,
        "lockedCutSha256": SHA,
        "lockedAudioSha256": "",
        "transcriptSha256": SHA,
        "wordTimingSha256": SHA,
        "fps": {"numerator": 30, "denominator": 1},
        "canvas": {"width": 1920, "height": 1080},
        "totalFrames": 180,
        "sourceEventAnchors": [],
        "sequences": sequences,
        "transitionBoundaries": [
            {
                "id": "b1",
                "fromSequenceId": "s1",
                "toSequenceId": "s2",
                "mode": "none",
                "implementationRef": None,
                "durationFrames": 0,
                "overlapFrames": 0,
                "chapterSafetyMargins": {},
                "policyReceiptIds": [],
            }
        ],
        "chapters": [
            {
                "id": "chapter-complete-idea",
                "editorialSectionId": "idea-1",
                "title": "One complete explanation",
                "completionRationale": "The setup and payoff form one completed editorial section.",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 180,
            }
        ],
    }


def test_canonical_hash_ignores_object_key_order_but_not_array_order() -> None:
    assert canonical_hash({"b": 2, "a": [1, 2]}) == canonical_hash({"a": [1, 2], "b": 2})
    assert canonical_hash({"a": [1, 2]}) != canonical_hash({"a": [2, 1]})


def test_production_context_loads_only_exact_allowlisted_frozen_bytes(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    workflow_source = tmp_path / "workflow.md"
    capability_source = tmp_path / "capability.md"
    workflow_source.write_text("workflow authority", encoding="utf-8")
    capability_source.write_text("bounded capability", encoding="utf-8")
    workflow = freeze_resource_bundle(
        root,
        bundle_id="workflow",
        bundle_version=1,
        resources={"workflow:main": workflow_source},
    )
    capabilities = freeze_resource_bundle(
        root,
        bundle_id="capabilities",
        bundle_version=1,
        resources={"capability:one": capability_source},
    )
    production_profile = {"id": "default", "version": 1}
    channel = _profile()
    allowed = {
        "workflow:main": workflow["resources"][0]["object"]["sha256"],
        "capability:one": capabilities["resources"][0]["object"]["sha256"],
    }
    lock = create_workflow_lock(
        workflow_bundle=workflow,
        production_profile=production_profile,
        channel_profile=channel,
        capability_bundle=capabilities,
        hyperframes_cli_version="0.7.54",
        hyperframes_cli_hash=SHA,
        compiler_version="1",
        compiler_hash=SHA,
        producer_adapter_version="1",
        producer_adapter_hash=SHA,
        allowed_domain_resources=allowed,
    )

    loaded, receipt = build_instruction_context(
        root,
        workflow_lock=lock,
        workflow_bundle=workflow,
        capability_bundle=capabilities,
        requested_resource_ids=["workflow:main", "capability:one"],
    )

    assert loaded == {"workflow:main": "workflow authority", "capability:one": "bounded capability"}
    assert receipt["owningWorkflowId"] == "creator-video-production"
    assert receipt["nativeWorkflowDiscoveryPerformed"] is False
    assert receipt["fallbackOccurred"] is False

    with pytest.raises(RuntimeError, match="Forbidden workflow"):
        build_instruction_context(
            root,
            workflow_lock=lock,
            workflow_bundle=workflow,
            capability_bundle=capabilities,
            requested_resource_ids=["talking-head-recut"],
        )


def test_locked_transcript_receipt_rejects_any_word_timing_change(tmp_path: Path) -> None:
    locked = tmp_path / "locked.mp4"
    transcript = tmp_path / "final.json"
    locked.write_bytes(b"locked cut")
    document = {
        "version": 5,
        "project": {
            "fps": 30,
            "words": [
                {
                    "id": "w1",
                    "start": 1.0,
                    "end": 1.2,
                    "start_frame": 30,
                    "end_frame": 36,
                }
            ],
            "generation": {},
        },
    }
    document["project"]["generation"]["lockedTranscript"] = {
        "timingAuthority": "final-locked-transcript",
        "timingMutationAllowed": False,
        "lockedCutSha256": __import__("hashlib").sha256(locked.read_bytes()).hexdigest(),
        "wordTimingSha256": transcript_word_timing_hash(document),
    }
    transcript.write_text(json.dumps(document), encoding="utf-8")
    receipt = create_locked_transcript_receipt(locked_cut=locked, transcript_path=transcript)
    verify_locked_transcript_receipt(receipt, locked_cut=locked, transcript_path=transcript)

    document["project"]["words"][0]["start"] = 0.9
    transcript.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="wordTimingSha256"):
        verify_locked_transcript_receipt(receipt, locked_cut=locked, transcript_path=transcript)


def test_locked_transcript_receipt_requires_matching_upstream_provenance(tmp_path: Path) -> None:
    locked = tmp_path / "locked.mp4"
    transcript = tmp_path / "final.json"
    locked.write_bytes(b"locked")
    transcript.write_text(
        json.dumps(
            {
                "project": {
                    "fps": 30,
                    "words": [
                        {"id": "w1", "start": 0, "end": 0.2, "start_frame": 0, "end_frame": 6}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="missing its locked-transcript provenance"):
        create_locked_transcript_receipt(locked_cut=locked, transcript_path=transcript)


def test_legacy_locked_transcript_requires_exact_explicit_attestation(tmp_path: Path) -> None:
    locked = tmp_path / "locked.mp4"
    transcript = tmp_path / "final.json"
    locked.write_bytes(b"locked")
    transcript.write_text(
        json.dumps(
            {
                "project": {
                    "fps": 30,
                    "words": [
                        {"id": "w1", "start": 0, "end": 0.2, "start_frame": 0, "end_frame": 6}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    attestation = create_legacy_locked_transcript_attestation(
        locked_cut=locked,
        transcript_path=transcript,
        actor="creator",
        reason="Explicit beside-not-overwrite import of a pre-provenance final transcript.",
    )
    receipt = create_locked_transcript_receipt(
        locked_cut=locked,
        transcript_path=transcript,
        legacy_import_attestation=attestation,
    )
    assert receipt["provenanceMode"] == "explicit-legacy-import-attestation"
    verify_locked_transcript_receipt(
        receipt,
        locked_cut=locked,
        transcript_path=transcript,
    )

    attestation["wordTimingSha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="attestation was modified"):
        create_locked_transcript_receipt(
            locked_cut=locked,
            transcript_path=transcript,
            legacy_import_attestation=attestation,
        )


def test_embedded_provenance_rejects_legacy_import_attestation(tmp_path: Path) -> None:
    locked = tmp_path / "locked.mp4"
    transcript = tmp_path / "final.json"
    locked.write_bytes(b"locked")
    document = {
        "project": {
            "fps": 30,
            "words": [
                {"id": "w1", "start": 0, "end": 0.2, "start_frame": 0, "end_frame": 6}
            ],
            "generation": {},
        }
    }
    document["project"]["generation"]["lockedTranscript"] = {
        "timingAuthority": "final-locked-transcript",
        "timingMutationAllowed": False,
        "lockedCutSha256": __import__("hashlib").sha256(locked.read_bytes()).hexdigest(),
        "wordTimingSha256": transcript_word_timing_hash(document),
    }
    transcript.write_text(json.dumps(document), encoding="utf-8")
    attestation = create_legacy_locked_transcript_attestation(
        locked_cut=locked,
        transcript_path=transcript,
        actor="creator",
        reason="Should not be accepted for a current transcript.",
    )
    with pytest.raises(RuntimeError, match="not allowed when embedded provenance exists"):
        create_locked_transcript_receipt(
            locked_cut=locked,
            transcript_path=transcript,
            legacy_import_attestation=attestation,
        )


def test_word_timing_hash_does_not_depend_on_transcript_copy_or_generation_metadata() -> None:
    document = {
        "project": {
            "fps": 30,
            "words": [
                {"id": "w1", "start": 0, "end": 0.2, "start_frame": 0, "end_frame": 6}
            ],
            "generation": {"model": "example"},
        }
    }
    copied = json.loads(json.dumps(document))
    copied["project"]["generation"]["model"] = "other"
    assert transcript_word_timing_hash(document) == transcript_word_timing_hash(copied)


def test_chapters_are_completed_editorial_sections_not_duration_targets() -> None:
    manifest = _manifest()
    validate_episode_manifest(manifest)
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    assert compiled["chapters"][0]["completionRationale"]
    assert len(compiled["sequences"]) == 2

    manifest["chapters"][0]["targetDurationSec"] = 60
    with pytest.raises(ValueError, match="Additional properties"):
        validate_episode_manifest(manifest)


def test_compiler_is_deterministic_and_does_not_mutate_the_manifest() -> None:
    manifest = _manifest()
    original = json.loads(json.dumps(manifest))
    first = compile_episode_manifest(manifest, compiler_version="1")
    second = compile_episode_manifest(manifest, compiler_version="1")
    assert first == second
    assert manifest == original


def test_channel_profile_uses_one_parent_and_replaces_ordered_arrays() -> None:
    parent = _profile("base")
    parent["brand"]["fonts"] = ["Parent Sans"]
    parent["capabilities"]["preferred"] = ["capability:a"]
    child = _profile("child", parent="base@1")
    child["brand"]["fonts"] = ["Child Sans"]
    child["capabilities"]["preferred"] = ["capability:b"]

    resolved = resolve_channel_profile(child, parent)

    assert resolved["brand"]["fonts"] == ["Child Sans"]
    assert resolved["capabilities"]["preferred"] == ["capability:a", "capability:b"]
    assert [item["id"] for item in resolved["resolvedLineage"]] == ["base", "child"]


def test_native_capability_inventory_is_complete_namespaced_and_not_selectable() -> None:
    repository = Path(__file__).resolve().parents[1]
    skill_root = Path.home() / ".codex" / "skills" / "hyperframes-animation"
    cli_path = repository / "node_modules" / "hyperframes" / "dist" / "cli.js"
    if not skill_root.is_dir() or not cli_path.is_file():
        pytest.skip("Pinned local HyperFrames installation is unavailable.")

    catalog = inventory_hyperframes_capabilities(
        skill_root=skill_root,
        hyperframes_cli_path=cli_path,
        hyperframes_version="0.7.54",
    )

    assert catalog["inventorySummary"]["ruleSourceCount"] == 48
    assert catalog["inventorySummary"]["blueprintSourceCount"] == 22
    assert catalog["inventorySummary"]["cssDocumentedCount"] == 32
    assert catalog["inventorySummary"]["cssGloballyBlockedCount"] == 4
    assert catalog["inventorySummary"]["plvTemplateCount"] == 5
    assert catalog["inventorySummary"]["shaderDocumentedCount"] == 13
    assert catalog["inventorySummary"]["shaderRuntimeCount"] == 15
    assert catalog["inventorySummary"]["unknownShaderFallbackDetected"] is True
    ids = {entry["id"] for entry in catalog["capabilities"]}
    assert "hf-css:crossfade" in ids
    assert "hf-plv-template:crossfade" in ids
    assert "hf-shader-runtime:crossfade" in ids
    assert len(ids) == len(catalog["capabilities"])
    assert all(entry["productionSelection"] == "not-selectable" for entry in catalog["capabilities"])
    with pytest.raises(RuntimeError, match="not production-selectable"):
        assert_capability_selectable(catalog, "hf-rule:kinetic-beat-slam")


def test_preserved_blueprints_carry_complete_instruction_dependencies() -> None:
    repository = Path(__file__).resolve().parents[1]
    cli_path = repository / "node_modules" / "hyperframes" / "dist" / "cli.js"
    candidates = sorted(
        (repository / "app" / "private-capability-snapshots").glob(
            "*/hyperframes-animation"
        )
    )
    skill_root = next(
        (
            candidate
            for candidate in reversed(candidates)
            if (candidate / "examples" / "metric-video-text-pivot.html").is_file()
        ),
        None,
    )
    if skill_root is None or not cli_path.is_file():
        pytest.skip("Preserved HyperFrames animation source is unavailable.")

    catalog = inventory_hyperframes_capabilities(
        skill_root=skill_root,
        hyperframes_cli_path=cli_path,
        hyperframes_version="0.7.54",
    )

    for capability in catalog["capabilities"]:
        if capability["adaptationEligibility"] != "adaptable":
            continue
        required = required_capability_resource_ids(catalog, capability["id"])
        assert "hf-contract:animation" in required
        assert any(
            resource["id"] in required
            and resource["relativePath"] == capability["source"]["relativePath"]
            and resource["sha256"] == capability["source"]["sha256"]
            for resource in catalog["sourceResources"]
        )
    pivot = required_capability_resource_ids(catalog, "hf-blueprint:video-text-pivot")
    assert "hf-support:adapters/gsap-transforms-and-perf.md" in pivot
    assert "hf-example:metric-video-text-pivot" in pivot
    assert "hf-rule-source:gsap-effects" in pivot


def test_capability_inventory_rejects_unindexed_rule_file(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    (skill / "rules").mkdir(parents=True)
    (skill / "blueprints").mkdir()
    (skill / "transitions").mkdir()
    (skill / "SKILL.md").write_text("skill", encoding="utf-8")
    (skill / "rules-index.md").write_text("[one](rules/one.md)", encoding="utf-8")
    (skill / "rules" / "one.md").write_text("one", encoding="utf-8")
    (skill / "rules" / "hidden.md").write_text("hidden", encoding="utf-8")
    (skill / "blueprints-index.md").write_text("", encoding="utf-8")
    cli = tmp_path / "cli.js"
    cli.write_text('TRANSITIONS["crossfade"] = crossfade;', encoding="utf-8")

    with pytest.raises(ValueError, match="Rule index/file mismatch"):
        inventory_hyperframes_capabilities(
            skill_root=skill,
            hyperframes_cli_path=cli,
            hyperframes_version="test",
        )


def _workflow_lock_for_build() -> dict:
    return {
        "hyperframesCliVersion": "0.7.54",
        "hyperframesCliHash": SHA,
        "compilerVersion": "1",
        "compilerHash": SHA,
        "producerAdapterVersion": "1",
        "producerAdapterHash": SHA,
        "capabilityCatalogSnapshotHash": SHA,
        "transitionSourceHashes": {},
        "transitionRuntimeRegistryHash": SHA,
    }


def test_build_lock_localizes_sequence_and_chapter_invalidation() -> None:
    manifest = _manifest()
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    dependencies = {"s1": {"tokens": ["ink"]}, "s2": {"tokens": ["ink"]}}
    implementations = {"s1": [SHA], "s2": [SHA]}
    hashes = {"s1": SHA, "s2": SHA}
    validations = {"s1": ["gate-1"], "s2": ["gate-2"]}
    first = create_build_lock(
        manifest=manifest,
        compiled=compiled,
        resolved_profile_hash=SHA,
        consumed_profile_dependencies=dependencies,
        capability_implementation_hashes=implementations,
        asset_hashes={"s1": [], "s2": []},
        generated_source_hashes=hashes,
        compiled_source_hashes=hashes,
        validation_result_ids=validations,
        workflow_lock=_workflow_lock_for_build(),
    )
    changed = json.loads(json.dumps(manifest))
    changed["revision"] = 2
    changed["sequences"][1]["compositionGraph"]["elements"][1]["properties"]["text"] = "Changed"
    changed_compiled = compile_episode_manifest(changed, compiler_version="1")
    second = create_build_lock(
        manifest=changed,
        compiled=changed_compiled,
        resolved_profile_hash=SHA,
        consumed_profile_dependencies=dependencies,
        capability_implementation_hashes=implementations,
        asset_hashes={"s1": [], "s2": []},
        generated_source_hashes=hashes,
        compiled_source_hashes=hashes,
        validation_result_ids=validations,
        workflow_lock=_workflow_lock_for_build(),
    )
    invalidation = calculate_localized_invalidation(first, second)
    assert invalidation["changedSequenceIds"] == ["s2"]
    assert invalidation["reusableSequenceIds"] == ["s1"]
    assert invalidation["changedChapterIds"] == ["chapter-complete-idea"]


def test_review_notes_autosave_and_only_creator_can_archive() -> None:
    manifest = _manifest()
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    build = create_build_lock(
        manifest=manifest,
        compiled=compiled,
        resolved_profile_hash=SHA,
        consumed_profile_dependencies={"s1": {}, "s2": {}},
        capability_implementation_hashes={"s1": [SHA], "s2": [SHA]},
        asset_hashes={},
        generated_source_hashes={},
        compiled_source_hashes={},
        validation_result_ids={},
        workflow_lock=_workflow_lock_for_build(),
    )
    review = create_review_state(episode_id="episode-1", build_lock=build)
    review = save_review_note(
        review,
        {
            "id": "note-1",
            "buildHash": build["buildHash"],
            "sequenceId": "s1",
            "elementId": "headline",
            "wordId": "w1",
            "absoluteFrame": 30,
            "note": "Move this away from the speaker.",
            "status": "changes-requested",
        },
    )
    assert review["autosave"]["status"] == "saved"
    with pytest.raises(PermissionError, match="Only the creator"):
        accept_review_note(review, "note-1", actor_role="agent")
    review = accept_review_note(review, "note-1", actor_role="creator")
    approved = create_approval_record(review, build, actor_role="creator")
    assert approved["approvalRecords"][0]["creatorApproved"] is True


def test_versioned_artifacts_preserve_exact_retrievable_bytes(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    artifact = {"schemaVersion": 1, "value": ["exact", "ordered"]}
    ref = write_versioned_artifact(
        root,
        artifact_kind="test",
        artifact_id="one",
        version=1,
        value=artifact,
    )
    stored = (root / ref["path"]).read_bytes()
    assert stored == json.dumps(
        artifact,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_versioned_artifacts_encode_semantic_ids_as_portable_paths(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    ref = write_versioned_artifact(
        root,
        artifact_kind="sequence-decision-receipts",
        artifact_id="sequence:01",
        version=1,
        value={"schemaVersion": 1},
    )

    assert ref["artifactId"] == "sequence:01"
    assert "sequence%3A01" in ref["path"]
    assert (root / ref["path"]).is_file()
    assert next_artifact_version(
        root,
        "sequence-decision-receipts",
        "sequence:01",
    ) == 2


def test_project_bootstrap_freezes_workflow_capabilities_and_transcript(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    skill_root = Path.home() / ".codex" / "skills" / "hyperframes-animation"
    cli_path = repository / "node_modules" / "hyperframes" / "dist" / "cli.js"
    if not skill_root.is_dir() or not cli_path.is_file():
        pytest.skip("Pinned local HyperFrames installation is unavailable.")
    root = _private_root(tmp_path)
    locked = root / "locked-cut.mp4"
    transcript = root / "final-transcript.json"
    locked.write_bytes(b"locked")
    document = {
        "project": {
            "fps": 30,
            "words": [
                {"id": "w1", "start": 0, "end": 0.2, "start_frame": 0, "end_frame": 6}
            ],
            "generation": {},
        }
    }
    document["project"]["generation"]["lockedTranscript"] = {
        "timingAuthority": "final-locked-transcript",
        "timingMutationAllowed": False,
        "lockedCutSha256": __import__("hashlib").sha256(locked.read_bytes()).hexdigest(),
        "wordTimingSha256": transcript_word_timing_hash(document),
    }
    transcript.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(
        "app.core.creator_project.locked_audio_stream_hash",
        lambda _path: "a" * 64,
    )

    current = initialize_creator_project(
        root,
        episode_id="episode-1",
        locked_cut=locked,
        final_transcript=transcript,
        hyperframes_skill_root=skill_root,
        hyperframes_cli_path=cli_path,
        hyperframes_version="0.7.54",
        channel_profile_id="vcg",
    )

    assert current["workflowId"] == "creator-video-production"
    assert len(current["capabilityBundle"]["resources"]) > 70
    verify_creator_project(root, current)
    verify_live_workflow_package_matches_lock(root, current)
    analysis_ref = write_versioned_artifact(
        root,
        artifact_kind="analyze-outputs",
        artifact_id="analysis",
        version=1,
        value={"schemaVersion": 1, "kind": "test-analysis"},
    )
    current = promote_creator_artifact(
        root,
        artifact_key="analysisLedger",
        artifact_reference=analysis_ref,
    )
    semantic_ref = write_versioned_artifact(
        root,
        artifact_kind="plan-outputs",
        artifact_id="semantic",
        version=1,
        value={"schemaVersion": 1, "kind": "test-semantic"},
    )
    decision_ref = write_versioned_artifact(
        root,
        artifact_kind="sequence-decision-indexes",
        artifact_id="episode-1",
        version=1,
        value={"schemaVersion": 1, "kind": "test-decisions"},
    )
    current = promote_creator_artifacts(
        root,
        artifact_references={
            "semanticManifest": semantic_ref,
            "sequenceDecisionIndex": decision_ref,
        },
    )
    classification_ref = write_versioned_artifact(
        root,
        artifact_kind="source-layout-classifications",
        artifact_id="episode-1",
        version=1,
        value={"schemaVersion": 1, "kind": "test-source-layout-classification"},
    )
    evidence_ref = write_versioned_artifact(
        root,
        artifact_kind="source-evidence-ledgers",
        artifact_id="episode-1",
        version=1,
        value={"schemaVersion": 1, "kind": "test-source-evidence"},
    )
    current = promote_creator_artifacts(
        root,
        artifact_references={
            "sourceLayoutClassification": classification_ref,
            "sourceEvidence": evidence_ref,
        },
    )

    from app.core import creator_project

    original_resource_bytes = creator_project._workflow_resource_bytes

    def changed_resource_bytes(*, additional_reference_grammar=None):
        resources = original_resource_bytes(
            additional_reference_grammar=additional_reference_grammar
        )
        resources["workflow:implementation:explicit-upgrade-test.txt"] = b"changed"
        return resources

    monkeypatch.setattr(
        "app.core.creator_project._workflow_resource_bytes",
        changed_resource_bytes,
    )
    with pytest.raises(RuntimeError, match="explicit workflow upgrade"):
        verify_live_workflow_package_matches_lock(root, current)

    upgraded = upgrade_creator_workflow_package(
        root,
        actor="test",
        reason="exercise explicit workflow supersession",
    )
    assert upgraded["workflowBundle"]["version"] == 2
    assert upgraded["workflowBundleHistory"] == [current["workflowBundle"]]
    assert upgraded["workflowLockHistory"] == [current["artifacts"]["workflowLock"]]
    assert upgraded["artifacts"]["workflowUpgrade"]
    assert "analysisLedger" not in upgraded["artifacts"]
    assert "semanticManifest" not in upgraded["artifacts"]
    assert "sequenceDecisionIndex" not in upgraded["artifacts"]
    assert "sourceLayoutClassification" not in upgraded["artifacts"]
    assert "sourceEvidence" not in upgraded["artifacts"]
    assert {
        item["artifactRef"]["sha256"]
        for item in upgraded["supersededArtifactHistory"]
    } == {
        analysis_ref["sha256"],
        semantic_ref["sha256"],
        decision_ref["sha256"],
        classification_ref["sha256"],
        evidence_ref["sha256"],
    }
    verify_live_workflow_package_matches_lock(root, upgraded)
