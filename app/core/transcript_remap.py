from __future__ import annotations

from dataclasses import replace

from app.core.splice_generation import KeptRange
from app.core.transcript_model import TranscriptProject, TranscriptWord


def remap_transcript(project: TranscriptProject, kept_ranges: list[KeptRange]) -> TranscriptProject:
    output_words: list[TranscriptWord] = []
    output_cursor = 0
    for kept_range in kept_ranges:
        range_words = _words_in_range(project, kept_range)
        source_start = kept_range.adjusted_start_frame
        for word in range_words:
            start_frame = output_cursor + max(0, word.start_frame - source_start)
            end_frame = output_cursor + max(0, word.end_frame - source_start)
            output_words.append(
                replace(
                    word,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start=round(start_frame / project.fps, 3),
                    end=round(end_frame / project.fps, 3),
                )
            )
        output_cursor += max(0, kept_range.adjusted_end_frame - kept_range.adjusted_start_frame + 1)

    return TranscriptProject(
        source=project.source,
        fps=project.fps,
        words=output_words,
        silence_ranges=[],
    )


def _words_in_range(project: TranscriptProject, kept_range: KeptRange) -> list[TranscriptWord]:
    start = project.word_index(kept_range.start_word_id)
    end = project.word_index(kept_range.end_word_id)
    if end < start:
        start, end = end, start
    return project.words[start : end + 1]
