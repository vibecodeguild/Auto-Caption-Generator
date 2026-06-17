from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.edit_decisions import EditDecisionList
from app.core.project_store import load_editor_project, save_editor_project
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord
from app import web_api
from app.web_api import app, state


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
    assert [token["id"] for token in data["tokens"]] == ["w1", "s1", "w2"]


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
    assert [token["id"] for token in snapshots[-1]["result"]["tokens"]] == ["w1", "s1", "w2"]


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
