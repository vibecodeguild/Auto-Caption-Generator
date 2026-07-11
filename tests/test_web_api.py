from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.edit_decisions import EditDecisionList
from app.core.audio_normalizer import LoudnessHotspot, LoudnessHotspots, LoudnessMeasurement
from app.core.project_store import load_editor_project, save_editor_project
from app.core.splice_generation import generate_splices
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord
from app import web_api
from app.web_api import app, state


def test_api_rejects_untrusted_host() -> None:
    client = TestClient(app)

    response = client.get("/api/health", headers={"host": "attacker.example"})

    assert response.status_code == 400


def test_api_rejects_untrusted_browser_origin() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/projects/open-dialog",
        headers={"origin": "https://attacker.example"},
        json={},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Requests are only accepted from the local VCG interface."


def test_api_accepts_local_browser_origin() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/health",
        headers={"origin": "http://127.0.0.1:3000"},
    )

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def _project() -> TranscriptProject:
    return TranscriptProject(
        source=str(Path("missing.mp4")),
        fps=30.0,
        words=[
            TranscriptWord("w1", "When", "When", 0.0, 0.2, 0, 5, 1),
            TranscriptWord("w2", " you", "you", 0.2, 0.4, 6, 11, 1),
            TranscriptWord("w3", " build", "build", 0.4, 0.7, 12, 20, 1),
            TranscriptWord("w4", " fast", "fast", 1.5, 1.8, 45, 53, 2),
            TranscriptWord("w5", " ship", "ship", 1.8, 2.1, 54, 62, 2),
        ],
        silence_ranges=[SilenceRange("s1", 0.7, 1.5, 21, 44)],
    )


def test_open_project_returns_transcript_tokens_and_splices(tmp_path: Path) -> None:
    project_path = tmp_path / "sample.vcg.json"
    edits = EditDecisionList()
    edits.delete_word_selection("w3", "w3")
    save_editor_project(project_path, _project(), edits)

    client = TestClient(app)
    response = client.post("/api/projects/open", json={"path": str(project_path)})

    assert response.status_code == 200
    data = response.json()
    assert data["project"]["fps"] == 30.0
    assert [token["id"] for token in data["tokens"]] == ["w1", "w2", "w3", "s1", "w4", "w5"]
    assert data["splices"][0]["left_word_id"] == "w2"
    assert data["splices"][0]["right_word_id"] == "w4"


def test_open_project_dialog_uses_selected_file(tmp_path: Path, monkeypatch) -> None:
    project_path = tmp_path / "sample.vcg.json"
    save_editor_project(project_path, _project(), EditDecisionList())
    monkeypatch.setattr(web_api, "_choose_project_file", lambda: project_path)

    client = TestClient(app)
    response = client.post("/api/projects/open-dialog")

    assert response.status_code == 200
    assert response.json()["project_path"] == str(project_path)


def test_choose_video_surfaces_windows_picker_error(monkeypatch) -> None:
    def fail_picker():
        raise RuntimeError("desktop unavailable")

    monkeypatch.setattr(web_api, "_windows_choose_video_file", fail_picker)

    response = TestClient(app).post("/api/projects/choose-video")

    assert response.status_code == 500
    assert response.json()["detail"] == "Windows video picker error (RuntimeError): desktop unavailable"


def test_choose_transcript_video_and_transcribe_loads_new_project(tmp_path: Path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    monkeypatch.setattr(web_api, "_choose_video_file", lambda: video_path)
    monkeypatch.setattr(
        web_api,
        "generate_editor_transcript",
        lambda **kwargs: TranscriptProject(
            source=str(kwargs["input_video_path"]),
            fps=24.0,
            words=[
                TranscriptWord("w1", "Hello", "Hello", 0.0, 0.5, 0, 12, 1),
                TranscriptWord("w2", " world", "world", 0.6, 1.0, 14, 24, 1),
            ],
            silence_ranges=[SilenceRange("s1", 0.5, 0.6, 13, 13)],
        ),
    )
    state.project = None
    state.edits = EditDecisionList()
    state.project_path = None

    client = TestClient(app)
    choose_response = client.post("/api/projects/choose-video")
    transcribe_response = client.post(
        "/api/projects/transcribe",
        json={"model_label": "Base - balanced", "compute_label": "CPU"},
    )

    assert choose_response.status_code == 200
    assert choose_response.json()["source"] == str(video_path)
    assert transcribe_response.status_code == 200
    data = transcribe_response.json()
    assert data["project_path"] is None
    assert data["project"]["source"] == str(video_path)
    assert [token["id"] for token in data["tokens"]] == ["w1", "w2"]


def test_transcribe_job_reports_progress_and_result(tmp_path: Path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    state.transcript_video_path = video_path
    state.project = None
    state.edits = EditDecisionList()
    state.project_path = None
    state.transcription_jobs = {}

    def fake_generate_editor_transcript(**kwargs) -> TranscriptProject:
        kwargs["progress_callback"](15, "Extracting audio...")
        time.sleep(0.02)
        kwargs["progress_callback"](65, "Transcribing... 2 words")
        return TranscriptProject(
            source=str(kwargs["input_video_path"]),
            fps=24.0,
            words=[
                TranscriptWord("w1", "Hello", "Hello", 0.0, 0.5, 0, 12, 1),
                TranscriptWord("w2", " world", "world", 0.6, 1.0, 14, 24, 1),
            ],
            silence_ranges=[SilenceRange("s1", 0.5, 0.6, 13, 13)],
        )

    monkeypatch.setattr(web_api, "generate_editor_transcript", fake_generate_editor_transcript)

    client = TestClient(app)
    start_response = client.post(
        "/api/projects/transcribe/start",
        json={"model_label": "Base - balanced", "compute_label": "CPU"},
    )

    assert start_response.status_code == 200
    job_id = start_response.json()["job_id"]
    snapshots = []
    for _ in range(20):
        snapshot = client.get(f"/api/projects/transcribe/jobs/{job_id}").json()
        snapshots.append(snapshot)
        if snapshot["status"] == "complete":
            break
        time.sleep(0.01)

    assert any(item["message"] == "Extracting audio..." for item in snapshots)
    assert snapshots[-1]["status"] == "complete"
    assert snapshots[-1]["result"]["project"]["source"] == str(video_path)
    assert [token["id"] for token in snapshots[-1]["result"]["tokens"]] == ["w1", "w2"]


def test_save_new_transcribed_project_prompts_for_project_path(tmp_path: Path, monkeypatch) -> None:
    project_path = tmp_path / "new-project.vcg.json"
    state.project = _project()
    state.edits = EditDecisionList()
    state.edits.delete_word_selection("w3", "w3")
    state.project_path = None
    monkeypatch.setattr(web_api, "_choose_project_save_file", lambda project: project_path)

    client = TestClient(app)
    response = client.post("/api/projects/current/save")

    assert response.status_code == 200
    assert response.json()["saved"] == str(project_path)
    assert state.project_path == project_path
    _, saved_edits = load_editor_project(project_path)
    assert [(item.start_word_id, item.end_word_id) for item in saved_edits.deleted_word_ranges] == [("w3", "w3")]


def test_project_document_returns_current_edits_for_web_save() -> None:
    state.project = _project()
    state.edits = EditDecisionList()
    state.edits.delete_word_selection("w3", "w3")
    state.project_path = None

    client = TestClient(app)
    response = client.get("/api/projects/current/document")

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "missing.vcg.json"
    assert data["document"]["project"]["fps"] == 30.0
    assert data["document"]["edits"]["deleted_word_ranges"][0]["start_word_id"] == "w3"
    assert data["document"]["edits"]["deleted_word_ranges"][0]["end_word_id"] == "w3"


def test_delete_selection_updates_dynamic_splices() -> None:
    state.project = _project()
    state.edits = EditDecisionList()
    state.project_path = None

    client = TestClient(app)
    response = client.post("/api/projects/current/delete", json={"token_ids": ["w3", "s1"]})

    assert response.status_code == 200
    data = response.json()
    assert data["deleted_word_ids"] == ["w3"]
    assert data["deleted_silence_ids"] == ["s1"]
    assert data["splices"][0]["left_word_id"] == "w2"
    assert data["splices"][0]["right_word_id"] == "w4"


def test_delete_selection_saves_loaded_project_edits(tmp_path: Path) -> None:
    project_path = tmp_path / "sample.vcg.json"
    save_editor_project(project_path, _project(), EditDecisionList())
    state.project = _project()
    state.edits = EditDecisionList()
    state.project_path = project_path

    client = TestClient(app)
    response = client.post("/api/projects/current/delete", json={"token_ids": ["w3", "s1"]})

    assert response.status_code == 200
    _, saved_edits = load_editor_project(project_path)
    assert [(item.start_word_id, item.end_word_id) for item in saved_edits.deleted_word_ranges] == [("w3", "w3")]
    assert [item.silence_id for item in saved_edits.deleted_silence_ranges] == ["s1"]


def test_adjust_splice_updates_preview_segments() -> None:
    state.project = _project()
    state.edits = EditDecisionList()
    state.edits.delete_word_selection("w3", "w3")
    state.project_path = None

    client = TestClient(app)
    opened = client.get("/api/projects/current").json()
    anchor_key = opened["splices"][0]["anchor_key"]
    response = client.post(
        "/api/projects/current/splices/adjust",
        json={"anchor_key": anchor_key, "left_delta": 2, "right_delta": -1},
    )

    assert response.status_code == 200
    splice = response.json()["splices"][0]
    assert splice["left_out_adjustment"] == 2
    assert splice["right_in_adjustment"] == -1
    assert splice["preview_segments_4s"] == [[0.0, 0.466667], [1.466667, 3.466667]]


def test_adjust_splice_rejects_and_rolls_back_overlapping_ranges() -> None:
    state.project = _project()
    state.edits = EditDecisionList()
    state.edits.delete_word_selection("w3", "w3")
    state.project_path = None

    client = TestClient(app)
    splice = client.get("/api/projects/current").json()["splices"][0]
    response = client.post(
        "/api/projects/current/splices/adjust",
        json={"anchor_key": splice["anchor_key"], "left_delta": 30, "right_delta": -10},
    )

    assert response.status_code == 400
    assert "overlap" in response.json()["detail"]
    rolled_back = client.get("/api/projects/current").json()["splices"][0]
    assert rolled_back["left_out_adjustment"] == 0
    assert rolled_back["right_in_adjustment"] == 0


def test_editor_settings_update_dead_space_candidate_count() -> None:
    state.project = _project()
    state.edits = EditDecisionList()
    state.project_path = None

    client = TestClient(app)
    response = client.post(
        "/api/projects/current/settings",
        json={"dead_space_min_seconds": 0.7},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["settings"] == {"dead_space_min_seconds": 0.7}
    assert data["dead_space_candidate_count"] == 0
    assert data["pause_analysis_pending_count"] == 1


def test_delete_dead_space_only_removes_gaps_meeting_project_threshold() -> None:
    project = _project()
    analyzed_silence = replace(
        project.silence_ranges[0],
        measured_start=project.silence_ranges[0].start,
        measured_end=project.silence_ranges[0].end,
        measured_start_frame=project.silence_ranges[0].start_frame,
        measured_end_frame=project.silence_ranges[0].end_frame,
        audio_analyzed=True,
    )
    state.project = replace(project, silence_ranges=[analyzed_silence])
    state.edits = EditDecisionList()
    state.edits.settings.dead_space_min_seconds = 1.0
    state.project_path = None

    client = TestClient(app)
    skipped = client.post("/api/projects/current/delete-dead-space", json={})

    assert skipped.status_code == 200
    assert skipped.json()["deleted_silence_ids"] == []

    state.edits.settings.dead_space_min_seconds = 0.7
    removed = client.post("/api/projects/current/delete-dead-space", json={})

    assert removed.status_code == 200
    assert removed.json()["deleted_silence_ids"] == ["s1"]


def test_delete_dead_space_does_not_remove_unanalyzed_whisper_candidates() -> None:
    state.project = _project()
    state.edits = EditDecisionList()
    state.edits.settings.dead_space_min_seconds = 0.7
    state.project_path = None

    response = TestClient(app).post("/api/projects/current/delete-dead-space", json={})

    assert response.status_code == 200
    assert response.json()["deleted_silence_ids"] == []


def test_analyze_pauses_restores_and_hides_rejected_candidate(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.edits.settings.dead_space_min_seconds = 0.8
    state.edits.delete_silence("delete_s1", "s1")
    state.project_path = None
    monkeypatch.setattr(web_api, "extract_audio", lambda *_args: tmp_path / "audio.wav")

    def analyzed(project, _audio_path, _minimum):
        silence = replace(
            project.silence_ranges[0],
            measured_start=1.1,
            measured_end=1.5,
            measured_start_frame=33,
            measured_end_frame=44,
            audio_analyzed=True,
        )
        return replace(project, silence_ranges=[silence]), {
            "candidates_checked": 1,
            "validated_long_pauses": 0,
            "rejected_candidates": 1,
        }

    monkeypatch.setattr(web_api, "analyze_pause_candidates", analyzed)
    response = TestClient(app).post("/api/projects/current/analyze-pauses", json={})

    assert response.status_code == 200
    assert response.json()["pause_analysis_summary"]["rejected_candidates"] == 1
    assert response.json()["deleted_silence_ids"] == []
    assert "s1" not in [token["id"] for token in response.json()["tokens"]]


def test_analyze_boundaries_updates_existing_project(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(
        source=str(source),
        fps=original.fps,
        words=original.words,
        silence_ranges=original.silence_ranges,
    )
    state.edits = EditDecisionList()
    state.edits.delete_word_selection("w3", "w3")
    state.project_path = None
    monkeypatch.setattr(web_api, "extract_audio", lambda *_args: tmp_path / "audio.wav")

    def assisted(project, _audio_path, word_ids):
        return {word_id: project.word_by_id(word_id).end_frame + 3 for word_id in word_ids}

    monkeypatch.setattr(web_api, "suggest_word_end_boundaries", assisted)

    response = TestClient(app).post("/api/projects/current/analyze-boundaries", json={})

    assert response.status_code == 200
    assert response.json()["fine_tune_summary"] == {
        "cuts_checked": 1,
        "cuts_adjusted": 1,
        "cuts_unchanged": 0,
    }
    splice = response.json()["splices"][0]
    assert state.edits.splice_adjustments[splice["anchor_key"]].assisted_left_out_frame == splice["left_suggested_out_frame"]


def test_fine_tune_skips_reviewed_splices(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.edits.delete_word_selection("w3", "w3")
    splice = generate_splices(state.project, state.edits).splices[0]
    state.edits.adjust_splice(splice.anchor_key, reviewed=True)
    state.project_path = None

    monkeypatch.setattr(web_api, "extract_audio", lambda *_args: pytest.fail("reviewed cut should not extract audio"))
    response = TestClient(app).post("/api/projects/current/analyze-boundaries", json={})

    assert response.status_code == 200
    assert response.json()["fine_tune_summary"]["cuts_checked"] == 0


def test_audio_analysis_is_required_before_normalized_export(tmp_path: Path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    output_dir = tmp_path / "exports"
    state.audio_video_path = video_path
    state.audio_analysis_key = None
    state.audio_analysis = None

    client = TestClient(app)
    response = client.post(
        "/api/audio/normalize",
        json={
            "preset_id": "gentle",
            "target_i": -14,
            "target_lra": 7,
            "target_tp": -1.5,
            "output_folder": str(output_dir),
        },
    )

    assert response.status_code == 400
    assert "Analyze this video" in response.json()["detail"]


def test_audio_analyze_and_export_use_matching_settings(tmp_path: Path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    output_dir = tmp_path / "exports"
    state.audio_video_path = video_path
    state.audio_analysis_key = None
    state.audio_analysis = None
    measurement = LoudnessMeasurement(
        input_i=-20.0,
        input_tp=-3.0,
        input_lra=8.0,
        input_thresh=-30.0,
        target_offset=0.1,
    )
    monkeypatch.setattr(web_api, "analyze_audio", lambda **kwargs: measurement)
    hotspots = LoudnessHotspots(
        loudest=LoudnessHotspot(30.0, 40.0, -12.0),
        quietest_speech=LoudnessHotspot(70.0, 80.0, -35.0),
    )
    monkeypatch.setattr(web_api, "analyze_loudness_hotspots", lambda **kwargs: hotspots)

    exported: dict[str, object] = {}

    def fake_normalize(**kwargs) -> Path:
        exported.update(kwargs)
        return kwargs["output_video"]

    monkeypatch.setattr(web_api, "normalize_video_audio", fake_normalize)

    client = TestClient(app)
    payload = {
        "preset_id": "gentle",
        "target_i": -14,
        "target_lra": 7,
        "target_tp": -1.5,
    }
    analyze_response = client.post("/api/audio/analyze", json=payload)
    export_response = client.post(
        "/api/audio/normalize",
        json={**payload, "output_folder": str(output_dir)},
    )

    assert analyze_response.status_code == 200
    assert analyze_response.json()["measurement"]["input_i"] == -20.0
    assert analyze_response.json()["hotspots"]["loudest"]["start_seconds"] == 30.0
    assert export_response.status_code == 200
    assert export_response.json()["output_path"] == str(output_dir / "source_normalized.mp4")
    assert exported["preset_id"] == "gentle"
    assert exported["measurement"] == measurement


def test_audio_preview_analyzes_when_needed_and_serves_both_versions(tmp_path: Path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    state.audio_video_path = video_path
    state.audio_analysis_key = None
    state.audio_analysis = None
    state.audio_preview_id = None
    state.audio_preview_original = None
    state.audio_preview_corrected = None
    measurement = LoudnessMeasurement(
        input_i=-19.0,
        input_tp=-2.8,
        input_lra=6.0,
        input_thresh=-29.0,
        target_offset=0.0,
    )
    monkeypatch.setattr(web_api, "analyze_audio", lambda **kwargs: measurement)
    hotspots = LoudnessHotspots(
        loudest=LoudnessHotspot(10.0, 20.0, -14.0),
        quietest_speech=LoudnessHotspot(40.0, 50.0, -33.0),
    )
    monkeypatch.setattr(web_api, "analyze_loudness_hotspots", lambda **kwargs: hotspots)
    monkeypatch.setattr(web_api, "temp_dir", lambda: tmp_path)

    captured: dict[str, object] = {}

    def fake_preview(**kwargs):
        captured.update(kwargs)
        kwargs["original_preview"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["original_preview"].write_bytes(b"original")
        kwargs["corrected_preview"].write_bytes(b"corrected")
        return kwargs["original_preview"], kwargs["corrected_preview"]

    monkeypatch.setattr(web_api, "create_audio_preview", fake_preview)
    client = TestClient(app)
    response = client.post(
        "/api/audio/preview",
        json={
            "preset_id": "gentle",
            "target_i": -14,
            "target_lra": 7,
            "target_tp": -1.5,
            "start_seconds": 12.5,
            "duration_seconds": 20,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["start_seconds"] == 12.5
    assert data["duration_seconds"] == 20
    assert data["measurement"]["input_i"] == -19.0
    assert data["hotspots"]["quietest_speech"]["start_seconds"] == 40.0
    assert captured["start_seconds"] == 12.5
    assert captured["duration_seconds"] == 20

    original_response = client.get(f"/api/audio/preview/{data['preview_id']}/original")
    corrected_response = client.get(f"/api/audio/preview/{data['preview_id']}/corrected")
    assert original_response.status_code == 200
    assert original_response.content == b"original"
    assert corrected_response.status_code == 200
    assert corrected_response.content == b"corrected"


def test_audio_preview_rejects_invalid_duration(tmp_path: Path) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    state.audio_video_path = video_path

    client = TestClient(app)
    response = client.post(
        "/api/audio/preview",
        json={
            "preset_id": "gentle",
            "target_i": -14,
            "target_lra": 7,
            "target_tp": -1.5,
            "start_seconds": 0,
            "duration_seconds": 45,
        },
    )

    assert response.status_code == 400
    assert "between 5 and 30 seconds" in response.json()["detail"]


def test_audio_preview_returns_friendly_ffmpeg_error(tmp_path: Path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    state.audio_video_path = video_path
    state.audio_analysis_key = None
    state.audio_analysis = None
    monkeypatch.setattr(
        web_api,
        "analyze_audio",
        lambda **kwargs: LoudnessMeasurement(-19.0, -2.8, 6.0, -29.0, 0.0),
    )
    monkeypatch.setattr(
        web_api,
        "analyze_loudness_hotspots",
        lambda **kwargs: LoudnessHotspots(
            loudest=LoudnessHotspot(10.0, 20.0, -14.0),
            quietest_speech=LoudnessHotspot(40.0, 50.0, -33.0),
        ),
    )
    monkeypatch.setattr(
        web_api,
        "create_audio_preview",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Could not create preview.\n\nFFmpeg details:\nlong internal output")),
    )

    client = TestClient(app)
    response = client.post(
        "/api/audio/preview",
        json={
            "preset_id": "gentle",
            "target_i": -14,
            "target_lra": 7,
            "target_tp": -1.5,
            "start_seconds": 0,
            "duration_seconds": 20,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Could not create preview."
