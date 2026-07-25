from __future__ import annotations

from pathlib import Path

import pytest

from app.core import video_project


def _create(tmp_path: Path, monkeypatch) -> tuple[Path, dict]:
    source = tmp_path / "recording.mp4"
    source.write_bytes(b"raw-video")
    checkout = tmp_path / "public-checkout"
    checkout.mkdir()
    monkeypatch.setattr(video_project, "project_root", lambda: checkout)
    monkeypatch.setattr(video_project, "probe_source_clip", lambda path: {
        "durationSec": 2.0, "videoCodec": "h264", "width": 1920, "height": 1080,
        "pixelFormat": "yuv420p", "frameRate": "30/1", "audioCodec": "aac",
        "audioSampleRate": 48000, "audioChannels": 2,
    })
    monkeypatch.setattr(video_project, "_run_ffmpeg", lambda command, message: Path(command[-1]).write_bytes(b"sequence"))
    return video_project.create_video_project(source, workspace_root=tmp_path / "private")


def test_create_video_project_copies_source_and_creates_portable_manifest(tmp_path: Path, monkeypatch) -> None:
    manifest_path, manifest = _create(tmp_path, monkeypatch)
    response = video_project.video_project_response(manifest_path, manifest)

    assert manifest_path.name == "project.vcg-project.json"
    assert Path(response["resolvedPaths"]["sourceVideo"]).read_bytes() == b"sequence"
    assert Path(response["resolvedPaths"]["editorProject"]).parent.name == "transcripts"
    assert Path(response["resolvedPaths"]["originalTranscript"]).name == "original-generated.vcg.json"
    assert Path(response["resolvedPaths"]["finalReviewedProject"]).name == "editor-final-reviewed.vcg.json"
    assert Path(response["resolvedPaths"]["editAnalysis"]).name == "edit-analysis.json"
    assert Path(response["resolvedPaths"]["visualPlan"]).parent.name == "visual-production"
    assert Path(response["resolvedPaths"]["finalVideo"]).name == "final-video.mp4"
    assert (manifest_path.parent / ".vcg-private").is_file()
    assert manifest["sourceSequence"][0]["startSec"] == 0
    assert manifest["sequenceBuild"]["mode"] == "stream-copy"


def test_video_project_paths_cannot_escape_private_root(tmp_path: Path, monkeypatch) -> None:
    manifest_path, manifest = _create(tmp_path, monkeypatch)
    manifest["paths"]["lockedCut"] = "../escaped.mp4"

    with pytest.raises(ValueError, match="escapes its private root"):
        video_project.save_video_project(manifest_path, manifest)


def test_visual_prompt_contains_exact_paths_rules_and_approval_gate(tmp_path: Path, monkeypatch) -> None:
    manifest_path, manifest = _create(tmp_path, monkeypatch)
    prompt = video_project.build_visual_plan_prompt(manifest_path, manifest)

    assert str(video_project.resolve_video_project_path(manifest_path, manifest, "lockedCut")) in prompt
    assert str(video_project.resolve_video_project_path(manifest_path, manifest, "editorProject")) in prompt
    assert "Never reveal punchlines" in prompt
    assert "Reuse-first and variety gate" in prompt
    assert "candidateTreatmentIds" in prompt
    assert "Speaker-safety gate" in prompt
    assert "overlayOcclusionBounds" in prompt
    assert "Creator Library index" in prompt
    assert "B-roll gate" in prompt
    assert "coverage.bRollAudit.decision" in prompt
    assert "Do not build cues, modify visual-plan.json, or render motion/full-production scenes yet" in prompt
    assert "Single Cook operation" in prompt
    assert "every rolling five-second interval" in prompt
    assert "meaningfulChanges" in prompt
    assert "exactly one representative sample frame" in prompt
    assert "Wait for creator approval" in prompt
    assert "must remain inside the private project root" in prompt


def test_preferred_source_advances_from_original_to_locked_cut(tmp_path: Path, monkeypatch) -> None:
    manifest_path, manifest = _create(tmp_path, monkeypatch)
    original = video_project.resolve_video_project_path(manifest_path, manifest, "sourceVideo")
    locked = video_project.resolve_video_project_path(manifest_path, manifest, "lockedCut")

    assert video_project.preferred_stage_source(manifest_path, manifest) == original
    locked.write_bytes(b"locked")
    video_project.mark_artifact_current(manifest, "lockedCutRevision")
    assert video_project.preferred_stage_source(manifest_path, manifest) == locked


def test_same_camera_clips_use_fast_concat_and_record_boundaries(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "part-one.mp4"
    second = tmp_path / "part-two.mp4"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(video_project, "project_root", lambda: checkout)
    durations = {"part-one.mp4": 3.5, "part-two.mp4": 5.25}
    monkeypatch.setattr(video_project, "probe_source_clip", lambda path: {
        "durationSec": durations[path.name.replace("001-", "").replace("002-", "")],
        "videoCodec": "h264", "width": 1920, "height": 1080, "pixelFormat": "yuv420p",
        "frameRate": "30/1", "audioCodec": "aac", "audioSampleRate": 48000, "audioChannels": 2,
    })
    commands = []
    monkeypatch.setattr(video_project, "_run_ffmpeg", lambda command, message: (commands.append(command), Path(command[-1]).write_bytes(b"joined")))

    _path, manifest = video_project.create_video_project_from_sources([first, second], workspace_root=tmp_path / "private")

    assert manifest["sequenceBuild"]["mode"] == "stream-copy"
    assert [clip["startSec"] for clip in manifest["sourceSequence"]] == [0.0, 3.5]
    assert commands[-1][commands[-1].index("-c") + 1] == "copy"


def test_rebuilding_sequence_invalidates_downstream_artifact_revisions(tmp_path: Path, monkeypatch) -> None:
    manifest_path, manifest = _create(tmp_path, monkeypatch)
    video_project.mark_artifact_current(manifest, "lockedCutRevision")
    previous_revision = manifest["sequenceRevision"]

    updated = video_project.reorder_source_clips(manifest_path, manifest, [manifest["sourceSequence"][0]["id"]])

    assert updated["sequenceRevision"] == previous_revision + 1
    assert not video_project.artifact_current(updated, "lockedCutRevision")
