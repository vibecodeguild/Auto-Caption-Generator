from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.core.edit_decisions import DeletedSilenceRange, DeletedWordRange, EditDecisionList, EditorSettings, ManualCut, SpliceAdjustment
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord


PROJECT_VERSION = 5
SUPPORTED_PROJECT_VERSIONS = {1, 2, 3, 4, PROJECT_VERSION}


def save_editor_project(path: Path, project: TranscriptProject, edits: EditDecisionList) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(editor_project_document(project, edits), indent=2), encoding="utf-8")


def editor_project_document(project: TranscriptProject, edits: EditDecisionList) -> dict:
    return {
        "version": PROJECT_VERSION,
        "project": {
            "source": project.source,
            "fps": project.fps,
            "words": [asdict(word) for word in project.words],
            "silence_ranges": [asdict(silence) for silence in project.silence_ranges],
            "generation": project.generation,
        },
        "edits": {
            "deleted_word_ranges": [asdict(item) for item in edits.deleted_word_ranges],
            "deleted_silence_ranges": [asdict(item) for item in edits.deleted_silence_ranges],
            "manual_cuts": [asdict(item) for item in edits.manual_cuts],
            "splice_adjustments": {key: asdict(value) for key, value in edits.splice_adjustments.items()},
            "final_out_frame": edits.final_out_frame,
            "settings": asdict(edits.settings),
        },
    }


def load_editor_project(path: Path) -> tuple[TranscriptProject, EditDecisionList]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") not in SUPPORTED_PROJECT_VERSIONS:
        raise ValueError(f"Unsupported editor project version: {data.get('version')}")

    project_data = data["project"]
    project = TranscriptProject(
        source=project_data["source"],
        fps=float(project_data["fps"]),
        words=[TranscriptWord(**_supported_word_fields(word)) for word in project_data["words"]],
        silence_ranges=[SilenceRange(**silence) for silence in project_data["silence_ranges"]],
        generation=project_data.get("generation", {}),
    )

    edits_data = data["edits"]
    edits = EditDecisionList(
        deleted_word_ranges=[DeletedWordRange(**item) for item in edits_data["deleted_word_ranges"]],
        deleted_silence_ranges=[DeletedSilenceRange(**item) for item in edits_data["deleted_silence_ranges"]],
        manual_cuts=[ManualCut(**item) for item in edits_data.get("manual_cuts", [])],
        splice_adjustments={
            key: SpliceAdjustment(**value) for key, value in edits_data["splice_adjustments"].items()
        },
        final_out_frame=edits_data.get("final_out_frame"),
        settings=EditorSettings(
            dead_space_min_seconds=edits_data.get("settings", {}).get("dead_space_min_seconds", 0.8)
        ),
    )
    return project, edits


def _supported_word_fields(word: dict) -> dict:
    """Ignore the abandoned per-word boundary field written by early v2 builds."""

    supported = {"id", "raw", "text", "start", "end", "start_frame", "end_frame", "sentence_id"}
    return {key: value for key, value in word.items() if key in supported}
