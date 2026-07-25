from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

from app.core.edit_decisions import EditDecisionList
from app.core.audio_normalizer import LoudnessHotspot, LoudnessHotspots, LoudnessMeasurement
from app.core.project_store import load_editor_project, save_editor_project
from app.core.splice_generation import generate_splices
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord
from app import web_api
from app.web_api import app, state


def test_media_range_response_streams_without_eagerly_reading_the_file(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "large.mp4"
    media.write_bytes(b"0123456789")
    original_open = Path.open
    opened = False

    def tracked_open(path: Path, *args, **kwargs):
        nonlocal opened
        opened = True
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)

    response = web_api._range_response(media, "bytes=0-")

    assert isinstance(response, StreamingResponse)
    assert opened is False
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-9/10"
    assert response.headers["content-length"] == "10"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=2-5", (2, 5)),
        ("bytes=7-", (7, 9)),
        ("bytes=-4", (6, 9)),
        ("bytes=-20", (0, 9)),
    ],
)
def test_media_range_parser_supports_browser_range_forms(header: str, expected: tuple[int, int]) -> None:
    assert web_api._parse_range(header, 10) == expected


@pytest.mark.parametrize("header", ["bytes=-", "bytes=-0", "bytes=8-2", "bytes=20-", "bytes=0-1,4-5"])
def test_media_range_parser_rejects_unsatisfiable_ranges(header: str) -> None:
    with pytest.raises(web_api.HTTPException) as caught:
        web_api._parse_range(header, 10)

    assert caught.value.status_code == 416
    assert caught.value.headers == {"Content-Range": "bytes */10"}


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


def test_caption_style_normalizes_hex_colors_before_generation() -> None:
    style = web_api.CaptionStylePayload(
        font_family="Montserrat",
        main_font_size=72,
        active_font_size=78,
        main_color="#fff",
        active_color="#ff0000",
        outline_color="#FFFFFF",
        outline_width=5,
        bold=True,
        active_bold=True,
        position="Bottom",
        margin_v=220,
    )

    assert style.main_color == "#FFFFFF"
    assert style.active_color == "#FF0000"
    assert style.outline_color == "#FFFFFF"


def test_caption_style_rejects_incomplete_hex_colors_at_api_boundary() -> None:
    with pytest.raises(ValueError, match="Colors must use #RRGGBB format"):
        web_api.CaptionStylePayload(
            font_family="Montserrat",
            main_font_size=72,
            active_font_size=78,
            main_color="#FFFFFF",
            active_color="#FF0000",
            outline_color="#FF",
            outline_width=5,
            bold=True,
            active_bold=True,
            position="Bottom",
            margin_v=220,
        )


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


def test_visual_project_create_and_save_uses_private_plan(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "private" / "plans" / "visual-plan.json"
    plan = {
        "schemaVersion": 1,
        "project": {"id": "visual-1", "name": "Pilot"},
        "source": {"video": "source/locked.mp4", "transcript": ""},
        "composition": {"durationSec": 60, "width": 1920, "height": 1080, "fps": 30, "brandId": "vcg-white-editorial"},
        "assets": [], "protectedFootage": [], "cues": [],
    }
    monkeypatch.setattr(web_api, "_choose_video_file", lambda: tmp_path / "cut.mp4")
    monkeypatch.setattr(web_api, "create_visual_project", lambda source, transcript_document=None: (plan_path, plan))
    monkeypatch.setattr(web_api, "visual_plan_response", lambda path, value: {"planPath": str(path), "projectRoot": str(path.parents[1]), "plan": value})
    saved_plan = {**plan, "project": {**plan["project"], "name": "Renamed"}}
    monkeypatch.setattr(web_api, "save_visual_plan", lambda path, value: value)
    state.visual_plan_path = None
    state.visual_plan = None

    client = TestClient(app)
    created = client.post("/api/visual/create-dialog")
    saved = client.post("/api/visual/save", json={"plan": saved_plan})

    assert created.status_code == 200
    assert created.json()["plan"]["project"]["id"] == "visual-1"
    assert saved.status_code == 200
    assert saved.json()["plan"]["project"]["name"] == "Renamed"


def test_visual_render_rejects_invalid_range(tmp_path: Path) -> None:
    state.visual_plan_path = tmp_path / "plans" / "visual-plan.json"
    state.visual_plan = {"composition": {"durationSec": 60}}

    response = TestClient(app).post("/api/visual/render", json={"start_sec": 20, "end_sec": 10, "quality": "draft"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Render end must be after render start."


def test_visual_final_export_reuses_active_job_and_restores_progress(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "private"
    plan_path = root / "visual-production" / "visual-plan.json"
    plan_path.parent.mkdir(parents=True)
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    plan = {"composition": {"durationSec": 60}}
    started_threads: list[object] = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started_threads.append(self)

    monkeypatch.setattr(state, "visual_plan_path", plan_path)
    monkeypatch.setattr(state, "visual_plan", plan)
    monkeypatch.setattr(state, "visual_render_jobs", {})
    monkeypatch.setattr(web_api, "_active_video_project", lambda: None)
    monkeypatch.setattr(web_api, "visual_production_gate_report", lambda _path, _plan: {
        "canRenderReview": True, "canDeliver": True, "messages": [],
    })
    monkeypatch.setattr(web_api.threading, "Thread", FakeThread)
    client = TestClient(app)

    first = client.post("/api/visual/render", json={"quality": "high", "purpose": "final"})
    second = client.post("/api/visual/render", json={"quality": "high", "purpose": "final"})
    job_id = first.json()["job_id"]
    state.visual_render_jobs[job_id].update(69, "Rendering visual-production frames...")
    active = client.get("/api/visual/render/active")

    assert first.status_code == 200
    assert first.json()["reused"] is False
    assert second.status_code == 200
    assert second.json() == {"job_id": job_id, "reused": True}
    assert len(started_threads) == 1
    assert active.status_code == 200
    assert active.json()["job"]["job_id"] == job_id
    assert active.json()["job"]["stage"] == "rendering"
    assert active.json()["job"]["value"] == 69
    assert (plan_path.parent / "render-job.json").is_file()


def test_visual_active_job_returns_completed_persisted_status_after_restart(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "visual-production" / "visual-plan.json"
    plan_path.parent.mkdir(parents=True)
    output = tmp_path / "exports" / "final-video.mp4"
    output.parent.mkdir()
    output.write_bytes(b"final")
    job = web_api.VisualRenderJob("completed-job", plan_path, "final")
    job.complete(output)

    monkeypatch.setattr(state, "visual_plan_path", plan_path)
    monkeypatch.setattr(state, "visual_plan", {"composition": {"durationSec": 60}})
    monkeypatch.setattr(state, "visual_render_jobs", {})

    response = TestClient(app).get("/api/visual/render/active")

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "complete"
    assert response.json()["job"]["output_path"] == str(output)


def test_visual_final_streams_the_persisted_active_revision(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "private"
    plan_path = root / "visual-production" / "visual-plan.json"
    final_path = root / "exports" / "final-video.mp4"
    plan_path.parent.mkdir(parents=True)
    final_path.parent.mkdir(parents=True)
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    final_path.write_bytes(b"persisted-v5")
    plan = {
        "assets": [{
            "id": "frozen-v5-master",
            "path": "exports/final-video.mp4",
            "origin": {"kind": "frozen-visual-revision", "active": True, "revisionId": "v5-final"},
        }],
    }
    monkeypatch.setattr(state, "visual_plan_path", plan_path)
    monkeypatch.setattr(state, "visual_plan", plan)

    response = TestClient(app).get("/api/visual/final")

    assert response.status_code == 200
    assert response.content == b"persisted-v5"


def test_visual_runtime_serves_registered_composition_and_local_assets(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "private"
    plan_path = root / "visual-production" / "visual-plan.json"
    runtime_root = root / "working" / "hyperframes-v5" / "public"
    plan_path.parent.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    (runtime_root / "index.html").write_text('<div data-composition-id="v5"></div></body>', encoding="utf-8")
    (runtime_root / "asset.txt").write_text("exact-runtime-asset", encoding="utf-8")
    plan = {
        "customCompositions": [{
            "id": "v5", "runtime": "hyperframes", "projectPath": "working/hyperframes-v5/public", "entryFile": "index.html",
        }],
        "cues": [{"id": "scene", "kind": "composition", "compositionId": "v5", "enabled": True}],
        "revisions": {"activeRevision": None, "items": []},
    }
    monkeypatch.setattr(state, "visual_plan_path", plan_path)
    monkeypatch.setattr(state, "visual_plan", plan)

    client = TestClient(app)
    entry = client.get("/api/visual/runtime/composition/index.html")
    asset = client.get("/api/visual/runtime/composition/asset.txt")

    assert entry.status_code == 200
    assert '/api/visual/runtime/core.js' in entry.text
    assert asset.status_code == 200
    assert asset.text == "exact-runtime-asset"


def test_choose_video_surfaces_windows_picker_error(monkeypatch) -> None:
    def fail_picker():
        raise RuntimeError("desktop unavailable")

    monkeypatch.setattr(web_api, "_windows_choose_video_files", fail_picker)

    response = TestClient(app).post("/api/projects/choose-video")

    assert response.status_code == 500
    assert response.json()["detail"] == "Windows multi-video picker error (RuntimeError): desktop unavailable"


def test_choose_transcript_video_and_transcribe_loads_new_project(tmp_path: Path, monkeypatch) -> None:
    from app.core import video_project

    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    monkeypatch.setenv("VCG_PRIVATE_WORKSPACE", str(tmp_path / "private-workspace"))
    monkeypatch.setattr(video_project, "project_root", lambda: tmp_path / "public-checkout")
    monkeypatch.setattr(web_api, "_choose_video_files", lambda: [video_path])
    monkeypatch.setattr(video_project, "probe_source_clip", lambda path: {
        "durationSec": 2.0, "videoCodec": "h264", "width": 1920, "height": 1080,
        "pixelFormat": "yuv420p", "frameRate": "24/1", "audioCodec": "aac",
        "audioSampleRate": 48000, "audioChannels": 2,
    })
    monkeypatch.setattr(video_project, "_run_ffmpeg", lambda command, message: Path(command[-1]).write_bytes(b"sequence"))
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
    copied_source = Path(choose_response.json()["source"])
    assert copied_source.name == "source-sequence.mp4"
    assert copied_source.read_bytes() == b"sequence"
    assert transcribe_response.status_code == 200
    data = transcribe_response.json()
    assert Path(data["project_path"]).name == "editor.vcg.json"
    assert data["project"]["source"] == str(copied_source)
    assert [token["id"] for token in data["tokens"]] == ["w1", "w2"]
    assert data["project"]["generation"]["model_id"] == "base.en"
    assert data["project"]["generation"]["compute_label"] == "CPU"
    assert data["project"]["generation"]["source"]["sha256"]
    original_path = Path(data["video_project"]["resolvedPaths"]["originalTranscript"])
    assert original_path.is_file()
    original_project, original_edits = load_editor_project(original_path)
    assert original_project.generation == data["project"]["generation"]
    assert original_edits == EditDecisionList()

    locked_cut = Path(data["video_project"]["resolvedPaths"]["lockedCut"])
    locked_cut.write_bytes(b"locked")
    web_api._save_final_transcript(state.project, generate_splices(state.project, state.edits), locked_cut)
    current_video_project = web_api.video_project_response(state.video_project_path, state.video_project)
    final_reviewed = Path(current_video_project["resolvedPaths"]["finalReviewedProject"])
    edit_analysis = Path(current_video_project["resolvedPaths"]["editAnalysis"])
    final_transcript = Path(current_video_project["resolvedPaths"]["finalTranscript"])
    assert final_reviewed.is_file()
    assert edit_analysis.is_file()
    assert final_transcript.is_file()
    reviewed_project, reviewed_edits = load_editor_project(final_reviewed)
    assert reviewed_project == state.project
    assert reviewed_edits == state.edits


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


def test_project_response_marks_and_clears_nearby_repeated_wording() -> None:
    state.project = TranscriptProject(
        source="repeat.mp4",
        fps=30.0,
        words=[
            TranscriptWord("w1", " I", "I", 0.0, 0.2, 0, 6, 1),
            TranscriptWord("w2", " know", "know", 0.2, 0.4, 6, 12, 1),
            TranscriptWord("w3", " there", "there", 0.4, 0.6, 12, 18, 1),
            TranscriptWord("w4", " are", "are", 0.6, 0.8, 18, 24, 1),
            TranscriptWord("w5", " at", "at", 0.8, 1.0, 24, 30, 1),
            TranscriptWord("w6", " least", "least", 1.0, 1.2, 30, 36, 1),
            TranscriptWord("w7", " I", "I", 1.8, 2.0, 54, 60, 1),
            TranscriptWord("w8", " know", "know", 2.0, 2.2, 60, 66, 1),
            TranscriptWord("w9", " there", "there", 2.2, 2.4, 66, 72, 1),
            TranscriptWord("w10", " are", "are", 2.4, 2.6, 72, 78, 1),
            TranscriptWord("w11", " at", "at", 2.6, 2.8, 78, 84, 1),
            TranscriptWord("w12", " least", "least", 2.8, 3.0, 84, 90, 1),
        ],
        silence_ranges=[],
    )
    state.edits = EditDecisionList()
    state.project_path = None
    client = TestClient(app)

    response = client.get("/api/projects/current")

    assert response.status_code == 200
    assert response.json()["repeated_word_ids"] == ["w1", "w2", "w3", "w4", "w5", "w6"]

    state.edits.delete_word_selection("w1", "w6")
    resolved = client.get("/api/projects/current")

    assert resolved.status_code == 200
    assert resolved.json()["repeated_word_ids"] == []


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


@pytest.mark.parametrize(
    ("measured_start_frame", "expected_out_frame"),
    [(22, 22), (40, 23)],
    ids=["nearby-measured-pause-is-used", "distant-measured-pause-is-ignored"],
)
def test_fine_tune_only_reuses_word_local_measured_pause(
    tmp_path: Path,
    monkeypatch,
    measured_start_frame: int,
    expected_out_frame: int,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    analyzed_silence = replace(
        original.silence_ranges[0],
        measured_start=measured_start_frame / original.fps,
        measured_end=original.silence_ranges[0].end,
        measured_start_frame=measured_start_frame,
        measured_end_frame=original.silence_ranges[0].end_frame,
        audio_analyzed=True,
    )
    state.project = TranscriptProject(
        source=str(source),
        fps=original.fps,
        words=original.words,
        silence_ranges=[analyzed_silence],
    )
    state.edits = EditDecisionList()
    state.edits.delete_silence("delete_s1", "s1")
    state.project_path = None
    monkeypatch.setattr(web_api, "extract_audio", lambda *_args: tmp_path / "audio.wav")

    def assisted(project, _audio_path, word_ids):
        return {word_id: project.word_by_id(word_id).end_frame + 3 for word_id in word_ids}

    monkeypatch.setattr(web_api, "suggest_word_end_boundaries", assisted)

    response = TestClient(app).post("/api/projects/current/analyze-boundaries", json={})

    assert response.status_code == 200
    splice = response.json()["splices"][0]
    assert splice["left_out_frame"] == expected_out_frame
    assert state.edits.splice_adjustments[splice["anchor_key"]].assisted_left_out_frame == expected_out_frame


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


def test_render_cut_preview_uses_complete_plan_and_returns_splice_timeline(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.edits.delete_word_selection("w3", "w3")
    state.project_path = None
    state.rendered_cut_preview_id = None
    state.rendered_cut_preview_path = None
    splice = generate_splices(state.project, state.edits).splices[0]
    rendered: dict[str, object] = {}

    def fake_cut(**kwargs) -> None:
        rendered.update(kwargs)
        kwargs["output_video"].write_bytes(b"rendered preview")

    monkeypatch.setattr(web_api, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(web_api, "run_cut", fake_cut)

    client = TestClient(app)
    response = client.post(
        "/api/projects/current/render-preview",
        json={},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["duration_seconds"] == 1.0
    assert data["splices"] == [{
        "id": splice.id,
        "anchor_key": splice.anchor_key,
        "preview_time_seconds": 0.4,
        "left_out_frame": splice.left_out_frame,
        "right_in_frame": splice.right_in_frame,
        "left_section": "When you",
        "right_section": "fast ship",
    }]
    assert data["segments"] == [
        {
            "source_start_frame": 0,
            "source_end_frame": 11,
            "preview_start_seconds": 0.0,
            "preview_end_seconds": 0.4,
        },
        {
            "source_start_frame": 45,
            "source_end_frame": 62,
            "preview_start_seconds": 0.4,
            "preview_end_seconds": 1.0,
        },
    ]
    assert rendered["input_video"] == source
    assert rendered["intervals"] == [(0.0, 0.4), (1.5, 2.1)]
    assert rendered["crf"] == 28
    assert rendered["preset"] == "ultrafast"

    media_response = client.get(f"/api/projects/current/render-preview/{data['preview_id']}")
    assert media_response.status_code == 200
    assert media_response.content == b"rendered preview"


def test_manual_cut_api_adds_adjusts_reviews_and_removes_source_frame_cut() -> None:
    state.project = _project()
    state.edits = EditDecisionList()
    state.project_path = None
    client = TestClient(app)

    added = client.post("/api/projects/current/manual-cuts", json={"out_frame": 22, "in_frame": 30})

    assert added.status_code == 200
    manual = next(splice for splice in added.json()["splices"] if splice["kind"] == "manual")
    assert added.json()["kept_ranges"][0]["adjusted_end_frame"] == 22
    assert added.json()["kept_ranges"][1]["adjusted_start_frame"] == 30

    adjusted = client.post(
        "/api/projects/current/manual-cuts/adjust",
        json={"cut_id": manual["manual_cut_id"], "out_delta": 1, "in_delta": 2},
    )
    assert adjusted.status_code == 200
    adjusted_manual = next(splice for splice in adjusted.json()["splices"] if splice["kind"] == "manual")
    assert (adjusted_manual["left_out_frame"], adjusted_manual["right_in_frame"]) == (23, 32)

    reviewed = client.post(
        "/api/projects/current/splices/review",
        json={"anchor_key": manual["anchor_key"], "reviewed": True},
    )
    assert reviewed.status_code == 200
    assert next(splice for splice in reviewed.json()["splices"] if splice["kind"] == "manual")["reviewed"] is True

    removed = client.delete(f"/api/projects/current/manual-cuts/{manual['manual_cut_id']}")
    assert removed.status_code == 200
    assert all(splice["kind"] != "manual" for splice in removed.json()["splices"])


def test_final_out_frame_is_saved_and_used_by_render_preview(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.project_path = tmp_path / "editor.vcg.json"
    state.rendered_cut_preview_id = None
    state.rendered_cut_preview_path = None
    rendered: dict[str, object] = {}

    def fake_cut(**kwargs) -> None:
        rendered.update(kwargs)
        kwargs["output_video"].write_bytes(b"rendered preview")

    monkeypatch.setattr(web_api, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(web_api, "run_cut", fake_cut)
    client = TestClient(app)

    updated = client.post("/api/projects/current/final-out-frame", json={"frame": 68})
    preview = client.post("/api/projects/current/render-preview", json={})
    _, saved_edits = load_editor_project(state.project_path)

    assert updated.status_code == 200
    assert updated.json()["final_cut"] == {
        "out_frame": 68,
        "suggested_out_frame": 62,
        "adjustment": 6,
        "minimum_out_frame": 0,
        "maximum_out_frame": None,
        "custom": True,
    }
    assert saved_edits.final_out_frame == 68
    assert preview.status_code == 200
    assert rendered["intervals"] == [(0.0, 2.3)]
    assert preview.json()["segments"][0]["source_end_frame"] == 68


def test_render_cut_preview_rejects_unknown_preview_id(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.project_path = None

    state.rendered_cut_preview_id = None
    state.rendered_cut_preview_path = None
    response = TestClient(app).get("/api/projects/current/render-preview/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Rendered cut preview not found."


def test_cut_export_remains_cut_only_by_default(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.project_path = None
    exported: dict[str, object] = {}

    def fake_cut(**kwargs) -> Path:
        exported.update(kwargs)
        kwargs["output_video"].write_bytes(b"cut")
        return kwargs["output_video"]

    monkeypatch.setattr(web_api, "run_cut", fake_cut)
    monkeypatch.setattr(web_api, "analyze_audio", lambda **kwargs: pytest.fail("normalization must stay opt-in"))

    response = TestClient(app).post(
        "/api/projects/current/export",
        json={"output_path": str(tmp_path / "daily_cut.mp4")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "output_path": str(tmp_path / "daily_cut.mp4"),
        "cut_output_path": str(tmp_path / "daily_cut.mp4"),
        "normalized": False,
    }
    assert exported["input_video"] == source


def test_cut_export_can_normalize_completed_cut_without_overwriting_it(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.project_path = None
    measurement = LoudnessMeasurement(-20.0, -3.0, 8.0, -30.0, 0.1)
    calls: dict[str, object] = {}

    def fake_cut(**kwargs) -> Path:
        kwargs["output_video"].write_bytes(b"cut")
        return kwargs["output_video"]

    def fake_analyze(**kwargs) -> LoudnessMeasurement:
        calls["analyze"] = kwargs
        return measurement

    def fake_normalize(**kwargs) -> Path:
        calls["normalize"] = kwargs
        kwargs["output_video"].write_bytes(b"normalized")
        return kwargs["output_video"]

    monkeypatch.setattr(web_api, "run_cut", fake_cut)
    monkeypatch.setattr(web_api, "analyze_audio", fake_analyze)
    monkeypatch.setattr(web_api, "normalize_video_audio", fake_normalize)
    cut_path = tmp_path / "daily_cut.mp4"

    response = TestClient(app).post(
        "/api/projects/current/export",
        json={
            "output_path": str(cut_path),
            "normalize_audio": True,
            "normalization_preset_id": "gentle",
        },
    )

    normalized_path = tmp_path / "daily_cut_normalized.mp4"
    assert response.status_code == 200
    assert response.json() == {
        "output_path": str(normalized_path),
        "cut_output_path": str(cut_path),
        "normalized": True,
    }
    assert calls["analyze"]["input_video"] == cut_path
    assert calls["normalize"]["input_video"] == cut_path
    assert calls["normalize"]["output_video"] == normalized_path
    assert cut_path.read_bytes() == b"cut"


def test_cut_export_preserves_cut_path_when_normalization_fails(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    original = _project()
    state.project = TranscriptProject(str(source), original.fps, original.words, original.silence_ranges)
    state.edits = EditDecisionList()
    state.project_path = None
    cut_path = tmp_path / "daily_cut.mp4"

    def fake_cut(**kwargs) -> Path:
        kwargs["output_video"].write_bytes(b"cut")
        return kwargs["output_video"]

    monkeypatch.setattr(web_api, "run_cut", fake_cut)
    monkeypatch.setattr(web_api, "analyze_audio", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bad audio")))

    response = TestClient(app).post(
        "/api/projects/current/export",
        json={"output_path": str(cut_path), "normalize_audio": True},
    )

    assert response.status_code == 500
    assert str(cut_path) in response.json()["detail"]
    assert "normalization failed" in response.json()["detail"]
    assert cut_path.read_bytes() == b"cut"


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
