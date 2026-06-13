from __future__ import annotations

from app.core.transcriber import words_to_transcript_project
from app.core.settings import WordTimestamp


def test_converts_words_to_transcript_project_with_sentences_and_silence() -> None:
    words = [
        WordTimestamp(text="Hello", start=0.0, end=0.5),
        WordTimestamp(text="world.", start=0.6, end=1.0),
        WordTimestamp(text="Build", start=2.0, end=2.4),
        WordTimestamp(text="fast", start=2.5, end=3.0),
    ]

    project = words_to_transcript_project("source.mp4", words, fps=30.0)

    assert [(word.id, word.text, word.start_frame, word.end_frame, word.sentence_id) for word in project.words] == [
        ("w000001", "Hello", 0, 15, 1),
        ("w000002", "world.", 18, 30, 1),
        ("w000003", "Build", 60, 72, 2),
        ("w000004", "fast", 75, 90, 2),
    ]
    assert len(project.silence_ranges) == 1
    assert project.silence_ranges[0].start_frame == 31
    assert project.silence_ranges[0].end_frame == 59
