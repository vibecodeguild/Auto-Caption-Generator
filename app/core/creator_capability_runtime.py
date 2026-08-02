from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from app.core.creator_adaptation import _validate_fixture_graph
from app.core.creator_production import (
    artifact_id_storage_segment,
    canonical_hash,
    canonical_json_bytes,
    require_private_root,
)
from app.core.process_utils import hidden_subprocess_flags


def execute_materialized_capability(
    private_root: Path,
    *,
    adaptation_id: str,
    implementation_source_hash: str,
    context: dict,
    catalog: dict | None = None,
    capability_id: str | None = None,
) -> dict:
    """Execute admitted capability bytes for materialization using UTF-8 JSON."""

    from app.core.creator_production_menu import resolve_library_implementation_path

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
        library = resolve_library_implementation_path(
            catalog=catalog,
            capability_id=capability_id,
            adaptation_id=adaptation_id,
            implementation_source_hash=implementation_source_hash,
        )
        if library is None or not library.is_file():
            raise ValueError("Admitted capability implementation bytes are unavailable.")
        implementation = library
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
        encoding="utf-8",
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
