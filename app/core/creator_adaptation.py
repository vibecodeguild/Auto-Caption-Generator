from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from app.core.creator_project import promote_creator_artifact, verify_creator_project
from app.core.creator_production import (
    artifact_id_storage_segment,
    canonical_hash,
    canonical_json_bytes,
    next_artifact_version,
    require_private_root,
    validate_artifact,
    write_versioned_artifact,
)
from app.core.process_utils import hidden_subprocess_flags


FORBIDDEN_IMPLEMENTATION_PATTERNS = (
    r"\bfetch\s*\(",
    r"\bXMLHttpRequest\b",
    r"\bWebSocket\b",
    r"\bprocess\.",
    r"\bDeno\.",
    r"\bBun\.",
    r"https?://",
    r"\bMath\.random\b",
    r"\bDate\.now\b",
)
SUPPORTED_OPERATIONS = {
    "set", "reveal", "enter", "show", "type-reveal", "move", "scale",
    "rotate", "emphasize", "hide", "exit",
}
FORBIDDEN_ANIMATED_LAYOUT_PROPERTIES = {
    "left", "top", "right", "bottom", "width", "height",
}


def _validate_motion_values(value: object, *, path: str) -> None:
    if isinstance(value, dict):
        forbidden = sorted(FORBIDDEN_ANIMATED_LAYOUT_PROPERTIES.intersection(value))
        if forbidden:
            raise ValueError(
                "Capability fixture animates forbidden layout properties at "
                f"{path}: {', '.join(forbidden)}"
            )
        for key, child in value.items():
            _validate_motion_values(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_motion_values(child, path=f"{path}[{index}]")


def _validate_fixture_graph(graph: dict) -> None:
    if not isinstance(graph, dict) or not isinstance(graph.get("elements"), list) or not isinstance(
        graph.get("events"), list
    ):
        raise ValueError("Capability fixture must produce elements and events arrays.")
    element_ids = set()
    for element in graph["elements"]:
        element_id = element.get("id")
        geometry = element.get("geometry")
        if not element_id or element_id in element_ids or not isinstance(geometry, dict):
            raise ValueError("Capability fixture produced invalid or duplicate elements.")
        element_ids.add(element_id)
        for key in ("x", "y", "width", "height"):
            value = geometry.get(key)
            if not isinstance(value, (int, float)):
                raise ValueError("Capability fixture geometry must be fully numeric.")
        if (
            geometry["x"] < 0
            or geometry["y"] < 0
            or geometry["width"] <= 0
            or geometry["height"] <= 0
            or geometry["x"] + geometry["width"] > 1
            or geometry["y"] + geometry["height"] > 1
        ):
            raise ValueError("Capability fixture geometry must stay inside normalized canvas.")
    for event in graph["events"]:
        if event.get("targetElementId") not in element_ids:
            raise ValueError("Capability fixture event targets an unknown element.")
        if event.get("operation") not in SUPPORTED_OPERATIONS:
            raise ValueError("Capability fixture uses an operation the renderer has not admitted.")
        parameters = event.get("parameters")
        if isinstance(parameters, dict):
            for motion_key in ("from", "to", "keyframes"):
                if motion_key in parameters:
                    _validate_motion_values(
                        parameters[motion_key],
                        path=f"event[{event.get('id', '?')}].parameters.{motion_key}",
                    )


def execute_project_capability(
    private_root: Path,
    *,
    adaptation_id: str,
    implementation_source_hash: str,
    context: dict,
) -> dict:
    root = require_private_root(private_root)
    implementation = (
        root
        / "creator-production"
        / "implementations"
        / artifact_id_storage_segment(adaptation_id)
        / implementation_source_hash
        / "implementation.mjs"
    )
    if not implementation.is_file():
        raise ValueError("Admitted capability implementation bytes are unavailable.")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to execute admitted capability source.")
    context_root = root / "creator-production" / "runtime-contexts"
    context_root.mkdir(parents=True, exist_ok=True)
    context_hash = canonical_hash(context)
    context_path = context_root / f"{context_hash}.json"
    content = canonical_json_bytes(context)
    if context_path.exists() and context_path.read_bytes() != content:
        raise RuntimeError("Capability runtime context hash collision.")
    context_path.write_bytes(content)
    probe = Path(__file__).resolve().parents[2] / "scripts" / "probe-creator-capability.mjs"
    executed = subprocess.run(
        [node, str(probe), str(implementation), str(context_path)],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if executed.returncode != 0:
        raise ValueError(
            "Admitted capability failed deterministic materialization: "
            + (executed.stderr or executed.stdout)[-800:]
        )
    try:
        graph = json.loads(executed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Admitted capability did not return a JSON graph.") from exc
    _validate_fixture_graph(graph)
    return graph


def admit_project_capability(
    private_root: Path,
    *,
    adaptation: dict,
    expected_sequence_id: str,
    expected_capability_id: str,
    promote: bool = True,
) -> tuple[dict, dict, dict]:
    root = require_private_root(private_root)
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    validate_artifact("capability-adaptation", adaptation)
    if adaptation["episodeId"] != current["episodeId"]:
        raise ValueError("Capability adaptation belongs to another episode.")
    if adaptation["sequenceId"] != expected_sequence_id:
        raise ValueError("Capability adaptation changed its authorized sequence.")
    if adaptation["sourceCapabilityId"] != expected_capability_id:
        raise ValueError("Capability adaptation changed its authorized source capability.")

    catalog_ref = current["artifacts"]["capabilityCatalog"]
    catalog = json.loads((root / catalog_ref["path"]).read_text(encoding="utf-8"))
    matching = [item for item in catalog["capabilities"] if item["id"] == expected_capability_id]
    if not matching:
        raise ValueError("Capability adaptation names a source outside the locked catalog.")
    capability = matching[0]
    required_resource_ids = capability.get("requiredResourceIds")
    if not isinstance(required_resource_ids, list) or not required_resource_ids:
        raise ValueError("Capability has no complete frozen instruction dependency set.")
    resource_index = {
        item["id"]: item
        for item in [*catalog["sourceResources"], *catalog["supportResources"]]
    }
    if adaptation["sourceResourceIds"] != required_resource_ids:
        raise ValueError(
            "Capability adaptation did not retain its exact frozen instruction dependency set."
        )
    required_hashes = list(
        dict.fromkeys(
            resource_index[resource_id]["sha256"]
            for resource_id in required_resource_ids
        )
    )
    if adaptation["sourceHashes"] != required_hashes:
        raise ValueError(
            "Capability adaptation did not retain the exact frozen instruction dependency hashes."
        )

    implementation_file = None
    seen_paths = set()
    for item in adaptation["files"]:
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in seen_paths:
            raise ValueError("Capability adaptation contains an unsafe or duplicate file path.")
        seen_paths.add(str(relative))
        if str(relative) == "implementation.mjs":
            implementation_file = item
        for pattern in FORBIDDEN_IMPLEMENTATION_PATTERNS:
            if re.search(pattern, item["content"]):
                raise ValueError(
                    f"Capability adaptation uses forbidden nondeterministic behavior: {pattern}"
                )
    if implementation_file is None:
        raise ValueError("Capability adaptation must contain implementation.mjs.")
    if not re.search(r"\bexport\s+(?:function|const)\s+build\b", implementation_file["content"]):
        raise ValueError("implementation.mjs must export build(context).")

    implementation_hash = canonical_hash(adaptation["files"])
    implementation_id = f"{adaptation['id']}@{adaptation['version']}:{implementation_hash[:12]}"
    implementation_root = (
        root
        / "creator-production"
        / "implementations"
        / artifact_id_storage_segment(adaptation["id"])
        / implementation_hash
    )
    for item in adaptation["files"]:
        destination = implementation_root / PurePosixPath(item["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = item["content"].encode("utf-8")
        if destination.exists() and destination.read_bytes() != content:
            raise RuntimeError("Immutable capability implementation bytes changed.")
        destination.write_bytes(content)

    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to technically admit capability source.")
    checked = subprocess.run(
        [node, "--check", str(implementation_root / "implementation.mjs")],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if checked.returncode != 0:
        raise ValueError(f"Capability implementation failed syntax admission: {checked.stderr[-800:]}")
    fixture_path = implementation_root / "fixture-input.json"
    fixture_path.write_bytes(canonical_json_bytes(adaptation["validationFixture"]))
    probe = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "probe-creator-capability.mjs"
    )
    results = []
    for _run in range(2):
        executed = subprocess.run(
            [node, str(probe), str(implementation_root / "implementation.mjs"), str(fixture_path)],
            capture_output=True,
            text=True,
            check=False,
            creationflags=hidden_subprocess_flags(),
        )
        if executed.returncode != 0:
            raise ValueError(
                "Capability implementation failed restricted fixture execution: "
                + (executed.stderr or executed.stdout)[-800:]
            )
        try:
            graph = json.loads(executed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Capability fixture did not return a JSON graph.") from exc
        _validate_fixture_graph(graph)
        results.append(graph)
    if canonical_json_bytes(results[0]) != canonical_json_bytes(results[1]):
        raise ValueError("Capability fixture output is not deterministic.")

    admitted = json.loads(canonical_json_bytes(adaptation).decode("utf-8"))
    admitted["implementationId"] = implementation_id
    admitted["implementationSourceHash"] = implementation_hash
    admitted["technicalAdmission"] = "project-admitted"
    admitted["productionSelection"] = "production-selectable"
    admitted["admissionEvidence"] = {
        "nodeSyntaxCheck": "passed",
        "determinismStaticCheck": "passed",
        "restrictedFixtureExecution": "passed",
        "fixtureInputHash": canonical_hash(adaptation["validationFixture"]),
        "fixtureOutputHash": canonical_hash(results[0]),
        "scope": {
            "episodeId": current["episodeId"],
            "sequenceId": expected_sequence_id,
        },
    }
    adaptation_ref = write_versioned_artifact(
        root,
        artifact_kind="capability-adaptations",
        artifact_id=adaptation["id"],
        version=next_artifact_version(
            root, "capability-adaptations", adaptation["id"]
        ),
        value=admitted,
    )

    capability["implementationMaturity"] = "technically-proven"
    capability["technicalAdmission"] = "project-admitted"
    capability["productionSelection"] = "production-selectable"
    capability["linkedImplementationIds"] = sorted(
        set([*capability["linkedImplementationIds"], implementation_id])
    )
    capability.setdefault("projectAdmissions", []).append(
        {
            "episodeId": current["episodeId"],
            "sequenceId": expected_sequence_id,
            "implementationId": implementation_id,
            "adaptationId": adaptation["id"],
            "implementationSourceHash": implementation_hash,
            "implementationRelativePath": (
                implementation_root / "implementation.mjs"
            ).relative_to(root).as_posix(),
            "adaptationArtifactSha256": adaptation_ref["sha256"],
        }
    )
    catalog["version"] = int(catalog["version"]) + 1
    catalog["inventorySummary"]["productionSelectable"] = sum(
        item["productionSelection"] == "production-selectable"
        for item in catalog["capabilities"]
    )
    catalog["inventorySummary"]["adaptationDebtCount"] = sum(
        item["sourceAvailability"] == "source-enabled"
        and item["productionSelection"] != "production-selectable"
        for item in catalog["capabilities"]
    )
    catalog["catalogHash"] = canonical_hash(
        {key: value for key, value in catalog.items() if key != "catalogHash"}
    )
    validate_artifact("capability-catalog", catalog)
    catalog_ref = write_versioned_artifact(
        root,
        artifact_kind="capability-catalogs",
        artifact_id=catalog["id"],
        version=next_artifact_version(
            root, "capability-catalogs", catalog["id"]
        ),
        value=catalog,
        schema_name="capability-catalog",
    )
    if promote:
        promote_creator_artifact(
            root,
            artifact_key="capabilityCatalog",
            artifact_reference=catalog_ref,
        )
        promote_creator_artifact(
            root,
            artifact_key="capabilityAdaptation",
            artifact_reference=adaptation_ref,
        )
    return adaptation_ref, catalog_ref, catalog
