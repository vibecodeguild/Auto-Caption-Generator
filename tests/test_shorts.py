from __future__ import annotations

import copy
import json
import subprocess
import threading
from pathlib import Path

import pytest

from app.core import shorts
from app.core.shorts import ShortsProject, edit_key, media_hash, read_json, write_json
from app.core.shorts_jobs import ShortsJobs
from app.core.settings import WordTimestamp
from app.core.video_cutter import CutCanceled


class Job:
    def __init__(self):
        import uuid
        self.id = uuid.uuid4().hex
        self.cancel = threading.Event()

    def check(self):
        if self.cancel.is_set():
            raise CutCanceled("Canceled")

    def update(self, *_args):
        pass

    def set_process(self, _process):
        pass


def make_project(tmp_path: Path) -> ShortsProject:
    root = tmp_path / "private-project"
    root.mkdir()
    (root / ".vcg-private").write_text("Private fixture")
    media = root / "exports/locked-cut.mp4"
    media.parent.mkdir()
    media.write_bytes(b"locked cut fixture")
    manifest = root / "project.vcg-project.json"
    write_json(manifest, {"schemaVersion": 1, "id": "test-project", "name": "Public test fixture", "paths": {}})
    write_json(root / "transcripts/final-transcript.json", {
        "project": {"fps": 30, "source": str(media),
                    "generation": {"lockedTranscript": {"lockedCutSha256": media_hash(media)}},
                    "words": [{"id": "w1", "text": "original", "start_frame": 0, "end_frame": 29},
                              {"id": "w2", "text": "long form", "start_frame": 60, "end_frame": 89},
                              {"id": "w3", "text": "transcript", "start_frame": 90, "end_frame": 119}]}})
    return ShortsProject(manifest)


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    monkeypatch.setattr(shorts, "probe_visual_source", lambda _p: {"width": 1920, "height": 1080, "durationSec": 4, "fps": 30})
    return project


def plan(project, *, stitched=False):
    sections = [{"id": "one", "startFrame": 0, "endFrameExclusive": 30}]
    if stitched:
        sections = [{"id": "later", "startFrame": 60, "endFrameExclusive": 120}, *sections]
    return {"schemaVersion": 1, "source": project.source(), "shorts": [{"id": "sample", "title": "A useful short", "sections": sections}]}


def saved(project):
    return project.load()["shorts"][0]


def fake_media(monkeypatch):
    cuts = []
    def cut(**kwargs):
        cuts.append(kwargs["intervals"])
        kwargs["output_video"].write_bytes(b"assembled short")
    def render(command, _work, job):
        job.check()
        Path(command[-1]).write_bytes(b"generated fixture")
    monkeypatch.setattr(shorts, "run_cut", cut)
    monkeypatch.setattr(shorts, "ffmpeg_job", render)
    monkeypatch.setattr(shorts, "verify_video", lambda *_a, **_k: None)
    return cuts


def prepare(project, monkeypatch, stitched=False):
    project.add(plan(project, stitched=stitched))
    cuts = fake_media(monkeypatch)
    calls = []
    def transcribe(path, **kwargs):
        calls.append((path, kwargs))
        return [WordTimestamp("short-owned", .05, .4), WordTimestamp("caption", .5, .9)]
    monkeypatch.setattr(shorts, "transcribe_audio", transcribe)
    shorts.execute(project, saved(project), "captions", Job())
    return cuts, calls


def test_word_anchor_import_preserves_order_and_original_suggestions(project):
    payload = {"schemaVersion": 1, "source": project.source(), "shorts": [{"id": "sample", "title": "A useful short", "sections": [
        {"id": "later", "startWordId": "w2", "endWordId": "w3", "startFrame": 9999},
        {"id": "earlier", "startWordId": "w1", "endWordId": "w1"}]}]}
    project.add(payload, imported=True)
    assert saved(project)["sections"] == [{"id": "later", "startFrame": 60, "endFrameExclusive": 120}, {"id": "earlier", "startFrame": 0, "endFrameExclusive": 30}]
    original_path = project.folder / "shorts-plan.original.json"
    original = original_path.read_bytes()
    project.update("sample", {"revision": 1, "title": "Reviewed title"})
    assert original_path.read_bytes() == original
    assert ShortsProject(project.manifest_path).load()["shorts"][0]["title"] == "Reviewed title"
    assert len(read_json(project.folder / "shorts-edit-ledger.json")["events"]) == 2


@pytest.mark.parametrize("mutation", ["source", "anchor", "duplicate", "version"])
def test_import_rejects_invalid_plans_atomically(project, mutation):
    payload = {"schemaVersion": 1, "source": project.source(), "shorts": [{"id": "sample", "title": "A useful short", "sections": [{"id": "one", "startWordId": "w1", "endWordId": "w1"}]}]}
    if mutation == "source": payload["source"]["lockedCutSha256"] = "wrong"
    if mutation == "anchor": payload["shorts"][0]["sections"][0]["startWordId"] = "missing"
    if mutation == "duplicate": payload["shorts"].append(copy.deepcopy(payload["shorts"][0]))
    if mutation == "version": payload["schemaVersion"] = 999
    with pytest.raises(ValueError): project.add(payload, imported=True)
    assert project.load()["shorts"] == []
    assert not (project.folder / "shorts-plan.original.json").exists()


@pytest.mark.parametrize("start,end", [(-1, 30), (30, 30), (31, 30), (0, 121), (0.5, 30), (True, 30)])
def test_frame_boundaries_are_validated(project, start, end):
    payload = plan(project)
    payload["shorts"][0]["sections"][0].update(startFrame=start, endFrameExclusive=end)
    with pytest.raises(ValueError): project.add(payload)
    assert project.load()["shorts"] == []


def test_path_and_revision_safety(project):
    payload = plan(project)
    payload["shorts"][0]["id"] = "../outside"
    with pytest.raises(ValueError): project.add(payload)
    with pytest.raises(ValueError): project.path("../outside")
    project.add(plan(project))
    with pytest.raises(ValueError, match="changed elsewhere"):
        project.update("sample", {"revision": 0, "title": "Stale edit"})
    assert saved(project)["title"] == "A useful short"


def test_locked_cut_must_match_final_transcript(project):
    (project.root / "exports/locked-cut.mp4").write_bytes(b"different source")
    with pytest.raises(ValueError, match="does not match"):
        project.source()


def test_captions_are_created_from_assembled_audio_and_export_never_transcribes(project, monkeypatch):
    cuts, calls = prepare(project, monkeypatch, stitched=True)
    assert cuts == [[(2., 4.), (0., 1.)]]
    assert len(calls) == 1 and calls[0][0].name == "audio.wav"
    caption = project.caption_document(saved(project))
    assert [w["text"] for w in caption["words"]] == ["short-owned", "caption"]
    assert caption["assemblySha256"] == saved(project)["assembly"]["sha256"]
    before = (project.root / "exports/locked-cut.mp4").read_bytes()
    monkeypatch.setattr(shorts, "transcribe_audio", lambda *_a, **_k: pytest.fail("export must reuse the saved transcript"))
    shorts.execute(project, saved(project), "export", Job())
    assert (project.root / "exports/locked-cut.mp4").read_bytes() == before
    assert project.view()["shorts"][0]["deliveryCurrent"]
    delivery = project.path(saved(project)["delivery"]["path"])
    assert delivery.name == "01-a-useful-short.mp4"
    assert delivery.parent == project.root / "exports/shorts"
    assert delivery.is_file() and delivery.with_name(f"{delivery.stem}-posting.json").is_file()
    assert delivery.with_name(f"{delivery.stem}-posting.txt").is_file()


def test_repeat_exports_preserve_previous_packages_and_skip_sidecar_collisions(project, monkeypatch):
    prepare(project, monkeypatch)
    shorts.execute(project, saved(project), "export", Job())
    previous = saved(project)["delivery"]
    output = project.path(previous["path"])
    original_package = {p: p.read_bytes() for p in output.parent.iterdir()}
    collision = output.with_name("01-a-useful-short-2-posting.txt")
    collision.write_text("keep this file")
    shorts.execute(project, saved(project), "export", Job())
    assert project.path(saved(project)["delivery"]["path"]).name == "01-a-useful-short-3.mp4"
    assert all(path.read_bytes() == content for path, content in original_package.items())
    assert collision.read_text() == "keep this file"
    assert project.view()["shorts"][0]["deliveryCurrent"]


def test_stale_export_does_not_publish_or_replace_previous_delivery(project, monkeypatch):
    prepare(project, monkeypatch)
    shorts.execute(project, saved(project), "export", Job())
    previous = saved(project)["delivery"]
    contents = {p: p.read_bytes() for p in (project.root / "exports/shorts").iterdir()}
    def render(command, _work, job):
        Path(command[-1]).write_bytes(b"late render")
        project.update("sample", {"revision": saved(project)["revision"], "title": "Newer title"})
    monkeypatch.setattr(shorts, "ffmpeg_job", render)
    with pytest.raises(ValueError, match="changed during"):
        shorts.execute(project, saved(project), "export", Job())
    assert saved(project)["delivery"] == previous
    assert {p: p.read_bytes() for p in (project.root / "exports/shorts").iterdir()} == contents


def test_partial_publication_failure_preserves_previous_package(project, monkeypatch):
    prepare(project, monkeypatch)
    shorts.execute(project, saved(project), "export", Job())
    previous = saved(project)["delivery"]
    contents = {p: p.read_bytes() for p in (project.root / "exports/shorts").iterdir()}
    replace = Path.replace
    def fail_posting(path, target):
        if Path(target).name == "01-a-useful-short-2-posting.json":
            raise OSError("fixture publication failure")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail_posting)
    with pytest.raises(OSError, match="publication failure"):
        shorts.execute(project, saved(project), "export", Job())
    assert saved(project)["delivery"] == previous
    assert {p: p.read_bytes() for p in (project.root / "exports/shorts").iterdir()} == contents


@pytest.mark.parametrize("title", ["CON", "../../An unsafe: title?", "你好"])
def test_export_filenames_are_safe_on_windows(project, monkeypatch, title):
    prepare(project, monkeypatch)
    project.update("sample", {"revision": saved(project)["revision"], "title": title})
    shorts.execute(project, saved(project), "export", Job())
    output = project.path(saved(project)["delivery"]["path"])
    assert output.parent == project.root / "exports/shorts"
    assert output.name.startswith("01-")
    assert output.is_file()


def test_title_and_style_keep_captions_but_frame_edits_require_regeneration(project, monkeypatch):
    prepare(project, monkeypatch)
    short = saved(project)
    transcript_path = short["caption"]["path"]
    project.update("sample", {"revision": short["revision"], "title": "A new title"})
    assert project.caption_current(saved(project))
    settings = copy.deepcopy(saved(project)["settings"])
    settings["style"]["active_color"] = "#00FF00"
    project.update("sample", {"revision": saved(project)["revision"], "settings": settings})
    assert project.caption_current(saved(project))
    sections = copy.deepcopy(saved(project)["sections"])
    sections[0]["startFrame"] = 1
    project.update("sample", {"revision": saved(project)["revision"], "sections": sections})
    assert not project.caption_current(saved(project))
    assert project.path(transcript_path).is_file()
    with pytest.raises(ValueError, match="regeneration"):
        shorts.execute(project, saved(project), "export", Job())


def test_late_job_does_not_replace_newer_decisions(project, monkeypatch):
    project.add(plan(project))
    fake_media(monkeypatch)
    snapshot = saved(project)
    def transcribe(_path, **_kwargs):
        project.update("sample", {"revision": snapshot["revision"], "title": "Newer decision"})
        return [WordTimestamp("hello", .1, .8)]
    monkeypatch.setattr(shorts, "transcribe_audio", transcribe)
    with pytest.raises(ValueError, match="changed during"):
        shorts.execute(project, snapshot, "captions", Job())
    assert saved(project)["caption"] is None
    assert saved(project)["title"] == "Newer decision"


def test_cancel_or_failure_preserves_previous_transcript(project, monkeypatch):
    prepare(project, monkeypatch)
    prior = saved(project)["caption"]
    job = Job()
    def transcribe(_path, **_kwargs):
        job.cancel.set()
        return [WordTimestamp("new", .1, .8)]
    monkeypatch.setattr(shorts, "transcribe_audio", transcribe)
    with pytest.raises(CutCanceled): shorts.execute(project, saved(project), "captions", job)
    assert saved(project)["caption"] == prior
    monkeypatch.setattr(shorts, "transcribe_audio", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("test failure")))
    with pytest.raises(RuntimeError): shorts.execute(project, saved(project), "captions", Job())
    assert saved(project)["caption"] == prior


def test_tampered_caption_transcript_cannot_be_exported(project, monkeypatch):
    prepare(project, monkeypatch)
    project.path(saved(project)["caption"]["path"]).write_text('{"words": []}')
    with pytest.raises(ValueError, match="changed"):
        project.caption_document(saved(project))


def test_job_restart_is_reported_as_interrupted(project):
    project.add(plan(project))
    write_json(project.path("shorts/sample/job.json"), {"id": "old-job", "status": "running"})
    receipt = ShortsJobs().active(project, "sample")
    assert receipt["status"] == "failed"
    assert "restarted" in receipt["error"]


def test_subtitle_layout_has_title_above_and_captions_below(project):
    project.add(plan(project))
    ass = shorts.short_ass(saved(project), {"words": [{"text": "caption", "start": .1, "end": .8}]})
    assert r"\pos(540,250)" in ass
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert ",1200,1" in ass
    assert "pad=1080:1920:0:500:black" in shorts.composition_filter()


def test_posting_review_tracks_caption_revision_and_preserves_drafts(project, monkeypatch):
    prepare(project, monkeypatch)
    drafts = {platform: {"title": "Useful title", "text": f"A draft for {platform}."} for platform in shorts.PLATFORMS}
    project.update("sample", {"revision": saved(project)["revision"], "posting": drafts, "reviewPosting": True})
    assert project.view()["shorts"][0]["postingCurrent"]
    shorts.execute(project, saved(project), "captions", Job())
    assert not project.view()["shorts"][0]["postingCurrent"]
    assert saved(project)["posting"] == drafts


def test_empty_posting_package_cannot_be_marked_reviewed(project, monkeypatch):
    prepare(project, monkeypatch)
    with pytest.raises(ValueError, match="each destination"):
        project.update("sample", {"revision": saved(project)["revision"], "posting": saved(project)["posting"], "reviewPosting": True})
    assert not project.posting_current(saved(project))


def test_changed_draft_loses_review_without_affecting_captions(project, monkeypatch):
    prepare(project, monkeypatch)
    drafts = {p: {"title": "A title", "text": "Reviewed content"} for p in shorts.PLATFORMS}
    project.update("sample", {"revision": saved(project)["revision"], "posting": drafts, "reviewPosting": True})
    drafts["YouTube"]["text"] = "Changed content"
    project.update("sample", {"revision": saved(project)["revision"], "posting": drafts})
    assert project.caption_current(saved(project))
    assert not project.posting_current(saved(project))


def test_real_ffmpeg_stitched_order_geometry_and_black_background(tmp_path, monkeypatch):
    """Public generated media verifies actual output, without Whisper or private footage."""
    from app.core.ffmpeg_locator import find_ffmpeg
    project = make_project(tmp_path)
    source = project.root / "exports/locked-cut.mp4"
    ffmpeg = str(find_ffmpeg())
    cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=2", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-f", "lavfi", "-i", "sine=frequency=880:duration=2", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source)]
    result = subprocess.run(cmd, capture_output=True)
    assert result.returncode == 0, result.stderr[-1000:]
    doc_path = project.root / "transcripts/final-transcript.json"
    doc = read_json(doc_path)
    doc["project"]["generation"]["lockedTranscript"]["lockedCutSha256"] = media_hash(source)
    write_json(doc_path, doc)
    project.add(plan(project, stitched=True))
    # Only local speech inference is substituted; assembly, filtering, probing,
    # subtitle burn-in, and publication are the real production code.
    monkeypatch.setattr(shorts, "transcribe_audio", lambda *_a, **_k: [WordTimestamp("A short caption", .1, 2.8)])
    shorts.execute(project, saved(project), "captions", Job())
    shorts.execute(project, saved(project), "export", Job())
    delivery = project.path(saved(project)["delivery"]["path"])
    probe = shorts.probe_visual_source(delivery)
    assert (probe["width"], probe["height"]) == (1080, 1920)
    assert abs(probe["durationSec"] - 3) < .15
    def pixel(time, x, y):
        result = subprocess.run([ffmpeg, "-ss", str(time), "-i", str(delivery), "-vf", f"crop=2:2:{x}:{y},format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
        assert result.returncode == 0
        return tuple(result.stdout[:3])
    blue = pixel(.5, 100, 700)
    red = pixel(2.5, 100, 700)
    black = pixel(.5, 50, 1700)
    assert blue[2] > 180 and blue[0] < 60
    assert red[0] > 180 and red[2] < 60
    assert max(black) < 20
    # Audio must follow the same reversed section order as the picture.
    import array
    import math
    def tone_energy(time, frequency):
        pcm = subprocess.run([ffmpeg, "-ss", str(time), "-i", str(delivery), "-t", "0.1", "-vn", "-ar", "16000", "-ac", "1", "-f", "s16le", "-"], capture_output=True, check=True).stdout
        samples = array.array("h", pcm)
        return abs(sum(v * complex(math.cos(2 * math.pi * frequency * i / 16000), math.sin(2 * math.pi * frequency * i / 16000)) for i, v in enumerate(samples)))
    assert tone_energy(.5, 880) > 5 * tone_energy(.5, 440)
    assert tone_energy(2.5, 440) > 5 * tone_energy(2.5, 880)
    for crop in ("1080:450:0:0", "1080:400:0:1120"):
        pixels = subprocess.run([ffmpeg, "-ss", "0.5", "-i", str(delivery), "-vf", f"crop={crop},format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        assert sum(1 for v in pixels if v > 180) > 500  # Actual title and caption pixels on black.
