from __future__ import annotations

import json
from pathlib import Path

from app.core.masterbeater import (
    BEAT_TYPES,
    canonicalize_word_id,
    extract_words,
    normalize_masterbeater_result,
    resolve_word_span,
    resolve_word_span_from_seconds,
)


def _sample_document() -> dict:
    return {
        "project": {
            "fps": 30,
            "words": [
                {
                    "id": "w1",
                    "text": "Soul-crushing",
                    "start": 0.0,
                    "end": 0.5,
                    "start_frame": 0,
                    "end_frame": 14,
                },
                {
                    "id": "w2",
                    "text": "jobs",
                    "start": 0.5,
                    "end": 0.9,
                    "start_frame": 15,
                    "end_frame": 26,
                },
                {
                    "id": "w3",
                    "text": "in",
                    "start": 1.0,
                    "end": 1.1,
                    "start_frame": 30,
                    "end_frame": 32,
                },
                {
                    "id": "w4",
                    "text": "PowerPoint",
                    "start": 1.2,
                    "end": 1.8,
                    "start_frame": 36,
                    "end_frame": 53,
                },
            ],
        }
    }


def test_extract_words_frame_first() -> None:
    words = extract_words(_sample_document())
    assert len(words) == 4
    assert words[0]["id"] == "w1"
    assert words[0]["startFrame"] == 0
    assert words[0]["endFrameExclusive"] == 15


def test_resolve_word_span_builds_frames_and_text() -> None:
    words = extract_words(_sample_document())
    resolved = resolve_word_span(words, start_word_id="w1", end_word_id="w2")
    assert resolved is not None
    assert resolved["wordsText"] == "Soul-crushing jobs"
    assert resolved["startFrame"] == 0
    assert resolved["endFrame"] == 26
    assert resolved["endFrameExclusive"] == 27
    assert resolved["wordIds"] == ["w1", "w2"]


def test_normalize_binds_word_ids_to_frames(tmp_path: Path) -> None:
    document = _sample_document()
    transcript = tmp_path / "final-transcript.json"
    transcript.write_text(json.dumps(document), encoding="utf-8")
    payload = {
        "mode": "tutorial",
        "beats": [
            {
                "id": "b1",
                "beatType": "hook",
                "startWordId": "w1",
                "endWordId": "w4",
                "span": "Corporate PowerPoint pain",
                "rationale": "Cold open.",
            },
            {
                "id": "b2",
                "beatType": "source-led-motion",
                "startWordId": "w1",
                "endWordId": "w2",
                "rationale": "should drop",
            },
        ],
    }
    result = normalize_masterbeater_result(
        payload,
        project_root=tmp_path,
        transcript_path=transcript,
        document=document,
    )
    assert result["timingAuthority"] == "frames"
    assert result["beatCount"] == 1
    beat = result["beats"][0]
    assert beat["beatType"] == "hook"
    assert beat["wordsText"] == "Soul-crushing jobs in PowerPoint"
    assert beat["startFrame"] == 0
    assert beat["endFrameExclusive"] == 54
    assert beat["startWordId"] == "w1"
    assert beat["endWordId"] == "w4"
    assert beat["startSec"] == 0.0
    assert set(BEAT_TYPES) >= {beat["beatType"]}


def test_canonicalize_word_id_variants() -> None:
    words = extract_words(
        {
            "project": {
                "fps": 30,
                "words": [
                    {
                        "id": "w000001",
                        "text": "If",
                        "start_frame": 0,
                        "end_frame": 8,
                        "start": 0.0,
                        "end": 0.2,
                    },
                    {
                        "id": "w000024",
                        "text": "later",
                        "start_frame": 100,
                        "end_frame": 110,
                        "start": 3.0,
                        "end": 3.5,
                    },
                ],
            }
        }
    )
    assert canonicalize_word_id("w000001", words) == "w000001"
    assert canonicalize_word_id("w1", words) == "w000001"
    assert canonicalize_word_id("W000001", words) == "w000001"
    assert canonicalize_word_id("1", words) == "w000001"
    assert canonicalize_word_id("w24", words) == "w000024"


def test_legacy_seconds_fallback_maps_to_words(tmp_path: Path) -> None:
    document = _sample_document()
    words = extract_words(document)
    resolved = resolve_word_span_from_seconds(words, start_sec=0.0, end_sec=1.0)
    assert resolved is not None
    assert resolved["startWordId"] == "w1"
    assert "jobs" in resolved["wordsText"]

    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps(document), encoding="utf-8")
    result = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "legacy",
                    "beatType": "punchline",
                    "startSec": 1.0,
                    "endSec": 2.0,
                    "rationale": "Legacy time-only beat.",
                }
            ],
        },
        project_root=tmp_path,
        transcript_path=transcript,
        document=document,
    )
    assert result["beatCount"] == 1
    assert result["beats"][0]["startFrame"] is not None
    assert result["beats"][0]["wordsText"]
