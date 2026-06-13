from __future__ import annotations

from app.core.edit_decisions import EditDecisionList


def test_delete_selected_words_adds_single_range() -> None:
    edits = EditDecisionList()

    edits.delete_word_selection("w000002", "w000005")

    assert len(edits.deleted_word_ranges) == 1
    deleted = edits.deleted_word_ranges[0]
    assert deleted.start_word_id == "w000002"
    assert deleted.end_word_id == "w000005"
    assert deleted.reason == "selection"


def test_restore_selected_words_removes_overlapping_deleted_ranges() -> None:
    edits = EditDecisionList()
    edits.delete_words("delete_one", "w000002", "w000005", reason="selection")
    edits.delete_words("delete_two", "w000008", "w000010", reason="selection")

    edits.restore_word_selection("w000004", "w000009")

    assert [(item.start_word_id, item.end_word_id) for item in edits.deleted_word_ranges] == []


def test_restore_selected_silence_removes_deleted_silence() -> None:
    edits = EditDecisionList()
    edits.delete_silence("delete_s1", "s1")

    edits.restore_silence("s1")

    assert edits.deleted_silence_ranges == []
