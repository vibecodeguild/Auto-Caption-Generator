from __future__ import annotations

import json
from pathlib import Path

from app.core.masterbeater import (
    BEAT_TYPES,
    LEDGER_FILENAME,
    OUTPUT_FILENAME,
    REVIEWED_FILENAME,
    canonicalize_word_id,
    extract_words,
    load_masterbeater_ledger,
    load_masterbeater_output,
    load_masterbeater_reviewed,
    normalize_masterbeater_result,
    resolve_word_span,
    resolve_word_span_from_seconds,
    save_masterbeater_edits_for_video_project,
    write_masterbeater_output,
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
    assert words[0]["sentenceId"] == 0


def test_extract_words_includes_sentence_id() -> None:
    document = _sample_document()
    document["project"]["words"][0]["sentence_id"] = 1
    document["project"]["words"][1]["sentence_id"] = 1
    document["project"]["words"][2]["sentence_id"] = 2
    document["project"]["words"][3]["sentence_id"] = 2
    words = extract_words(document)
    assert [word["sentenceId"] for word in words] == [1, 1, 2, 2]


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


def test_save_masterbeater_edits_writes_reviewed_not_original(tmp_path: Path) -> None:
    """Human trims endWordId; auto-save updates reviewed + ledger; original stays put."""
    root = tmp_path / "project"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    transcript = root / "final-transcript.json"
    document = _sample_document()
    transcript.write_text(json.dumps(document), encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = {
        "paths": {
            "finalTranscript": "final-transcript.json",
            "lockedCut": "locked.mp4",
            "sourceVideo": "source.mp4",
        }
    }
    # Original agent suggestion: full span including PowerPoint (w4).
    prior = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w4",
                    "rationale": "Cold open.",
                }
            ],
        },
        project_root=root,
        transcript_path=transcript,
        document=document,
    )
    write_masterbeater_output(root, prior)
    original_before = json.loads((root / OUTPUT_FILENAME).read_text(encoding="utf-8"))

    saved = save_masterbeater_edits_for_video_project(
        manifest_path,
        manifest,
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w3",
                    "rationale": "Cold open.",
                }
            ],
            "edit": {
                "op": "removeWord",
                "beatId": "b1",
                "wordId": "w4",
                "wordText": "PowerPoint",
            },
        },
    )
    assert saved["ok"] is True
    assert saved["edited"] is True
    assert saved["role"] == "reviewed"
    assert saved["beatCount"] == 1
    beat = saved["beats"][0]
    assert beat["endWordId"] == "w3"
    assert beat["wordsText"] == "Soul-crushing jobs in"
    assert beat["endFrame"] == 32

    # Original agent file is unchanged.
    original_after = json.loads((root / OUTPUT_FILENAME).read_text(encoding="utf-8"))
    assert original_after["beats"][0]["endWordId"] == "w4"
    assert original_after == original_before
    assert load_masterbeater_output(root)["beats"][0]["endWordId"] == "w4"

    # Working copy holds the edit.
    assert (root / REVIEWED_FILENAME).is_file()
    reviewed = load_masterbeater_reviewed(root)
    assert reviewed is not None
    assert reviewed["beats"][0]["endWordId"] == "w3"

    # Ledger records the membership change for process refinement.
    assert (root / LEDGER_FILENAME).is_file()
    ledger = load_masterbeater_ledger(root)
    assert ledger["entryCount"] == 1
    entry = ledger["entries"][0]
    assert entry["op"] == "removeWord"
    assert entry["wordText"] == "PowerPoint"
    assert entry["before"]["endWordId"] == "w4"
    assert entry["after"]["endWordId"] == "w3"


def test_save_masterbeater_manual_first_without_agent_run(tmp_path: Path) -> None:
    """Human can author Stage 1 without running Masterbeater; first save seeds baseline."""
    root = tmp_path / "project"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    transcript = root / "final-transcript.json"
    document = _sample_document()
    transcript.write_text(json.dumps(document), encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = {
        "paths": {
            "finalTranscript": "final-transcript.json",
            "lockedCut": "locked.mp4",
            "sourceVideo": "source.mp4",
        }
    }
    assert load_masterbeater_output(root) is None

    first = save_masterbeater_edits_for_video_project(
        manifest_path,
        manifest,
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b-manual-1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w2",
                    "rationale": "Human placed.",
                }
            ],
            "edit": {
                "op": "addBeat",
                "beatId": "b-manual-1",
                "wordText": "Soul-crushing jobs",
            },
        },
    )
    assert first["ok"] is True
    assert first["seededManualBaseline"] is True
    assert first["manualSeed"] is True
    assert first["beatCount"] == 1
    assert (root / OUTPUT_FILENAME).is_file()
    assert (root / REVIEWED_FILENAME).is_file()
    original = load_masterbeater_output(root)
    assert original is not None
    assert original["agent"] == "masterbeater-manual"
    assert original["manualSeed"] is True
    assert original["beats"][0]["endWordId"] == "w2"
    original_before = json.loads((root / OUTPUT_FILENAME).read_text(encoding="utf-8"))

    # Second edit extends the beat; baseline original stays frozen.
    second = save_masterbeater_edits_for_video_project(
        manifest_path,
        manifest,
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b-manual-1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w4",
                    "rationale": "Human placed.",
                }
            ],
            "edit": {
                "op": "addWord",
                "beatId": "b-manual-1",
                "wordId": "w4",
            },
        },
    )
    assert second["ok"] is True
    assert second.get("seededManualBaseline") is False
    assert second["beats"][0]["endWordId"] == "w4"
    original_after = json.loads((root / OUTPUT_FILENAME).read_text(encoding="utf-8"))
    assert original_after == original_before
    reviewed = load_masterbeater_reviewed(root)
    assert reviewed is not None
    assert reviewed["beats"][0]["endWordId"] == "w4"
    ledger = load_masterbeater_ledger(root)
    assert ledger["entryCount"] == 2


def test_normalize_sorts_beats_by_transcript_timeline() -> None:
    """Split/merge used to append siblings at array end — store in time order."""
    document = _sample_document()
    result = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "late",
                    "beatType": "context",
                    "startWordId": "w3",
                    "endWordId": "w4",
                    "rationale": "Later speech.",
                },
                {
                    "id": "early",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w2",
                    "rationale": "Earlier speech.",
                },
            ],
        },
        project_root=Path("."),
        transcript_path=Path("t.json"),
        document=document,
    )
    ids = [b["id"] for b in result["beats"]]
    assert ids == ["early", "late"]
    assert result["beats"][0]["startFrame"] <= result["beats"][1]["startFrame"]


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
