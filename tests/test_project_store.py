from __future__ import annotations

import json

from app.core.edit_decisions import EditDecisionList
from app.core.project_store import PROJECT_VERSION, load_editor_project, save_editor_project
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord


def test_saves_and_loads_editor_project(tmp_path) -> None:
    project = TranscriptProject(
        source="source/raw.mp4",
        fps=30.0,
        words=[
            TranscriptWord("w1", " Hello", "Hello", 0.0, 0.5, 0, 15, 1),
            TranscriptWord("w2", " world", "world", 0.6, 1.0, 18, 30, 1),
        ],
        silence_ranges=[
            SilenceRange(
                "s1",
                0.51,
                0.59,
                16,
                17,
                measured_start=0.52,
                measured_end=0.58,
                measured_start_frame=16,
                measured_end_frame=16,
                audio_analyzed=True,
            )
        ],
    )
    edits = EditDecisionList()
    edits.delete_words("delete_w2", "w2", "w2", reason="word")
    edits.adjust_splice("w1->w2", left_out_delta=2, right_in_delta=-1, reviewed=True)
    edits.set_assisted_out_frame("w1->w2", 17)
    edits.settings.dead_space_min_seconds = 0.9

    path = tmp_path / "editor.json"
    save_editor_project(path, project, edits)
    loaded_project, loaded_edits = load_editor_project(path)

    assert loaded_project == project
    assert loaded_edits.deleted_word_ranges == edits.deleted_word_ranges
    assert loaded_edits.deleted_silence_ranges == edits.deleted_silence_ranges
    assert loaded_edits.splice_adjustments["w1->w2"].left_out_delta == 2
    assert loaded_edits.splice_adjustments["w1->w2"].right_in_delta == -1
    assert loaded_edits.splice_adjustments["w1->w2"].reviewed is True
    assert loaded_edits.splice_adjustments["w1->w2"].assisted_left_out_frame == 17
    assert loaded_edits.settings == edits.settings
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == PROJECT_VERSION


def test_loads_version_one_project_with_safe_setting_defaults(tmp_path) -> None:
    path = tmp_path / "legacy.vcg.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "project": {
                    "source": "source.mp4",
                    "fps": 30.0,
                    "words": [],
                    "silence_ranges": [],
                },
                "edits": {
                    "deleted_word_ranges": [],
                    "deleted_silence_ranges": [],
                    "splice_adjustments": {},
                },
            }
        ),
        encoding="utf-8",
    )

    _, loaded_edits = load_editor_project(path)

    assert loaded_edits.settings.dead_space_min_seconds == 0.8


def test_ignores_abandoned_per_word_assisted_end_field(tmp_path) -> None:
    project = TranscriptProject(
        source="source.mp4",
        fps=30.0,
        words=[TranscriptWord("w1", " word", "word", 0.0, 0.5, 0, 15, 1)],
        silence_ranges=[],
    )
    document = {
        "version": 2,
        "project": {
            "source": project.source,
            "fps": project.fps,
            "words": [{**project.words[0].__dict__, "assisted_end_frame": 20}],
            "silence_ranges": [],
        },
        "edits": {"deleted_word_ranges": [], "deleted_silence_ranges": [], "splice_adjustments": {}, "settings": {}},
    }
    path = tmp_path / "drifted.vcg.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded, _ = load_editor_project(path)

    assert loaded.words == project.words
