from __future__ import annotations

from app.core.transcript_model import TranscriptWord


MAX_REPEAT_GAP_SECONDS = 12.0
MAX_REPEAT_DISTANCE_WORDS = 40
MAX_REPEAT_LENGTH_WORDS = 16
MIN_LONG_REPEAT_WORDS = 6
MAX_SHORT_RESTART_SECONDS = 3.0
MAX_SHORT_RESTART_WORDS = 6
UTTERANCE_GAP_SECONDS = 0.35
SINGLE_WORD_RESTARTS = {"i", "you", "we", "they", "he", "she", "it"}


def detect_repeated_word_ids(
    words: list[TranscriptWord],
    deleted_word_ids: set[str] | None = None,
) -> set[str]:
    """Find likely earlier takes that are restated shortly afterward."""
    deleted = deleted_word_ids or set()
    normalized = [_normalize_word(word.text) for word in words]
    repeated: set[str] = set()

    for first_index, first_word in enumerate(words):
        if first_word.id in deleted or not normalized[first_index]:
            continue

        last_second_index = min(len(words), first_index + MAX_REPEAT_DISTANCE_WORDS + 1)
        for second_index in range(first_index + 1, last_second_index):
            second_word = words[second_index]
            if second_word.start - first_word.start > MAX_REPEAT_GAP_SECONDS:
                break
            if second_word.id in deleted or normalized[first_index] != normalized[second_index]:
                continue

            max_match_length = min(
                MAX_REPEAT_LENGTH_WORDS,
                second_index - first_index,
                len(words) - second_index,
            )
            match_length = 0
            while match_length < max_match_length:
                first_match = words[first_index + match_length]
                second_match = words[second_index + match_length]
                if first_match.id in deleted or second_match.id in deleted:
                    break
                if normalized[first_index + match_length] != normalized[second_index + match_length]:
                    break
                match_length += 1

            is_suffix_of_longer_match = (
                first_index > 0
                and second_index > 0
                and words[first_index - 1].id not in deleted
                and words[second_index - 1].id not in deleted
                and normalized[first_index - 1] == normalized[second_index - 1]
            )

            if match_length >= MIN_LONG_REPEAT_WORDS:
                if is_suffix_of_longer_match:
                    continue
                repeated.update(
                    _earlier_take_ids(
                        words,
                        first_index,
                        second_index,
                        match_length,
                        deleted,
                    )
                )
                continue

            is_short_restart = (
                match_length >= 2
                and second_index - first_index <= MAX_SHORT_RESTART_WORDS
                and second_word.start - first_word.start <= MAX_SHORT_RESTART_SECONDS
                and _is_utterance_start(words, first_index)
                and _is_utterance_start(words, second_index)
            )
            if is_short_restart:
                repeated.update(
                    word.id
                    for word in words[first_index:second_index]
                    if word.id not in deleted
                )
                continue

            is_immediate_pronoun_restart = (
                match_length == 1
                and second_index == first_index + 1
                and normalized[first_index] in SINGLE_WORD_RESTARTS
            )
            if is_immediate_pronoun_restart:
                repeated.add(first_word.id)

    return repeated


def _normalize_word(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum() or character == "'")


def _is_utterance_start(words: list[TranscriptWord], index: int) -> bool:
    if index == 0:
        return True
    previous = words[index - 1]
    current = words[index]
    return (
        previous.sentence_id != current.sentence_id
        or current.start - previous.end >= UTTERANCE_GAP_SECONDS
    )


def _earlier_take_ids(
    words: list[TranscriptWord],
    first_index: int,
    second_index: int,
    match_length: int,
    deleted_word_ids: set[str],
) -> set[str]:
    sentence_ids = {
        words[first_index + offset].sentence_id
        for offset in range(match_length)
    }
    start = first_index
    while (
        start > 0
        and words[start - 1].id not in deleted_word_ids
        and words[start - 1].sentence_id in sentence_ids
    ):
        start -= 1

    end = first_index + match_length
    while (
        end < second_index
        and words[end].id not in deleted_word_ids
        and words[end].sentence_id in sentence_ids
    ):
        end += 1

    return {
        word.id
        for word in words[start:end]
        if word.id not in deleted_word_ids
    }
