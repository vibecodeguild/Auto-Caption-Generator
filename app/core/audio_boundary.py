from __future__ import annotations

import math
import wave
from array import array
from dataclasses import replace
from pathlib import Path

from app.core.transcript_model import SilenceRange, TranscriptProject


WINDOW_SECONDS = 0.01
MAX_EXTENSION_SECONDS = 0.35
MIN_SILENCE_SECONDS = 0.05
PEAK_LOOKBACK_SECONDS = 0.20
MIN_ACTIVE_DBFS = -50.0
NOISE_MARGIN_DB = 6.0


def analyze_pause_candidates(
    project: TranscriptProject,
    audio_path: Path,
    minimum_seconds: float,
) -> tuple[TranscriptProject, dict[str, int]]:
    """Measure only Whisper gaps that meet the configured long-pause threshold."""

    samples, sample_rate = _read_mono_pcm16(audio_path)
    levels = _window_dbfs(samples, max(1, round(sample_rate * WINDOW_SECONDS)))
    candidates = [
        silence
        for silence in project.silence_ranges
        if (silence.end_frame - silence.start_frame + 1) / project.fps >= minimum_seconds
    ]
    measured: list[SilenceRange] = []
    kept = 0
    rejected = 0
    candidate_ids = {silence.id for silence in candidates}

    for silence in project.silence_ranges:
        if silence.id not in candidate_ids:
            measured.append(silence)
            continue
        start, end = _measure_longest_silence(levels, silence.start, silence.end)
        start_frame = round(start * project.fps)
        end_frame = max(start_frame, round(end * project.fps) - 1)
        updated = replace(
            silence,
            measured_start=start,
            measured_end=end,
            measured_start_frame=start_frame,
            measured_end_frame=end_frame,
            audio_analyzed=True,
        )
        measured.append(updated)
        if (end_frame - start_frame + 1) / project.fps >= minimum_seconds:
            kept += 1
        else:
            rejected += 1

    return replace(project, silence_ranges=measured), {
        "candidates_checked": len(candidates),
        "validated_long_pauses": kept,
        "rejected_candidates": rejected,
    }


def _measure_longest_silence(levels: list[float], start: float, end: float) -> tuple[float, float]:
    start_index = max(0, round(start / WINDOW_SECONDS))
    end_index = min(len(levels), math.ceil(end / WINDOW_SECONDS))
    if start_index >= end_index:
        return start, start

    gap_levels = levels[start_index:end_index]
    sorted_levels = sorted(gap_levels)
    noise_floor = sorted_levels[max(0, round((len(sorted_levels) - 1) * 0.2))]
    context_start = max(0, start_index - round(PEAK_LOOKBACK_SECONDS / WINDOW_SECONDS))
    context_end = min(len(levels), end_index + round(PEAK_LOOKBACK_SECONDS / WINDOW_SECONDS))
    speech_peak = max(levels[context_start:context_end], default=MIN_ACTIVE_DBFS)
    active_threshold = max(MIN_ACTIVE_DBFS, speech_peak - 30.0, noise_floor + NOISE_MARGIN_DB)

    best_start = start_index
    best_end = start_index
    run_start: int | None = None
    for index in range(start_index, end_index + 1):
        quiet = index < end_index and levels[index] < active_threshold
        if quiet and run_start is None:
            run_start = index
        if not quiet and run_start is not None:
            if index - run_start > best_end - best_start:
                best_start, best_end = run_start, index
            run_start = None

    if (best_end - best_start) * WINDOW_SECONDS < MIN_SILENCE_SECONDS:
        return start, start
    return best_start * WINDOW_SECONDS, best_end * WINDOW_SECONDS


def suggest_word_end_boundaries(
    project: TranscriptProject,
    audio_path: Path,
    word_ids: set[str],
) -> dict[str, int | None]:
    """Suggest extended ends for only the requested splice-anchor words.

    The Whisper timestamp remains untouched. An assisted boundary is only
    stored when local audio provides evidence that speech continues beyond it.
    """

    samples, sample_rate = _read_mono_pcm16(audio_path)
    window_size = max(1, round(sample_rate * WINDOW_SECONDS))
    levels = _window_dbfs(samples, window_size)
    if not levels:
        return {word_id: None for word_id in word_ids}

    suggestions: dict[str, int | None] = {}
    for index, word in enumerate(project.words):
        if word.id not in word_ids:
            continue
        next_start = project.words[index + 1].start if index + 1 < len(project.words) else None
        assisted_seconds = _assisted_end_seconds(
            levels,
            whisper_end=word.end,
            word_start=word.start,
            next_word_start=next_start,
        )
        assisted_frame = round(assisted_seconds * project.fps)
        if next_start is not None:
            assisted_frame = min(assisted_frame, round(next_start * project.fps) - 1)
        if assisted_frame <= word.end_frame:
            assisted_frame = None
        suggestions[word.id] = assisted_frame

    return {word_id: suggestions.get(word_id) for word_id in word_ids}


def _assisted_end_seconds(
    levels: list[float],
    *,
    whisper_end: float,
    word_start: float,
    next_word_start: float | None,
) -> float:
    start_index = max(0, round(whisper_end / WINDOW_SECONDS))
    max_end = whisper_end + MAX_EXTENSION_SECONDS
    if next_word_start is not None:
        max_end = min(max_end, next_word_start)
    end_index = min(len(levels), math.ceil(max_end / WINDOW_SECONDS))
    if start_index >= end_index:
        return whisper_end

    lookback_start = max(0, round(max(word_start, whisper_end - PEAK_LOOKBACK_SECONDS) / WINDOW_SECONDS))
    local_peak = max(levels[lookback_start:max(start_index + 1, lookback_start + 1)], default=MIN_ACTIVE_DBFS)
    analysis_levels = sorted(levels[start_index:end_index])
    noise_floor = analysis_levels[max(0, round((len(analysis_levels) - 1) * 0.2))]
    active_threshold = max(MIN_ACTIVE_DBFS, local_peak - 30.0, noise_floor + NOISE_MARGIN_DB)
    silence_windows = max(1, math.ceil(MIN_SILENCE_SECONDS / WINDOW_SECONDS))

    last_active_index: int | None = None
    quiet_run = 0
    for index in range(start_index, end_index):
        if levels[index] >= active_threshold:
            last_active_index = index
            quiet_run = 0
            continue
        quiet_run += 1
        if last_active_index is not None and quiet_run >= silence_windows:
            return max(whisper_end, (last_active_index + 1) * WINDOW_SECONDS)

    if last_active_index is None:
        return whisper_end
    return max(whisper_end, (last_active_index + 1) * WINDOW_SECONDS)


def _read_mono_pcm16(path: Path) -> tuple[array, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Audio Boundary Assist requires mono 16-bit PCM audio.")
        sample_rate = source.getframerate()
        samples = array("h")
        samples.frombytes(source.readframes(source.getnframes()))
    return samples, sample_rate


def _window_dbfs(samples: array, window_size: int) -> list[float]:
    levels: list[float] = []
    for start in range(0, len(samples), window_size):
        window = samples[start : start + window_size]
        if not window:
            continue
        mean_square = sum(sample * sample for sample in window) / len(window)
        if mean_square <= 0:
            levels.append(-96.0)
            continue
        rms = math.sqrt(mean_square)
        levels.append(20.0 * math.log10(rms / 32768.0))
    return levels
