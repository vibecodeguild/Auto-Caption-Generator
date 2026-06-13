from __future__ import annotations

from app.core.edit_decisions import EditDecisionList
from app.core.splice_generation import generate_splices
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord


def _project() -> TranscriptProject:
    words = [
        TranscriptWord("w1", " When", "When", 0.00, 0.30, 0, 8, 1),
        TranscriptWord("w2", " you", "you", 0.31, 0.55, 9, 16, 1),
        TranscriptWord("w3", " build", "build", 0.56, 0.92, 17, 28, 1),
        TranscriptWord("w4", " quickly", "quickly", 1.00, 1.34, 30, 40, 2),
        TranscriptWord("w5", " skip", "skip", 1.35, 1.70, 41, 51, 2),
        TranscriptWord("w6", " syntax", "syntax", 2.20, 2.62, 66, 79, 3),
        TranscriptWord("w7", " errors", "errors", 2.63, 3.00, 80, 90, 3),
    ]
    silence = [SilenceRange("s1", 1.71, 2.19, 52, 65)]
    return TranscriptProject(source="demo.mp4", fps=30.0, words=words, silence_ranges=silence)


def test_deleted_sentence_creates_dynamic_splice_between_surrounding_kept_ranges() -> None:
    edits = EditDecisionList()
    edits.delete_words("delete_sentence_2", "w4", "w5", reason="sentence")

    plan = generate_splices(_project(), edits)

    assert [(item.start_word_id, item.end_word_id) for item in plan.kept_ranges] == [
        ("w1", "w3"),
        ("w6", "w7"),
    ]
    assert len(plan.splices) == 1
    splice = plan.splices[0]
    assert splice.left_word_id == "w3"
    assert splice.right_word_id == "w6"
    assert splice.left_out_frame == 28
    assert splice.right_in_frame == 66
    assert splice.left_context == "...you build"
    assert splice.right_context == "syntax errors..."


def test_deleting_first_word_after_gap_moves_splice_to_next_kept_word() -> None:
    edits = EditDecisionList()
    edits.delete_words("delete_sentence_2", "w4", "w5", reason="sentence")
    edits.delete_words("delete_first_word_3", "w6", "w6", reason="word")

    plan = generate_splices(_project(), edits)

    assert [(item.start_word_id, item.end_word_id) for item in plan.kept_ranges] == [
        ("w1", "w3"),
        ("w7", "w7"),
    ]
    assert len(plan.splices) == 1
    assert plan.splices[0].left_word_id == "w3"
    assert plan.splices[0].right_word_id == "w7"
    assert plan.splices[0].right_in_frame == 80


def test_frame_adjustments_are_preserved_by_source_anchors() -> None:
    edits = EditDecisionList()
    edits.delete_words("delete_sentence_2", "w4", "w5", reason="sentence")
    first_plan = generate_splices(_project(), edits)
    first_splice = first_plan.splices[0]

    edits.adjust_splice(first_splice.anchor_key, left_out_delta=3, right_in_delta=-2)
    second_plan = generate_splices(_project(), edits)

    assert second_plan.splices[0].left_out_frame == 31
    assert second_plan.splices[0].right_in_frame == 64
    assert second_plan.splices[0].left_out_adjustment == 3
    assert second_plan.splices[0].right_in_adjustment == -2
    assert second_plan.kept_ranges[0].adjusted_end_frame == 31
    assert second_plan.kept_ranges[1].adjusted_start_frame == 64


def test_deleted_silence_creates_splice_between_adjacent_words() -> None:
    edits = EditDecisionList()
    edits.delete_silence("delete_dead_space", "s1")

    plan = generate_splices(_project(), edits)

    assert len(plan.splices) == 1
    assert plan.splices[0].left_word_id == "w5"
    assert plan.splices[0].right_word_id == "w6"
    assert plan.splices[0].left_out_frame == 51
    assert plan.splices[0].right_in_frame == 66
