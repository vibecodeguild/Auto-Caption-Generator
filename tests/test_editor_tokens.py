from __future__ import annotations

from app.core.editor_tokens import token_ids_between, transcript_tokens
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord


def _project() -> TranscriptProject:
    return TranscriptProject(
        source="demo.mp4",
        fps=30.0,
        words=[
            TranscriptWord("w1", " Hello", "Hello", 0.0, 0.4, 0, 12, 1),
            TranscriptWord("w2", " there", "there", 0.5, 0.9, 15, 27, 1),
            TranscriptWord("w3", " Build", "Build", 2.0, 2.4, 60, 72, 2),
            TranscriptWord("w4", " fast", "fast", 2.5, 3.0, 75, 90, 2),
        ],
        silence_ranges=[
            SilenceRange("s1", 0.933, 1.967, 28, 59),
        ],
    )


def test_transcript_tokens_merge_words_and_silence_in_frame_order() -> None:
    tokens = transcript_tokens(_project())

    assert [(token.id, token.kind) for token in tokens] == [
        ("w1", "word"),
        ("w2", "word"),
        ("s1", "silence"),
        ("w3", "word"),
        ("w4", "word"),
    ]


def test_token_ids_between_selects_words_and_silence_as_one_stream() -> None:
    tokens = transcript_tokens(_project())

    selected = token_ids_between(tokens, "w2", "w4")

    assert selected == ["w2", "s1", "w3", "w4"]
