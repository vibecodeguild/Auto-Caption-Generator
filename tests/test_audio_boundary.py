from __future__ import annotations

import math
import wave
from array import array

import pytest
from app.core.audio_boundary import analyze_pause_candidates, suggest_word_end_boundaries
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord


def _write_tone_then_silence(
    path,
    *,
    tone_end: float,
    noise_amplitude: int = 0,
    duration: float = 1.0,
    sample_rate: int = 16000,
) -> None:
    samples = array("h")
    for index in range(round(duration * sample_rate)):
        time = index / sample_rate
        if 0.2 <= time < tone_end:
            value = int(9000 * math.sin(2 * math.pi * 220 * time))
        else:
            value = int(noise_amplitude * math.sin(2 * math.pi * 97 * time))
        samples.append(value)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(samples.tobytes())


def _project() -> TranscriptProject:
    return TranscriptProject(
        source="source.mp4",
        fps=30.0,
        words=[TranscriptWord("w1", " word", "word", 0.2, 0.5, 6, 15, 1)],
        silence_ranges=[],
    )


def test_extends_whisper_end_to_sustained_local_silence(tmp_path) -> None:
    audio_path = tmp_path / "tail.wav"
    _write_tone_then_silence(audio_path, tone_end=0.62)

    suggestions = suggest_word_end_boundaries(_project(), audio_path, {"w1"})

    assert _project().words[0].end_frame == 15
    assert suggestions == {"w1": 19}


def test_keeps_whisper_end_when_no_speech_continues_past_it(tmp_path) -> None:
    audio_path = tmp_path / "accurate.wav"
    _write_tone_then_silence(audio_path, tone_end=0.5)

    suggestions = suggest_word_end_boundaries(_project(), audio_path, {"w1"})

    assert suggestions == {"w1": None}


def test_steady_room_noise_does_not_extend_the_boundary(tmp_path) -> None:
    audio_path = tmp_path / "room-noise.wav"
    _write_tone_then_silence(audio_path, tone_end=0.5, noise_amplitude=700)

    suggestions = suggest_word_end_boundaries(_project(), audio_path, {"w1"})

    assert suggestions == {"w1": None}


def test_assisted_end_stays_before_the_next_word_frame(tmp_path) -> None:
    audio_path = tmp_path / "continuous.wav"
    _write_tone_then_silence(audio_path, tone_end=0.7)
    project = _project()
    project = TranscriptProject(
        source=project.source,
        fps=project.fps,
        words=project.words + [TranscriptWord("w2", " next", "next", 0.63, 0.8, 19, 24, 1)],
        silence_ranges=[],
    )

    suggestions = suggest_word_end_boundaries(project, audio_path, {"w1"})

    assert suggestions["w1"] is None or suggestions["w1"] < 19


def test_only_requested_cut_anchor_words_are_analyzed(tmp_path) -> None:
    audio_path = tmp_path / "targeted.wav"
    _write_tone_then_silence(audio_path, tone_end=0.62)
    project = _project()
    project = TranscriptProject(
        project.source,
        project.fps,
        project.words + [TranscriptWord("w2", " later", "later", 0.8, 0.9, 24, 27, 1)],
        [],
    )

    suggestions = suggest_word_end_boundaries(project, audio_path, {"w1"})

    assert set(suggestions) == {"w1"}


def test_pause_analysis_measures_only_threshold_candidates(tmp_path) -> None:
    audio_path = tmp_path / "pauses.wav"
    sample_rate = 16000
    samples = array("h")
    for index in range(round(3.0 * sample_rate)):
        time = index / sample_rate
        speaking = 0.2 <= time < 0.8 or 1.3 <= time < 1.6 or 1.9 <= time < 2.55
        samples.append(int(9000 * math.sin(2 * math.pi * 220 * time)) if speaking else 0)
    with wave.open(str(audio_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(samples.tobytes())

    project = TranscriptProject(
        source="source.mp4",
        fps=30.0,
        words=[],
        silence_ranges=[
            SilenceRange("candidate", 0.5, 1.5, 15, 44),
            SilenceRange("below-threshold", 1.6, 2.2, 48, 65),
        ],
    )

    analyzed, summary = analyze_pause_candidates(project, audio_path, minimum_seconds=0.8)

    candidate = analyzed.silence_by_id("candidate")
    below = analyzed.silence_by_id("below-threshold")
    assert candidate.audio_analyzed is True
    assert candidate.effective_start() == 0.8
    assert candidate.effective_end() == 1.3
    assert candidate.effective_duration() == pytest.approx(0.5)
    assert below.audio_analyzed is False
    assert summary == {
        "candidates_checked": 1,
        "validated_long_pauses": 0,
        "rejected_candidates": 1,
    }
