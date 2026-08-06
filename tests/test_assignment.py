"""Stage 2 Assignment — deal algorithm + original/working/ledger artifacts."""

from __future__ import annotations

import json
import random
from pathlib import Path

from app.core.assignment import (
    OUTPUT_FILENAME,
    REVIEWED_FILENAME,
    LEDGER_FILENAME,
    SOURCE_HUMAN,
    deal_assignments,
    load_assignment_ledger,
    load_assignment_original,
    load_assignment_reviewed,
    run_assignment_for_video_project,
    save_assignment_override_for_video_project,
)
from app.core.graphics_library import LIBRARY_SCHEMA_VERSION
from app.core.masterbeater import (
    normalize_masterbeater_result,
    write_masterbeater_output,
)


def _sample_document() -> dict:
    return {
        "project": {
            "fps": 30,
            "words": [
                {
                    "id": "w1",
                    "text": "Hello",
                    "start": 0.0,
                    "end": 0.3,
                    "start_frame": 0,
                    "end_frame": 9,
                },
                {
                    "id": "w2",
                    "text": "world",
                    "start": 0.3,
                    "end": 0.6,
                    "start_frame": 9,
                    "end_frame": 18,
                },
                {
                    "id": "w3",
                    "text": "context",
                    "start": 1.0,
                    "end": 1.3,
                    "start_frame": 30,
                    "end_frame": 39,
                },
                {
                    "id": "w4",
                    "text": "again",
                    "start": 1.3,
                    "end": 1.6,
                    "start_frame": 39,
                    "end_frame": 48,
                },
                {
                    "id": "w5",
                    "text": "more",
                    "start": 2.0,
                    "end": 2.3,
                    "start_frame": 60,
                    "end_frame": 69,
                },
            ],
        }
    }


def _write_library(library_root: Path, entries: list[dict]) -> None:
    library_root.mkdir(parents=True, exist_ok=True)
    # Outside-repo private root is enforced on save elsewhere; tests only load.
    (library_root / "graphics-library.json").write_text(
        json.dumps(
            {
                "schemaVersion": LIBRARY_SCHEMA_VERSION,
                "updatedAt": "2026-08-02T00:00:00Z",
                "rootLabel": "test",
                "entries": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_deal_uses_bag_without_replacement_then_refills() -> None:
    beats = [
        {"id": "b1", "beatType": "context"},
        {"id": "b2", "beatType": "context"},
        {"id": "b3", "beatType": "context"},
        {"id": "b4", "beatType": "context"},
    ]
    usages = [
        {"id": "g1", "beatTypes": ["context"], "allowedLayouts": ["talking-left"]},
        {"id": "g2", "beatTypes": ["context"], "allowedLayouts": ["talking-left"]},
    ]
    layouts = {b["id"]: "talking-left" for b in beats}
    # Seeded: first two unique, third+fourth refill same pool.
    dealt = deal_assignments(
        beats, usages, layout_by_beat=layouts, rng=random.Random(0)
    )
    assert len(dealt) == 4
    first_pair = {dealt[0]["usageId"], dealt[1]["usageId"]}
    assert first_pair == {"g1", "g2"}
    assert dealt[2]["usageId"] in {"g1", "g2"}
    assert dealt[3]["usageId"] in {"g1", "g2"}
    assert dealt[2]["usageId"] != dealt[3]["usageId"]


def test_deal_preserves_human_overrides() -> None:
    beats = [
        {"id": "b1", "beatType": "context"},
        {"id": "b2", "beatType": "context"},
    ]
    usages = [
        {"id": "g1", "beatTypes": ["context"], "allowedLayouts": ["talking-left"]},
        {"id": "g2", "beatTypes": ["context"], "allowedLayouts": ["talking-left"]},
    ]
    layouts = {"b1": "talking-left", "b2": "talking-left"}
    preserve = {
        "b1": {"beatId": "b1", "usageId": "g2", "source": SOURCE_HUMAN},
    }
    dealt = deal_assignments(
        beats, usages, layout_by_beat=layouts, preserve=preserve, rng=random.Random(1)
    )
    assert dealt[0]["usageId"] == "g2"
    assert dealt[0]["source"] == SOURCE_HUMAN
    assert dealt[1]["source"] == "algorithm"
    assert dealt[1]["usageId"] in {"g1", "g2"}


def test_deal_leaves_unassigned_when_no_golden_for_type() -> None:
    beats = [{"id": "b1", "beatType": "hook"}]
    usages = [
        {"id": "g1", "beatTypes": ["context"], "allowedLayouts": ["talking-left"]}
    ]
    dealt = deal_assignments(
        beats,
        usages,
        layout_by_beat={"b1": "talking-left"},
        rng=random.Random(0),
    )
    assert dealt[0]["usageId"] is None
    assert dealt[0]["source"] == "algorithm"


def test_deal_requires_layout_match() -> None:
    beats = [{"id": "b1", "beatType": "context"}]
    usages = [
        {
            "id": "g1",
            "beatTypes": ["context"],
            "allowedLayouts": ["talking-right"],
        }
    ]
    dealt = deal_assignments(
        beats,
        usages,
        layout_by_beat={"b1": "talking-left"},
        rng=random.Random(0),
    )
    assert dealt[0]["usageId"] is None

    dealt_ok = deal_assignments(
        beats,
        usages,
        layout_by_beat={"b1": "talking-right"},
        rng=random.Random(0),
    )
    assert dealt_ok[0]["usageId"] == "g1"


def test_deal_unassigned_without_layout() -> None:
    beats = [{"id": "b1", "beatType": "context"}]
    usages = [
        {"id": "g1", "beatTypes": ["context"], "allowedLayouts": ["talking-left"]}
    ]
    dealt = deal_assignments(beats, usages, layout_by_beat={}, rng=random.Random(0))
    assert dealt[0]["usageId"] is None


def test_run_assignment_writes_original_and_reviewed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".vcg-private").write_text("private\n", encoding="utf-8")
    transcript = project / "final-transcript.json"
    document = _sample_document()
    transcript.write_text(json.dumps(document), encoding="utf-8")
    manifest_path = project / "manifest.json"
    manifest = {
        "paths": {
            "finalTranscript": "final-transcript.json",
            "lockedCut": "locked.mp4",
            "sourceVideo": "source.mp4",
        }
    }
    mb = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b1",
                    "beatType": "context",
                    "startWordId": "w1",
                    "endWordId": "w2",
                    "rationale": "A",
                },
                {
                    "id": "b2",
                    "beatType": "context",
                    "startWordId": "w3",
                    "endWordId": "w4",
                    "rationale": "B",
                },
            ],
        },
        project_root=project,
        transcript_path=transcript,
        document=document,
    )
    write_masterbeater_output(project, mb)

    library = tmp_path / "library"
    _write_library(
        library,
        [
            {
                "id": "ctx-a",
                "displayName": "Context A",
                "status": "golden",
                "engineId": "dependency-stack",
                "beatTypes": ["context"],
                "allowedLayouts": ["talking-left", "full-screen-talking"],
            },
            {
                "id": "ctx-b",
                "displayName": "Context B",
                "status": "golden",
                "engineId": "dependency-stack",
                "beatTypes": ["context"],
                "allowedLayouts": ["talking-left", "full-screen-talking"],
            },
            {
                "id": "ctx-candidate",
                "displayName": "Candidate only",
                "status": "candidate",
                "engineId": "dependency-stack",
                "beatTypes": ["context"],
                "allowedLayouts": ["talking-left"],
            },
        ],
    )

    # Scenelayer working copy required for layout filter.
    from app.core.scenelayer import write_scenelayer_original, write_scenelayer_reviewed

    sl = {
        "agent": "scenelayer",
        "schemaVersion": 1,
        "beats": [
            {"beatId": "b1", "layoutId": "talking-left", "source": "algorithm"},
            {"beatId": "b2", "layoutId": "talking-left", "source": "algorithm"},
        ],
    }
    write_scenelayer_original(project, sl)
    write_scenelayer_reviewed(project, {**sl, "agent": "scenelayer-reviewed", "role": "reviewed"})

    result = run_assignment_for_video_project(
        manifest_path,
        manifest,
        library_root=library,
        rng=random.Random(42),
    )
    assert result["ok"] is True
    assert result["firstRun"] is True
    assert result["assignedCount"] == 2
    assert (project / OUTPUT_FILENAME).is_file()
    assert (project / REVIEWED_FILENAME).is_file()

    original = load_assignment_original(project)
    reviewed = load_assignment_reviewed(project)
    assert original is not None and reviewed is not None
    assert original["beats"][0]["source"] == "algorithm"
    # Candidate never assigned
    used_ids = {row["usageId"] for row in original["beats"]}
    assert "ctx-candidate" not in used_ids
    assert used_ids <= {"ctx-a", "ctx-b"}

    original_before = json.loads((project / OUTPUT_FILENAME).read_text(encoding="utf-8"))

    # Human override on b1
    saved = save_assignment_override_for_video_project(
        manifest_path,
        manifest,
        {"beatId": "b1", "usageId": "ctx-b", "detail": "prefer B"},
        library_root=library,
    )
    assert saved["ok"] is True
    reviewed2 = load_assignment_reviewed(project)
    assert reviewed2 is not None
    by_id = {row["beatId"]: row for row in reviewed2["beats"]}
    assert by_id["b1"]["usageId"] == "ctx-b"
    assert by_id["b1"]["source"] == SOURCE_HUMAN

    # Original unchanged
    original_after = json.loads((project / OUTPUT_FILENAME).read_text(encoding="utf-8"))
    assert original_after == original_before

    ledger = load_assignment_ledger(project)
    assert ledger["entryCount"] == 1
    assert ledger["entries"][0]["toUsageId"] == "ctx-b"

    # Re-run keeps human on b1
    rerun = run_assignment_for_video_project(
        manifest_path,
        manifest,
        library_root=library,
        rng=random.Random(99),
    )
    assert rerun["firstRun"] is False
    reviewed3 = load_assignment_reviewed(project)
    assert reviewed3 is not None
    by_id3 = {row["beatId"]: row for row in reviewed3["beats"]}
    assert by_id3["b1"]["usageId"] == "ctx-b"
    assert by_id3["b1"]["source"] == SOURCE_HUMAN
    assert by_id3["b2"]["source"] == "algorithm"

    # Original still frozen
    assert json.loads((project / OUTPUT_FILENAME).read_text(encoding="utf-8")) == original_before
    assert not (project / LEDGER_FILENAME).read_text(encoding="utf-8") == ""
