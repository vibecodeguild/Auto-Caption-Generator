from __future__ import annotations

from pathlib import Path

from app.core.edit_decisions import EditDecisionList
from app.core.splice_generation import generate_splices
from app.core.transcript_history import build_edit_analysis, build_generation_metadata
from app.core.transcript_model import TranscriptProject, TranscriptWord


def test_generation_metadata_records_reproducible_source_and_runtime(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-content")

    metadata = build_generation_metadata(
        source,
        model_label="Large v3 - best accuracy",
        model_id="large-v3",
        compute_label="NVIDIA GPU",
        compute={"device": "cuda", "compute_type": "float16"},
        sequence_revision=3,
    )

    assert metadata["model_id"] == "large-v3"
    assert metadata["compute"] == {"device": "cuda", "compute_type": "float16"}
    assert metadata["sequence_revision"] == 3
    assert metadata["source"]["size_bytes"] == len(b"source-content")
    assert len(metadata["source"]["sha256"]) == 64


def test_edit_analysis_keeps_whisper_assisted_and_manual_boundaries_separate() -> None:
    project = TranscriptProject(
        source="source.mp4",
        fps=30.0,
        words=[
            TranscriptWord("w1", " I", "I", 0.0, 0.2, 0, 6, 1),
            TranscriptWord("w2", " can", "can", 0.2, 0.4, 7, 12, 1),
            TranscriptWord("w3", " retry", "retry", 0.5, 0.8, 15, 24, 1),
            TranscriptWord("w4", " ship", "ship", 1.2, 1.5, 36, 45, 2),
        ],
        silence_ranges=[],
        generation={"initial_repeated_word_ids": ["w1", "w2"]},
    )
    edits = EditDecisionList()
    edits.delete_word_selection("w2", "w3")
    edits.set_assisted_out_frame("w1->w4", 8)
    edits.set_assisted_in_frame("w1->w4", 40)
    edits.adjust_splice("w1->w4", left_out_delta=2, right_in_delta=3, reviewed=True)
    plan = generate_splices(project, edits)

    analysis = build_edit_analysis(project, edits, plan)

    splice = analysis["splices"][0]
    assert splice["left_whisper_out_frame"] == 6
    assert splice["left_suggested_out_frame"] == 8
    assert splice["left_final_out_frame"] == 10
    assert splice["right_whisper_in_frame"] == 36
    assert splice["right_suggested_in_frame"] == 40
    assert splice["right_final_in_frame"] == 43
    assert analysis["repetition_suggestions"]["suggested_words_later_deleted"] == ["w2"]
