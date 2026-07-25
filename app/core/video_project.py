from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.settings import project_root
from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe
from app.core.process_utils import hidden_subprocess_flags


VIDEO_PROJECT_VERSION = 1
VIDEO_PROJECT_SUFFIX = ".vcg-project.json"
DEFAULT_PROJECT_PATHS = {
    "sourceVideo": "working/source-sequence.mp4",
    "editorProject": "transcripts/editor.vcg.json",
    "originalTranscript": "transcripts/original-generated.vcg.json",
    "finalReviewedProject": "transcripts/editor-final-reviewed.vcg.json",
    "finalTranscript": "transcripts/final-transcript.json",
    "editAnalysis": "transcripts/edit-analysis.json",
    "lockedCut": "exports/locked-cut.mp4",
    "captionedCut": "exports/captioned-cut.mp4",
    "visualPlan": "visual-production/visual-plan.json",
    "finalVideo": "exports/final-video.mp4",
    "importedAssets": "assets/imported",
    "generatedAssets": "assets/generated",
    "cutPreviews": "previews/cut",
    "audioPreviews": "previews/audio",
    "visualPreviews": "previews/visual",
}
PROJECT_DIRECTORIES = (
    "source",
    "transcripts",
    "edits",
    "audio",
    "assets/imported",
    "assets/generated",
    "visual-production",
    "working",
    "previews/cut",
    "previews/audio",
    "previews/visual",
    "exports",
)


def default_video_workspace() -> Path:
    configured = os.environ.get("VCG_PRIVATE_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Videos" / "VCG Projects").resolve()


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "video-project"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _unique_root(workspace: Path, name: str) -> Path:
    candidate = workspace / _slug(name)
    index = 2
    while candidate.exists():
        candidate = workspace / f"{_slug(name)}-{index}"
        index += 1
    return candidate


def create_video_project(source_video: Path, *, workspace_root: Path | None = None) -> tuple[Path, dict]:
    return create_video_project_from_sources([source_video], workspace_root=workspace_root)


def create_video_project_from_sources(
    source_videos: list[Path], *, workspace_root: Path | None = None
) -> tuple[Path, dict]:
    sources = [path.expanduser().resolve() for path in source_videos]
    if not sources or any(not path.is_file() for path in sources):
        raise ValueError("Choose one or more existing source videos.")
    workspace = (workspace_root or default_video_workspace()).expanduser().resolve()
    if _is_within(workspace, project_root()):
        raise ValueError("The private video-project workspace must be outside the public Git checkout.")
    workspace.mkdir(parents=True, exist_ok=True)
    root = _unique_root(workspace, sources[0].stem)
    for directory in PROJECT_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / ".vcg-private").write_text(
        "Private VCG video project. Never add this directory to a public repository.\n",
        encoding="utf-8",
    )
    source_sequence = []
    for index, source in enumerate(sources, start=1):
        source_name = f"{index:03d}-{_slug(source.stem)}{source.suffix.lower()}"
        destination = root / "source" / source_name
        shutil.copy2(source, destination)
        source_sequence.append({
            "id": uuid.uuid4().hex[:12],
            "name": source.name,
            "path": destination.relative_to(root).as_posix(),
            "order": index - 1,
            "startSec": 0.0,
            "durationSec": 0.0,
            "metadata": probe_source_clip(destination),
        })
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schemaVersion": VIDEO_PROJECT_VERSION,
        "id": uuid.uuid4().hex,
        "name": sources[0].stem,
        "createdAt": now,
        "updatedAt": now,
        "paths": dict(DEFAULT_PROJECT_PATHS),
        "sourceSequence": source_sequence,
        "sequenceRevision": 0,
        "artifacts": {},
    }
    manifest_path = root / f"project{VIDEO_PROJECT_SUFFIX}"
    build_source_sequence(manifest_path, manifest)
    save_video_project(manifest_path, manifest)
    return manifest_path, manifest


def probe_source_clip(path: Path) -> dict:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise RuntimeError("FFprobe is required to inspect source clips.")
    result = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,profile,level,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,sample_rate,channels",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not inspect source clip {path.name}. {(result.stderr or result.stdout)[-600:]}")
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError(f"Source clip has no video stream: {path.name}")
    return {
        "durationSec": round(float(data["format"]["duration"]), 3),
        "videoCodec": video.get("codec_name"),
        "videoProfile": video.get("profile"),
        "videoLevel": video.get("level"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "pixelFormat": video.get("pix_fmt"),
        "frameRate": video.get("r_frame_rate") or video.get("avg_frame_rate") or "30/1",
        "timeBase": video.get("time_base"),
        "audioCodec": audio.get("codec_name") if audio else None,
        "audioSampleRate": int(audio.get("sample_rate") or 0) if audio else None,
        "audioChannels": int(audio.get("channels") or 0) if audio else None,
    }


def compatibility_report(manifest: dict) -> dict:
    clips = sorted(manifest.get("sourceSequence", []), key=lambda clip: int(clip.get("order", 0)))
    if not clips:
        return {"compatible": False, "mode": "missing", "differences": ["No source clips"]}
    keys = ("videoCodec", "videoProfile", "videoLevel", "width", "height", "pixelFormat", "frameRate", "timeBase", "audioCodec", "audioSampleRate", "audioChannels")
    baseline = clips[0].get("metadata") or {}
    differences = []
    for clip in clips[1:]:
        metadata = clip.get("metadata") or {}
        changed = [key for key in keys if metadata.get(key) != baseline.get(key)]
        if changed:
            differences.append(f"{clip.get('name')}: {', '.join(changed)}")
    return {
        "compatible": not differences,
        "mode": "stream-copy" if not differences else "normalized",
        "differences": differences,
        "baseline": {key: baseline.get(key) for key in keys},
    }


def build_source_sequence(manifest_path: Path, manifest: dict) -> dict:
    root = manifest_path.expanduser().resolve().parent
    clips = sorted(manifest.get("sourceSequence", []), key=lambda clip: int(clip.get("order", 0)))
    if not clips:
        raise ValueError("Add at least one source clip before building the sequence.")
    report = compatibility_report(manifest)
    sequence_sources = [root / clip["path"] for clip in clips]
    if report["compatible"]:
        mode = "stream-copy"
    else:
        mode = "normalized"
        normalized_root = root / "working" / "normalized"
        normalized_root.mkdir(parents=True, exist_ok=True)
        baseline = clips[0]["metadata"]
        sequence_sources = []
        for index, (clip, source) in enumerate(zip(clips, [root / item["path"] for item in clips]), start=1):
            normalized = normalized_root / f"{index:03d}.mp4"
            _normalize_clip(source, normalized, baseline)
            sequence_sources.append(normalized)
            clip["normalizedPath"] = normalized.relative_to(root).as_posix()
    destination = root / manifest["paths"]["sourceVideo"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    concat_file = root / "working" / "source-sequence.txt"
    concat_file.write_text("".join(f"file '{path.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in sequence_sources), encoding="utf-8")
    command = [str(find_ffmpeg()), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", "-fflags", "+genpts", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(destination)]
    _run_ffmpeg(command, "FFmpeg could not assemble the source sequence.")
    cursor = 0.0
    for clip in clips:
        duration = float((clip.get("metadata") or {}).get("durationSec") or clip.get("durationSec") or 0)
        clip["startSec"] = round(cursor, 3)
        clip["durationSec"] = round(duration, 3)
        cursor += duration
    manifest["sourceSequence"] = clips
    manifest["sequenceRevision"] = int(manifest.get("sequenceRevision") or 0) + 1
    manifest["sequenceBuild"] = {"mode": mode, "compatible": report["compatible"], "differences": report["differences"], "durationSec": round(cursor, 3)}
    manifest["artifacts"] = {"sourceSequenceRevision": manifest["sequenceRevision"]}
    return manifest


def add_source_clips(manifest_path: Path, manifest: dict, sources: list[Path]) -> dict:
    root = video_project_root(manifest_path)
    clips = list(manifest.get("sourceSequence", []))
    for source in sources:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"Source clip not found: {source}")
        index = len(clips) + 1
        destination = root / "source" / f"{index:03d}-{_slug(source.stem)}-{uuid.uuid4().hex[:6]}{source.suffix.lower()}"
        shutil.copy2(source, destination)
        clips.append({"id": uuid.uuid4().hex[:12], "name": source.name, "path": destination.relative_to(root).as_posix(), "order": index - 1, "startSec": 0.0, "durationSec": 0.0, "metadata": probe_source_clip(destination)})
    manifest["sourceSequence"] = clips
    build_source_sequence(manifest_path, manifest)
    return save_video_project(manifest_path, manifest)


def reorder_source_clips(manifest_path: Path, manifest: dict, clip_ids: list[str]) -> dict:
    by_id = {clip["id"]: clip for clip in manifest.get("sourceSequence", [])}
    if set(clip_ids) != set(by_id) or len(clip_ids) != len(by_id):
        raise ValueError("Clip order must contain every source clip exactly once.")
    manifest["sourceSequence"] = [{**by_id[clip_id], "order": index} for index, clip_id in enumerate(clip_ids)]
    build_source_sequence(manifest_path, manifest)
    return save_video_project(manifest_path, manifest)


def remove_source_clip(manifest_path: Path, manifest: dict, clip_id: str) -> dict:
    clips = [clip for clip in manifest.get("sourceSequence", []) if clip.get("id") != clip_id]
    if len(clips) == len(manifest.get("sourceSequence", [])):
        raise ValueError("Source clip not found.")
    if not clips:
        raise ValueError("A video project must contain at least one source clip.")
    manifest["sourceSequence"] = [{**clip, "order": index} for index, clip in enumerate(clips)]
    build_source_sequence(manifest_path, manifest)
    return save_video_project(manifest_path, manifest)


def _normalize_clip(source: Path, destination: Path, baseline: dict) -> None:
    width = int(baseline.get("width") or 1920)
    height = int(baseline.get("height") or 1080)
    frame_rate = str(baseline.get("frameRate") or "30/1")
    filters = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={frame_rate}"
    command = [str(find_ffmpeg()), "-y", "-i", str(source), "-vf", filters, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", str(destination)]
    _run_ffmpeg(command, f"Could not normalize source clip {source.name}.")


def _run_ffmpeg(command: list[str], message: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False, creationflags=hidden_subprocess_flags())
    if result.returncode != 0:
        raise RuntimeError(f"{message} {(result.stderr or result.stdout)[-1000:]}")


def video_project_root(manifest_path: Path) -> Path:
    root = manifest_path.expanduser().resolve().parent
    if not (root / ".vcg-private").is_file():
        raise ValueError("Video project is not inside a marked private workspace.")
    return root


def resolve_video_project_path(manifest_path: Path, manifest: dict, key: str) -> Path:
    relative = (manifest.get("paths") or {}).get(key)
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"Video project is missing its {key} path.")
    root = video_project_root(manifest_path)
    resolved = (root / relative).resolve()
    if not _is_within(resolved, root):
        raise ValueError(f"Video-project path {key} escapes its private root.")
    return resolved


def load_video_project(manifest_path: Path) -> dict:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _ensure_default_paths(manifest)
    validate_video_project(manifest_path, manifest)
    return manifest


def save_video_project(manifest_path: Path, manifest: dict) -> dict:
    manifest = json.loads(json.dumps(manifest))
    _ensure_default_paths(manifest)
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    validate_video_project(manifest_path, manifest)
    temporary = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def validate_video_project(manifest_path: Path, manifest: dict) -> None:
    if manifest.get("schemaVersion") != VIDEO_PROJECT_VERSION:
        raise ValueError(f"Unsupported video-project version: {manifest.get('schemaVersion')}")
    if not str(manifest.get("id") or "") or not str(manifest.get("name") or ""):
        raise ValueError("Video project requires an id and name.")
    _ensure_default_paths(manifest)
    for key in DEFAULT_PROJECT_PATHS:
        resolve_video_project_path(manifest_path, manifest, key)
    root = video_project_root(manifest_path)
    clip_ids = set()
    for clip in manifest.get("sourceSequence", []):
        clip_id = str(clip.get("id") or "")
        if not clip_id or clip_id in clip_ids:
            raise ValueError("Every source clip needs a unique id.")
        clip_ids.add(clip_id)
        path = (root / str(clip.get("path") or "")).resolve()
        if not _is_within(path, root):
            raise ValueError("Source clip path escapes its private root.")


def _ensure_default_paths(manifest: dict) -> None:
    paths = manifest.setdefault("paths", {})
    for key, value in DEFAULT_PROJECT_PATHS.items():
        paths.setdefault(key, value)


def video_project_response(manifest_path: Path, manifest: dict) -> dict:
    return {
        "manifestPath": str(manifest_path.resolve()),
        "root": str(video_project_root(manifest_path)),
        "name": manifest["name"],
        "preferredSource": str(preferred_stage_source(manifest_path, manifest)),
        "manifest": manifest,
        "resolvedPaths": {
            key: str(resolve_video_project_path(manifest_path, manifest, key))
            for key in manifest["paths"]
        },
    }


def preferred_stage_source(manifest_path: Path, manifest: dict) -> Path:
    artifact_keys = {"lockedCut": "lockedCutRevision", "captionedCut": "captionedCutRevision"}
    for key in ("lockedCut", "captionedCut"):
        candidate = resolve_video_project_path(manifest_path, manifest, key)
        if candidate.is_file() and artifact_current(manifest, artifact_keys[key]):
            return candidate
    return resolve_video_project_path(manifest_path, manifest, "sourceVideo")


def artifact_current(manifest: dict, artifact_key: str) -> bool:
    if "sourceSequence" not in manifest:
        return True
    return int((manifest.get("artifacts") or {}).get(artifact_key) or -1) == int(manifest.get("sequenceRevision") or 0)


def mark_artifact_current(manifest: dict, artifact_key: str) -> None:
    manifest.setdefault("artifacts", {})[artifact_key] = int(manifest.get("sequenceRevision") or 0)


def build_visual_plan_prompt(manifest_path: Path, manifest: dict) -> str:
    paths = {key: resolve_video_project_path(manifest_path, manifest, key) for key in manifest["paths"]}
    transcript = paths["finalTranscript"] if paths["finalTranscript"].is_file() else paths["editorProject"]
    locked_cut = paths["lockedCut"]
    readiness = []
    if not locked_cut.is_file() or not artifact_current(manifest, "lockedCutRevision"):
        readiness.append("- The locked cut does not exist yet. Finish Phase 5 export before building or rendering the plan.")
    if not transcript.is_file() or not artifact_current(manifest, "finalTranscriptRevision"):
        readiness.append("- The timestamped transcript does not exist yet. Generate and save it before analysis.")
    readiness_text = "\n".join(readiness) if readiness else "- The locked cut and timestamped transcript are available."
    repo = project_root().resolve()
    creator_library = Path(os.environ.get("VCG_CREATOR_LIBRARY") or (Path.home() / "Videos" / "VCG Creator Library")).expanduser().resolve()
    return f"""Use the VCG Visual Producer skill to cook a visual plan for this private video project.

Project: {manifest['name']}
Private project manifest: {manifest_path.resolve()}
Private project root: {video_project_root(manifest_path)}
Locked cut: {locked_cut}
Timestamped transcript: {transcript}
Editor transcript project: {paths['editorProject']}
Final transcript export: {paths['finalTranscript']}
Imported assets folder: {paths['importedAssets']}
Generated assets folder: {paths['generatedAssets']}
Visual plan destination: {paths['visualPlan']}
Visual suggestions destination: {video_project_root(manifest_path) / 'visual-production' / 'visual-suggestions.json'}
Visual review folder: {paths['visualPreviews']}
Final render destination: {paths['finalVideo']}

Public reusable contracts:
- Brand: {repo / 'visual-production' / 'brand' / 'vcg-white-editorial.json'}
- Module catalog: {repo / 'visual-production' / 'modules' / 'catalog.json'}
- Proven treatment recipes: {repo / 'visual-production' / 'recipes' / 'catalog.json'}
- Plan schema: {repo / 'visual-production' / 'schemas' / 'visual-plan.schema.json'}
- Storytelling asset contract: {repo / 'docs' / 'visual-storytelling-assets.md'}
- Suggestions schema: {repo / 'visual-production' / 'schemas' / 'visual-suggestions.schema.json'}

Private reusable sources to inspect before proposing new work:
- Creator Library index: {creator_library / 'library.json'}
- Prior recipe previews: {creator_library / 'recipe-previews'}

Readiness:
{readiness_text}

First pass only: inspect the locked cut and timestamped transcript together, identify protected source-footage moments, and propose an editable timeline of graphics, reframes, imported-animation opportunities, transitions, intentional clean sections, and appropriate B-roll. Never reveal punchlines or conclusions before the matching spoken words. Move the speaker into a bounded container before showing side panels. Animate charts toward the spoken conclusion. Use Montserrat and the VCG white-editorial brand.

Single Cook operation: perform Scene Analysis, Scene Selection, Production Planning, Variation Audit, cadence audit, and preview-evidence preparation sequentially inside this one Cook pass. These are responsibilities within one path, not separate agents, handoffs, files, or competing workflows. The Scene Analysis stage must create scenePacket with the actual layout, screenshot time, actual speaker and protected-content geometry, transcript and spoken beats, editorial purpose, content density, motion/reveal opportunities, B-roll fit, intentional-series identity, and surrounding constraints. The only valid layouts are full-screen-talking, talking-left, talking-right, talking-bottom-left, talking-top-left, talking-bottom-right, talking-top-right, and computer-screen-only.

Visual cadence standard: account for the complete locked-cut runtime with explicit editorial decisions. Schedule at least one meaningful visual change in every rolling five-second interval unless that interval is deliberately marked as an intentional clean-performance hold or protected-footage hold with a concrete reason. A meaningful change may be a treatment entrance or exit, an internal bullet or label reveal, chart/data change, UI action, callout change, composition or speaker reframe, supporting visual, punch zoom, or emphasis change. A treatment may remain on screen longer than five seconds when its internal reveals or other meaningful changes keep meeting this cadence. Record those timed internal events in meaningfulChanges. Entrance and exit count automatically; do not split one coherent graphic into arbitrary five-second cards. Use zoom-in or zoom-out only when it creates a purposeful emphasis or reframe, not as meaningless motion. Do not use the same selected treatment more than twice unless the later use is a declared intentional callback or series.

Reuse-first and variety gate (Scene Selector): inspect the complete registered module catalog, proven treatment recipes, Creator Library index, creator ratings and locked defaults in treatments.json, and prior recipe previews before proposing bespoke work. For every graphic scene, return at least three rankedCandidates with treatmentId, rank, family, fitReason, limitations, previewAvailable, creatorRating, and lockedDefault. Hard-filter candidates by scenePacket.layout and every protected region before ranking exact intent, locked canonical default, creator rating, proven usage, content/motion fit, and global variation. Copy the ranked IDs into candidateTreatmentIds, select exactly one moduleId or recipeId, record visualFamily and selectionRationale, and include it in the top-level reuse audit. When the spoken intent is “Example number ___”, numbered-step-intro is the locked first-choice family whenever compatible. The Producer may accept the best compatible library treatment or record a structured bespoke gap; it may not silently substitute an easier generic card.

Variation Agent gate: maintain coverage.variationAudit with familyCounts, treatmentCounts, intentionalSeriesIds, and warnings. Do not place the same visualFamily on consecutive graphic suggestions or use one selected treatment more than twice unless it belongs to a declared intentional series or callback with seriesId, intentionalRepeat true, and a concrete repeatRationale. Reuse atoms and motion grammar while varying the full composition, choreography, and speaker placement. Every Creator Library suggestion needs a concrete libraryQuery. Use a bespoke treatment only when registered and library sources cannot serve the editorial beat, and record the reason in coverage.reuseAudit.bespokeRationales.

Speaker-safety gate: inspect the locked footage at the setup, every reveal that changes occupied area, the resolved state, and the exit. Every graphic suggestion must include speakerSafety with checked true, a speaker mode, normalized speakerBounds, normalized overlayOcclusionBounds for every region rendered above the speaker, at least three verifiedAtSec values, and maxSpeakerAbsenceSec no greater than 2. Overlay occlusion bounds may not intersect the protected speaker bounds. If the graphic intentionally replaces the speaker, use brief-full-frame-hit and keep both the suggestion and declared absence at two seconds or less. A centered-bottom or lower-third treatment is not automatically safe: measure it against the actual face in this footage.

Pre-render approval gate: save every scene with decision.status pending. The creator must compare the locked-video screenshot with the candidate treatment screenshot, approve the selected treatment, or reject it with notes before any full production render. Rejected notes stay in rejectionHistory and are routed back through the Producer. Intentional series may be approved as a group. The accepted treatment map is an implementation contract: do not substitute another family or treatment without returning the scene to decision.status revision-requested.

One-frame evidence gate: every graphic needs approvalEvidence bound to its currently selected treatment. Set sourceFrameTimeSec to the actual scene frame shown on the left and representativeTimeSec/representativeState to one resolved state that honestly shows the proposed composition on the right. When a historical render exists, use status historical-ready. When it does not exist, render exactly one representative sample frame inside the private project, save it at previews/visual/approval-samples/<suggestion-id>-<treatment-id>.png, and use status sample-ready with sampleFramePath. Do not render a motion preview or full scene during Cook. Do not use a generic illustration, wireframe, or different treatment as evidence. A missing historical render is a requirement to make this one sample frame, not a reason to omit the proposal.

Build-through gate: when an approved graphic is built later, copy planningSuggestionId, approvedTreatmentId, speakerSafety, visualFamily, candidateTreatmentIds, selectionRationale, meaningfulChanges, approvalEvidence, and recipeId into the registered cue parameters; set the suggestion status to built and its cueId to that cue. Review and final export are blocked when a contract-version-three suggestion lacks creator approval, is not registered, or its cue drops the approved safety, evidence, cadence, and treatment audit.

B-roll gate: explicitly audit the full transcript and footage for literal or metaphorical B-roll opportunities. Do not force B-roll over a software demonstration, authored joke, gesture, or strong direct-address beat. Set coverage.bRollAudit.decision to planned when at least one useful B-roll suggestion exists, otherwise set it to not-suitable and explain why. Planned B-roll items must use timelineLane b-roll and include a structured stockBrief or a Creator Library query. This audit is required even when the correct decision is no B-roll.

Do not build cues, modify visual-plan.json, or render motion/full-production scenes yet. The only permitted render during Cook is the required single approval sample frame for a selected treatment that lacks historical evidence. Save one machine-readable version-one suggestion file using approval contract three to the exact Visual suggestions destination. Include coverage.reuseAudit {{ contractVersion: 3, reviewed, reusedModuleIds, reusedRecipeIds, creatorLibraryQueries, bespokeRationales }}, coverage.variationAudit {{ reviewed, familyCounts, treatmentCounts, intentionalSeriesIds, warnings }}, and coverage.bRollAudit {{ reviewed, decision, rationale }}. The app computes coverage.runtimeSec, coverage.decisionCounts, and coverage.cadenceAudit from the saved suggestions; do not invent or hand-count those numbers. Use one of these categories for each item: clean-speaker, protected-footage, graphic, creator-library, project-asset, stock, or ai-brief. Every item needs a unique id, status proposed, exact startSec/endSec, transcriptContext, editorialPurpose, confidence, protectedFootageConflict, scenePacket, meaningfulChanges (an empty list is valid only when entrance/exit already satisfy cadence), decision {{ status: "pending", selectedTreatmentId, notes: "" }}, rejectionHistory, and the appropriate moduleParameters, libraryQuery, stockBrief, or generationBrief. A deliberate clean section also needs intentionalHold {{ reason, representativeTimeSec }} and may only use category clean-speaker or protected-footage. Every graphic also needs rankedCandidates, candidateTreatmentIds, visualFamily, selectionRationale, intentionalRepeat, approvalEvidence, and the complete speakerSafety record described above. A stockBrief needs literalQueries, metaphoricalQueries, avoid, and desiredDurationSec. Present the same items as a timestamped approval table using the app-computed fixed counts: total timeline decisions, graphic treatments, clean-performance holds, protected-footage decisions, B-roll decisions, and unresolved approvals. Show the source frame and bound historical/sample evidence side by side for every graphic. Wait for creator approval on every decision before building cues.

Privacy: all footage, transcripts, suggestions, plans, assets, previews, and renders must remain inside the private project root. Only content-neutral reusable code and contracts may enter the public repository.
"""
