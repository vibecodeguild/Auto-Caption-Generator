from __future__ import annotations

from app.core.settings import CaptionGroup, WordTimestamp


def normalize_words(words: list[WordTimestamp]) -> list[WordTimestamp]:
    normalized = []
    for word in words:
        text = word.text.strip()
        if not text:
            continue
        if word.end <= word.start:
            continue
        normalized.append(WordTimestamp(text=text, start=float(word.start), end=float(word.end)))
    return normalized


def group_words(
    words: list[WordTimestamp],
    max_words: int,
    max_duration: float,
    max_chars: int,
) -> list[CaptionGroup]:
    groups: list[CaptionGroup] = []
    current: list[WordTimestamp] = []

    for word in normalize_words(words):
        if not current:
            current.append(word)
            continue

        proposed = current + [word]
        proposed_text = " ".join(item.text for item in proposed)
        proposed_duration = proposed[-1].end - proposed[0].start

        should_break = (
            len(proposed) > max_words
            or proposed_duration > max_duration
            or len(proposed_text) > max_chars
            or current[-1].text.endswith((".", "?", "!"))
        )

        if should_break:
            groups.append(CaptionGroup(words=current))
            current = [word]
        else:
            current.append(word)

    if current:
        groups.append(CaptionGroup(words=current))

    return groups
