from __future__ import annotations

from dataclasses import replace

from app.core.splice_generation import KeptRange
from app.core.transcript_model import TranscriptProject, TranscriptWord


def remap_transcript(project: TranscriptProject, kept_ranges: list[KeptRange]) -> TranscriptProject:
    output_words: list[TranscriptWord] = []
    emitted_word_ids: set[str] = set()
    output_cursor = 0
    for kept_range in kept_ranges:
        source_start = kept_range.adjusted_start_frame
        source_end = kept_range.adjusted_end_frame
        for word in project.words:
            midpoint = (word.start_frame + word.end_frame) // 2
            if word.id in emitted_word_ids or not source_start <= midpoint <= source_end:
                continue
            clipped_start = max(source_start, word.start_frame)
            clipped_end = min(source_end, word.end_frame)
            start_frame = output_cursor + clipped_start - source_start
            end_frame = output_cursor + clipped_end - source_start
            output_words.append(
                replace(
                    word,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start=round(start_frame / project.fps, 3),
                    end=round(end_frame / project.fps, 3),
                )
            )
            emitted_word_ids.add(word.id)
        output_cursor += max(0, kept_range.adjusted_end_frame - kept_range.adjusted_start_frame + 1)

    return TranscriptProject(
        source=project.source,
        fps=project.fps,
        words=output_words,
        silence_ranges=[],
        generation=project.generation,
    )
