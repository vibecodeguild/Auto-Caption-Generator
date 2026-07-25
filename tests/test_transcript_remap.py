from __future__ import annotations

from app.core.splice_generation import KeptRange
from app.core.transcript_model import TranscriptProject, TranscriptWord
from app.core.transcript_remap import remap_transcript


def _project() -> TranscriptProject:
    return TranscriptProject(
        source="demo.mp4",
        fps=30.0,
        silence_ranges=[],
        words=[
            TranscriptWord("w1", " Build", "Build", 0.0, 0.4, 0, 12, 1),
            TranscriptWord("w2", " fast", "fast", 0.5, 0.9, 15, 27, 1),
            TranscriptWord("w3", " remove", "remove", 1.5, 2.0, 45, 60, 2),
            TranscriptWord("w4", " friction", "friction", 2.1, 2.6, 63, 78, 3),
        ],
    )


def test_remaps_kept_words_to_cut_timeline() -> None:
    kept_ranges = [
        KeptRange("keep_001", "w1", "w2", 0, 27, 0, 27),
        KeptRange("keep_002", "w4", "w4", 63, 78, 63, 78),
    ]

    remapped = remap_transcript(_project(), kept_ranges)

    assert [(word.id, word.start_frame, word.end_frame) for word in remapped.words] == [
        ("w1", 0, 12),
        ("w2", 15, 27),
        ("w4", 28, 43),
    ]
    assert [(word.id, word.start, word.end) for word in remapped.words] == [
        ("w1", 0.0, 0.4),
        ("w2", 0.5, 0.9),
        ("w4", 0.933, 1.433),
    ]


def test_uses_adjusted_range_edges_when_remapping() -> None:
    kept_ranges = [
        KeptRange("keep_001", "w1", "w2", 0, 27, 0, 30),
        KeptRange("keep_002", "w4", "w4", 63, 78, 60, 80),
    ]

    remapped = remap_transcript(_project(), kept_ranges)

    assert remapped.words[-1].start_frame == 34
    assert remapped.words[-1].end_frame == 49


def test_manual_split_does_not_duplicate_a_word_and_clips_it_to_the_kept_side() -> None:
    kept_ranges = [
        KeptRange("keep_left", "w1", "w2", 0, 27, 0, 22),
        KeptRange("keep_right", "w2", "w4", 15, 78, 26, 78),
    ]

    remapped = remap_transcript(_project(), kept_ranges)

    fast = [word for word in remapped.words if word.id == "w2"]
    assert len(fast) == 1
    assert (fast[0].start_frame, fast[0].end_frame) == (15, 22)
