from __future__ import annotations

from app.core.edit_decisions import EditDecisionList
from app.core.project_store import load_editor_project, save_editor_project
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord


def test_saves_and_loads_editor_project(tmp_path) -> None:
    project = TranscriptProject(
        source="source/raw.mp4",
        fps=30.0,
        words=[
            TranscriptWord("w1", " Hello", "Hello", 0.0, 0.5, 0, 15, 1),
            TranscriptWord("w2", " world", "world", 0.6, 1.0, 18, 30, 1),
        ],
        silence_ranges=[SilenceRange("s1", 0.51, 0.59, 16, 17)],
    )
    edits = EditDecisionList()
    edits.delete_words("delete_w2", "w2", "w2", reason="word")
    edits.adjust_splice("w1->w2", left_out_delta=2, right_in_delta=-1, reviewed=True)

    path = tmp_path / "editor.json"
    save_editor_project(path, project, edits)
    loaded_project, loaded_edits = load_editor_project(path)

    assert loaded_project == project
    assert loaded_edits.deleted_word_ranges == edits.deleted_word_ranges
    assert loaded_edits.deleted_silence_ranges == edits.deleted_silence_ranges
    assert loaded_edits.splice_adjustments["w1->w2"].left_out_delta == 2
    assert loaded_edits.splice_adjustments["w1->w2"].right_in_delta == -1
    assert loaded_edits.splice_adjustments["w1->w2"].reviewed is True
