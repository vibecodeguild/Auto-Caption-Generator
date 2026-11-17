from dataclasses import replace
import math
import wave
from array import array

import pytest

from app.core.audio_boundary import suggest_word_start_boundaries
from app.core.audio_waveform import peaks_from_wav, waveform_window
from app.core.edit_decisions import EditDecisionList
from app.core.project_store import save_editor_project, load_editor_project
from app.core.splice_generation import generate_splices, InvalidCutPlanError
from app.core.splice_preview import source_splice_preview_segments
from app.core.transcript_model import TranscriptProject, TranscriptWord


def project():
    return TranscriptProject("source.mp4", 30., [
        TranscriptWord("w1", " first", "first", 0., 1., 0, 29, 1),
        TranscriptWord("w2", " last", "last", 2., 3., 60, 89, 1),
    ], [], {"boundary_review_version": 1, "source_maximum_frame": 119})


def test_start_and_end_are_single_sided_and_persist_adjustments(tmp_path):
    source = project()
    edits = EditDecisionList()
    start, end = generate_splices(source, edits).splices
    assert (start.kind, end.kind) == ("front_trim", "end_trim")
    assert start.left_keep_range_id == end.right_keep_range_id == ""
    edits.adjust_splice(start.anchor_key, right_in_delta=3, reviewed=True)
    edits.set_final_out_frame(100)
    edits.adjust_splice(end.anchor_key, reviewed=True)
    path = tmp_path / "project.json"
    save_editor_project(path, source, edits)
    reopened, restored = load_editor_project(path)
    plan = generate_splices(reopened, restored)
    assert plan.export_intervals() == [(3, 100)]
    assert all(splice.reviewed for splice in plan.splices)


def test_end_assistance_and_custom_end_keep_original_timing_separate():
    source, edits = project(), EditDecisionList()
    edits.set_assisted_out_frame("w2->END", 95)
    end = generate_splices(source, edits).splices[-1]
    assert (end.left_whisper_out_frame, end.left_suggested_out_frame, end.left_out_frame) == (89, 95, 95)
    edits.set_final_out_frame(98)
    assert generate_splices(source, edits).splices[-1].left_out_frame == 98


def test_endpoint_safety_rejects_collapsed_ranges_and_outside_media():
    source, edits = project(), EditDecisionList()
    edits.set_final_out_frame(120)
    with pytest.raises(InvalidCutPlanError):
        generate_splices(source, edits)
    edits.set_final_out_frame(2)
    edits.adjust_splice("START->w1", right_in_delta=3)
    with pytest.raises(InvalidCutPlanError):
        generate_splices(source, edits)


def test_end_assistance_cannot_reinclude_deleted_trailing_words():
    source, edits = project(), EditDecisionList()
    edits.delete_word_selection("w2", "w2")
    edits.set_assisted_out_frame("w1->END", 61)
    with pytest.raises(InvalidCutPlanError):
        generate_splices(source, edits)


def test_endpoint_auditions_use_existing_lengths():
    start, end = generate_splices(project(), EditDecisionList()).splices
    assert source_splice_preview_segments(start, fps=30, seconds=4) == [(0., 4.)]
    segments = source_splice_preview_segments(end, fps=30, seconds=2)
    assert len(segments) == 1
    assert segments[0][0] == 1.
    segments = source_splice_preview_segments(end, fps=30, seconds=6, minimum_frame=60)
    assert segments[0][0] == 2.
    segments = source_splice_preview_segments(start, fps=30, seconds=6, maximum_frame=29)
    assert segments == [(0., 1.)]


def write_audio(path, *, onset=.5, quiet_onset=None):
    samples = array("h")
    for index in range(16000):
        time = index / 16000
        amplitude = 0 if time < onset else 9000
        if quiet_onset is not None and quiet_onset <= time < onset:
            amplitude = 200
        samples.append(int(amplitude * math.sin(2 * math.pi * 220 * time)))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(samples.tobytes())


def test_in_assistance_trims_half_second_of_quiet_and_preserves_soft_onset(tmp_path):
    path = tmp_path / "audio.wav"
    write_audio(path)
    assert suggest_word_start_boundaries(project(), path, {"w1"}) == {"w1": 15}
    write_audio(path, quiet_onset=.4)
    assert suggest_word_start_boundaries(project(), path, {"w1"}) == {"w1": 12}


def test_in_assistance_never_moves_earlier_or_skips_initial_sound(tmp_path):
    path = tmp_path / "audio.wav"
    write_audio(path, onset=0.)
    assert suggest_word_start_boundaries(project(), path, {"w1"}) == {"w1": None}


def test_waveform_cache_is_independent_and_invalidates_on_source_change(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"first source")
    calls = []
    def extract(_source, target):
        calls.append(target)
        write_audio(target)
        return target
    monkeypatch.setattr("app.core.audio_waveform.extract_audio", extract)
    first = waveform_window(source, tmp_path / "cache", 0., 1.)
    assert len(first["peaks"]) == 100
    assert first["peaks"][0] == [0., 0.]
    waveform_window(source, tmp_path / "cache", .1, .6)
    assert len(calls) == 1
    source.write_bytes(b"changed source")
    second = waveform_window(source, tmp_path / "cache", 0., 1.)
    assert len(calls) == 2
    assert first["sourceKey"] != second["sourceKey"]


def set_api_project(monkeypatch, tmp_path):
    from app import web_api
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(web_api.state, "project", replace(project(), source=str(source)))
    monkeypatch.setattr(web_api.state, "edits", EditDecisionList())
    monkeypatch.setattr(web_api.state, "project_path", None)
    monkeypatch.setattr(web_api.state, "video_project_path", None)
    monkeypatch.setattr(web_api.state, "video_project", None)
    return web_api


def test_fine_tune_includes_start_end_and_preserves_review_and_manual_values(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    api = set_api_project(monkeypatch, tmp_path)
    audio = tmp_path / "audio.wav"
    write_audio(audio)
    monkeypatch.setattr(api, "extract_audio", lambda *_args: audio)
    monkeypatch.setattr(api, "suggest_word_end_boundaries", lambda *_args: {"w2": 95})
    monkeypatch.setattr(api, "suggest_word_start_boundaries", lambda *_args: {"w1": 15})
    client = TestClient(api.app)
    response = client.post("/api/projects/current/analyze-boundaries")
    assert response.status_code == 200
    assert response.json()["fine_tune_summary"] == {"cuts_checked": 2, "cuts_adjusted": 2, "cuts_unchanged": 0}
    start, end = response.json()["splices"]
    assert (start["right_in_frame"], end["left_out_frame"]) == (15, 95)
    client.post("/api/projects/current/splices/review", json={"anchor_key": start["anchor_key"], "reviewed": True})
    client.post("/api/projects/current/splices/adjust", json={"anchor_key": end["anchor_key"], "left_delta": 3, "right_delta": 0})
    data = client.post("/api/projects/current/analyze-boundaries").json()
    assert data["fine_tune_summary"]["cuts_checked"] == 1
    assert (data["splices"][0]["right_in_frame"], data["splices"][-1]["left_out_frame"]) == (15, 98)


def test_endpoint_adjustment_rejects_missing_side_and_source_overrun(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    api = set_api_project(monkeypatch, tmp_path)
    client = TestClient(api.app)
    end = client.get("/api/projects/current").json()["splices"][-1]
    for left, right in [(0, 1), (100, 0)]:
        response = client.post("/api/projects/current/splices/adjust",
                               json={"anchor_key": end["anchor_key"], "left_delta": left, "right_delta": right})
        assert response.status_code == 400
    assert api.state.edits.final_out_frame is None


def test_waveform_api_rejects_stale_project_source_without_reading_it(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    api = set_api_project(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "waveform_window", lambda *_args: pytest.fail("must reject stale source first"))
    response = TestClient(api.app).get("/api/projects/current/waveform", params={"source": "other.mp4", "start": 0, "end": 2})
    assert response.status_code == 409
