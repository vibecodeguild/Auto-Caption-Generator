from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptWord:
    id: str
    raw: str
    text: str
    start: float
    end: float
    start_frame: int
    end_frame: int
    sentence_id: int


@dataclass(frozen=True)
class SilenceRange:
    id: str
    start: float
    end: float
    start_frame: int
    end_frame: int
    measured_start: float | None = None
    measured_end: float | None = None
    measured_start_frame: int | None = None
    measured_end_frame: int | None = None
    audio_analyzed: bool = False

    def effective_start(self) -> float:
        return self.measured_start if self.measured_start is not None else self.start

    def effective_end(self) -> float:
        return self.measured_end if self.measured_end is not None else self.end

    def effective_duration(self) -> float:
        return max(0.0, self.effective_end() - self.effective_start())


@dataclass(frozen=True)
class TranscriptProject:
    source: str
    fps: float
    words: list[TranscriptWord]
    silence_ranges: list[SilenceRange]

    def word_index(self, word_id: str) -> int:
        for index, word in enumerate(self.words):
            if word.id == word_id:
                return index
        raise ValueError(f"Unknown word id: {word_id}")

    def word_by_id(self, word_id: str) -> TranscriptWord:
        return self.words[self.word_index(word_id)]

    def silence_by_id(self, silence_id: str) -> SilenceRange:
        for silence in self.silence_ranges:
            if silence.id == silence_id:
                return silence
        raise ValueError(f"Unknown silence id: {silence_id}")
