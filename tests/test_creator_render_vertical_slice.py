from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.creator_production import canonical_hash, compile_episode_manifest
from app.core.creator_rendering import (
    build_chapter_compositions,
    creator_renderer_environment,
    hyperframes_chapter_render_command,
    probe_video_identity,
    resolve_creator_renderer_assets,
)
from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe


SHA = "a" * 64


def test_source_led_chapter_renders_exact_frame_count(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    cli = resolve_creator_renderer_assets(repository)["hyperframesCli"]
    node = shutil.which("node")
    ffprobe = find_ffprobe()
    if not node or not cli.is_file() or ffprobe is None:
        pytest.skip("Pinned HyperFrames runtime is unavailable.")
    root = tmp_path / "private"
    root.mkdir()
    (root / ".vcg-private").write_text("private", encoding="utf-8")
    locked = root / "locked.mp4"
    generated = subprocess.run(
        [
            str(find_ffmpeg()),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x224466:s=320x180:r=30:d=0.4",
            "-frames:v",
            "12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(locked),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    manifest = {
        "schemaVersion": 1,
        "episodeId": "vertical-slice",
        "revision": 1,
        "state": "MATERIALIZING",
        "workflowLockHash": SHA,
        "lockedCutSha256": SHA,
        "lockedAudioSha256": "",
        "transcriptSha256": SHA,
        "wordTimingSha256": SHA,
        "fps": {"numerator": 30, "denominator": 1},
        "canvas": {"width": 320, "height": 180},
        "totalFrames": 12,
        "sourceEventAnchors": [],
        "sequences": [
            {
                "id": "sequence-1",
                "chapterId": "chapter-1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 12,
                "startWordId": None,
                "endWordId": None,
                "conceptId": "concept-1",
                "seriesId": None,
                "callbackTo": None,
                "propositionId": "proposition-1",
                "semanticBeatKind": "source",
                "editorialJob": "establish-speaker",
                "semanticForm": "source-footage",
                "presentationRole": "source-led",
                "narrativeStateRole": "establish",
                "sourceImplementationMode": "source-pass-through",
                "selectedCanvasTopology": "full-source",
                "selectedCapabilityBindings": [],
                "assetRequirements": [],
                "resolvedAssetRefs": [],
                "resolvedImplementationSetRef": {"source": "locked-cut"},
                "consumedProfileDependencies": {
                    "tokenPaths": [],
                    "fontIds": [],
                    "policyIds": [],
                    "thresholdIds": [],
                    "preferenceIds": [],
                    "referenceGrammarFields": [],
                },
                "compositionGraph": {
                    "elements": [
                        {
                            "id": "speaker",
                            "kind": "video",
                            "parentId": None,
                            "zIndex": 0,
                            "geometry": {"x": 0, "y": 0, "width": 1, "height": 1},
                            "tokenBindings": {},
                            "properties": {"role": "speaker-source", "initiallyVisible": True},
                        }
                    ],
                    "events": [],
                },
                "policyExceptionRefs": [],
                "sourceOverrideRef": None,
                "policyReceiptIds": [],
                "sequenceDecisionReceiptId": "decision:sequence-1:v1",
                "routingConfidence": 1,
                "unresolvedReasons": [],
            }
        ],
        "transitionBoundaries": [],
        "chapters": [
            {
                "id": "chapter-1",
                "editorialSectionId": "section-1",
                "title": "Complete thought",
                "completionRationale": "The test section is complete.",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 12,
            }
        ],
    }
    first_sequence = manifest["sequences"][0]
    first_sequence["absoluteEndFrameExclusive"] = 6
    first_sequence["compositionGraph"]["elements"].append(
        {
            "id": "label",
            "kind": "text",
            "parentId": None,
            "zIndex": 1,
            "geometry": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.2},
            "tokenBindings": {},
            "properties": {"text": "FIRST", "initiallyVisible": True},
        }
    )
    second_sequence = json.loads(json.dumps(first_sequence))
    second_sequence["id"] = "sequence-2"
    second_sequence["absoluteStartFrame"] = 6
    second_sequence["absoluteEndFrameExclusive"] = 12
    second_sequence["conceptId"] = "concept-2"
    second_sequence["propositionId"] = "proposition-2"
    second_sequence["sequenceDecisionReceiptId"] = "decision:sequence-2:v1"
    second_sequence["compositionGraph"]["elements"][1]["properties"]["text"] = "SECOND"
    manifest["sequences"].append(second_sequence)
    manifest["transitionBoundaries"] = [
        {
            "id": "boundary-1",
            "fromSequenceId": "sequence-1",
            "toSequenceId": "sequence-2",
            "mode": "hard-cut",
            "implementationRef": None,
            "durationFrames": 0,
            "overlapFrames": 0,
            "chapterSafetyMargins": {},
            "policyReceiptIds": [],
        }
    ]
    compiled = compile_episode_manifest(manifest, compiler_version="test")
    chapter_input_hash = canonical_hash({"chapter": manifest["chapters"][0]})
    build_lock = {
        "schemaVersion": 1,
        "episodeId": manifest["episodeId"],
        "manifestRevision": 1,
        "manifestHash": canonical_hash(manifest),
        "workflowLockHash": SHA,
        "lockedCutSha256": SHA,
        "lockedAudioSha256": "",
        "transcriptSha256": SHA,
        "wordTimingSha256": SHA,
        "resolvedProfileHash": SHA,
        "runtime": {
            "hyperframesCliHash": SHA,
            "producerAdapterHash": SHA,
        },
        "sequences": [
            {"sequenceId": "sequence-1", "chapterId": "chapter-1"},
            {"sequenceId": "sequence-2", "chapterId": "chapter-1"},
        ],
        "chapters": [
            {
                "chapterId": "chapter-1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 12,
                "chapterInputHash": chapter_input_hash,
            }
        ],
        "createdAt": "test",
        "buildHash": SHA,
    }
    entries = build_chapter_compositions(
        root,
        manifest=manifest,
        compiled=compiled,
        build_lock=build_lock,
        locked_cut=locked,
        repository_root=repository,
    )
    composition_source = entries["chapter-1"].read_text(encoding="utf-8")
    assert 'id="sequence-1--label"' in composition_source
    assert 'id="sequence-2--label"' in composition_source
    assert 'id="sequence--sequence-1"' in composition_source
    assert 'id="sequence--sequence-2"' in composition_source
    output = root / "chapter.mp4"
    command = hyperframes_chapter_render_command(
        node_executable=Path(node),
        hyperframes_cli=cli,
        project_directory=entries["chapter-1"].parent,
        composition_path=entries["chapter-1"],
        output_path=output,
        fps="30/1",
        quality="draft",
        workers="1",
    )
    environment = creator_renderer_environment(repository)
    rendered = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    assert probe_video_identity(output)["frameCount"] == 12
