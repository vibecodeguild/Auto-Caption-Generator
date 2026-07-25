from __future__ import annotations

from app.core.repetition_detection import detect_repeated_word_ids
from app.core.transcript_model import TranscriptWord


def _words(
    text: list[str],
    *,
    spacing: float = 0.4,
    starts: list[float] | None = None,
) -> list[TranscriptWord]:
    return [
        TranscriptWord(
            id=f"w{index + 1}",
            raw=f" {word}",
            text=word,
            start=(starts[index] if starts else index * spacing),
            end=(starts[index] if starts else index * spacing) + 0.25,
            start_frame=round((starts[index] if starts else index * spacing) * 30),
            end_frame=round(((starts[index] if starts else index * spacing) + 0.25) * 30),
            sentence_id=1,
        )
        for index, word in enumerate(text)
    ]


def test_highlights_only_the_earlier_take_of_a_long_repeated_phrase() -> None:
    words = _words(["I", "know", "there", "are", "at", "least,", "I", "know", "there", "are", "at", "least", "a", "few"])

    repeated = detect_repeated_word_ids(words)

    assert repeated == {f"w{index}" for index in range(1, 7)}


def test_highlights_short_abandoned_fragment_only_when_restart_is_immediate() -> None:
    words = _words(
        ["I", "need", "a", "I", "need", "the", "website"],
        starts=[0.0, 0.25, 0.5, 1.4, 1.65, 1.9, 2.15],
    )

    repeated = detect_repeated_word_ids(words)

    assert repeated == {"w1", "w2", "w3"}


def test_highlights_only_the_first_immediate_repeated_pronoun() -> None:
    immediate = _words(["You", "you", "literally", "just"])
    separated = _words(["You", "can", "do", "what", "you", "want"])
    emphasis = _words(["very", "very", "important"])

    assert detect_repeated_word_ids(immediate) == {"w1"}
    assert detect_repeated_word_ids(separated) == set()
    assert detect_repeated_word_ids(emphasis) == set()


def test_does_not_highlight_normal_short_phrase_reuse_across_sentences() -> None:
    words = _words(
        [
            "solve", "a", "problem", "that", "you", "have", "because", "it's",
            "a", "problem", "that", "you", "understand",
        ]
    )

    assert detect_repeated_word_ids(words) == set()


def test_does_not_highlight_phrase_outside_close_window() -> None:
    words = _words(["I", "need", "this", "I", "need", "that"], spacing=5.0)

    assert detect_repeated_word_ids(words) == set()


def test_deleted_copy_is_not_reported_or_bridged() -> None:
    words = _words(["I", "know", "there", "are", "at", "least", "I", "know", "there", "are", "at", "least"])

    repeated = detect_repeated_word_ids(
        words,
        deleted_word_ids={"w1", "w2", "w3", "w4", "w5", "w6"},
    )

    assert repeated == set()
