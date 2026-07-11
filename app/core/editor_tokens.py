from __future__ import annotations

from dataclasses import dataclass

from app.core.transcript_model import TranscriptProject


@dataclass(frozen=True)
class EditorToken:
    id: str
    kind: str
    start_frame: int
    end_frame: int


def transcript_tokens(project: TranscriptProject, min_silence_seconds: float = 0.0) -> list[EditorToken]:
    tokens: list[EditorToken] = []
    tokens.extend(
        EditorToken(
            id=word.id,
            kind="word",
            start_frame=word.start_frame,
            end_frame=word.end_frame,
        )
        for word in project.words
    )
    tokens.extend(
        EditorToken(
            id=silence.id,
            kind="silence",
            start_frame=silence.start_frame,
            end_frame=silence.end_frame,
        )
        for silence in project.silence_ranges
        if silence.effective_duration() >= min_silence_seconds
    )
    return sorted(tokens, key=lambda token: (token.start_frame, token.end_frame))


def token_ids_between(tokens: list[EditorToken], start_token_id: str, end_token_id: str) -> list[str]:
    indexes = {token.id: index for index, token in enumerate(tokens)}
    start = indexes[start_token_id]
    end = indexes[end_token_id]
    if end < start:
        start, end = end, start
    return [token.id for token in tokens[start : end + 1]]
