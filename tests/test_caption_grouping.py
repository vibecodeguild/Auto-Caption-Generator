from app.core.caption_grouping import group_words
from app.core.settings import WordTimestamp


def word(text, start, end):
    return WordTimestamp(text=text, start=start, end=end)


def test_group_words_respects_max_words():
    groups = group_words(
        [
            word("I", 0.0, 0.1),
            word("built", 0.1, 0.3),
            word("this", 0.3, 0.5),
            word("tool", 0.5, 0.8),
        ],
        max_words=2,
        max_duration=10.0,
        max_chars=100,
    )

    assert [group.text for group in groups] == ["I built", "this tool"]
    assert groups[0].start == 0.0
    assert groups[0].end == 0.3


def test_group_words_respects_max_duration_without_changing_timestamps():
    groups = group_words(
        [
            word("one", 0.0, 0.4),
            word("two", 0.4, 1.0),
            word("three", 1.0, 1.7),
        ],
        max_words=10,
        max_duration=1.0,
        max_chars=100,
    )

    assert [group.text for group in groups] == ["one two", "three"]
    assert groups[1].start == 1.0
    assert groups[1].end == 1.7


def test_group_words_breaks_after_sentence_punctuation():
    groups = group_words(
        [
            word("Done.", 0.0, 0.5),
            word("Next", 0.5, 0.9),
            word("thing", 0.9, 1.2),
        ],
        max_words=10,
        max_duration=10.0,
        max_chars=100,
    )

    assert [group.text for group in groups] == ["Done.", "Next thing"]


def test_group_words_filters_invalid_words():
    groups = group_words(
        [
            word("", 0.0, 0.1),
            word("bad", 0.5, 0.4),
            word("good", 0.6, 0.9),
        ],
        max_words=3,
        max_duration=2.0,
        max_chars=20,
    )

    assert [group.text for group in groups] == ["good"]
