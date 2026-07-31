from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.core.creator_rendering import (
    _element_markup,
    _event_timeline_line,
    _frame_exact_duration_text,
    assemble_verified_chapters,
    assert_chapter_stream_compatibility,
    chapter_cache_key,
    creator_renderer_environment,
    hyperframes_chapter_render_command,
    plan_chapter_renders,
    probe_video_identity,
    resolve_creator_renderer_assets,
)
from app.core.creator_production import canonical_hash, locked_audio_stream_hash
from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe
from app.core.file_utils import sha256_file


SHA = "a" * 64


def test_frame_duration_never_rounds_past_the_half_open_end_frame() -> None:
    nonterminating = _frame_exact_duration_text(
        1577,
        fps_numerator=30,
        fps_denominator=1,
    )
    assert nonterminating == "52.566666666"
    assert float(nonterminating) * 30 < 1577
    assert float(nonterminating) * 30 > 1576
    assert (
        _frame_exact_duration_text(
            12,
            fps_numerator=30,
            fps_denominator=1,
        )
        == "0.400000000"
    )


def test_graph_element_styles_are_allowlisted_and_escaped() -> None:
    markup = _element_markup(
        {
            "id": "headline",
            "kind": "text",
            "zIndex": 2,
            "geometry": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2},
            "properties": {
                "text": "Evidence > decoration",
                "style": {
                    "background": "linear-gradient(90deg, #007C7D, #FF00CE)",
                    "color": "#FFFFFF",
                    "fontSize": "42px",
                },
            },
        },
        {},
        dom_id="seq--headline",
    )
    assert "linear-gradient" in markup
    assert "Evidence &gt; decoration" in markup
    with pytest.raises(ValueError, match="not admitted"):
        _element_markup(
            {
                "id": "unsafe",
                "kind": "text",
                "zIndex": 1,
                "geometry": {"x": 0, "y": 0, "width": 0.2, "height": 0.2},
                "properties": {"text": "x", "style": {"position": "fixed"}},
            },
            {},
            dom_id="seq--unsafe",
        )


def test_speaker_source_events_can_target_the_real_video_element() -> None:
    line = _event_timeline_line(
        {
            "targetElementId": "speaker-source",
            "operation": "move",
            "absoluteFrame": 30,
            "durationFrames": 15,
            "easing": "power3.out",
            "parameters": {
                "to": {"xPercent": -20, "scale": 0.8},
                "resolvedGeometry": {"x": 0, "y": 0.1, "width": 0.8, "height": 0.8},
            },
        },
        chapter_start=0,
        fps=30,
        target_dom_id="main-video",
    )
    assert '[id=\\"main-video\\"]' in line
    assert "xPercent" in line


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir()
    (root / ".vcg-private").write_text("private", encoding="utf-8")
    return root


def _build_lock() -> dict:
    return {
        "schemaVersion": 1,
        "episodeId": "episode",
        "manifestRevision": 1,
        "manifestHash": SHA,
        "workflowLockHash": SHA,
        "lockedCutSha256": SHA,
        "lockedAudioSha256": "",
        "transcriptSha256": SHA,
        "wordTimingSha256": SHA,
        "resolvedProfileHash": SHA,
        "runtime": {
            "hyperframesCliVersion": "0.7.54",
            "hyperframesCliHash": SHA,
            "compilerVersion": "1",
            "compilerHash": SHA,
            "producerAdapterVersion": "1",
            "producerAdapterHash": SHA,
            "capabilityCatalogSnapshotHash": SHA,
            "transitionSourceHashes": {},
            "transitionRuntimeRegistryHash": SHA,
        },
        "sequences": [{"sequenceId": "s1"}],
        "chapters": [
            {
                "chapterId": "chapter-one",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 90,
                "chapterInputHash": SHA,
            }
        ],
        "createdAt": "now",
        "buildHash": SHA,
    }


def _renderer_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    browser_tree = repository / "assets" / "browser"
    browser = browser_tree / "chrome.exe"
    ffmpeg = repository / "tools" / "ffmpeg.exe"
    ffprobe = repository / "tools" / "ffprobe.exe"
    package_root = repository / "assets" / "hyperframes"
    package = package_root / "package.json"
    cli = package_root / "dist" / "cli.js"
    gsap = repository / "assets" / "gsap.min.js"
    for path, content in (
        (browser, b"browser"),
        (ffmpeg, b"ffmpeg"),
        (ffprobe, b"ffprobe"),
        (cli, b"cli"),
        (gsap, b"gsap"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text(json.dumps({"version": "0.7.54"}), encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "hyperframesVersion": "0.7.54",
        "chromeBuild": "test",
        "trees": {
            "hyperframesPackage": {
                "path": package_root.relative_to(repository).as_posix(),
                "fileCount": 2,
                "sha256": canonical_hash(
                    [
                        {
                            "path": item.relative_to(package_root).as_posix(),
                            "bytes": item.stat().st_size,
                            "sha256": sha256_file(item),
                        }
                        for item in sorted(
                            package_root.rglob("*"),
                            key=lambda value: value.relative_to(package_root).as_posix(),
                        )
                        if item.is_file()
                    ]
                ),
            },
            "browserBundle": {
                "path": browser_tree.relative_to(repository).as_posix(),
                "fileCount": 1,
                "sha256": canonical_hash(
                    [
                        {
                            "path": browser.name,
                            "bytes": browser.stat().st_size,
                            "sha256": sha256_file(browser),
                        }
                    ]
                ),
            },
        },
        "assets": {
            "browser": {
                "path": browser.relative_to(repository).as_posix(),
                "sha256": sha256_file(browser),
            },
            "hyperframesCli": {
                "path": cli.relative_to(repository).as_posix(),
                "sha256": sha256_file(cli),
            },
            "gsap": {
                "path": gsap.relative_to(repository).as_posix(),
                "sha256": sha256_file(gsap),
            },
            "ffmpeg": {
                "path": ffmpeg.relative_to(repository).as_posix(),
                "sha256": sha256_file(ffmpeg),
            },
            "ffprobe": {
                "path": ffprobe.relative_to(repository).as_posix(),
                "sha256": sha256_file(ffprobe),
            },
        },
    }
    manifest_path = repository / "app" / "private-renderer-assets" / "renderer-assets.v1.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return repository


def test_renderer_environment_uses_only_hash_checked_local_assets(tmp_path: Path) -> None:
    repository = _renderer_repository(tmp_path)
    assets = resolve_creator_renderer_assets(repository)
    environment = creator_renderer_environment(repository)
    assert environment["HYPERFRAMES_BROWSER_PATH"] == str(assets["browser"])
    assert environment["PRODUCER_HEADLESS_SHELL_PATH"] == str(assets["browser"])
    expected_tool_directories = list(
        dict.fromkeys(
            [str(assets["ffmpeg"].parent), str(assets["ffprobe"].parent)]
        )
    )
    assert environment["PATH"].split(os.pathsep)[: len(expected_tool_directories)] == (
        expected_tool_directories
    )


def test_renderer_environment_rejects_changed_asset_bytes(tmp_path: Path) -> None:
    repository = _renderer_repository(tmp_path)
    (repository / "assets" / "browser" / "chrome.exe").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="tree identity changed: browserBundle"):
        resolve_creator_renderer_assets(repository)


def test_chapter_cache_key_changes_only_with_render_dependencies() -> None:
    chapter = _build_lock()["chapters"][0]
    first = chapter_cache_key(
        chapter,
        render_profile={"quality": "high"},
        hyperframes_cli_hash=SHA,
        producer_adapter_hash=SHA,
    )
    second = chapter_cache_key(
        chapter,
        render_profile={"quality": "standard"},
        hyperframes_cli_hash=SHA,
        producer_adapter_hash=SHA,
    )
    assert first != second


def test_render_plan_reuses_only_verified_exact_cache(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    composition = root / "compositions" / "chapter-one.html"
    composition.parent.mkdir()
    composition.write_text("<html></html>", encoding="utf-8")
    jobs = plan_chapter_renders(
        root,
        build_lock=_build_lock(),
        composition_paths={"chapter-one": composition},
        render_profile={"quality": "high"},
    )
    assert jobs[0]["expectedFrameCount"] == 90
    assert jobs[0]["cacheStatus"] == "miss"
    jobs[0]["outputPath"].parent.mkdir(parents=True)
    jobs[0]["outputPath"].write_bytes(b"render")
    jobs[0]["receiptPath"].write_text(
        json.dumps(
            {
                "cacheKey": jobs[0]["cacheKey"],
                "chapterInputHash": SHA,
                "outputSha256": __import__("hashlib").sha256(b"render").hexdigest(),
                "status": "verified",
            }
        ),
        encoding="utf-8",
    )
    cached = plan_chapter_renders(
        root,
        build_lock=_build_lock(),
        composition_paths={"chapter-one": composition},
        render_profile={"quality": "high"},
    )
    assert cached[0]["cacheStatus"] == "verified-hit"


def test_hyperframes_render_command_has_explicit_composition_and_no_skill_router(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    composition = project / "compositions" / "chapter.html"
    composition.parent.mkdir(parents=True)
    composition.write_text("", encoding="utf-8")
    command = hyperframes_chapter_render_command(
        node_executable=Path("node"),
        hyperframes_cli=Path("hyperframes.js"),
        project_directory=project,
        composition_path=composition,
        output_path=tmp_path / "chapter.mp4",
        fps="30000/1001",
        quality="high",
    )
    assert command[command.index("--composition") + 1] == "compositions/chapter.html"
    assert "--strict" in command
    assert "--skill" not in command


def test_chapter_assembly_rejects_stream_mismatch() -> None:
    base = {
        "chapterId": "a",
        "videoIdentity": {
            "codec": "h264",
            "width": 1920,
            "height": 1080,
            "pixelFormat": "yuv420p",
            "rFrameRate": "30/1",
        },
    }
    changed = json.loads(json.dumps(base))
    changed["chapterId"] = "b"
    changed["videoIdentity"]["width"] = 1280
    with pytest.raises(RuntimeError, match="incompatible"):
        assert_chapter_stream_compatibility([base, changed])


def test_lossless_chapter_assembly_preserves_frames_and_locked_audio(tmp_path: Path) -> None:
    if find_ffprobe() is None:
        pytest.skip("FFprobe is required for the codec proof.")
    root = _private_root(tmp_path)
    source = root / "locked.mp4"
    generated = subprocess.run(
        [
            str(find_ffmpeg()),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x112233:s=320x180:r=30:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.4",
            "-frames:v",
            "12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    receipts = []
    for index, (start, end) in enumerate(((0, 6), (6, 12)), start=1):
        chapter = root / f"chapter-{index}.mp4"
        split = subprocess.run(
            [
                str(find_ffmpeg()),
                "-y",
                "-i",
                str(source),
                "-vf",
                f"select='between(n\\,{start}\\,{end - 1})',setpts=N/FRAME_RATE/TB",
                "-frames:v",
                str(end - start),
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "16",
                "-preset",
                "medium",
                "-pix_fmt",
                "yuv420p",
                str(chapter),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert split.returncode == 0, split.stderr
        receipts.append(
            {
                "chapterId": f"chapter-{index}",
                "status": "verified",
                "outputRelativePath": chapter.relative_to(root).as_posix(),
                "outputSha256": sha256_file(chapter),
                "receiptHash": SHA,
                "videoIdentity": probe_video_identity(chapter),
            }
        )
    locked_audio_hash = locked_audio_stream_hash(source)
    receipt = assemble_verified_chapters(
        root,
        receipts=receipts,
        locked_audio_source=source,
        destination=root / "delivered.mp4",
        expected_total_frames=12,
        expected_locked_audio_sha256=locked_audio_hash,
        provenance={
            "workflowLockHash": SHA,
            "resolvedProfileHash": SHA,
            "capabilityCatalogSnapshotHash": SHA,
            "manifestHash": SHA,
            "buildHash": SHA,
            "lockedCutSha256": SHA,
            "transcriptSha256": SHA,
            "wordTimingSha256": SHA,
            "runtime": {},
            "renderConfiguration": {},
            "browserPreflightIndexHash": SHA,
        },
    )
    assert receipt["videoIdentity"]["frameCount"] == 12
    assert receipt["seamValidation"]["passed"] is True
    assert len(receipt["seamValidation"]["boundaries"]) == 1
    assert locked_audio_stream_hash(root / "delivered.mp4") == locked_audio_hash
