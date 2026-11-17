from __future__ import annotations

import copy
import threading

import pytest
from fastapi.testclient import TestClient

from app import web_api
from app.core import shorts, shorts_jobs
from tests.test_shorts import make_project, plan, prepare, saved


@pytest.fixture
def api(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    monkeypatch.setattr(shorts, "probe_visual_source", lambda _p: {"width": 1920, "height": 1080, "durationSec": 4, "fps": 30})
    monkeypatch.setattr(web_api, "_shorts_project", lambda: project)
    monkeypatch.setattr(web_api, "shorts_jobs", shorts_jobs.ShortsJobs())
    return TestClient(web_api.app), project


def test_shorts_http_source_bound_import_and_manual_create(api):
    client, project = api
    status = client.get("/api/shorts")
    assert status.status_code == 200 and status.json()["ready"]
    brief = client.get("/api/shorts/brief").json()
    payload = brief["planShape"]
    payload["shorts"][0].update(id="agent-short", title="Agent candidate")
    payload["shorts"][0]["sections"] = [{"id": "part", "startWordId": "w1", "endWordId": "w1"}]
    response = client.post("/api/shorts/import", json=payload)
    assert response.status_code == 200
    assert response.json()["shorts"][0]["sections"][0]["endFrameExclusive"] == 30
    response = client.post("/api/shorts", json=plan(project))
    assert response.status_code == 200 and len(response.json()["shorts"]) == 2


def test_shorts_http_rejects_bad_frames_and_stale_updates(api):
    client, project = api
    payload = plan(project)
    payload["shorts"][0]["sections"][0]["endFrameExclusive"] = 999
    assert client.post("/api/shorts", json=payload).status_code == 400
    client.post("/api/shorts", json=plan(project))
    assert client.put("/api/shorts/sample", json={"revision": 0, "title": "Stale"}).status_code == 400
    assert client.get("/api/shorts/sample/media/assembly").status_code == 400


def test_shorts_http_posting_import_requires_current_caption_hash(api, monkeypatch):
    client, project = api
    prepare(project, monkeypatch)
    brief = client.get("/api/shorts/sample/posting-brief").json()
    payload = brief["responseShape"]
    payload["posting"] = {p: {"title": "A title", "text": f"Copy for {p}"} for p in shorts.PLATFORMS}
    wrong = copy.deepcopy(payload)
    wrong["captionSha256"] = "wrong"
    assert client.post("/api/shorts/sample/posting-import", json=wrong).status_code == 400
    assert client.post("/api/shorts/sample/posting-import", json=payload).status_code == 200
    assert client.get("/api/shorts/sample/posting-package").json()["posting"]["YouTube"]["text"] == "Copy for YouTube"
    assert "short-owned" in str(brief["transcript"])


def test_duplicate_jobs_reconnect_and_cancel_only_the_selected_job(api, monkeypatch):
    client, project = api
    project.add(plan(project))
    started = threading.Event()
    def wait_for_cancel(_project, _short, _operation, job):
        started.set()
        job.cancel.wait(5)
        job.check()
        return {}
    monkeypatch.setattr(shorts_jobs, "execute", wait_for_cancel)
    first = client.post("/api/shorts/sample/jobs", json={"operation": "assemble"}).json()
    assert started.wait(2)
    second = client.post("/api/shorts/sample/jobs", json={"operation": "assemble"}).json()
    assert first["id"] == second["id"]
    assert client.post("/api/shorts/sample/jobs", json={"operation": "export"}).status_code == 400
    assert client.post("/api/shorts/sample/jobs/not-this-job/cancel").status_code == 400
    response = client.post(f"/api/shorts/sample/jobs/{first['id']}/cancel")
    assert response.status_code == 200 and response.json()["status"] == "canceling"
    live = web_api.shorts_jobs.jobs[(str(project.root), "sample")]
    # Completion is bounded; this is a test worker, never an application server.
    for _ in range(100):
        if live.snapshot()["status"] == "canceled": break
        threading.Event().wait(.01)
    assert live.snapshot()["status"] == "canceled"
