from __future__ import annotations

import pytest

from app.core.creator_production import compile_episode_manifest, create_build_lock
from app.core.creator_studio import apply_studio_edits, create_studio_handoff
from tests.test_creator_production import SHA, _manifest, _workflow_lock_for_build


def _build(manifest: dict) -> dict:
    compiled = compile_episode_manifest(manifest, compiler_version="1")
    return create_build_lock(
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


def test_studio_edits_round_trip_through_manifest_without_timing_or_selection_changes() -> None:
    manifest = _manifest()
    build = _build(manifest)
    handoff = create_studio_handoff(
        manifest=manifest,
        build_lock=build,
        sequence_id="s1",
        element_id="headline",
        absolute_frame=30,
    )
    updated, receipt = apply_studio_edits(
        manifest=manifest,
        build_lock=build,
        handoff=handoff,
        edits=[
            {
                "kind": "element-geometry",
                "targetId": "headline",
                "path": "x",
                "value": 0.15,
            }
        ],
    )
    assert updated["revision"] == 2
    assert updated["sequences"][0]["compositionGraph"]["events"][0]["absoluteFrame"] == 30
    assert (
        updated["sequences"][0]["selectedCapabilityBindings"]
        == manifest["sequences"][0]["selectedCapabilityBindings"]
    )
    assert receipt["timingAuthorityChanged"] is False


def test_studio_cannot_edit_semantic_form_or_absolute_timing() -> None:
    manifest = _manifest()
    build = _build(manifest)
    handoff = create_studio_handoff(
        manifest=manifest,
        build_lock=build,
        sequence_id="s1",
        element_id=None,
        absolute_frame=30,
    )
    with pytest.raises(ValueError, match="outside the manifest-aware allowlist"):
        apply_studio_edits(
            manifest=manifest,
            build_lock=build,
            handoff=handoff,
            edits=[
                {
                    "kind": "sequence-semantic-form",
                    "targetId": "s1",
                    "path": "",
                    "value": "other",
                }
            ],
        )
