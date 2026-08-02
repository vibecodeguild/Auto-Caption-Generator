"""Graphics Library - private usages store, ensure engines, path safety, status updates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import graphics_library as gr
from app.core.visual_production import MODULE_IDS


@pytest.fixture()
def library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "graphics-library"
    # Keep Creator Library outside repo as well.
    library = tmp_path / "creator-library"
    library.mkdir()
    monkeypatch.setenv("VCG_GRAPHICS_LIBRARY", str(root))
    monkeypatch.setenv("VCG_CREATOR_LIBRARY", str(library))
    return root


def test_create_and_ensure_candidates_never_auto_golden(library_root: Path) -> None:
    gr.create_graphics_library(library_root)
    report = gr.ensure_candidate_usages_from_engines(library_root)
    assert report["total"] >= len(MODULE_IDS)
    document = gr.load_graphics_library(library_root)
    assert document["schemaVersion"] == 1
    assert all(entry["status"] == "candidate" for entry in document["entries"])
    assert all(entry["id"] in MODULE_IDS for entry in document["entries"])
    assert not any(entry["status"] == "golden" for entry in document["entries"])
    # buildable is dropped product noise - not written on new usages
    assert not any("buildable" in entry for entry in document["entries"])


def test_update_status_only(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = sorted(MODULE_IDS)[0]
    updated = gr.update_entry(entry_id, {"status": "golden"}, library_root)
    assert updated["status"] == "golden"
    assert "rating" not in updated
    assert "notes" not in updated
    assert "history" not in updated
    reloaded = gr.get_entry(entry_id, library_root)
    assert reloaded["status"] == "golden"


def test_library_metrics_counts_beats_and_layouts(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = sorted(MODULE_IDS)[0]
    gr.update_entry(
        entry_id,
        {
            "status": "golden",
            "beatTypes": ["punchline", "proof"],
            "allowedLayouts": ["full-screen-talking", "talking-right"],
        },
        library_root,
    )
    metrics = gr.library_metrics(library_root)
    assert metrics["exists"] is True
    assert metrics["entryCount"] >= len(MODULE_IDS)
    by_beat = {row["id"]: row for row in metrics["byBeatType"]}
    by_layout = {row["id"]: row for row in metrics["byLayout"]}
    assert by_beat["punchline"]["total"] >= 1
    assert by_beat["punchline"]["golden"] >= 1
    assert by_beat["proof"]["total"] >= 1
    assert by_layout["full-screen-talking"]["total"] >= 1
    assert by_layout["talking-right"]["total"] >= 1
    # Untagged rows exist for engines that still have empty beatTypes/layouts.
    assert metrics["untaggedBeatTypes"]["total"] >= 0
    assert metrics["untaggedLayouts"]["total"] >= 0


def test_resolve_sample_layout_respects_allowed() -> None:
    entry = {"allowedLayouts": ["talking-bottom-left", "computer-screen-only"]}
    assert gr.resolve_sample_layout_id(entry, None) == "talking-bottom-left"
    assert gr.resolve_sample_layout_id(entry, "computer-screen-only") == "computer-screen-only"
    with pytest.raises(ValueError, match="not in this usage"):
        gr.resolve_sample_layout_id(entry, "talking-left")


def test_layout_clips_list_and_import(library_root: Path, tmp_path: Path) -> None:
    status = gr.list_layout_clips(library_root)
    assert status["complete"] is False
    assert "talking-bottom-right" in status["missing"]
    # Create a tiny valid video via a copied zero-byte is invalid — write a minimal
    # fake mp4 path by reusing import from a short generated file if ffmpeg available.
    source = tmp_path / "layout-source.mp4"
    # Minimal: if we cannot make a real video, just copy a path and skip encode by
    # writing dummy then expecting import with full copy when start=0 duration None.
    source.write_bytes(b"not-a-real-video")
    # Full copy path doesn't re-encode when start_sec=0 and duration None.
    status = gr.import_layout_clip(
        "talking-bottom-right",
        source,
        root=library_root,
        start_sec=0.0,
        duration_sec=None,
    )
    assert "talking-bottom-right" in status["present"]
    assert gr.layout_clip_path("talking-bottom-right", library_root).is_file()


def test_update_producer_metadata(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = "numbered-example-card" if "numbered-example-card" in MODULE_IDS else sorted(MODULE_IDS)[0]
    updated = gr.update_entry(
        entry_id,
        {
            "beatTypes": ["example", "list", "example"],
            "allowedLayouts": ["talking-left", "talking-bottom-left"],
        },
        library_root,
    )
    assert updated["beatTypes"] == ["example", "list"]
    assert updated["allowedLayouts"] == ["talking-left", "talking-bottom-left"]
    # Persist + list summary must still show fields (UI load path).
    reloaded = gr.get_entry(entry_id, library_root)
    assert reloaded["beatTypes"] == ["example", "list"]
    assert reloaded["allowedLayouts"] == ["talking-left", "talking-bottom-left"]
    listed = next(
        item for item in gr.summary(library_root)["entries"] if item["id"] == entry_id
    )
    assert listed["beatTypes"] == ["example", "list"]
    assert listed["allowedLayouts"] == ["talking-left", "talking-bottom-left"]


def test_beat_types_reject_unknown(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = sorted(MODULE_IDS)[0]
    with pytest.raises(ValueError, match="Invalid beat type"):
        gr.update_entry(entry_id, {"beatTypes": ["hook", "not-a-beat"]}, library_root)


def test_media_path_rejects_escape(library_root: Path, tmp_path: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = sorted(MODULE_IDS)[0]
    document = gr.load_graphics_library(library_root)
    for entry in document["entries"]:
        if entry["id"] == entry_id:
            entry["sample"] = {
                "relativePath": "../secret.mp4",
                "posterRelativePath": None,
            }
    gr.save_graphics_library(document, library_root)
    # Create a file outside root that a naive join might find.
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"nope")
    with pytest.raises(ValueError, match="escapes|missing|No sample"):
        gr.resolve_media_path(entry_id, "sample", library_root)


def test_summary_empty(library_root: Path) -> None:
    snap = gr.summary(library_root)
    assert snap["exists"] is False
    assert snap["entryCount"] == 0
    assert snap["productionSet"]["empty"] is True
    assert snap["productionSet"]["count"] == 0


def test_production_set_only_golden(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_a, entry_b = sorted(MODULE_IDS)[:2]
    gr.update_entry(entry_a, {"status": "golden"}, library_root)
    gr.update_entry(entry_b, {"status": "candidate"}, library_root)

    emptyish = gr.get_production_graphics(library_root, policy="golden-only")
    assert emptyish["empty"] is False
    assert emptyish["ids"] == [entry_a]
    assert all(item["status"] == "golden" for item in emptyish["usages"])
    assert emptyish["usages"][0]["engineId"] == entry_a
    assert entry_b not in emptyish["ids"]
    assert "requireBuildable" not in emptyish
    assert "buildable" not in emptyish["usages"][0]


def test_legacy_statuses_normalize_to_candidate(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = sorted(MODULE_IDS)[0]
    document = gr.load_graphics_library(library_root)
    for entry in document["entries"]:
        if entry["id"] == entry_id:
            entry["status"] = "rejected"
    gr.save_graphics_library(document, library_root)
    reloaded = gr.get_entry(entry_id, library_root)
    assert reloaded["status"] == "candidate"


def test_production_set_empty_without_golden(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    result = gr.get_production_graphics(library_root, policy="golden-only")
    assert result["exists"] is True
    assert result["empty"] is True
    assert result["ids"] == []
    assert result["emptyReason"] == "no-golden-status"
    assert "promote" in result["message"].lower() or "golden" in result["message"].lower()


def test_production_set_missing_record(library_root: Path) -> None:
    result = gr.get_production_graphics(library_root)
    assert result["exists"] is False
    assert result["empty"] is True
    assert result["emptyReason"] == "no-graphics-library"


def test_production_set_includes_golden_usage_with_engine(library_root: Path) -> None:
    """Production set is golden status; engineId is composition on the usage."""
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = sorted(MODULE_IDS)[0]
    gr.update_entry(entry_id, {"status": "golden"}, library_root)
    result = gr.get_production_graphics(library_root)
    assert entry_id in result["ids"]
    usage = next(item for item in result["usages"] if item["id"] == entry_id)
    assert usage["engineId"] == entry_id


def test_public_view_hides_dropped_fields_and_exposes_engine(library_root: Path) -> None:
    gr.ensure_candidate_usages_from_engines(library_root)
    entry_id = sorted(MODULE_IDS)[0]
    document = gr.load_graphics_library(library_root)
    for entry in document["entries"]:
        if entry["id"] == entry_id:
            entry["buildable"] = True
            entry["demoBed"] = "talking-head"
            entry["reusePolicy"] = "limited"
            entry["purpose"] = "legacy"
            entry["engineId"] = entry_id
    gr.save_graphics_library(document, library_root)
    # End-pass scrub: legacy keys not re-written to disk.
    reloaded = gr.load_graphics_library(library_root)
    stored = next(item for item in reloaded["entries"] if item["id"] == entry_id)
    assert "buildable" not in stored
    assert "demoBed" not in stored
    assert "implementationId" not in stored
    public = gr.get_entry(entry_id, library_root)
    assert "buildable" not in public
    assert "demoBed" not in public
    assert "reusePolicy" not in public
    assert "purpose" not in public
    assert "parameters" not in public
    assert public["engineId"] == entry_id
    assert isinstance(public.get("engineInterface"), list)
    assert gr.resolve_engine_id(entry_id, library_root) == entry_id


def test_import_skips_unbuildable(library_root: Path) -> None:
    import os

    library = Path(os.environ["VCG_CREATOR_LIBRARY"])
    library.mkdir(parents=True, exist_ok=True)
    treatments = {
        "schemaVersion": 1,
        "treatments": [
            {
                "id": "numbered-example-card",
                "lockedDefault": True,
            },
            {
                "id": "build-review-change-loop",
            },
        ],
    }
    (library / "treatments.json").write_text(json.dumps(treatments), encoding="utf-8")
    report = gr.import_treatment_harvest(library_root)
    assert report["skippedUnbuildable"] >= 1
    entry = gr.get_entry("numbered-example-card", library_root)
    assert "rating" not in entry
    assert "notes" not in entry
    assert entry["status"] == "candidate"  # harvest never auto-golden
    assert entry["status"] != "golden"
