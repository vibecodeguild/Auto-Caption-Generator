"""Stage 4 program edit list: legal T, program clock, mute, transcript markers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.masterbeater import normalize_masterbeater_result, write_masterbeater_output
from app.core.program_edits import (
    build_program_concat_filter,
    build_program_timeline,
    build_program_transcript,
    cut_end_frame_exclusive,
    is_legal_t_frame,
    legal_slots,
    save_program_edits,
    shift_aroll_word,
)
from app.core.settings import WordTimestamp


def _beats_doc() -> dict:
    return {
        "project": {
            "fps": 30,
            "words": [
                {
                    "id": "w1",
                    "text": "Hello",
                    "start": 0.0,
                    "end": 0.3,
                    "start_frame": 0,
                    "end_frame": 9,
                },
                {
                    "id": "w2",
                    "text": "world",
                    "start": 0.3,
                    "end": 0.6,
                    "start_frame": 9,
                    "end_frame": 18,
                },
                {
                    "id": "w3",
                    "text": "later",
                    "start": 2.0,
                    "end": 2.3,
                    "start_frame": 60,
                    "end_frame": 69,
                },
            ],
        }
    }


def test_legal_t_rejects_strictly_inside_beat() -> None:
    spans = [(0, 30), (60, 90)]
    cut_end = 120
    assert is_legal_t_frame(0, spans, cut_end)
    assert is_legal_t_frame(30, spans, cut_end)
    assert is_legal_t_frame(45, spans, cut_end)
    assert is_legal_t_frame(60, spans, cut_end)
    assert is_legal_t_frame(90, spans, cut_end)
    assert is_legal_t_frame(120, spans, cut_end)
    assert not is_legal_t_frame(15, spans, cut_end)
    assert not is_legal_t_frame(61, spans, cut_end)
    assert not is_legal_t_frame(-1, spans, cut_end)
    assert not is_legal_t_frame(121, spans, cut_end)


def test_legal_slots_include_zero_length_between_adjacent_beats() -> None:
    slots = legal_slots([(0, 30), (30, 60)], cut_end=90)
    assert {"startFrame": 30, "endFrameExclusive": 30} in slots
    assert slots[0] == {"startFrame": 0, "endFrameExclusive": 0}
    assert slots[-1] == {"startFrame": 60, "endFrameExclusive": 90}


def test_save_rejects_t_inside_beat(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside a beat"):
        save_program_edits(
            tmp_path,
            [{"tFrame": 10, "videoAssetId": "clip-a", "displayName": "A.mp4"}],
            spans=[(0, 30)],
            cut_end=90,
            probe_clip=False,
        )


def test_save_keeps_trimmed_clip_duration(tmp_path: Path) -> None:
    doc = save_program_edits(
        tmp_path,
        [
            {
                "tFrame": 30,
                "videoAssetId": "clip-a",
                "clipStartSec": 0.0,
                "durationSec": 5.0,
                "displayName": "A.mp4",
            }
        ],
        spans=[(0, 30)],
        cut_end=90,
        probe_clip=False,
    )
    assert doc["inserts"][0]["durationSec"] == 5.0


def test_program_timeline_shifts_later_aroll(tmp_path: Path) -> None:
    inserts = [
        {
            "id": "ins_aaa111",
            "tFrame": 30,
            "videoAssetId": "clip-a",
            "clipStartSec": 0.0,
            "muted": False,
            "displayName": "A.mp4",
            "durationSec": 2.0,
        }
    ]
    pieces = build_program_timeline(inserts, cut_end=90, fps=30)
    kinds = [p["kind"] for p in pieces]
    assert kinds == ["aroll", "insert", "aroll"]
    assert pieces[0]["cutStartFrame"] == 0
    assert pieces[0]["cutEndFrameExclusive"] == 30
    assert pieces[1]["programStartFrame"] == 30
    assert pieces[1]["programEndFrameExclusive"] == 90
    assert pieces[2]["cutStartFrame"] == 30
    assert pieces[2]["programStartFrame"] == 90
    assert pieces[2]["programEndFrameExclusive"] == 150


def test_aroll_word_after_insert_shifts_by_clip_duration() -> None:
    inserts = [{"tFrame": 30, "durationSec": 2.0}]
    shifted = shift_aroll_word(
        {"id": "w3", "text": "later", "start_frame": 60, "end_frame": 69},
        inserts=inserts,
        fps=30,
    )
    assert shifted["id"] == "w3"
    assert shifted["sourceStartFrame"] == 60
    assert shifted["start_frame"] == 120
    assert shifted["end_frame"] == 129


def test_aroll_word_before_insert_does_not_shift() -> None:
    inserts = [{"tFrame": 30, "durationSec": 2.0}]
    shifted = shift_aroll_word(
        {"id": "w1", "text": "Hello", "start_frame": 0, "end_frame": 9},
        inserts=inserts,
        fps=30,
    )
    assert shifted["start_frame"] == 0


def test_muted_insert_is_marker_only(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".vcg-private").write_text("private\n", encoding="utf-8")
    transcript = project / "final-transcript.json"
    document = _beats_doc()
    transcript.write_text(json.dumps(document), encoding="utf-8")
    mb = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w2",
                    "rationale": "Open",
                }
            ],
        },
        project_root=project,
        transcript_path=transcript,
        document=document,
    )
    write_masterbeater_output(project, mb)
    manifest = {"paths": {"finalTranscript": "final-transcript.json"}}
    manifest_path = project / "manifest.json"

    inserts = [
        {
            "id": "ins_mute01",
            "tFrame": 30,
            "videoAssetId": "clip-a",
            "clipStartSec": 0.0,
            "muted": True,
            "displayName": "B-roll.mp4",
            "durationSec": 1.0,
        }
    ]
    pieces = build_program_timeline(inserts, cut_end=90, fps=30)

    def _must_not_transcribe(_path: Path):
        raise AssertionError("muted inserts must not be transcribed")

    result = build_program_transcript(
        manifest_path,
        manifest,
        pieces=pieces,
        inserts=inserts,
        fps=30,
        transcribe_clip=_must_not_transcribe,
    )
    markers = [w for w in result["words"] if w.get("kind") == "insert-marker"]
    speech = [w for w in result["words"] if w.get("kind") == "insert-word"]
    assert len(markers) == 1
    assert markers[0]["text"] == "B-roll.mp4"
    assert markers[0]["raw"] == "[B-roll.mp4]"
    assert markers[0]["id"] == "ins:ins_mute01:marker"
    assert speech == []
    aroll = [w for w in result["words"] if w.get("id") == "w3"]
    assert aroll[0]["start_frame"] == 90


def test_unmuted_insert_splices_clip_words(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".vcg-private").write_text("private\n", encoding="utf-8")
    transcript = project / "final-transcript.json"
    document = _beats_doc()
    transcript.write_text(json.dumps(document), encoding="utf-8")
    mb = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w2",
                    "rationale": "Open",
                }
            ],
        },
        project_root=project,
        transcript_path=transcript,
        document=document,
    )
    write_masterbeater_output(project, mb)
    media = project / "assets" / "placement"
    media.mkdir(parents=True)
    clip = media / "clip-a.mp4"
    clip.write_bytes(b"fake")
    monkeypatch.setattr(
        "app.core.visual_production.probe_has_audio_stream",
        lambda _path: True,
    )
    manifest_path = project / "manifest.json"
    manifest = {"paths": {"finalTranscript": "final-transcript.json"}}

    inserts = [
        {
            "id": "ins_talk01",
            "tFrame": 30,
            "videoAssetId": "clip-a",
            "clipStartSec": 0.5,
            "muted": False,
            "displayName": "Demo.mp4",
            "durationSec": 2.0,
        }
    ]
    pieces = build_program_timeline(inserts, cut_end=90, fps=30)

    def _words(_path: Path):
        return [
            WordTimestamp(text="shown", start=0.6, end=0.9),
            WordTimestamp(text="here", start=1.0, end=1.2),
        ]

    result = build_program_transcript(
        manifest_path,
        manifest,
        pieces=pieces,
        inserts=inserts,
        fps=30,
        transcribe_clip=_words,
    )
    speech = [w for w in result["words"] if w.get("kind") == "insert-word"]
    assert [w["id"] for w in speech] == ["ins:ins_talk01:w:000001", "ins:ins_talk01:w:000002"]
    assert speech[0]["text"] == "shown"
    # clip local 0.6 with in-point 0.5 → 0.1s into the insert, which starts at program frame 30
    assert speech[0]["start_frame"] == 33
    aroll_ids = {w["id"] for w in result["words"] if not str(w["id"]).startswith("ins:")}
    assert "w1" in aroll_ids
    assert "ins:ins_talk01:w:000001" not in aroll_ids


def test_muted_concat_filter_uses_silence() -> None:
    pieces = [
        {
            "inputIndex": 0,
            "startSec": 0.0,
            "durationSec": 1.0,
            "muted": False,
            "hasAudio": True,
        },
        {
            "inputIndex": 1,
            "startSec": 0.0,
            "durationSec": 2.0,
            "muted": True,
            "hasAudio": True,
        },
    ]
    filt = build_program_concat_filter(pieces, width=1920, height=1080, fps=30)
    assert "anullsrc" in filt
    assert "concat=n=2:v=1:a=1" in filt
    assert "[1:a]" not in filt


def test_cut_end_frame_rounds_duration() -> None:
    assert cut_end_frame_exclusive(5.0, 30) == 150
    assert cut_end_frame_exclusive(0, 30) == 1
