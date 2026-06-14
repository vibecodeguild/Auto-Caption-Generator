from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.edit_decisions import EditDecisionList
from app.core.project_store import save_editor_project
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
