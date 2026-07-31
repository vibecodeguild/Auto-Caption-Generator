from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.core.creator_adaptation import _validate_fixture_graph
from app.core.creator_capability_runtime import execute_materialized_capability
from app.core.creator_project import PACKAGE_ROOT, _workflow_resource_bytes
from app.core.creator_production import (
    artifact_id_storage_segment,
    validate_artifact,
    write_versioned_artifact,
)
from app.core.creator_rendering import _event_timeline_line


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir()
    (root / ".vcg-private").write_text("private", encoding="utf-8")
    return root


def test_every_shipped_channel_profile_validates_and_has_a_frozen_grammar() -> None:
    for profile_path in (PACKAGE_ROOT / "profiles").glob("*.json"):
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if "parentProfileRef" not in profile:
            continue
        validate_artifact("channel-profile", profile)
        grammar = profile["referenceGrammarRef"].replace("@", ".v")
        assert (PACKAGE_ROOT / "reference-grammars" / f"{grammar}.md").is_file()


def test_workflow_snapshot_contains_every_execution_layer() -> None:
    resources = _workflow_resource_bytes()
    required = {
        "workflow:main",
        "workflow:task:analyze",
        "workflow:task:plan",
        "workflow:task:adapt",
        "workflow:task:materialize",
        "workflow:task:revise",
        "workflow:package:schemas/editorial-plan-decisions.schema.json",
        "workflow:package:schemas/spoken-span-receipt.schema.json",
        "workflow:package:schemas/semantic-plan-materialization-receipt.schema.json",
        "workflow:implementation:creator_task_handoff.py",
        "workflow:implementation:creator_semantic_planning.py",
        "workflow:implementation:creator-task-handoff-cli.py",
        "workflow:implementation:creator_adaptation.py",
        "workflow:implementation:creator_render_jobs.py",
        "workflow:implementation:probe-creator-capability.mjs",
    }
    assert required <= set(resources)


def test_immutable_artifact_version_cannot_fork(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    write_versioned_artifact(
        root,
        artifact_kind="proof",
        artifact_id="one",
        version=1,
        value={"value": "first"},
    )
    with pytest.raises(RuntimeError, match="already exists"):
        write_versioned_artifact(
            root,
            artifact_kind="proof",
            artifact_id="one",
            version=1,
            value={"value": "different"},
        )


def test_semantic_ids_use_portable_implementation_and_composition_segments() -> None:
    assert artifact_id_storage_segment("adaptation:sequence-01:graphic") == (
        "adaptation%3Asequence-01%3Agraphic"
    )
    assert artifact_id_storage_segment("chapter:introduction") == "chapter%3Aintroduction"


def test_renderer_rejects_an_unadmitted_graph_operation() -> None:
    with pytest.raises(ValueError, match="no admitted graph operation"):
        _event_timeline_line(
            {
                "operation": "invent-an-effect",
                "targetElementId": "target",
                "absoluteFrame": 10,
                "durationFrames": 1,
                "easing": None,
                "parameters": {},
            },
            chapter_start=0,
            fps=30,
        )


def test_capability_fixture_graph_must_stay_inside_normalized_canvas() -> None:
    with pytest.raises(ValueError, match="inside normalized canvas"):
        _validate_fixture_graph(
            {
                "elements": [
                    {
                        "id": "bad",
                        "geometry": {"x": 0.9, "y": 0, "width": 0.2, "height": 1},
                    }
                ],
                "events": [],
            }
        )


def test_capability_fixture_rejects_animated_layout_properties() -> None:
    with pytest.raises(ValueError, match="forbidden layout properties"):
        _validate_fixture_graph(
            {
                "elements": [
                    {
                        "id": "speaker",
                        "geometry": {"x": 0, "y": 0, "width": 1, "height": 1},
                    }
                ],
                "events": [
                    {
                        "id": "bad-move",
                        "targetElementId": "speaker",
                        "operation": "move",
                        "parameters": {
                            "to": {
                                "left": "2%",
                                "top": "4%",
                                "width": "82%",
                                "height": "82%",
                            },
                            "resolvedGeometry": {
                                "x": 0.02,
                                "y": 0.04,
                                "width": 0.82,
                                "height": 0.82,
                            },
                        },
                    }
                ],
            }
        )


def test_restricted_capability_probe_is_deterministic(tmp_path: Path) -> None:
    implementation = tmp_path / "implementation.mjs"
    fixture = tmp_path / "fixture.json"
    implementation.write_text(
        "export function build(context){return {elements:[{id:'speaker',geometry:{x:0,y:0,width:1,height:1}}],events:[]};}",
        encoding="utf-8",
    )
    fixture.write_text("{}", encoding="utf-8")
    probe = Path(__file__).resolve().parents[1] / "scripts" / "probe-creator-capability.mjs"
    result = subprocess.run(
        ["node", str(probe), str(implementation), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["elements"][0]["id"] == "speaker"


def test_restricted_capability_probe_blocks_randomness(tmp_path: Path) -> None:
    implementation = tmp_path / "implementation.mjs"
    fixture = tmp_path / "fixture.json"
    implementation.write_text(
        "export function build(){return Math.random();}",
        encoding="utf-8",
    )
    fixture.write_text("{}", encoding="utf-8")
    probe = Path(__file__).resolve().parents[1] / "scripts" / "probe-creator-capability.mjs"
    result = subprocess.run(
        ["node", str(probe), str(implementation), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Math.random is unavailable" in result.stderr
def test_materialization_runtime_decodes_capability_json_as_utf8(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    adaptation_id = "adaptation:utf8"
    source_hash = "a" * 64
    implementation = (
        root
        / "creator-production"
        / "implementations"
        / artifact_id_storage_segment(adaptation_id)
        / source_hash
        / "implementation.mjs"
    )
    implementation.parent.mkdir(parents=True)
    implementation.write_text(
        """
export function build() {
  return {
    elements: [{
      id: "label", kind: "text", parentId: null, zIndex: 1,
      geometry: {x: 0, y: 0, width: 1, height: 1},
      tokenBindings: {},
      properties: {text: "CAN’T SCAN THIS"}
    }],
    events: []
  };
}
""".strip(),
        encoding="utf-8",
    )

    graph = execute_materialized_capability(
        root,
        adaptation_id=adaptation_id,
        implementation_source_hash=source_hash,
        context={},
    )

    assert graph["elements"][0]["properties"]["text"] == "CAN’T SCAN THIS"
