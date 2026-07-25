from __future__ import annotations

import hashlib
import importlib.metadata
from datetime import datetime, timezone
from pathlib import Path

from app.core.edit_decisions import EditDecisionList
from app.core.repetition_detection import detect_repeated_word_ids
from app.core.splice_generation import SplicePlan
from app.core.transcript_model import TranscriptProject


def build_generation_metadata(
    source: Path,
    *,
    model_label: str,
    model_id: str,
    compute_label: str,
    compute: dict,
    sequence_revision: int | None,
) -> dict:
    stat = source.stat()
    try:
        faster_whisper_version = importlib.metadata.version("faster-whisper")
    except importlib.metadata.PackageNotFoundError:
        faster_whisper_version = None
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "faster-whisper",
        "engine_version": faster_whisper_version,
        "model_label": model_label,
        "model_id": model_id,
        "compute_label": compute_label,
        "compute": dict(compute),
        "options": {"word_timestamps": True, "vad_filter": True},
        "source": {
            "path": str(source.resolve()),
            "size_bytes": stat.st_size,
            "sha256": _sha256(source),
        },
        "sequence_revision": sequence_revision,
    }


def with_initial_repeat_suggestions(project: TranscriptProject, word_ids: set[str]) -> dict:
    generation = dict(project.generation)
    generation["initial_repeated_word_ids"] = sorted(word_ids)
    return generation


def build_edit_analysis(project: TranscriptProject, edits: EditDecisionList, plan: SplicePlan) -> dict:
    deleted_word_ids = _deleted_word_ids(project, edits)
    initial_repeats = set(project.generation.get("initial_repeated_word_ids", []))
    active_splices = plan.splices
    reviewed = [splice for splice in active_splices if splice.reviewed]
    in_moves = [splice.right_in_adjustment for splice in reviewed if splice.right_in_adjustment]
    out_moves = [splice.left_out_adjustment for splice in reviewed if splice.left_out_adjustment]
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "generation": project.generation,
        "counts": {
            "words": len(project.words),
            "deleted_word_ranges": len(edits.deleted_word_ranges),
            "deleted_silence_ranges": len(edits.deleted_silence_ranges),
            "manual_cuts": len(edits.manual_cuts),
            "active_splices": len(active_splices),
            "reviewed_splices": len(reviewed),
        },
        "boundary_adjustments": {
            "in": _adjustment_summary(in_moves),
            "out": _adjustment_summary(out_moves),
        },
        "repetition_suggestions": {
            "initial_word_ids": sorted(initial_repeats),
            "suggested_words_later_deleted": sorted(initial_repeats & deleted_word_ids),
            "suggested_words_kept": sorted(initial_repeats - deleted_word_ids),
            "remaining_current_suggestions": sorted(detect_repeated_word_ids(project.words, deleted_word_ids)),
        },
        "splices": [
            {
                "anchor_key": splice.anchor_key,
                "kind": splice.kind,
                "manual_cut_id": splice.manual_cut_id or None,
                "reviewed": splice.reviewed,
                "left_whisper_out_frame": splice.left_whisper_out_frame,
                "left_suggested_out_frame": splice.left_suggested_out_frame,
                "left_final_out_frame": splice.left_out_frame,
                "left_manual_delta": splice.left_out_adjustment,
                "right_whisper_in_frame": splice.right_whisper_in_frame,
                "right_suggested_in_frame": splice.right_suggested_in_frame,
                "right_final_in_frame": splice.right_in_frame,
                "right_manual_delta": splice.right_in_adjustment,
            }
            for splice in active_splices
        ],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _deleted_word_ids(project: TranscriptProject, edits: EditDecisionList) -> set[str]:
    deleted: set[str] = set()
    for item in edits.deleted_word_ranges:
        start = project.word_index(item.start_word_id)
        end = project.word_index(item.end_word_id)
        if end < start:
            start, end = end, start
        deleted.update(word.id for word in project.words[start : end + 1])
    return deleted


def _adjustment_summary(values: list[int]) -> dict:
    ordered = sorted(values)
    return {
        "moved_count": len(ordered),
        "positive_count": sum(value > 0 for value in ordered),
        "negative_count": sum(value < 0 for value in ordered),
        "mean_frames": round(sum(ordered) / len(ordered), 2) if ordered else 0,
        "median_frames": ordered[len(ordered) // 2] if ordered else 0,
        "min_frames": min(ordered, default=0),
        "max_frames": max(ordered, default=0),
    }
