from __future__ import annotations

import html
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe
from app.core.file_utils import bounds_intersect, is_within, normalized_bounds, sha256_file, slug
from app.core.process_utils import hidden_subprocess_flags
from app.core.settings import project_root


VISUAL_PLAN_VERSION = 2
# The speaker modes a graphic may declare. Full-frame takeovers are deliberately absent.
SPEAKER_SAFETY_MODES = {
    "full-frame-speaker",
    "left-container",
    "right-container",
    "bottom-container",
    "corner-container",
}
BRAND_ID = "vcg-white-editorial"
MODULE_IDS = {
    "punchline-reveal",
    "source-footage-hold",
    "speaker-side-panel",
    "progress-scale",
    "dependency-stack",
    "dual-comparison",
    "numbered-example-card",
    # Movement and emphasis over a software demonstration. Without these the vocabulary could not
    # express anything at all over 500+ seconds of screen recording, so plans went bare there.
    "source-punch-zoom",
    "ui-callout",
    # Ported from the July-22 project's built library. These are the families that already worked
    # over a software demonstration: they anchor to one edge and leave the screen readable.
    "side-list-panel",
    "result-badge",
    "link-chip",
    "milestone-path",
    "before-after-grade",
    "lower-third-flow",
    "three-step-celebration",
    "career-pathway",
    "list-reveal-pinned-thesis",
    "kinetic-word-punctuation",
    "numbered-step-intro",
    "problem-card-triptych",
    "speaker-rise-callouts",
    "conversation-bubble-sequence",
    "tradeoff-meter",
    "rank-medal-hit",
    "brand-cta-lockup",
    "command-popup-stack",
    "windows-prompt-typing",
    "uplifting-sunrise-finale",
}
CUE_KINDS = {"module", "asset", "composition"}
ANCHOR_TYPES = {"spoken", "scene-relative", "unanchored"}
COMMON_MODULE_PARAMETERS = {
    "reviewLabel", "editorialPurpose", "recipeId", "opacity", "transitionIn", "transitionOut",
    "speakerSafety", "visualFamily", "candidateTreatmentIds", "selectionRationale",
    "planningSuggestionId", "approvedTreatmentId", "meaningfulChanges", "approvalEvidence",
}
MODULE_PARAMETER_KEYS = {
    "punchline-reveal": COMMON_MODULE_PARAMETERS | {"text", "kicker", "accentColor", "imageAssetId"},
    "source-footage-hold": COMMON_MODULE_PARAMETERS,
    "speaker-side-panel": COMMON_MODULE_PARAMETERS | {"text", "kicker", "accentColor", "side", "panelWidth", "videoBounds", "frameStyle", "items"},
    "progress-scale": COMMON_MODULE_PARAMETERS | {"text", "kicker", "startLabel", "targetLabel", "accentColor", "milestones"},
    "dependency-stack": COMMON_MODULE_PARAMETERS | {"text", "kicker", "nodes", "accentColor"},
    "dual-comparison": COMMON_MODULE_PARAMETERS | {"kicker", "leftTitle", "rightTitle", "leftItems", "rightItems", "leftColor", "rightColor"},
    "numbered-example-card": COMMON_MODULE_PARAMETERS | {
        "kicker", "exampleNumber", "totalExamples", "titleLines", "accentLineIndex", "tags", "accentColor",
    },
    "source-punch-zoom": COMMON_MODULE_PARAMETERS | {"focusX", "focusY", "zoom", "settleSec"},
    "ui-callout": COMMON_MODULE_PARAMETERS | {"label", "detail", "targetBounds", "accentColor", "pointer"},
    "side-list-panel": COMMON_MODULE_PARAMETERS | {"kicker", "text", "rows", "accentRowIndex", "side", "rowStyle"},
    "result-badge": COMMON_MODULE_PARAMETERS | {"kicker", "lines", "accentLineIndex", "mark", "side"},
    "link-chip": COMMON_MODULE_PARAMETERS | {"kicker", "glyph", "words", "accentWordIndex", "side"},
    "milestone-path": COMMON_MODULE_PARAMETERS | {"kicker", "text", "stops", "accentStopIndex", "side"},
    "before-after-grade": COMMON_MODULE_PARAMETERS | {"kicker", "before", "after", "arrow", "footerLeft", "footerRight", "side"},
    "lower-third-flow": COMMON_MODULE_PARAMETERS | {"kicker", "items", "accentItemIndex", "variant"},
    "three-step-celebration": COMMON_MODULE_PARAMETERS | {"kicker", "steps", "payoff", "side"},
    "career-pathway": COMMON_MODULE_PARAMETERS | {"kicker", "rows", "accentRowIndex", "side"},
    "list-reveal-pinned-thesis": COMMON_MODULE_PARAMETERS | {"kicker", "thesis", "rows", "accentRowIndex", "side"},
    "kinetic-word-punctuation": COMMON_MODULE_PARAMETERS | {"phrase", "anchor", "side", "accentColor"},
    "numbered-step-intro": COMMON_MODULE_PARAMETERS | {"stepNumber", "title", "action", "side", "showNumber"},
    "problem-card-triptych": COMMON_MODULE_PARAMETERS | {"kicker", "cards", "accentCardIndex"},
    "speaker-rise-callouts": COMMON_MODULE_PARAMETERS | {"thesis", "callouts", "accentCalloutIndex"},
    "conversation-bubble-sequence": COMMON_MODULE_PARAMETERS | {"kicker", "bubbles", "accentBubbleIndex", "side"},
    "tradeoff-meter": COMMON_MODULE_PARAMETERS | {"kicker", "leftLabel", "rightLabel", "value", "verdict", "side"},
    "rank-medal-hit": COMMON_MODULE_PARAMETERS | {"rank", "verdict", "medal", "side"},
    "brand-cta-lockup": COMMON_MODULE_PARAMETERS | {"logoText", "logoAssetId", "action", "destination", "side"},
    "command-popup-stack": COMMON_MODULE_PARAMETERS | {"kicker", "commands", "purposes", "accentCommandIndex", "side"},
    "windows-prompt-typing": COMMON_MODULE_PARAMETERS | {"appName", "prompt", "side"},
    "uplifting-sunrise-finale": COMMON_MODULE_PARAMETERS | {"kicker", "claim", "action"},
}
SIDE_ANCHORS = {"left", "right"}
MAX_PUNCH_ZOOM = 2.0
ASSET_PARAMETER_KEYS = {
    "x", "y", "width", "height", "opacity", "scale", "rotation", "fit", "muted", "volume",
    "sourceStartSec", "playbackRate", "loop", "transitionIn", "transitionOut", "reviewLabel",
    "editorialPurpose", "recipeId", "speakerSafety", "visualFamily", "candidateTreatmentIds", "selectionRationale",
    "planningSuggestionId", "approvedTreatmentId", "meaningfulChanges", "approvalEvidence",
}
COMPOSITION_PARAMETER_KEYS = {
    "reviewLabel", "editorialPurpose", "recipeId", "speakerSafety", "visualFamily",
    "candidateTreatmentIds", "selectionRationale", "planningSuggestionId", "approvedTreatmentId",
    "meaningfulChanges", "approvalEvidence",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ASSET_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
ProgressCallback = Callable[[int, str], None]


def default_visual_workspace() -> Path:
    configured = os.environ.get("VCG_PRIVATE_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Videos" / "VCG Projects").resolve()


# Kept as module-local names because callers and tests refer to them here.
_slug = slug
_is_within = is_within


def _unique_directory(root: Path, name: str) -> Path:
    candidate = root / _slug(name)
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = root / f"{_slug(name)}-{index}"
        if not candidate.exists():
            return candidate
        index += 1


def probe_visual_source(path: Path) -> dict:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        return _probe_visual_source_with_ffmpeg(path)
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,r_frame_rate:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Could not inspect the selected video. {details[-600:]}")
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1"
    numerator, denominator = rate.split("/", 1) if "/" in rate else (rate, "1")
    fps = float(numerator) / max(float(denominator), 1.0)
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(fps, 3),
        "durationSec": round(float(data["format"]["duration"]), 3),
    }


def scene_frame_preview(plan_path: Path, time_sec: float) -> Path:
    plan = load_visual_plan(plan_path)
    duration = float(plan["composition"]["durationSec"])
    moment = max(0.0, min(float(time_sec), max(0.0, duration - 0.001)))
    root = find_visual_root(plan_path)
    source = resolve_project_path(root, plan["source"]["video"])
    preview_root = root / "visual-production" / "scene-previews"
    preview_root.mkdir(parents=True, exist_ok=True)
    destination = preview_root / f"scene-{round(moment * 1000):010d}.jpg"
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    result = subprocess.run(
        [
            str(find_ffmpeg()),
            "-y",
            "-ss",
            f"{moment:.4f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Could not capture the scene review frame. {details[-800:]}")
    return destination


def _probe_visual_source_with_ffmpeg(path: Path) -> dict:
    """Read basic metadata from FFmpeg when a standalone FFprobe is unavailable."""
    result = subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    details = f"{result.stdout}\n{result.stderr}"
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", details)
    video_line = next((line for line in details.splitlines() if "Video:" in line), "")
    size_match = re.search(r"(?:^|\D)(\d{2,5})x(\d{2,5})(?:\D|$)", video_line)
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", video_line)
    if not duration_match or not size_match:
        raise RuntimeError(f"Could not inspect the selected video. {details[-600:]}")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return {
        "width": int(size_match.group(1)),
        "height": int(size_match.group(2)),
        "fps": round(float(fps_match.group(1)) if fps_match else 30.0, 3),
        "durationSec": round(duration, 3),
    }


def create_visual_project(
    source_video: Path,
    *,
    transcript_document: dict | None = None,
    workspace_root: Path | None = None,
) -> tuple[Path, dict]:
    source_video = source_video.expanduser().resolve()
    if not source_video.is_file() or source_video.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Choose a supported source video before creating a visual project.")

    workspace = (workspace_root or default_visual_workspace()).expanduser().resolve()
    if _is_within(workspace, project_root()):
        raise ValueError("The private visual workspace must be outside the public Git checkout.")
    workspace.mkdir(parents=True, exist_ok=True)
    root = _unique_directory(workspace, source_video.stem)
    for name in ("source", "transcript", "assets", "plans", "working", "renders"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / ".vcg-private").write_text(
        "Private VCG creator project. Never add this directory to a public repository.\n",
        encoding="utf-8",
    )

    source_name = f"locked-cut{source_video.suffix.lower()}"
    shutil.copy2(source_video, root / "source" / source_name)
    transcript_ref = ""
    if transcript_document is not None:
        transcript_ref = "transcript/transcript.vcg.json"
        (root / transcript_ref).write_text(
            json.dumps(transcript_document, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    metadata = probe_visual_source(root / "source" / source_name)
    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "schemaVersion": VISUAL_PLAN_VERSION,
        "project": {
            "id": uuid.uuid4().hex,
            "name": source_video.stem,
            "createdAt": now,
            "updatedAt": now,
        },
        "source": {
            "video": f"source/{source_name}",
            "transcript": transcript_ref,
        },
        "composition": {**metadata, "brandId": BRAND_ID},
        "assets": [],
        "customCompositions": [],
        "protectedFootage": [],
        "cues": [],
        "revisions": {"activeRevision": None, "items": []},
        "productionGates": {"representativeApproval": None, "fullReviewApproval": None, "layoutInspection": None, "deliveryReopen": None},
        "reviews": [],
        "reviewHistory": [],
    }
    plan_path = root / "plans" / "visual-plan.json"
    save_visual_plan(plan_path, plan)
    return plan_path, plan


def create_visual_plan_in_video_project(
    project_root_path: Path,
    *,
    source_video: Path,
    transcript_path: Path | None,
    plan_path: Path,
) -> tuple[Path, dict]:
    """Create the visual child plan inside an existing marked private video project."""
    root = project_root_path.expanduser().resolve()
    if not (root / ".vcg-private").is_file():
        raise ValueError("The parent video project is not marked private.")
    source_video = source_video.expanduser().resolve()
    if not source_video.is_file():
        raise ValueError("Export the locked cut before starting Visual Production.")
    try:
        source_ref = source_video.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Visual source must be inside the private video project.") from exc
    transcript_ref = ""
    if transcript_path is not None and transcript_path.is_file():
        try:
            transcript_ref = transcript_path.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("Visual transcript must be inside the private video project.") from exc
    for directory in (root / "assets", root / "working", root / "previews" / "visual", root / "exports"):
        directory.mkdir(parents=True, exist_ok=True)
    metadata = probe_visual_source(source_video)
    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "schemaVersion": VISUAL_PLAN_VERSION,
        "project": {"id": uuid.uuid4().hex, "name": root.name, "createdAt": now, "updatedAt": now},
        # Cue times are seconds against this exact file. Recording which file it was turns a
        # re-cut from silent drift into an explicit mismatch.
        "source": {"video": source_ref, "transcript": transcript_ref, "videoSha256": sha256_file(source_video)},
        "composition": {**metadata, "brandId": BRAND_ID},
        "assets": [],
        "customCompositions": [],
        "protectedFootage": [],
        "cues": [],
        "revisions": {"activeRevision": None, "items": []},
        "productionGates": {"representativeApproval": None, "fullReviewApproval": None, "layoutInspection": None, "deliveryReopen": None},
        "reviews": [],
        "reviewHistory": [],
    }
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    save_visual_plan(plan_path, plan)
    return plan_path, plan


def find_visual_root(plan_path: Path) -> Path:
    resolved = plan_path.expanduser().resolve()
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / ".vcg-private").is_file():
            return candidate
    raise ValueError("Visual plan is not inside a marked private VCG project.")


def resolve_project_path(root: Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("The visual plan is missing a required project-relative path.")
    resolved = (root / relative_path).resolve()
    if not _is_within(resolved, root):
        raise ValueError("Visual plan path escapes its private project.")
    return resolved


def _module_semantic_texts(cue: dict) -> list[tuple[str, str, str]]:
    """Return every visible module string that requires an explicit reveal anchor."""
    if cue.get("kind") != "module" or cue.get("moduleId") == "source-footage-hold":
        return []
    params = cue.get("parameters") if isinstance(cue.get("parameters"), dict) else {}
    module_id = cue.get("moduleId")
    fields: list[tuple[str, str]] = []
    if module_id in {"punchline-reveal", "speaker-side-panel", "progress-scale", "dependency-stack"}:
        fields.extend([("parameters.kicker", str(params.get("kicker") or "")), ("parameters.text", str(params.get("text") or ""))])
    if module_id == "progress-scale":
        fields.extend([("parameters.startLabel", str(params.get("startLabel") or "")), ("parameters.targetLabel", str(params.get("targetLabel") or ""))])
    if module_id == "dual-comparison":
        fields.extend([
            ("parameters.kicker", str(params.get("kicker") or "")),
            ("parameters.leftTitle", str(params.get("leftTitle") or "")),
            ("parameters.rightTitle", str(params.get("rightTitle") or "")),
        ])
    if module_id == "numbered-example-card":
        fields.append(("parameters.kicker", str(params.get("kicker") or "")))
    if module_id in PORTED_MODULE_IDS:
        for key in ("kicker", "thesis", "phrase", "title", "action", "payoff", "verdict", "rank",
                    "leftLabel", "rightLabel", "logoText", "destination", "appName", "prompt", "claim"):
            if key in MODULE_PARAMETER_KEYS.get(module_id, set()):
                fields.append((f"parameters.{key}", str(params.get(key) or "")))
    if module_id in LIBRARY_MODULE_IDS:
        fields.append(("parameters.kicker", str(params.get("kicker") or "")))
        for key in ("text", "before", "after", "footerLeft", "footerRight"):
            if key in MODULE_PARAMETER_KEYS.get(module_id, set()):
                fields.append((f"parameters.{key}", str(params.get(key) or "")))
    if module_id == "ui-callout":
        fields.extend([
            ("parameters.label", str(params.get("label") or "")),
            ("parameters.detail", str(params.get("detail") or "")),
        ])
    list_fields = (
        ["nodes"] if module_id == "dependency-stack"
        else ["leftItems", "rightItems"] if module_id == "dual-comparison"
        else ["milestones"] if module_id == "progress-scale"
        else ["items"] if module_id == "speaker-side-panel"
        else ["titleLines"] if module_id == "numbered-example-card"
        else ["rows"] if module_id == "side-list-panel"
        else ["lines"] if module_id == "result-badge"
        else ["words"] if module_id == "link-chip"
        else ["stops"] if module_id == "milestone-path"
        else ["items"] if module_id == "lower-third-flow"
        else ["steps"] if module_id == "three-step-celebration"
        else ["rows"] if module_id in {"career-pathway", "list-reveal-pinned-thesis"}
        else ["cards"] if module_id == "problem-card-triptych"
        else ["callouts"] if module_id == "speaker-rise-callouts"
        else ["bubbles"] if module_id == "conversation-bubble-sequence"
        else ["commands", "purposes"] if module_id == "command-popup-stack"
        else []
    )
    for field in list_fields:
        values = params.get(field) if isinstance(params.get(field), list) else []
        fields.extend((f"parameters.{field}.{index}", str(value)) for index, value in enumerate(values))
    return [(path, text, path.rsplit(".", 1)[-1]) for path, text in fields if text.strip()]


def _unanchored_semantic_items(cue: dict) -> list[dict]:
    start = float(cue.get("startSec") or 0)
    end = float(cue.get("endSec") or start + 0.01)
    fully_visible = min(end, start + 0.5)
    return [
        {
            "id": f"semantic-{index + 1}",
            "label": label,
            "text": text,
            "parameterPath": path,
            "phrase": "",
            "anchorType": "unanchored",
            "spokenStartSec": start,
            "fullyVisibleSec": fully_visible,
        }
        for index, (path, text, label) in enumerate(_module_semantic_texts(cue))
    ]


def normalize_visual_plan(plan: dict) -> dict:
    """Upgrade legacy plans in memory while keeping delivery media private and untouched."""
    normalized = json.loads(json.dumps(plan))
    version = normalized.get("schemaVersion", 1)
    if version not in {1, VISUAL_PLAN_VERSION}:
        raise ValueError(f"Unsupported visual plan version: {version}")
    normalized["schemaVersion"] = VISUAL_PLAN_VERSION
    normalized.setdefault("customCompositions", [])
    normalized.setdefault("revisions", {"activeRevision": None, "items": []})
    normalized.setdefault("productionGates", {
        "representativeApproval": None,
        "fullReviewApproval": None,
        "layoutInspection": None,
        "deliveryReopen": None,
    })
    normalized.setdefault("reviews", [])
    normalized.setdefault("reviewHistory", [])
    normalized.setdefault("assets", [])
    normalized.setdefault("protectedFootage", [])
    normalized.setdefault("cues", [])
    for cue in normalized["cues"]:
        parameters = cue.setdefault("parameters", {})
        if version == 1:
            parameters.pop("frozenRevision", None)
            parameters.pop("revisionId", None)
        cue.setdefault("semanticItems", _unanchored_semantic_items(cue))
    return normalized


def calculate_visual_plan_hash(plan: dict, root: Path | None = None) -> str:
    """Hash creative inputs only; review notes and gate acknowledgements do not change a revision."""
    normalized = normalize_visual_plan(plan)
    project = normalized.get("project") or {}
    custom_compositions = json.loads(json.dumps(normalized.get("customCompositions", [])))
    if root is not None:
        for composition in custom_compositions:
            project_path = str(composition.get("projectPath") or "")
            if project_path:
                composition["sourceHash"] = sha256_directory(resolve_project_path(root, project_path))
    payload = {
        "schemaVersion": normalized["schemaVersion"],
        "project": {"id": project.get("id"), "name": project.get("name")},
        "source": normalized.get("source"),
        "composition": normalized.get("composition"),
        "assets": normalized.get("assets", []),
        "customCompositions": custom_compositions,
        "protectedFootage": normalized.get("protectedFootage", []),
        "cues": normalized.get("cues", []),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def active_visual_revision(plan: dict) -> dict | None:
    revisions = plan.get("revisions") if isinstance(plan.get("revisions"), dict) else {}
    active_number = revisions.get("activeRevision")
    return next((item for item in revisions.get("items", []) if item.get("number") == active_number), None)


def load_visual_plan(plan_path: Path) -> dict:
    root = find_visual_root(plan_path)
    plan = normalize_visual_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    # Domain validation first: it names the cue and the rule. The schema runs second as the
    # backstop that catches anything the hand-written checks do not cover.
    validate_visual_plan(plan, root)
    validate_document_schema("visual-plan", plan, label=f"{plan_path.name}")
    return plan


def save_visual_plan(plan_path: Path, plan: dict) -> dict:
    root = find_visual_root(plan_path)
    plan = normalize_visual_plan(plan)
    plan.setdefault("project", {})["updatedAt"] = datetime.now(timezone.utc).isoformat()
    validate_visual_plan(plan, root)
    validate_document_schema("visual-plan", plan, label=f"{plan_path.name}")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = plan_path.with_suffix(f"{plan_path.suffix}.tmp")
    temporary.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(plan_path)
    return plan


def validate_visual_plan(plan: dict, root: Path) -> None:
    if plan.get("schemaVersion") != VISUAL_PLAN_VERSION:
        raise ValueError(f"Unsupported visual plan version: {plan.get('schemaVersion')}")
    composition = plan.get("composition") or {}
    duration = float(composition.get("durationSec") or 0)
    if duration <= 0 or int(composition.get("width") or 0) <= 0 or int(composition.get("height") or 0) <= 0:
        raise ValueError("Visual plan composition metadata is invalid.")
    source = resolve_project_path(root, (plan.get("source") or {}).get("video", ""))
    # Cue timing is validated against the composition duration, so a stored duration that no
    # longer matches the media would validate cues that fall off the end of the real video.
    if source.is_file():
        try:
            probed = float(probe_visual_source(source)["durationSec"])
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError):
            probed = duration
        if abs(probed - duration) > 0.5:
            raise ValueError(
                f"The visual plan records a {duration:.3f}s runtime but its locked cut is "
                f"{probed:.3f}s. Re-create the plan from the current locked cut."
            )

    assets = {asset.get("id"): asset for asset in plan.get("assets", [])}
    if None in assets or len(assets) != len(plan.get("assets", [])):
        raise ValueError("Every imported asset needs a unique id.")
    for asset in assets.values():
        resolve_project_path(root, asset.get("path", ""))

    custom_compositions = {item.get("id"): item for item in plan.get("customCompositions", [])}
    if None in custom_compositions or len(custom_compositions) != len(plan.get("customCompositions", [])):
        raise ValueError("Every custom composition needs a unique id.")
    for composition_record in custom_compositions.values():
        if composition_record.get("runtime") != "hyperframes":
            raise ValueError(f"Custom composition {composition_record.get('id')} must use the HyperFrames runtime.")
        if not str(composition_record.get("name") or "") or not str(composition_record.get("rootCompositionId") or ""):
            raise ValueError(f"Custom composition {composition_record.get('id')} needs a name and root composition id.")
        if not re.fullmatch(r"[0-9a-f]{64}", str(composition_record.get("sourceHash") or "")):
            raise ValueError(f"Custom composition {composition_record.get('id')} needs a SHA-256 source hash.")
        project_path = resolve_project_path(root, str(composition_record.get("projectPath") or ""))
        entry_file = str(composition_record.get("entryFile") or "index.html")
        entry_path = resolve_project_path(root, f"{composition_record.get('projectPath', '').rstrip('/')}/{entry_file}")
        if not project_path.is_dir() or not entry_path.is_file():
            raise ValueError(f"Custom composition {composition_record.get('id')} source is missing.")
        # The hash must match the directory it claims to describe. Checking only its shape let a
        # declared value stand in for a measured one, which is the same hole as guessed geometry.
        measured = sha256_directory(project_path)
        if composition_record["sourceHash"] != measured:
            raise ValueError(
                f"Custom composition {composition_record.get('id')} records sourceHash "
                f"{composition_record['sourceHash'][:12]}… but its source directory hashes to "
                f"{measured[:12]}…. Register the hash of the files that are actually there."
            )
        for optional_path in ("storyboardPath", "timingLedgerPath"):
            value = str(composition_record.get(optional_path) or "")
            if value:
                resolve_project_path(root, value)

    cue_ids: set[str] = set()
    for cue in plan.get("cues", []):
        cue_id = str(cue.get("id") or "")
        if not cue_id or cue_id in cue_ids:
            raise ValueError("Every visual cue needs a unique id.")
        cue_ids.add(cue_id)
        start = float(cue.get("startSec") or 0)
        end = float(cue.get("endSec") or 0)
        if start < 0 or end <= start or end > duration + 0.01:
            raise ValueError(f"Visual cue {cue_id} has invalid timing.")
        kind = cue.get("kind")
        if kind == "module" and cue.get("moduleId") not in MODULE_IDS:
            raise ValueError(f"Unknown visual module: {cue.get('moduleId')}")
        if kind == "asset" and cue.get("assetId") not in assets:
            raise ValueError(f"Visual cue {cue_id} references a missing imported asset.")
        if kind == "composition" and cue.get("compositionId") not in custom_compositions:
            raise ValueError(f"Visual cue {cue_id} references a missing custom composition.")
        if kind == "composition" and not str(cue.get("sceneId") or ""):
            raise ValueError(f"Visual cue {cue_id} needs a custom-composition scene id.")
        if kind not in CUE_KINDS:
            raise ValueError(f"Visual cue {cue_id} has an unknown kind.")
        parameters = cue.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"Visual cue {cue_id} parameters must be an object.")
        allowed_parameters = MODULE_PARAMETER_KEYS.get(str(cue.get("moduleId")), set()) if kind == "module" else ASSET_PARAMETER_KEYS if kind == "asset" else COMPOSITION_PARAMETER_KEYS
        unknown_parameters = sorted(set(parameters) - allowed_parameters)
        if unknown_parameters:
            raise ValueError(f"Visual cue {cue_id} has unsupported parameters: {', '.join(unknown_parameters)}")
        semantic_items = cue.get("semanticItems")
        if not isinstance(semantic_items, list):
            raise ValueError(f"Visual cue {cue_id} needs a semanticItems array.")
        semantic_ids: set[str] = set()
        semantic_paths: set[str] = set()
        for semantic in semantic_items:
            semantic_id = str(semantic.get("id") or "")
            parameter_path = str(semantic.get("parameterPath") or "")
            if not semantic_id or semantic_id in semantic_ids or not parameter_path or parameter_path in semantic_paths:
                raise ValueError(f"Visual cue {cue_id} semantic items need unique ids and parameter paths.")
            semantic_ids.add(semantic_id)
            semantic_paths.add(parameter_path)
            if semantic.get("anchorType") not in ANCHOR_TYPES:
                raise ValueError(f"Visual cue {cue_id} semantic item {semantic_id} has an unknown anchor type.")
            try:
                spoken_start = float(semantic["spokenStartSec"])
                fully_visible = float(semantic["fullyVisibleSec"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Visual cue {cue_id} semantic item {semantic_id} needs spokenStartSec and fullyVisibleSec.") from exc
            if spoken_start < start - 0.01 or fully_visible < spoken_start or fully_visible > end + 0.01:
                raise ValueError(f"Visual cue {cue_id} semantic item {semantic_id} has invalid reveal timing.")
        required_paths = {path for path, _text, _label in _module_semantic_texts(cue)}
        missing_paths = sorted(required_paths - semantic_paths)
        if missing_paths:
            raise ValueError(f"Visual cue {cue_id} has visible text without semantic timing: {', '.join(missing_paths)}")

    revisions = plan.get("revisions")
    if not isinstance(revisions, dict) or not isinstance(revisions.get("items"), list):
        raise ValueError("Visual plan revisions are invalid.")
    revision_numbers: set[int] = set()
    revision_ids: set[str] = set()
    for revision in revisions["items"]:
        number = revision.get("number")
        revision_id = str(revision.get("id") or "")
        if not isinstance(number, int) or number <= 0 or number in revision_numbers or not revision_id or revision_id in revision_ids:
            raise ValueError("Every visual revision needs a unique positive number and id.")
        revision_numbers.add(number)
        revision_ids.add(revision_id)
        if revision.get("runtime") != "hyperframes":
            raise ValueError(f"Visual revision {revision_id} must use the HyperFrames runtime.")
        composition_id = revision.get("compositionId")
        if composition_id is not None and composition_id not in custom_compositions:
            raise ValueError(f"Visual revision {revision_id} references a missing custom composition.")
        source_path = resolve_project_path(root, str(revision.get("hyperframesSource") or ""))
        entry_file = str(revision.get("entryFile") or "index.html")
        entry_path = resolve_project_path(root, f"{str(revision.get('hyperframesSource') or '').rstrip('/')}/{entry_file}")
        if not source_path.is_dir() or not entry_path.is_file():
            raise ValueError(f"Visual revision {revision_id} HyperFrames source is missing.")
        for render_key in ("reviewRender", "finalRender"):
            render_path = str(revision.get(render_key) or "")
            if render_path:
                resolve_project_path(root, render_path)
        if not re.fullmatch(r"[0-9a-f]{64}", str(revision.get("planHash") or "")):
            raise ValueError(f"Visual revision {revision_id} needs a SHA-256 plan hash.")
        if revision.get("status") not in {"review", "delivered", "superseded"}:
            raise ValueError(f"Visual revision {revision_id} has an unknown status.")
    active_revision_number = revisions.get("activeRevision")
    if active_revision_number is not None and active_revision_number not in revision_numbers:
        raise ValueError("The active visual revision does not exist.")

    production_gates = plan.get("productionGates")
    if not isinstance(production_gates, dict):
        raise ValueError("Visual production gates are invalid.")

    for item in plan.get("protectedFootage", []):
        start = float(item.get("startSec") or 0)
        end = float(item.get("endSec") or 0)
        if start < 0 or end <= start or end > duration + 0.01:
            raise ValueError("Protected footage range has invalid timing.")

    review_ids: set[str] = set()
    review_targets: set[tuple[str, str]] = set()
    for review in plan.get("reviews", []):
        _validate_review_record(review, duration, review_ids, accepted=False)
        target = (str(review.get("itemType")), str(review.get("itemId")))
        if target in review_targets:
            raise ValueError("Only one active visual review is allowed per cue or suggestion.")
        review_targets.add(target)
    history_ids: set[str] = set()
    for review in plan.get("reviewHistory", []):
        _validate_review_record(review, duration, history_ids, accepted=True)


def _validate_review_record(review: dict, duration: float, ids: set[str], *, accepted: bool) -> None:
    review_id = str(review.get("id") or "")
    if not review_id or review_id in ids:
        raise ValueError("Every visual review record needs a unique id.")
    ids.add(review_id)
    if review.get("itemType") not in {"cue", "suggestion"} or not str(review.get("itemId") or ""):
        raise ValueError(f"Visual review {review_id} needs a cue or suggestion item id.")
    start = float(review.get("startSec") or 0)
    end = float(review.get("endSec") or 0)
    if start < 0 or end <= start or end > duration + 0.01:
        raise ValueError(f"Visual review {review_id} has invalid timing.")
    if review.get("directive", "targeted") not in {"targeted", "leave-everything-else", "replace-all"}:
        raise ValueError(f"Visual review {review_id} has an unknown directive.")
    if review.get("status", "changes-requested") not in {"changes-requested", "ready-for-review"}:
        raise ValueError(f"Visual review {review_id} has an unknown status.")
    if not isinstance(review.get("note", ""), str):
        raise ValueError(f"Visual review {review_id} note must be text.")
    if accepted and not str(review.get("acceptedAt") or ""):
        raise ValueError(f"Accepted visual review {review_id} needs an accepted timestamp.")


def import_visual_asset(plan_path: Path, source: Path) -> tuple[dict, dict]:
    root = find_visual_root(plan_path)
    plan = load_visual_plan(plan_path)
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in ASSET_EXTENSIONS:
        raise ValueError("Choose a supported video, animation, or image asset.")
    asset_id = uuid.uuid4().hex[:12]
    asset_directory = root / "assets" / "imported" if (root / "assets" / "imported").is_dir() else root / "assets"
    asset_directory.mkdir(parents=True, exist_ok=True)
    destination = asset_directory / f"{asset_id}-{_slug(source.stem)}{source.suffix.lower()}"
    shutil.copy2(source, destination)
    asset = {
        "id": asset_id,
        "name": source.name,
        "path": destination.relative_to(root).as_posix(),
        "mediaType": "video" if source.suffix.lower() in VIDEO_EXTENSIONS else "image",
        "durationSec": None,
        "hasTransparency": source.suffix.lower() in {".webm", ".png", ".webp"},
    }
    if asset["mediaType"] == "video":
        try:
            asset["durationSec"] = probe_visual_source(destination)["durationSec"]
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError):
            asset["durationSec"] = None
    plan["assets"].append(asset)
    save_visual_plan(plan_path, plan)
    return asset, plan


def visual_plan_response(plan_path: Path, plan: dict) -> dict:
    root = find_visual_root(plan_path)
    final_path, revision = active_visual_master(plan_path, plan)
    final_available = final_path.is_file()
    final_stat = final_path.stat() if final_available else None
    runtime_root, runtime_entry, _composition = active_visual_runtime(plan_path, plan)
    runtime_stat = runtime_entry.stat() if runtime_entry is not None and runtime_entry.is_file() else None
    gate_report = visual_production_gate_report(plan_path, plan)
    return {
        "planPath": str(plan_path.resolve()),
        "projectRoot": str(root),
        "plan": plan,
        "finalVideo": {
            "available": final_available,
            "revisionId": revision.get("id") if revision else None,
            "revisionName": revision.get("name") if revision else None,
            "revisionNumber": revision.get("number") if revision else None,
            "cacheKey": f"{final_stat.st_mtime_ns}-{final_stat.st_size}" if final_stat else None,
        },
        "runtimePreview": {
            "available": runtime_entry is not None and runtime_entry.is_file(),
            "accurate": True,
            "runtime": "hyperframes",
            "source": str(runtime_root) if runtime_root else None,
            "cacheKey": f"{runtime_stat.st_mtime_ns}-{runtime_stat.st_size}-{gate_report['planHash']}" if runtime_stat else gate_report["planHash"],
        },
        "activeRevision": revision,
        "production": gate_report,
        "libraryCuration": delivery_library_curation(plan_path),
    }


def delivery_library_curation(plan_path: Path) -> dict | None:
    """Expose the last harvest outcome so a failed one is visible instead of buried in a file."""
    manifest = find_visual_root(plan_path) / "visual-production" / "delivery-manifest.json"
    if not manifest.is_file():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("libraryCuration")
    except (OSError, json.JSONDecodeError):
        return {"status": "failed", "error": "The delivery manifest could not be read."}


def active_visual_master(plan_path: Path, plan: dict) -> tuple[Path, dict | None]:
    root = find_visual_root(plan_path)
    revision = active_visual_revision(plan)
    if revision is not None and str(revision.get("finalRender") or ""):
        return resolve_project_path(root, str(revision["finalRender"])), revision
    # Compatibility fallback for a schema-v1 project before its explicit migration.
    for asset in plan.get("assets", []):
        origin = asset.get("origin")
        if not isinstance(origin, dict):
            continue
        if origin.get("kind") == "frozen-visual-revision" and origin.get("active") is True:
            return resolve_project_path(root, str(asset.get("path") or "")), {
                "id": origin.get("revisionId"),
                "name": origin.get("revisionName"),
                "number": None,
            }
    return (root / "exports" / "final-video.mp4").resolve(), None


def active_visual_runtime(plan_path: Path, plan: dict) -> tuple[Path | None, Path | None, dict | None]:
    """Resolve the exact HyperFrames project used by both preview and render."""
    root = find_visual_root(plan_path)
    revision = active_visual_revision(plan)
    source_ref = str(revision.get("hyperframesSource") or "") if revision else ""
    composition_record = None
    if revision and revision.get("compositionId") is not None:
        composition_record = next((item for item in plan.get("customCompositions", []) if item.get("id") == revision.get("compositionId")), None)
    if not source_ref and composition_record is not None:
        source_ref = str(composition_record.get("projectPath") or "")
    if not source_ref:
        composition_cue = next((cue for cue in plan.get("cues", []) if cue.get("kind") == "composition" and cue.get("enabled", True)), None)
        if composition_cue is not None:
            composition_record = next((item for item in plan.get("customCompositions", []) if item.get("id") == composition_cue.get("compositionId")), None)
            source_ref = str(composition_record.get("projectPath") or "") if composition_record else ""
    if not source_ref:
        return None, None, None
    source_root = resolve_project_path(root, source_ref)
    entry_file = str((revision or {}).get("entryFile") or (composition_record or {}).get("entryFile") or "index.html")
    entry_path = resolve_project_path(root, f"{source_ref.rstrip('/')}/{entry_file}")
    return source_root, entry_path, composition_record


def _relative_project_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Visual revision artifacts must stay inside the private project.") from exc


def sha256_directory(path: Path) -> str:
    """Hash every registered composition source file and its project-relative name."""
    if not path.is_dir():
        raise ValueError(f"HyperFrames source directory is missing: {path}")
    digest = hashlib.sha256()
    for file_path in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.relative_to(path).as_posix()):
        relative = file_path.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        if file_path.suffix.lower() in VIDEO_EXTENSIONS | {".wav", ".mp3", ".m4a", ".aac", ".flac"}:
            stat = file_path.stat()
            digest.update(f"media:{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
            continue
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _copied_stream_hash(path: Path, stream_selector: str) -> str:
    """Hash encoded packets after stream copy so delivery can prove media identity."""
    result = subprocess.run(
        [
            str(find_ffmpeg()),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            stream_selector,
            "-c",
            "copy",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Could not verify the {stream_selector} stream in {path.name}. {details[-800:]}")
    match = re.search(r"SHA256=([0-9a-fA-F]{64})", result.stdout or "")
    if match is None:
        raise RuntimeError(f"FFmpeg did not return a stream hash for {path.name}.")
    return match.group(1).lower()


def remux_locked_audio(
    rendered_video: Path,
    locked_source: Path,
    output_path: Path,
    *,
    start_sec: float | None = None,
    duration_sec: float | None = None,
) -> None:
    """Attach the locked source audio without re-encoding either media stream."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(find_ffmpeg()), "-y", "-i", str(rendered_video)]
    if start_sec is not None and start_sec > 0:
        command += ["-ss", f"{start_sec:.4f}"]
    command += ["-i", str(locked_source), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy"]
    if duration_sec is not None:
        command += ["-t", f"{duration_sec:.4f}"]
    command += ["-movflags", "+faststart", str(output_path)]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Could not attach the locked audio to the visual render. {details[-1200:]}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg reported success but produced no audio-remuxed visual render.")

    if start_sec is None and duration_sec is None:
        locked_hash = _copied_stream_hash(locked_source, "0:a:0")
        delivered_hash = _copied_stream_hash(output_path, "0:a:0")
        if delivered_hash != locked_hash:
            raise RuntimeError("The delivered audio packet stream does not match the locked cut.")


def probe_delivery_media(path: Path) -> dict:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise RuntimeError("FFprobe is required to verify a Visual Production delivery.")
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration,nb_frames,sample_rate,channels:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Could not inspect the completed Visual Production video. {details[-1000:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FFprobe returned invalid delivery metadata.") from exc


def _frame_rate(value: str | None) -> float:
    text = str(value or "0")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return float(numerator) / max(float(denominator), 1.0)
    return float(text)


def _numeric_media_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def verify_delivered_media(path: Path, locked_source: Path, composition: dict, *, full_length: bool) -> dict:
    """Reject silent, truncated, or technically mismatched delivery files."""
    metadata = probe_delivery_media(path)
    streams = metadata.get("streams") if isinstance(metadata.get("streams"), list) else []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("The completed Visual Production file has no video stream.")
    if audio is None:
        raise RuntimeError("The completed Visual Production file has no audio stream.")

    expected_width = int(composition["width"])
    expected_height = int(composition["height"])
    expected_fps = float(composition["fps"])
    actual_fps = _frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    if int(video.get("width") or 0) != expected_width or int(video.get("height") or 0) != expected_height:
        raise RuntimeError("The completed Visual Production file does not match the planned delivery resolution.")
    if abs(actual_fps - expected_fps) > 0.02:
        raise RuntimeError("The completed Visual Production file does not match the planned frame rate.")

    expected_duration = float(composition["durationSec"])
    actual_duration = _numeric_media_value((metadata.get("format") or {}).get("duration") or video.get("duration"))
    duration_tolerance = max(0.08, 2 / max(expected_fps, 1.0))
    if full_length and abs(actual_duration - expected_duration) > duration_tolerance:
        raise RuntimeError("The completed Visual Production file does not match the locked-cut duration.")
    frame_count = round(_numeric_media_value(video.get("nb_frames")))
    expected_frames = round(expected_duration * expected_fps)
    if full_length and frame_count and abs(frame_count - expected_frames) > 2:
        raise RuntimeError("The completed Visual Production file does not match the planned frame count.")

    locked_metadata = probe_delivery_media(locked_source)
    locked_audio = next((stream for stream in locked_metadata.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if locked_audio is None:
        raise RuntimeError("The locked cut has no audio stream to deliver.")
    if str(audio.get("sample_rate") or "") != str(locked_audio.get("sample_rate") or "") or int(audio.get("channels") or 0) != int(locked_audio.get("channels") or 0):
        raise RuntimeError("The completed Visual Production audio format does not match the locked cut.")
    if full_length and _copied_stream_hash(path, "0:a:0") != _copied_stream_hash(locked_source, "0:a:0"):
        raise RuntimeError("The delivered audio packet stream does not match the locked cut.")
    return metadata


def write_delivery_manifest(
    plan_path: Path,
    final_render: Path,
    locked_source: Path,
    metadata: dict,
    *,
    library_curation: dict | None = None,
) -> Path:
    root = find_visual_root(plan_path)
    streams = metadata.get("streams") if isinstance(metadata.get("streams"), list) else []
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    project_manifest = next(root.glob("*.vcg-project.json"), None)
    normalization = {
        "applied": None,
        "status": "not-recorded",
        "preset": None,
        "targetIntegratedLufs": None,
        "measuredIntegratedLufs": None,
        "measurementPoint": "not-measured",
    }
    if project_manifest is not None:
        try:
            project_data = json.loads(project_manifest.read_text(encoding="utf-8"))
            evidence = (project_data.get("artifacts") or {}).get("audioDelivery")
            if isinstance(evidence, dict):
                applied = evidence.get("normalizationApplied")
                normalization = {
                    "applied": applied,
                    "status": "verified" if isinstance(applied, bool) else "not-recorded",
                    "preset": evidence.get("presetId"),
                    "targetIntegratedLufs": evidence.get("targetIntegratedLufs"),
                    "measuredIntegratedLufs": evidence.get("measuredIntegratedLufs"),
                    "measurementPoint": evidence.get("measurementPoint") or "not-measured",
                }
        except (OSError, json.JSONDecodeError):
            pass
    manifest = {
        "schemaVersion": 1,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "finalVideo": _relative_project_path(root, final_render),
        "lockedAudioSource": _relative_project_path(root, locked_source),
        "audio": {
            "normalization": normalization,
            "packetIdentity": "verified",
            "sourcePacketSha256": _copied_stream_hash(locked_source, "0:a:0"),
            "deliveredPacketSha256": _copied_stream_hash(final_render, "0:a:0"),
            "codec": audio.get("codec_name"),
            "sampleRate": int(audio.get("sample_rate") or 0),
            "channels": int(audio.get("channels") or 0),
        },
        "video": {
            "codec": video.get("codec_name"),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "frameRate": video.get("avg_frame_rate") or video.get("r_frame_rate"),
            "durationSec": _numeric_media_value((metadata.get("format") or {}).get("duration") or video.get("duration")),
        },
        "libraryCuration": library_curation or {"status": "not-run", "treatmentsRecorded": 0},
    }
    destination = root / "visual-production" / "delivery-manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)
    return destination


def publish_verified_render(staged_path: Path, requested_path: Path) -> Path:
    """Publish atomically, falling back to a versioned name when Windows holds the old file open."""
    requested_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staged_path, requested_path)
        return requested_path
    except OSError:
        if not requested_path.is_file():
            raise
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    for suffix in (timestamp, *[f"{timestamp}-{index}" for index in range(2, 100)]):
        fallback = requested_path.with_name(f"{requested_path.stem}-{suffix}{requested_path.suffix}")
        if fallback.exists():
            continue
        os.replace(staged_path, fallback)
        return fallback
    raise RuntimeError("Could not choose an available filename for the completed Visual Production video.")


def _hyperframes_progress_percent(line: str) -> float | None:
    percent = re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)%", line)
    if percent:
        return max(0.0, min(100.0, float(percent.group(1))))
    frames = re.search(r"(?<!\d)(\d+)\s*/\s*(\d+)\s*frames?", line, re.IGNORECASE)
    if frames and int(frames.group(2)) > 0:
        return max(0.0, min(100.0, int(frames.group(1)) / int(frames.group(2)) * 100))
    return None


def blanket_overflow_exceptions(plan_path: Path, plan: dict) -> list[str]:
    """Reject composition-root overflow suppression while allowing targeted decorative exceptions."""
    runtime_root, _entry, _composition = active_visual_runtime(plan_path, plan)
    if runtime_root is None or not runtime_root.is_dir():
        return []
    offenders: list[str] = []
    root_tag = re.compile(r"<(?P<tag>div|section|main)\b(?P<attrs>[^>]*data-composition-id[^>]*)>", re.IGNORECASE | re.DOTALL)
    for path in runtime_root.rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in root_tag.finditer(text):
            if "data-layout-allow-overflow" in match.group("attrs"):
                offenders.append(path.relative_to(runtime_root).as_posix())
                break
    return sorted(offenders)


def visual_safety_gate_issues(plan_path: Path, plan: dict) -> list[str]:
    """Require every approved audited graphic suggestion to survive into its rendered cue."""
    suggestions_path = find_visual_root(plan_path) / "visual-production" / "visual-suggestions.json"
    if not suggestions_path.is_file():
        return _missing_suggestions_issues(plan, "speaker-safety and treatment audits")
    try:
        data = json.loads(suggestions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["The visual suggestions audit cannot be read."]

    cues = {cue.get("id"): cue for cue in plan.get("cues", []) if cue.get("enabled", True)}
    issues: list[str] = []
    for suggestion in data.get("suggestions", []):
        is_graphic = suggestion.get("timelineLane") == "graphics" or suggestion.get("category") == "graphic"
        if not is_graphic or suggestion.get("status") in {"rejected", "needs-alternatives"}:
            continue
        suggestion_id = str(suggestion.get("id") or "unnamed graphic")
        cue_id = suggestion.get("cueId")
        cue = cues.get(cue_id)
        if suggestion.get("status") != "built" or cue is None:
            issues.append(f"{suggestion_id} has not been realized as its registered plan cue.")
            continue
        parameters = cue.get("parameters") if isinstance(cue.get("parameters"), dict) else {}
        for key in ("speakerSafety", "visualFamily", "candidateTreatmentIds", "selectionRationale"):
            if parameters.get(key) != suggestion.get(key):
                issues.append(f"{suggestion_id} cue does not preserve its approved {key} audit.")
        selected_id = suggestion.get("moduleId") or suggestion.get("recipeId")
        # A treatment renders either as its own module cue or as a registered custom composition
        # that names it. Either way the cue must say which treatment it is.
        realized_id = cue.get("moduleId") or parameters.get("recipeId")
        if selected_id != realized_id:
            issues.append(f"{suggestion_id} cue does not use its approved treatment {selected_id}.")
        for key in ("meaningfulChanges", "approvalEvidence"):
            if parameters.get(key) != suggestion.get(key):
                issues.append(f"{suggestion_id} cue does not preserve its approved {key} contract.")
        if parameters.get("planningSuggestionId") != suggestion_id:
            issues.append(f"{suggestion_id} cue is not linked back to its approved scene packet.")
        approved_id = (suggestion.get("decision") or {}).get("selectedTreatmentId")
        if parameters.get("approvedTreatmentId") != approved_id:
            issues.append(f"{suggestion_id} cue does not preserve its approved treatment-map decision.")
        issues.extend(speaker_safety_issues(
            suggestion_id,
            suggestion.get("speakerSafety"),
            (suggestion.get("scenePacket") or {}).get("layout"),
            start_sec=float(suggestion.get("startSec") or 0),
            end_sec=float(suggestion.get("endSec") or 0),
        ))
        packet = suggestion.get("scenePacket") if isinstance(suggestion.get("scenePacket"), dict) else {}
        protected_regions = packet.get("protectedRegions") if isinstance(packet.get("protectedRegions"), list) else []
        overlays = (suggestion.get("speakerSafety") or {}).get("overlayOcclusionBounds")
        if isinstance(overlays, list):
            for region in protected_regions:
                protected = _safe_normalized_bounds(region.get("bounds") if isinstance(region, dict) else None)
                if protected is None:
                    issues.append(f"{suggestion_id} has an invalid protected-content region.")
                    continue
                for value in overlays:
                    overlay = _safe_normalized_bounds(value)
                    if overlay is not None and bounds_intersect(protected, overlay):
                        issues.append(
                            f"{suggestion_id} places rendered graphics over protected content: "
                            f"{region.get('label') or 'important screen region'}."
                        )
    return issues


def locked_cut_drift_issues(plan_path: Path, plan: dict) -> list[str]:
    """Detect a plan whose cue times were authored against a different locked cut.

    Every cue time is seconds into a specific file. Re-cutting the transcript rewrites that file
    and leaves every cue pointing at the wrong moment, with nothing to notice it.
    """
    recorded = str((plan.get("source") or {}).get("videoSha256") or "")
    if not recorded:
        if not any(cue.get("enabled", True) for cue in plan.get("cues", [])):
            return []
        return [
            "This plan does not record which locked cut it was authored against, so cue timing "
            "cannot be verified. Re-create the visual plan from the current locked cut."
        ]
    try:
        source = resolve_project_path(find_visual_root(plan_path), (plan.get("source") or {}).get("video", ""))
    except ValueError:
        return ["The plan's locked cut is outside the private project."]
    if not source.is_file():
        return ["The locked cut this plan was authored against is missing."]
    if sha256_file(source) != recorded:
        cue_count = sum(1 for cue in plan.get("cues", []) if cue.get("enabled", True))
        return [
            f"The locked cut has changed since this plan was authored. All {cue_count} cue "
            "time(s) refer to the previous cut and must be re-timed before rendering."
        ]
    return []


def _missing_suggestions_issues(plan: dict, what: str) -> list[str]:
    """A plan with cues and no decision record cannot be traced, so it cannot be delivered."""
    if not any(cue.get("enabled", True) for cue in plan.get("cues", [])):
        return []
    return [
        f"visual-suggestions.json is missing, so the {what} cannot be checked "
        "and no cue in this plan can be traced to an approved decision."
    ]


def visual_planning_gate_issues(plan_path: Path, plan: dict) -> list[str]:
    """Block production until every planning decision is approved and traceable."""
    suggestions_path = find_visual_root(plan_path) / "visual-production" / "visual-suggestions.json"
    if not suggestions_path.is_file():
        return _missing_suggestions_issues(plan, "planning approvals")
    try:
        data = json.loads(suggestions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["The visual suggestions approval contract cannot be read."]
    suggestions = [
        item
        for item in data.get("suggestions", [])
        if item.get("status") != "rejected"
    ]
    issues = []
    cadence = (data.get("coverage") or {}).get("cadenceAudit") or {}
    if cadence.get("completeCoverage") is not True:
        issues.append("The visual plan does not account for the complete locked-cut runtime.")
    for violation in cadence.get("violations", []):
        try:
            label = f"{float(violation['startSec']):.3f}s-{float(violation['endSec']):.3f}s"
        except (KeyError, TypeError, ValueError):
            label = "unknown range"
        issues.append(f"Visual cadence violation at {label}: {violation.get('reason') or 'meaningful visual change gap exceeds five seconds'}.")
    approved_by_id = {}
    for suggestion in suggestions:
        suggestion_id = str(suggestion.get("id") or "unnamed scene")
        decision = suggestion.get("decision") if isinstance(suggestion.get("decision"), dict) else {}
        if decision.get("status") != "approved":
            issues.append(f"{suggestion_id} has not been approved in the pre-render scene review.")
            continue
        if suggestion.get("category") == "graphic" or suggestion.get("timelineLane") == "graphics":
            evidence = suggestion.get("approvalEvidence") if isinstance(suggestion.get("approvalEvidence"), dict) else {}
            selected = decision.get("selectedTreatmentId")
            if evidence.get("status") not in {"historical-ready", "sample-ready"}:
                issues.append(f"{suggestion_id} has no approved historical example or exact sample frame.")
            elif evidence.get("selectedTreatmentId") != selected:
                issues.append(f"{suggestion_id} approval evidence does not match its approved treatment.")
        approved_by_id[suggestion_id] = suggestion
    for cue in plan.get("cues", []):
        if not cue.get("enabled", True) or cue.get("moduleId") == "source-footage-hold":
            continue
        parameters = cue.get("parameters") if isinstance(cue.get("parameters"), dict) else {}
        suggestion_id = parameters.get("planningSuggestionId")
        if suggestion_id not in approved_by_id:
            issues.append(f"{cue.get('id') or 'unnamed cue'} is not backed by an approved scene selection.")
    return issues


@lru_cache(maxsize=4)
def _document_validator(name: str):
    from jsonschema import Draft202012Validator

    path = project_root() / "visual-production" / "schemas" / f"{name}.schema.json"
    if not path.is_file():
        raise RuntimeError(f"The {name} schema is missing. Documents cannot be validated without it.")
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_document_schema(name: str, document: dict, *, label: str) -> None:
    """Enforce the published JSON Schema on every read and write.

    The schemas were previously documentation: jsonschema was not a dependency, so no document
    had ever been checked against them. Running them alongside the Python validators means the
    two contracts cannot silently disagree.
    """
    errors = sorted(_document_validator(name).iter_errors(document), key=lambda error: list(error.path))
    if not errors:
        return
    details = "; ".join(_describe_schema_error(error) for error in errors[:5])
    more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
    raise ValueError(f"{label} does not match {name}.schema.json. {details}{more}")


def _describe_schema_error(error) -> str:
    """Name the field that is wrong.

    A oneOf failure reports the whole object as invalid, which says nothing useful when the real
    problem is one mistyped field. Drill into the closest-matching branch instead.
    """
    from jsonschema.exceptions import best_match

    if error.context:
        deepest = best_match(error.context)
        if deepest is not None:
            path = list(error.absolute_path) + list(deepest.path)
            location = "/".join(str(part) for part in path) or "document root"
            return f"{location}: {deepest.message}"
    location = "/".join(str(part) for part in error.absolute_path) or "document root"
    return f"{location}: {error.message}"


def scene_geometry_path() -> Path:
    return project_root() / "visual-production" / "layouts" / "scene-geometry.json"


@lru_cache(maxsize=1)
def scene_geometry() -> dict:
    path = scene_geometry_path()
    if not path.is_file():
        raise RuntimeError(
            "visual-production/layouts/scene-geometry.json is missing. Speaker safety cannot be measured without it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def measured_speaker_bounds(layout: str) -> dict[str, float] | None:
    """Return the measured speaker rectangle for a recording layout, or None when no speaker is on screen.

    Composited layouts are computed from the OBS scene geometry; full-screen-talking is measured from
    delivered footage because its camera source is uncropped. Either way these are facts about the
    capture setup, so they are looked up rather than accepted from a suggestion.
    """
    entry = scene_geometry()["layouts"].get(layout)
    if entry is None:
        raise ValueError(f"Layout {layout} has no measured scene geometry.")
    bounds = entry.get("speakerBounds")
    return dict(bounds) if isinstance(bounds, dict) else None


SCREEN_SHARE_SPEAKER_AREA = 0.15


def is_screen_share_layout(layout: str) -> bool:
    """True when the speaker sits in a corner or is absent, so the frame is mostly screen.

    On these layouts the thing that must stay readable is a region of the screen, not the whole
    span of time. Naming the region is what lets a graphic sit beside a demonstration instead of
    the demonstration being declared off-limits for minutes at a stretch.
    """
    bounds = measured_speaker_bounds(layout)
    if bounds is None:
        return True
    return bounds["width"] * bounds["height"] < SCREEN_SHARE_SPEAKER_AREA


def bounds_match(left: dict[str, float], right: dict[str, float], tolerance: float = 0.02) -> bool:
    return all(abs(left[key] - right[key]) <= tolerance for key in ("x", "y", "width", "height"))


def describe_bounds(bounds: dict[str, float]) -> str:
    frame = scene_geometry()["frame"]
    x0 = round(bounds["x"] * frame["width"])
    y0 = round(bounds["y"] * frame["height"])
    x1 = round((bounds["x"] + bounds["width"]) * frame["width"])
    y1 = round((bounds["y"] + bounds["height"]) * frame["height"])
    return f"({x0},{y0})-({x1},{y1})px"


def speaker_safety_issues(
    suggestion_id: str,
    safety: object,
    layout: object,
    *,
    start_sec: float | None = None,
    end_sec: float | None = None,
) -> list[str]:
    """The speaker-safety rules, in one place.

    Two implementations of these rules previously existed: one raising in the suggestion
    validator, one collecting issues in the production gate. They could disagree about what was
    safe, which is the worst possible way for a safety check to fail.
    """
    if not isinstance(safety, dict) or safety.get("checked") is not True:
        return [f"{suggestion_id} is missing its completed speaker-safety audit."]
    if safety.get("mode") not in SPEAKER_SAFETY_MODES:
        return [f"{suggestion_id} has an unknown speakerSafety mode."]
    try:
        absence = float(safety.get("maxSpeakerAbsenceSec"))
    except (TypeError, ValueError):
        return [f"{suggestion_id} needs maxSpeakerAbsenceSec."]
    if absence != 0:
        return [f"{suggestion_id} may not hide the speaker. Every graphic is an overlay; the speaker stays on screen."]

    issues: list[str] = []
    if start_sec is not None and end_sec is not None:
        verified = safety.get("verifiedAtSec")
        if not isinstance(verified, list):
            issues.append(f"{suggestion_id} must verify speaker safety at least three scene states.")
        else:
            try:
                times = [float(value) for value in verified]
            except (TypeError, ValueError):
                return [*issues, f"{suggestion_id} has invalid speakerSafety verifiedAtSec values."]
            if len(set(times)) < 3:
                issues.append(f"{suggestion_id} must verify speaker safety at least three scene states.")
            if any(value < start_sec or value > end_sec for value in times):
                issues.append(f"{suggestion_id} speakerSafety checks must stay inside the suggestion range.")

    try:
        speaker = measured_speaker_bounds(str(layout))
    except (ValueError, RuntimeError):
        return [
            *issues,
            f"{suggestion_id} needs a known scenePacket.layout before speaker safety can be measured.",
        ]
    reported = safety.get("speakerBounds")
    if speaker is not None:
        parsed = normalized_bounds(reported)
        if parsed is None or not bounds_match(parsed, speaker):
            issues.append(
                f"{suggestion_id} reports speakerBounds that do not match the measured geometry for "
                f"layout {layout} ({describe_bounds(speaker)}). Use the measured bounds; they are not "
                "a judgement call."
            )
    elif reported is not None:
        issues.append(f"{suggestion_id} uses layout {layout}, which has no speaker on screen.")

    overlays = safety.get("overlayOcclusionBounds")
    if not isinstance(overlays, list):
        return [*issues, f"{suggestion_id} needs overlayOcclusionBounds."]
    for index, value in enumerate(overlays):
        overlay = normalized_bounds(value)
        if overlay is None:
            issues.append(f"{suggestion_id} overlayOcclusionBounds[{index}] must be normalized frame bounds.")
        elif speaker is not None and bounds_intersect(speaker, overlay):
            issues.append(
                f"{suggestion_id} places an overlay over the speaker. Layout {layout} occupies "
                f"{describe_bounds(speaker)}; this overlay covers {describe_bounds(overlay)}."
            )
    return issues


def _safe_normalized_bounds(value: object) -> dict[str, float] | None:
    return normalized_bounds(value)


def visual_production_gate_report(plan_path: Path, plan: dict) -> dict:
    root = find_visual_root(plan_path)
    plan_hash = calculate_visual_plan_hash(plan, root)
    gates = plan.get("productionGates") if isinstance(plan.get("productionGates"), dict) else {}
    unanchored = [
        {"cueId": cue.get("id"), "semanticId": semantic.get("id"), "label": semantic.get("label")}
        for cue in plan.get("cues", []) if cue.get("enabled", True)
        for semantic in cue.get("semanticItems", [])
        if semantic.get("anchorType") == "unanchored" or not str(semantic.get("phrase") or "").strip()
    ]
    representative = gates.get("representativeApproval") if isinstance(gates.get("representativeApproval"), dict) else None
    representative_approved = bool(representative and representative.get("planHash") == plan_hash)
    revision = active_visual_revision(plan)
    review_render_available = False
    if revision and revision.get("planHash") == plan_hash and str(revision.get("reviewRender") or ""):
        review_render_available = resolve_project_path(find_visual_root(plan_path), str(revision["reviewRender"])).is_file()
    full_review = gates.get("fullReviewApproval") if isinstance(gates.get("fullReviewApproval"), dict) else None
    full_review_approved = bool(
        full_review and revision and review_render_available
        and full_review.get("planHash") == plan_hash
        and full_review.get("revisionNumber") == revision.get("number")
    )
    layout = gates.get("layoutInspection") if isinstance(gates.get("layoutInspection"), dict) else None
    layout_passed = bool(layout and layout.get("planHash") == plan_hash and layout.get("status") == "passed")
    overflow_files = blanket_overflow_exceptions(plan_path, plan)
    visual_safety_issues = visual_safety_gate_issues(plan_path, plan)
    planning_approval_issues = visual_planning_gate_issues(plan_path, plan)
    source_drift_issues = locked_cut_drift_issues(plan_path, plan)
    reopen = gates.get("deliveryReopen") if isinstance(gates.get("deliveryReopen"), dict) else None
    reopen_verified = bool(
        reopen and revision and revision.get("status") == "delivered"
        and reopen.get("planHash") == plan_hash
        and reopen.get("revisionNumber") == revision.get("number")
    )
    timing_anchored = not unanchored
    active_review_count = sum(1 for item in plan.get("reviews", []) if str(item.get("note") or "").strip())
    # Loop A gates the review render: every scene approved from its still frame.
    # Loop B gates delivery: the full render watched in context and signed off.
    # There is deliberately no route to a final export that skips either loop.
    planning_ready = (
        timing_anchored
        and not overflow_files
        and not visual_safety_issues
        and not planning_approval_issues
        and not source_drift_issues
    )
    can_render_review = planning_ready
    can_deliver = planning_ready and full_review_approved and active_review_count == 0
    messages: list[str] = []
    if unanchored:
        messages.append(f"Anchor {len(unanchored)} visible semantic item(s) to spokenStartSec and fullyVisibleSec before exporting.")
    if overflow_files:
        messages.append(f"Remove composition-root overflow suppression from {len(overflow_files)} HyperFrames file(s).")
    if visual_safety_issues:
        messages.append(f"Resolve {len(visual_safety_issues)} speaker-safety or treatment-audit issue(s) before rendering.")
    if planning_approval_issues:
        messages.append(f"Approve or revise {len(planning_approval_issues)} scene-planning decision(s) before rendering.")
    if active_review_count:
        messages.append(f"Accept or resolve {active_review_count} active review note(s) before exporting the final video.")
    if source_drift_issues:
        messages.extend(source_drift_issues)
    if planning_ready and not full_review_approved:
        messages.append(
            "Render a review pass and approve it against the full cut before exporting the final video."
            if not review_render_available
            else "Approve the full review render before exporting the final video."
        )
    return {
        "planHash": plan_hash,
        "representativeApproved": representative_approved,
        "fullReviewApproved": full_review_approved,
        "reviewRenderAvailable": review_render_available,
        "layoutInspectionPassed": layout_passed,
        "timingAnchored": timing_anchored,
        "unanchoredCount": len(unanchored),
        "unanchoredItems": unanchored,
        "noBlanketOverflow": not overflow_files,
        "blanketOverflowFiles": overflow_files,
        "speakerSafetyPassed": not visual_safety_issues,
        "speakerSafetyIssues": visual_safety_issues,
        "planningApprovalPassed": not planning_approval_issues,
        "planningApprovalIssues": planning_approval_issues,
        "lockedCutMatches": not source_drift_issues,
        "lockedCutIssues": source_drift_issues,
        "canRenderReview": can_render_review,
        "canDeliver": can_deliver,
        "canExportFinal": can_deliver,
        "activeReviewCount": active_review_count,
        "deliveryReopenVerified": reopen_verified,
        "messages": messages,
    }


def approve_representative_scene(plan_path: Path, cue_id: str) -> dict:
    plan = load_visual_plan(plan_path)
    cue = next((item for item in plan.get("cues", []) if item.get("id") == cue_id and item.get("enabled", True)), None)
    if cue is None:
        raise ValueError("Choose an enabled plan-backed cue as the representative scene.")
    plan["productionGates"]["representativeApproval"] = {
        "planHash": calculate_visual_plan_hash(plan, find_visual_root(plan_path)),
        "cueId": cue_id,
        "startSec": cue["startSec"],
        "endSec": cue["endSec"],
        "approvedAt": datetime.now(timezone.utc).isoformat(),
    }
    return save_visual_plan(plan_path, plan)


def approve_full_review(plan_path: Path) -> dict:
    plan = load_visual_plan(plan_path)
    plan_hash = calculate_visual_plan_hash(plan, find_visual_root(plan_path))
    revision = active_visual_revision(plan)
    if revision is None or revision.get("planHash") != plan_hash or not str(revision.get("reviewRender") or ""):
        raise ValueError("Render the current plan as a full review revision before approving it.")
    review_path = resolve_project_path(find_visual_root(plan_path), str(revision["reviewRender"]))
    if not review_path.is_file():
        raise ValueError("The active review render is missing.")
    plan["productionGates"]["fullReviewApproval"] = {
        "planHash": plan_hash,
        "revisionNumber": revision["number"],
        "approvedAt": datetime.now(timezone.utc).isoformat(),
    }
    return save_visual_plan(plan_path, plan)


def record_layout_inspection(plan_path: Path, *, commands: list[str]) -> dict:
    plan = load_visual_plan(plan_path)
    plan["productionGates"]["layoutInspection"] = {
        "planHash": calculate_visual_plan_hash(plan, find_visual_root(plan_path)),
        "status": "passed",
        "commands": commands,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    return save_visual_plan(plan_path, plan)


def record_review_revision(plan_path: Path, runtime_root: Path, review_render: Path) -> dict:
    plan = load_visual_plan(plan_path)
    root = find_visual_root(plan_path)
    plan_hash = calculate_visual_plan_hash(plan, root)
    revisions = plan["revisions"]
    active = active_visual_revision(plan)
    revision = active if active and active.get("status") == "review" and active.get("planHash") == plan_hash else None
    if revision is None:
        number = max((int(item["number"]) for item in revisions["items"]), default=0) + 1
        _runtime_root, runtime_entry, composition_record = active_visual_runtime(plan_path, plan)
        entry_file = runtime_entry.name if runtime_entry is not None else "index.html"
        now = datetime.now(timezone.utc).isoformat()
        revision = {
            "number": number,
            "id": f"r{number}",
            "name": f"Revision {number}",
            "status": "review",
            "runtime": "hyperframes",
            "compositionId": composition_record.get("id") if composition_record else None,
            "hyperframesSource": _relative_project_path(root, runtime_root),
            "entryFile": entry_file,
            "reviewRender": "",
            "finalRender": "",
            "planHash": plan_hash,
            "createdAt": now,
            "updatedAt": now,
        }
        revisions["items"].append(revision)
    revision["reviewRender"] = _relative_project_path(root, review_render)
    revision["reviewHash"] = sha256_file(review_render)
    revision["status"] = "review"
    revision["updatedAt"] = datetime.now(timezone.utc).isoformat()
    revisions["activeRevision"] = revision["number"]
    plan["productionGates"]["fullReviewApproval"] = None
    plan["productionGates"]["deliveryReopen"] = None
    return save_visual_plan(plan_path, plan)


def record_final_revision(plan_path: Path, final_render: Path) -> dict:
    plan = load_visual_plan(plan_path)
    root = find_visual_root(plan_path)
    plan_hash = calculate_visual_plan_hash(plan, root)
    revision = active_visual_revision(plan)
    if revision is None or revision.get("planHash") != plan_hash:
        runtime_root, runtime_entry, composition_record = active_visual_runtime(plan_path, plan)
        if runtime_root is None or runtime_entry is None:
            raise ValueError("Final delivery requires a registered HyperFrames composition.")
        number = max((int(item["number"]) for item in plan["revisions"]["items"]), default=0) + 1
        now = datetime.now(timezone.utc).isoformat()
        revision = {
            "number": number,
            "id": f"r{number}",
            "name": f"Revision {number}",
            "status": "review",
            "runtime": "hyperframes",
            "compositionId": composition_record.get("id") if composition_record else None,
            "hyperframesSource": _relative_project_path(root, runtime_root),
            "entryFile": runtime_entry.name,
            "reviewRender": "",
            "finalRender": "",
            "planHash": plan_hash,
            "createdAt": now,
            "updatedAt": now,
        }
        plan["revisions"]["items"].append(revision)
        plan["revisions"]["activeRevision"] = number
    for item in plan["revisions"]["items"]:
        if item is not revision and item.get("status") == "delivered":
            item["status"] = "superseded"
    revision["finalRender"] = _relative_project_path(root, final_render)
    revision["finalHash"] = sha256_file(final_render)
    revision["status"] = "delivered"
    revision["updatedAt"] = datetime.now(timezone.utc).isoformat()
    plan["productionGates"]["deliveryReopen"] = None
    return save_visual_plan(plan_path, plan)


def verify_delivered_revision_reopened(plan_path: Path, revision_number: int, plan_hash: str) -> dict:
    plan = load_visual_plan(plan_path)
    revision = active_visual_revision(plan)
    if revision is None or revision.get("number") != revision_number or revision.get("status") != "delivered":
        raise ValueError("The requested delivered revision is not active.")
    if plan_hash != calculate_visual_plan_hash(plan, find_visual_root(plan_path)) or revision.get("planHash") != plan_hash:
        raise ValueError("The delivered revision does not match the reopened plan hash.")
    final_path, _metadata = active_visual_master(plan_path, plan)
    _runtime_root, runtime_entry, _composition = active_visual_runtime(plan_path, plan)
    if not final_path.is_file() or runtime_entry is None or not runtime_entry.is_file():
        raise ValueError("The reopened delivery is missing its final render or HyperFrames source.")
    plan["productionGates"]["deliveryReopen"] = {
        "planHash": plan_hash,
        "revisionNumber": revision_number,
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
    }
    return save_visual_plan(plan_path, plan)


def _number(value, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _cue_window(cue: dict, range_start: float, range_end: float) -> tuple[float, float] | None:
    start = max(float(cue["startSec"]), range_start)
    end = min(float(cue["endSec"]), range_end)
    if end <= start:
        return None
    return start - range_start, end - start


LIBRARY_MODULE_IDS = {
    "side-list-panel", "result-badge", "link-chip",
    "milestone-path", "before-after-grade", "lower-third-flow",
}
# The catalog families, built. Each was a name with a description and no renderer; a plan that
# selected one could not even produce an approval frame, which is why plans came back thin.
PORTED_MODULE_IDS = {
    "three-step-celebration", "career-pathway", "list-reveal-pinned-thesis",
    "kinetic-word-punctuation", "numbered-step-intro", "problem-card-triptych",
    "speaker-rise-callouts", "conversation-bubble-sequence", "tradeoff-meter",
    "rank-medal-hit", "brand-cta-lockup", "command-popup-stack",
    "windows-prompt-typing", "uplifting-sunrise-finale",
}


def _ported_markup(
    module_id: str,
    params: dict,
    common: str,
    accent: str,
    kicker: str,
    staged_assets: dict[str, str] | None = None,
) -> str:
    """Markup for the fourteen catalog families, built against the creator's brand language."""
    side = str(params.get("side")) if str(params.get("side")) in SIDE_ANCHORS else "right"
    open_tag = f'<section {common} style="--cue-accent:{accent}">'
    kick = f'<div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'

    def accent_at(key: str) -> int:
        return int(_number(params.get(key), -1, -1, 9))

    if module_id == "three-step-celebration":
        steps = _strings(params.get("steps"), 3)
        payoff = html.escape(str(params.get("payoff") or ""))
        body = "".join(
            f'<div class="pf-step"><i>{index + 1}</i>'
            f'<span data-semantic-path="parameters.steps.{index}">{html.escape(step)}</span></div>'
            for index, step in enumerate(steps)
        )
        spark = "".join('<i class="pf-spark"></i>' for _ in range(9))
        return (f'{open_tag}<div class="pf-card pf-{side}">{kick}<div class="pf-steps">{body}</div>'
                f'<div class="pf-payoff" data-semantic-path="parameters.payoff">{payoff}</div>'
                f'<div class="pf-sparks">{spark}</div></div></section>')

    if module_id == "career-pathway":
        rows = _strings(params.get("rows"), 4)
        marked = accent_at("accentRowIndex")
        body = "".join(
            f'<div class="pf-path-row pf-{"odd" if index % 2 else "even"}{" lib-accent" if index == marked else ""}" '
            f'data-semantic-path="parameters.rows.{index}">{html.escape(row)}</div>'
            for index, row in enumerate(rows)
        )
        return f'{open_tag}<div class="pf-card pf-{side}">{kick}<div class="pf-path">{body}</div></div></section>'

    if module_id == "list-reveal-pinned-thesis":
        thesis = html.escape(str(params.get("thesis") or ""))
        rows = _strings(params.get("rows"), 5)
        marked = accent_at("accentRowIndex")
        body = "".join(
            f'<div class="pf-pin-row{" lib-accent" if index == marked else ""}" data-layout-allow-overlap>'
            f'<i></i><span data-semantic-path="parameters.rows.{index}">{html.escape(row)}</span></div>'
            for index, row in enumerate(rows)
        )
        return (f'{open_tag}<div class="pf-card pf-{side}">{kick}'
                f'<div class="pf-thesis" data-semantic-path="parameters.thesis">{thesis}</div>'
                f'<div class="pf-pin-rows">{body}</div></div></section>')

    if module_id == "kinetic-word-punctuation":
        phrase = html.escape(str(params.get("phrase") or "THIS"))
        anchor = str(params.get("anchor")) if str(params.get("anchor")) in {"top", "middle", "bottom"} else "middle"
        return (f'{open_tag}<div class="pf-kinetic pf-k-{anchor} pf-{side}">'
                f'<span data-semantic-path="parameters.phrase">{phrase}</span></div></section>')

    if module_id == "numbered-step-intro":
        number = int(_number(params.get("stepNumber"), 1, 1, 99))
        show_number = params.get("showNumber") is not False
        title = html.escape(str(params.get("title") or ""))
        action = html.escape(str(params.get("action") or ""))
        number_markup = f'<div class="pf-step-num">{number:02d}</div>' if show_number else ""
        no_number = " pf-step-no-num" if not show_number else ""
        return (f'{open_tag}<div class="pf-card pf-step-intro{no_number} pf-{side}">'
                f'{number_markup}'
                f'<div class="pf-step-title" data-semantic-path="parameters.title">{title}</div>'
                f'<div class="pf-step-action" data-semantic-path="parameters.action">{action}</div></div></section>')

    if module_id == "problem-card-triptych":
        cards = _strings(params.get("cards"), 3)
        marked = accent_at("accentCardIndex")
        body = "".join(
            f'<div class="pf-tri-card{" lib-accent" if index == marked else ""}"><i>{index + 1:02d}</i>'
            f'<span data-semantic-path="parameters.cards.{index}">{html.escape(card)}</span></div>'
            for index, card in enumerate(cards)
        )
        return f'{open_tag}<div class="pf-triptych">{kick}<div class="pf-tri-row">{body}</div></div></section>'

    if module_id == "speaker-rise-callouts":
        thesis = html.escape(str(params.get("thesis") or ""))
        callouts = _strings(params.get("callouts"), 4)
        marked = accent_at("accentCalloutIndex")
        body = "".join(
            f'<div class="pf-rise-item{" lib-accent" if index == marked else ""}" '
            f'data-semantic-path="parameters.callouts.{index}">{html.escape(call)}</div>'
            for index, call in enumerate(callouts)
        )
        return (f'{open_tag}<div class="pf-rise-thesis" data-semantic-path="parameters.thesis">{thesis}</div>'
                f'<div class="pf-rise">{body}</div></section>')

    if module_id == "conversation-bubble-sequence":
        bubbles = _strings(params.get("bubbles"), 4)
        marked = accent_at("accentBubbleIndex")
        body = "".join(
            f'<div class="pf-bubble pf-b-{"right" if index % 2 else "left"}{" lib-accent" if index == marked else ""}" '
            f'data-semantic-path="parameters.bubbles.{index}">{html.escape(bubble)}</div>'
            for index, bubble in enumerate(bubbles)
        )
        return f'{open_tag}<div class="pf-card pf-{side}">{kick}<div class="pf-bubbles">{body}</div></div></section>'

    if module_id == "tradeoff-meter":
        left_label = html.escape(str(params.get("leftLabel") or "EASY"))
        right_label = html.escape(str(params.get("rightLabel") or "CONTROL"))
        verdict = html.escape(str(params.get("verdict") or ""))
        value = _number(params.get("value"), 0.5, 0, 1) * 100
        return (f'{open_tag}<div class="pf-card pf-{side}">{kick}'
                f'<div class="pf-meter"><div class="pf-meter-fill" style="width:{value:.1f}%"></div>'
                f'<div class="pf-meter-knob" style="left:{value:.1f}%"></div></div>'
                f'<div class="pf-meter-labels"><span data-semantic-path="parameters.leftLabel">{left_label}</span>'
                f'<span data-semantic-path="parameters.rightLabel">{right_label}</span></div>'
                f'<div class="pf-verdict" data-semantic-path="parameters.verdict">{verdict}</div></div></section>')

    if module_id == "rank-medal-hit":
        rank = html.escape(str(params.get("rank") or "#1"))
        verdict = html.escape(str(params.get("verdict") or ""))
        medal = html.escape(str(params.get("medal") or "★"))
        return (f'{open_tag}<div class="pf-card pf-medal pf-{side}"><div class="pf-medal-disc">{medal}</div>'
                f'<div class="pf-rank" data-semantic-path="parameters.rank">{rank}</div>'
                f'<div class="pf-verdict" data-semantic-path="parameters.verdict">{verdict}</div></div></section>')

    if module_id == "brand-cta-lockup":
        logo = html.escape(str(params.get("logoText") or "VCG"))
        logo_asset_id = str(params.get("logoAssetId") or "")
        staged_logo = (staged_assets or {}).get(logo_asset_id)
        if logo_asset_id and not staged_logo:
            raise ValueError(f"brand-cta-lockup references unknown logoAssetId: {logo_asset_id}")
        action = html.escape(str(params.get("action") or ""))
        destination = html.escape(str(params.get("destination") or ""))
        logo_markup = (
            f'<img class="pf-logo-image" src="assets/{html.escape(staged_logo)}" alt="{logo}" '
            f'data-semantic-path="parameters.logoText"/>'
            if staged_logo else
            f'<div class="pf-logo" data-semantic-path="parameters.logoText">{logo}</div>'
        )
        community_class = " pf-community" if staged_logo else ""
        return (f'{open_tag}<div class="pf-card pf-cta{community_class} pf-{side}">'
                f'{logo_markup}'
                f'<div class="pf-action" data-semantic-path="parameters.action">{action}</div>'
                f'<div class="pf-dest" data-semantic-path="parameters.destination">{destination}</div></div></section>')

    if module_id == "command-popup-stack":
        commands = _strings(params.get("commands"), 5)
        purposes = _strings(params.get("purposes"), 5)
        marked = accent_at("accentCommandIndex")
        body = "".join(
            f'<div class="pf-cmd{" lib-accent" if index == marked else ""}">'
            f'<b data-semantic-path="parameters.commands.{index}">{html.escape(command)}</b>'
            + (f'<span data-semantic-path="parameters.purposes.{index}">{html.escape(purposes[index])}</span>'
               if index < len(purposes) else "")
            + '</div>'
            for index, command in enumerate(commands)
        )
        return f'{open_tag}<div class="pf-card pf-{side}">{kick}<div class="pf-cmds">{body}</div></div></section>'

    if module_id == "windows-prompt-typing":
        app_name = html.escape(str(params.get("appName") or "PowerPoint"))
        prompt_text = html.escape(str(params.get("prompt") or ""))
        return (f'{open_tag}<div class="pf-window pf-{side}">'
                f'<div class="pf-titlebar"><span data-semantic-path="parameters.appName">{app_name}</span>'
                f'<i></i><i></i><i></i></div>'
                f'<div class="pf-prompt" data-semantic-path="parameters.prompt">{prompt_text}</div></div></section>')

    claim = html.escape(str(params.get("claim") or ""))
    action = html.escape(str(params.get("action") or ""))
    return (f'{open_tag}<div class="pf-sunrise"><div class="pf-sun"></div>{kick}'
            f'<div class="pf-claim" data-semantic-path="parameters.claim">{claim}</div>'
            f'<div class="pf-final-action" data-semantic-path="parameters.action">{action}</div></div></section>')


def _strings(value: object, limit: int) -> list[str]:
    return [str(item) for item in value[:limit]] if isinstance(value, list) else []


def _library_markup(module_id: str, params: dict, common: str, accent: str, kicker: str, text: str) -> str:
    """Markup for the families ported from the creator's built library.

    Each anchors to one edge of the frame so a software demonstration stays readable behind it,
    which is why these were the ones that worked in the July-22 video.
    """
    side = str(params.get("side")) if str(params.get("side")) in SIDE_ANCHORS else "right"
    accent_index = int(_number(params.get("accentRowIndex", params.get("accentLineIndex", params.get("accentWordIndex", params.get("accentStopIndex", params.get("accentItemIndex", -1))))), -1, -1, 9))
    open_tag = f'<section {common} style="--cue-accent:{accent}">'

    if module_id == "side-list-panel":
        rows = _strings(params.get("rows"), 6)
        numbered = str(params.get("rowStyle")) != "plain"
        body = "".join(
            f'<div class="lib-row{" lib-accent" if index == accent_index else ""}">'
            f'{f"<i>{index + 1:02d}</i>" if numbered else "<i></i>"}'
            f'<b data-semantic-path="parameters.rows.{index}">{html.escape(row)}</b></div>'
            for index, row in enumerate(rows)
        )
        title = f'<div class="lib-title" data-semantic-path="parameters.text">{text}</div>' if params.get("text") else ""
        return (f'{open_tag}<div class="lib-panel lib-{side}">'
                f'<div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
                f'{title}<div class="lib-rows">{body}</div></div></section>')

    if module_id == "result-badge":
        lines = _strings(params.get("lines"), 4)
        mark = html.escape(str(params.get("mark") or "✓"))
        body = "".join(
            f'<div class="lib-result-line{" lib-accent" if index == accent_index else ""}" '
            f'data-semantic-path="parameters.lines.{index}">{html.escape(line)}</div>'
            for index, line in enumerate(lines)
        )
        return (f'{open_tag}<div class="lib-badge lib-{side}"><span class="lib-check">{mark}</span>'
                f'<div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
                f'{body}</div></section>')

    if module_id == "link-chip":
        words = _strings(params.get("words"), 6)
        glyph = html.escape(str(params.get("glyph") or "→"))
        body = "".join(
            f'<span class="{"lib-accent" if index == accent_index else ""}" '
            f'data-semantic-path="parameters.words.{index}">{html.escape(word)}</span>'
            for index, word in enumerate(words)
        )
        return (f'{open_tag}<div class="lib-chip lib-{side}"><div class="lib-glyph">{glyph}</div>'
                f'<div><div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
                f'<div class="lib-words">{body}</div></div></div></section>')

    if module_id == "milestone-path":
        stops = _strings(params.get("stops"), 5)
        body = "".join(
            f'<div class="lib-stop{" lib-accent" if index == accent_index else ""}"><i></i>'
            f'<span data-semantic-path="parameters.stops.{index}">{html.escape(stop)}</span></div>'
            for index, stop in enumerate(stops)
        )
        title = f'<div class="lib-title" data-semantic-path="parameters.text">{text}</div>' if params.get("text") else ""
        return (f'{open_tag}<div class="lib-path lib-{side}"><div class="lib-spine"></div>'
                f'<div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
                f'{title}{body}</div></section>')

    if module_id == "before-after-grade":
        before_raw = str(params.get("before") or "C")
        after_raw = str(params.get("after") or "A")
        before = html.escape(before_raw)
        after = html.escape(after_raw)
        before_class = " lib-long" if len(before_raw) > 3 else ""
        after_class = " lib-long" if len(after_raw) > 3 else ""
        arrow = html.escape(str(params.get("arrow") or "→"))
        footer_left = html.escape(str(params.get("footerLeft") or ""))
        footer_right = html.escape(str(params.get("footerRight") or ""))
        return (f'{open_tag}<div class="lib-grade lib-{side}">'
                f'<div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
                f'<div class="lib-track"><span class="lib-before{before_class}" data-semantic-path="parameters.before">{before}</span>'
                f'<i>{arrow}</i><span class="lib-after{after_class}" data-semantic-path="parameters.after">{after}</span></div>'
                f'<div class="lib-grade-foot"><span data-semantic-path="parameters.footerLeft">{footer_left}</span>'
                f'<b data-semantic-path="parameters.footerRight">{footer_right}</b></div></div></section>')

    items = _strings(params.get("items"), 6)
    variant = str(params.get("variant")) if str(params.get("variant")) in {"flow", "stack", "celebrate"} else "flow"
    body = "".join(
        f'<span class="lib-flow-item{" lib-accent" if index == accent_index else ""}" '
        f'data-semantic-path="parameters.items.{index}">{html.escape(item)}</span>'
        for index, item in enumerate(items)
    )
    return (f'{open_tag}<div class="lib-lower lib-{variant}"><div class="lib-lower-rail"></div>'
            f'<div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
            f'<div class="lib-flow">{body}</div></div></section>')


def _speaker_safe_overlay_style(params: dict) -> str:
    """Place an opaque graphic inside the exact region approved by speaker safety."""
    safety = params.get("speakerSafety") if isinstance(params.get("speakerSafety"), dict) else {}
    overlays = safety.get("overlayOcclusionBounds")
    overlay_items = overlays if isinstance(overlays, list) else [overlays] if isinstance(overlays, dict) else []
    valid = [
        bounds
        for item in overlay_items
        if (bounds := normalized_bounds(item)) is not None
    ]
    bounds = max(valid, key=lambda item: item["width"] * item["height"]) if valid else {
        "x": .18, "y": .02, "width": .78, "height": .62,
    }
    return (
        f'left:{bounds["x"] * 100:.3f}%;top:{bounds["y"] * 100:.3f}%;'
        f'width:{bounds["width"] * 100:.3f}%;height:{bounds["height"] * 100:.3f}%;'
        "right:auto;bottom:auto;border:3px solid var(--ink);"
        "box-shadow:14px 16px 0 rgba(0,124,125,.24)"
    )


def _module_markup(
    cue: dict,
    element_id: str,
    start: float,
    duration: float,
    track: int,
    staged_assets: dict[str, str] | None = None,
) -> str:
    params = cue.get("parameters") or {}
    module_id = cue["moduleId"]
    text = html.escape(str(params.get("text") or "EDIT THIS TEXT"))
    kicker = html.escape(str(params.get("kicker") or "VCG / VISUAL"))
    accent_color = html.escape(str(params.get("accentColor") or "#FF00CE"))
    common = (
        f'id="{element_id}" class="clip module module-{module_id}" '
        f'data-start="{start:.4f}" data-duration="{duration:.4f}" data-track-index="{track}"'
    )
    safe_overlay_style = _speaker_safe_overlay_style(params)
    if module_id == "source-footage-hold":
        return ""
    if module_id == "punchline-reveal":
        image_asset_id = str(params.get("imageAssetId") or "")
        staged_image = (staged_assets or {}).get(image_asset_id)
        if image_asset_id and not staged_image:
            raise ValueError(f"punchline-reveal references unknown imageAssetId: {image_asset_id}")
        if staged_image:
            return (
                f'<section {common} style="--cue-accent:{accent_color}">'
                f'<div class="joke-card-approved">'
                f'<img class="joke-image-approved" src="assets/{html.escape(staged_image)}" alt="" />'
                f'<div class="joke-copy-approved">'
                f'<div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
                f'<div class="joke-line-approved" data-semantic-path="parameters.text">{text}</div>'
                f'</div></div></section>'
            )
        return f'<section {common} style="--cue-accent:{accent_color}"><div class="module-fill" style="{safe_overlay_style}"><div class="grid"></div><div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div><div class="punchline" data-semantic-path="parameters.text">{text}</div><div class="rule"></div></div></section>'
    if module_id == "speaker-side-panel":
        return f'<section {common} style="--cue-accent:{accent_color}"><div class="side-copy"><div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div><div class="side-title" data-semantic-path="parameters.text">{text}</div></div><div class="video-outline"></div></section>'
    if module_id == "progress-scale":
        start_label = html.escape(str(params.get("startLabel") or "START"))
        target_label = html.escape(str(params.get("targetLabel") or "TARGET"))
        milestones = params.get("milestones") if isinstance(params.get("milestones"), list) else []
        milestone_markup = "".join(
            f'<span data-semantic-path="parameters.milestones.{index}" '
            f'style="border-left:5px solid var(--teal);padding:8px 10px;color:var(--ink);'
            f'font-size:18px;font-weight:800;line-height:1.05">{html.escape(str(item))}</span>'
            for index, item in enumerate(milestones[:4])
        )
        milestones_markup = (
            f'<div class="scale-milestones" style="position:absolute;left:7%;right:7%;bottom:24%;'
            f'display:grid;grid-template-columns:repeat({len(milestones[:4])},minmax(0,1fr));'
            f'gap:12px">{milestone_markup}</div>'
            if milestone_markup else ""
        )
        return f'<section {common}><div class="module-fill" style="{safe_overlay_style}"><div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div><div class="stat-title" data-semantic-path="parameters.text">{text}</div>{milestones_markup}<div class="scale"><div class="scale-fill"></div><div class="scale-marker"></div><div class="scale-labels"><span data-semantic-path="parameters.startLabel">{start_label}</span><span data-semantic-path="parameters.targetLabel">{target_label}</span></div></div></div></section>'
    if module_id == "dual-comparison":
        left_title = html.escape(str(params.get("leftTitle") or "OPTION A"))
        right_title = html.escape(str(params.get("rightTitle") or "OPTION B"))
        left_color = html.escape(str(params.get("leftColor") or "#4D7CFE"))
        right_color = html.escape(str(params.get("rightColor") or "#6E56CF"))
        left_items = params.get("leftItems") if isinstance(params.get("leftItems"), list) else []
        right_items = params.get("rightItems") if isinstance(params.get("rightItems"), list) else []
        left_markup = "".join(f'<li data-semantic-path="parameters.leftItems.{index}">{html.escape(str(item))}</li>' for index, item in enumerate(left_items[:5]))
        right_markup = "".join(f'<li data-semantic-path="parameters.rightItems.{index}">{html.escape(str(item))}</li>' for index, item in enumerate(right_items[:5]))
        return (
            f'<section {common} style="--left-accent:{left_color};--right-accent:{right_color}">'
            f'<div class="comparison-canvas" style="{safe_overlay_style};grid-template-columns:repeat(2,minmax(0,1fr));padding:76px 28px 24px">'
            f'<div class="comparison-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
            f'<div class="comparison-column comparison-left"><h2 data-semantic-path="parameters.leftTitle">{left_title}</h2><ul>{left_markup}</ul></div>'
            f'<div class="comparison-column comparison-right"><h2 data-semantic-path="parameters.rightTitle">{right_title}</h2><ul>{right_markup}</ul></div>'
            f'</div></section>'
        )
    if module_id == "source-punch-zoom":
        # Pure camera move on the source. It renders no overlay at all, which is what makes it
        # usable over a demonstration that must stay readable.
        return f'<section {common}></section>'
    if module_id in LIBRARY_MODULE_IDS:
        return _library_markup(module_id, params, common, accent_color, kicker, text)
    if module_id in PORTED_MODULE_IDS:
        return _ported_markup(module_id, params, common, accent_color, kicker, staged_assets)
    if module_id == "ui-callout":
        label = html.escape(str(params.get("label") or "THIS"))
        detail = html.escape(str(params.get("detail") or ""))
        target = normalized_bounds(params.get("targetBounds")) or {"x": .55, "y": .12, "width": .35, "height": .18}
        pointer = "above" if str(params.get("pointer")) == "above" else "below"
        left, top = target["x"] * 100, target["y"] * 100
        wide, tall = target["width"] * 100, target["height"] * 100
        label_top = (target["y"] + target["height"]) * 100 if pointer == "below" else target["y"] * 100
        align_right = target["x"] + target["width"] > .78
        label_left = (target["x"] + target["width"]) * 100 if align_right else left
        alignment_class = " callout-align-right" if align_right else ""
        detail_markup = (
            f'<span class="callout-detail" data-semantic-path="parameters.detail">{detail}</span>' if detail else ""
        )
        return (
            f'<section {common} style="--cue-accent:{accent_color}">'
            f'<div class="callout-ring" style="left:{left:.3f}%;top:{top:.3f}%;width:{wide:.3f}%;height:{tall:.3f}%"></div>'
            f'<div class="callout-label callout-{pointer}{alignment_class}" style="left:{label_left:.3f}%;top:{label_top:.3f}%">'
            f'<span class="callout-text" data-semantic-path="parameters.label">{label}</span>{detail_markup}</div>'
            f'</section>'
        )
    if module_id == "numbered-example-card":
        number = int(_number(params.get("exampleNumber"), 1, 1, 99))
        total = int(_number(params.get("totalExamples"), 10, 1, 99))
        accent_index = int(_number(params.get("accentLineIndex"), -1, -1, 4))
        lines = params.get("titleLines") if isinstance(params.get("titleLines"), list) else []
        tags = params.get("tags") if isinstance(params.get("tags"), list) else []
        line_markup = "".join(
            f'<div class="example-line{" example-line-accent" if index == accent_index else ""}" '
            f'data-semantic-path="parameters.titleLines.{index}">{html.escape(str(line))}</div>'
            for index, line in enumerate(lines[:3])
        )
        tag_markup = html.escape(" • ".join(str(tag) for tag in tags[:4]))
        pips = "".join(
            f'<span class="example-pip{" example-pip-filled" if index < number else ""}"></span>'
            for index in range(total)
        )
        return (
            f'<section {common} style="--cue-accent:{accent_color}">'
            f'<div class="example-card">'
            f'<div class="example-rail"><div class="example-number">{number:02d}</div><div class="example-rail-label">EXAMPLE</div></div>'
            f'<div class="example-body">'
            f'<div class="example-head"><span class="kicker" data-semantic-path="parameters.kicker">{kicker}</span>'
            f'<span class="example-count">{number:02d} / {total:02d}</span></div>'
            f'<div class="example-rule"></div>'
            f'<div class="example-lines">{line_markup}</div>'
            f'<div class="example-foot"><span class="example-tags">{tag_markup}</span><span class="example-pips">{pips}</span></div>'
            f'</div></div></section>'
        )
    nodes = params.get("nodes") if isinstance(params.get("nodes"), list) else ["YOUR PRODUCT", "PLATFORM", "DEPENDENCY"]
    node_markup = "".join(f'<div class="node" data-semantic-path="parameters.nodes.{index}">{html.escape(str(node))}</div>' for index, node in enumerate(nodes[:5]))
    return f'<section {common}><div class="dependency-panel"><div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div><div class="dependency-title" data-semantic-path="parameters.text">{text}</div><div class="nodes">{node_markup}</div></div></section>'


def _asset_markup(asset: dict, cue: dict, element_id: str, staged_name: str, start: float, duration: float, track: int) -> tuple[str, str | None]:
    params = cue.get("parameters") or {}
    x = _number(params.get("x"), 0, 0, 100)
    y = _number(params.get("y"), 0, 0, 100)
    width = _number(params.get("width"), 100, 1, 100)
    height = _number(params.get("height"), 100, 1, 100)
    opacity = _number(params.get("opacity"), 1, 0, 1)
    scale = _number(params.get("scale"), 1, 0.05, 10)
    rotation = _number(params.get("rotation"), 0, -360, 360)
    media_start = _number(params.get("sourceStartSec"), 0, 0, 86400)
    fit = params.get("fit") if params.get("fit") in {"cover", "contain", "fill"} else "cover"
    style = (
        f'left:{x}%;top:{y}%;width:{width}%;height:{height}%;opacity:{opacity};object-fit:{fit};'
        f'transform:scale({scale}) rotate({rotation}deg);transform-origin:center center;'
    )
    attrs = (
        f'id="{element_id}" class="clip imported" src="assets/{html.escape(staged_name)}" '
        f'data-start="{start:.4f}" data-duration="{duration:.4f}" data-media-start="{media_start:.4f}" '
        f'data-track-index="{track}" style="{style}"'
    )
    if asset["mediaType"] == "image":
        return f'<img {attrs} alt="" />', None
    video = f'<video {attrs} muted playsinline></video>'
    if bool(params.get("muted", True)):
        return video, None
    volume = _number(params.get("volume"), 1, 0, 1)
    audio = (
        f'<audio id="{element_id}-audio" src="assets/{html.escape(staged_name)}" '
        f'data-start="{start:.4f}" data-duration="{duration:.4f}" data-media-start="{media_start:.4f}" '
        f'data-track-index="{track + 100}" data-volume="{volume}"></audio>'
    )
    return video, audio


def _semantic_timeline_lines(cue: dict, element_id: str, range_start: float, range_end: float, clip_start: float) -> list[str]:
    lines: list[str] = []
    for semantic in cue.get("semanticItems", []):
        path = str(semantic.get("parameterPath") or "").replace('"', '\\"')
        spoken = float(semantic["spokenStartSec"])
        fully = float(semantic["fullyVisibleSec"])
        selector = f'#{element_id} [data-semantic-path="{path}"]'
        if fully <= range_start:
            lines.append(f'tl.set(\'{selector}\', {{opacity:1,y:0}}, {clip_start:.4f});')
            continue
        if spoken >= range_end:
            lines.append(f'tl.set(\'{selector}\', {{opacity:0,y:12}}, {clip_start:.4f});')
            continue
        reveal_at = max(spoken, range_start) - range_start
        reveal_duration = max(0.001, fully - max(spoken, range_start))
        lines.append(f'tl.set(\'{selector}\', {{opacity:0,y:12}}, {clip_start:.4f});')
        lines.append(f'tl.fromTo(\'{selector}\', {{opacity:0,y:12}}, {{opacity:1,y:0,duration:{reveal_duration:.4f},ease:"power2.out",immediateRender:false}}, {reveal_at:.4f});')
    return lines


def _wrap_module_motion(markup: str) -> str:
    """Keep authored motion off the framework-owned clip element.

    HyperFrames owns visibility for ``.clip`` nodes. Animating a clip directly makes
    non-linear seeking ambiguous, so every module gets one inner wrapper for entrance
    and exit motion while the registered clip remains untouched.
    """
    if not markup:
        return markup
    opening_end = markup.find(">")
    closing_start = markup.rfind("</section>")
    if opening_end < 0 or closing_start < 0:
        raise ValueError("Visual module markup must be a section element.")
    return (
        f'{markup[:opening_end + 1]}<div class="cue-motion">'
        f'{markup[opening_end + 1:closing_start]}</div>{markup[closing_start:]}'
    )


def _entry_preroll_time(start: float, fps: int) -> float:
    """Advance entrance motion one frame without changing clip visibility timing."""
    return max(0.0, start - (1.0 / max(1, fps)))


def build_hyperframes_composition(
    plan_path: Path,
    *,
    start_sec: float | None = None,
    end_sec: float | None = None,
    workspace_override: Path | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Path, float]:
    progress = progress or (lambda _value, _message: None)
    root = find_visual_root(plan_path)
    plan = load_visual_plan(plan_path)
    composition = plan["composition"]
    full_duration = float(composition["durationSec"])
    range_start = max(0.0, float(start_sec or 0.0))
    range_end = min(full_duration, float(end_sec if end_sec is not None else full_duration))
    if range_end <= range_start:
        raise ValueError("Render range must have a positive duration.")
    render_duration = range_end - range_start
    fps = max(1, round(float(composition.get("fps") or 30)))
    width = int(composition["width"])
    height = int(composition["height"])

    workspace = workspace_override.resolve() if workspace_override is not None else root / "working" / "hyperframes"
    if not _is_within(workspace, root):
        raise ValueError("HyperFrames workspace must stay inside the private visual project.")
    public = workspace / "public"
    if workspace.exists():
        shutil.rmtree(workspace)
    (public / "assets").mkdir(parents=True, exist_ok=True)
    (public / "fonts").mkdir(parents=True, exist_ok=True)
    (public / "vendor").mkdir(parents=True, exist_ok=True)

    progress(8, "Preparing the locked source video...")
    source = resolve_project_path(root, plan["source"]["video"])
    staged_source = public / "source.mp4"
    command = [str(find_ffmpeg()), "-y"]
    if range_start > 0:
        command += ["-ss", f"{range_start:.4f}"]
    command += ["-i", str(source), "-t", f"{render_duration:.4f}", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-g", str(fps), "-keyint_min", str(fps), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", str(staged_source)]
    result = subprocess.run(command, capture_output=True, text=True, check=False, creationflags=hidden_subprocess_flags())
    if result.returncode != 0:
        raise RuntimeError(f"Could not prepare the visual-production source. {(result.stderr or result.stdout)[-1000:]}")

    progress(22, "Freezing imported assets into the render workspace...")
    assets_by_id = {asset["id"]: asset for asset in plan.get("assets", [])}
    staged_assets: dict[str, str] = {}
    for asset in assets_by_id.values():
        source_asset = resolve_project_path(root, asset["path"])
        staged_name = f'{asset["id"]}{source_asset.suffix.lower()}'
        shutil.copy2(source_asset, public / "assets" / staged_name)
        staged_assets[asset["id"]] = staged_name

    repo = project_root()
    gsap_source = repo / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    if not gsap_source.is_file():
        raise RuntimeError("GSAP is not installed. Run npm install before rendering visual projects.")
    shutil.copy2(gsap_source, public / "vendor" / "gsap.min.js")
    font_files = repo / "node_modules" / "@fontsource" / "montserrat" / "files"
    for weight in (400, 600, 700, 800, 900):
        candidate = font_files / f"montserrat-latin-{weight}-normal.woff2"
        if candidate.is_file():
            shutil.copy2(candidate, public / "fonts" / f"Montserrat-{weight}.woff2")

    progress(34, "Building the deterministic HyperFrames composition...")
    clip_markup: list[str] = []
    audio_markup: list[str] = []
    timeline_lines: list[str] = []
    cue_index = 0
    for cue in sorted((item for item in plan.get("cues", []) if item.get("enabled", True)), key=lambda item: float(item["startSec"])):
        window = _cue_window(cue, range_start, range_end)
        if window is None:
            continue
        start, duration = window
        element_id = f"cue-{re.sub(r'[^a-zA-Z0-9_-]', '-', str(cue['id']))}"
        track = 20 + cue_index
        cue_index += 1
        if cue["kind"] == "module":
            markup = _wrap_module_motion(
                _module_markup(cue, element_id, start, duration, track, staged_assets)
            )
            if markup:
                clip_markup.append(markup)
            module_id = cue["moduleId"]
            params = cue.get("parameters") or {}
            motion_selector = f"#{element_id} > .cue-motion"
            transition_in = params.get("transitionIn", "editorial-snap")
            transition_out = params.get("transitionOut", "fade")
            enter = min(0.45, duration / 3)
            exit_duration = min(0.35, duration / 4)
            entry_start = _entry_preroll_time(start, fps)
            if markup:
                if transition_in == "none":
                    timeline_lines.append(f'tl.set("{motion_selector}", {{opacity:1,x:0}}, {start:.4f});')
                elif transition_in == "fade":
                    timeline_lines.append(f'tl.fromTo("{motion_selector}", {{opacity:0}}, {{opacity:1,duration:{enter:.3f},ease:"power2.out"}}, {entry_start:.4f});')
                else:
                    distance = -70 if transition_in == "editorial-snap" else -35
                    timeline_lines.append(f'tl.fromTo("{motion_selector}", {{opacity:0,x:{distance}}}, {{opacity:1,x:0,duration:{enter:.3f},ease:"power3.out"}}, {entry_start:.4f});')
                if transition_out != "none" and duration > exit_duration + enter:
                    exit_x = 35 if transition_out == "slide" else 0
                    timeline_lines.append(f'tl.to("{motion_selector}", {{opacity:0,x:{exit_x},duration:{exit_duration:.3f},ease:"power2.in"}}, {(start + duration - exit_duration):.4f});')
                    timeline_lines.append(f'tl.set("{motion_selector}", {{opacity:0}}, {(start + duration):.4f});')
                timeline_lines.extend(_semantic_timeline_lines(cue, element_id, range_start, range_end, start))
            if module_id == "punchline-reveal":
                # The graphic occupies only its audited overlay region. The source speaker remains
                # visible continuously; the canonical contract forbids full-frame takeovers.
                pass
            elif module_id == "speaker-side-panel":
                timeline_lines.append(f'tl.to("#main-video", {{scale:0.48,x:{width * .48:.2f},y:{height * .26:.2f},duration:0.5,ease:"power3.inOut"}}, {start:.4f});')
                timeline_lines.append(f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:0.45,ease:"power3.inOut"}}, {(start + duration - 0.45):.4f});')
            elif module_id == "progress-scale":
                timeline_lines.append(f'tl.fromTo("#{element_id} .scale-fill", {{scaleX:0}}, {{scaleX:1,duration:{max(.2, duration - .8):.3f},ease:"power2.inOut"}}, {(start + .4):.4f});')
            elif module_id == "dual-comparison":
                timeline_lines.append(f'tl.fromTo("#{element_id} .comparison-column", {{opacity:0,y:24}}, {{opacity:1,y:0,duration:0.38,stagger:0.08,ease:"power2.out"}}, {(start + .28):.4f});')
            elif module_id == "source-punch-zoom":
                focus_x = _number(params.get("focusX"), 0.5, 0, 1) * 100
                focus_y = _number(params.get("focusY"), 0.5, 0, 1) * 100
                zoom = _number(params.get("zoom"), 1.25, 1.02, MAX_PUNCH_ZOOM)
                settle = _number(params.get("settleSec"), 0.6, 0.2, max(0.3, duration / 2))
                timeline_lines.append(f'tl.to("#main-video", {{scale:{zoom:.4f},transformOrigin:"{focus_x:.2f}% {focus_y:.2f}%",duration:{settle:.3f},ease:"power2.inOut"}}, {start:.4f});')
                timeline_lines.append(f'tl.to("#main-video", {{scale:1,transformOrigin:"{focus_x:.2f}% {focus_y:.2f}%",duration:{settle:.3f},ease:"power2.inOut"}}, {(start + duration - settle):.4f});')
            elif module_id in PORTED_MODULE_IDS:
                shell = ".pf-card, #%s .pf-triptych, #%s .pf-window, #%s .pf-sunrise, #%s .pf-kinetic, #%s .pf-rise-thesis" % ((element_id,) * 5)
                kids = (".pf-step, #%s .pf-path-row, #%s .pf-pin-row, #%s .pf-tri-card, #%s .pf-rise-item, "
                        "#%s .pf-bubble, #%s .pf-cmd, #%s .pf-payoff, #%s .pf-verdict, #%s .pf-final-action") % ((element_id,) * 9)
                drift = 44 if str(params.get("side")) == "right" else -44
                timeline_lines.append(f'tl.fromTo("#{element_id} {shell}", {{opacity:0,x:{drift},scale:0.97}}, {{opacity:1,x:0,scale:1,duration:0.44,ease:"power3.out"}}, {entry_start:.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} {kids}", {{opacity:0,y:18}}, {{opacity:1,y:0,duration:0.3,stagger:0.1,ease:"power2.out"}}, {(start + .24):.4f});')
                if module_id == "tradeoff-meter":
                    timeline_lines.append(f'tl.fromTo("#{element_id} .pf-meter-fill", {{scaleX:0}}, {{scaleX:1,duration:0.6,ease:"power2.inOut"}}, {(start + .3):.4f});')
                if module_id == "three-step-celebration":
                    timeline_lines.append(f'tl.fromTo("#{element_id} .pf-spark", {{opacity:0,scale:0}}, {{opacity:1,scale:1,y:-90,rotation:180,duration:0.7,stagger:0.03,ease:"power2.out"}}, {(start + duration - 1.1):.4f});')
                timeline_lines.append(f'tl.to("#{element_id} {shell}", {{opacity:0,duration:0.28,ease:"power2.in"}}, {(start + duration - 0.28):.4f});')
                timeline_lines.append(f'tl.set("#{element_id} {shell}", {{opacity:0}}, {(start + duration):.4f});')
            elif module_id in LIBRARY_MODULE_IDS:
                card = ".lib-panel, #%s .lib-badge, #%s .lib-chip, #%s .lib-path, #%s .lib-grade, #%s .lib-lower" % ((element_id,) * 5)
                rows = ".lib-row, #%s .lib-result-line, #%s .lib-stop, #%s .lib-words span, #%s .lib-flow-item" % ((element_id,) * 4)
                offset = -40 if str(params.get("side")) != "right" else 40
                timeline_lines.append(f'tl.fromTo("#{element_id} {card}", {{opacity:0,x:{offset}}}, {{opacity:1,x:0,duration:0.42,ease:"power3.out"}}, {entry_start:.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} {rows}", {{opacity:0,y:16}}, {{opacity:1,y:0,duration:0.3,stagger:0.09,ease:"power2.out"}}, {(start + .22):.4f});')
                timeline_lines.append(f'tl.to("#{element_id} {card}", {{opacity:0,x:{offset // 2},duration:0.28,ease:"power2.in"}}, {(start + duration - 0.28):.4f});')
                timeline_lines.append(f'tl.set("#{element_id} {card}", {{opacity:0}}, {(start + duration):.4f});')
            elif module_id == "ui-callout":
                timeline_lines.append(f'tl.fromTo("#{element_id} .callout-ring", {{opacity:0,scale:1.12}}, {{opacity:1,scale:1,transformOrigin:"center center",duration:0.32,ease:"power3.out"}}, {entry_start:.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} .callout-label", {{opacity:0,y:10}}, {{opacity:1,y:0,duration:0.28,ease:"power2.out"}}, {(start + .16):.4f});')
                timeline_lines.append(f'tl.to("#{element_id} .callout-ring, #{element_id} .callout-label", {{opacity:0,duration:0.24,ease:"power2.in"}}, {(start + duration - 0.24):.4f});')
                timeline_lines.append(f'tl.set("#{element_id} .callout-ring, #{element_id} .callout-label", {{opacity:0}}, {(start + duration):.4f});')
            elif module_id == "numbered-example-card":
                # The card animates in place. The source footage is never moved or scaled, so the
                # speaker stays exactly where the measured geometry says he is.
                timeline_lines.append(f'tl.fromTo("#{element_id} .example-card", {{opacity:0,x:-40}}, {{opacity:1,x:0,duration:0.42,ease:"power3.out"}}, {entry_start:.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} .example-number", {{opacity:0,y:18}}, {{opacity:1,y:0,duration:0.3,ease:"power2.out"}}, {(start + .18):.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} .example-rule", {{scaleX:0}}, {{scaleX:1,transformOrigin:"left center",duration:0.34,ease:"power2.out"}}, {(start + .26):.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} .example-pip-filled", {{scale:0}}, {{scale:1,duration:0.22,stagger:0.04,ease:"back.out(2)"}}, {(start + .5):.4f});')
                timeline_lines.append(f'tl.to("#{element_id} .example-card", {{opacity:0,x:-28,duration:0.3,ease:"power2.in"}}, {(start + duration - 0.3):.4f});')
                timeline_lines.append(f'tl.set("#{element_id} .example-card", {{opacity:0}}, {(start + duration):.4f});')
            elif module_id == "source-footage-hold":
                timeline_lines.append(f'tl.to("#main-video", {{opacity:1,scale:1,x:0,y:0,duration:0.2}}, {start:.4f});')
        else:
            asset = assets_by_id[cue["assetId"]]
            markup, audio = _asset_markup(asset, cue, element_id, staged_assets[asset["id"]], start, duration, track)
            clip_markup.append(markup)
            if audio:
                audio_markup.append(audio)
            params = cue.get("parameters") or {}
            target_opacity = _number(params.get("opacity"), 1, 0, 1)
            target_scale = _number(params.get("scale"), 1, 0.05, 10)
            transition_in = params.get("transitionIn", "fade")
            transition_out = params.get("transitionOut", "fade")
            enter_duration = min(.4, duration / 3)
            entry_start = _entry_preroll_time(start, fps)
            if transition_in == "none":
                timeline_lines.append(f'tl.set("#{element_id}", {{opacity:{target_opacity:.3f},scale:{target_scale:.3f},x:0}}, {start:.4f});')
            elif transition_in == "slide":
                timeline_lines.append(f'tl.fromTo("#{element_id}", {{opacity:0,x:-35,scale:{target_scale:.3f}}}, {{opacity:{target_opacity:.3f},x:0,duration:{enter_duration:.3f},ease:"power2.out"}}, {entry_start:.4f});')
            else:
                timeline_lines.append(f'tl.fromTo("#{element_id}", {{opacity:0,scale:{target_scale * .96:.3f}}}, {{opacity:{target_opacity:.3f},scale:{target_scale:.3f},duration:{enter_duration:.3f},ease:"power2.out"}}, {entry_start:.4f});')
            if transition_out != "none" and duration > .4:
                exit_duration = min(.3, duration / 4)
                exit_x = 35 if transition_out == "slide" else 0
                timeline_lines.append(f'tl.to("#{element_id}", {{opacity:0,x:{exit_x},duration:{exit_duration:.3f},ease:"power2.in"}}, {(start + duration - exit_duration):.4f});')

    font_faces = "".join(
        f'@font-face{{font-family:"Montserrat";src:url("fonts/Montserrat-{weight}.woff2") format("woff2");font-weight:{weight};font-display:block;}}'
        for weight in (400, 600, 700, 800, 900)
        if (public / "fonts" / f"Montserrat-{weight}.woff2").is_file()
    )
    runtime_css_path = repo / "visual-production" / "modules" / "runtime.css"
    if not runtime_css_path.is_file():
        raise RuntimeError("The registered module runtime stylesheet is missing.")
    runtime_css = (
        runtime_css_path.read_text(encoding="utf-8")
        .replace("__WIDTH__", str(width))
        .replace("__HEIGHT__", str(height))
    )
    index_html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><style>
{font_faces}
:root{{--white:#fff;--paper:#fbfbfd;--ink:#1a1a2e;--body:#4a4a5a;--line:#dedee6;--magenta:#ff00ce;--magenta-deep:#c700a1;--magenta-tint:#fff0fb;--teal:#007c7d;--teal-tint:#e6f5f5;}}
.cue-motion{{position:absolute;inset:0;width:100%;height:100%;}}
{runtime_css}
.module-progress-scale .stat-title{{font-size:94px;line-height:.88;}}
.lib-grade-foot{{min-height:52px;padding-bottom:12px;align-items:flex-start;}}
.joke-card-approved{{position:absolute;left:3.96%;top:12.41%;width:39.58%;height:48.15%;background:var(--paper);border:4px solid var(--ink);box-shadow:18px 20px 0 rgba(255,0,206,.22);overflow:hidden}}.joke-image-approved{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.joke-copy-approved{{position:absolute;left:24px;right:24px;bottom:24px;padding:18px 22px;background:rgba(251,251,253,.95);border:3px solid var(--ink)}}.joke-copy-approved .kicker{{font-size:17px;color:var(--teal)}}.joke-line-approved{{margin-top:10px;color:var(--magenta);font-size:42px;font-weight:900;line-height:.92;letter-spacing:-.045em}}.pf-step-no-num{{padding-top:38px}}.pf-step-no-num .pf-step-title{{margin-top:0}}.pf-community{{top:7.2%;width:33.85%;min-height:48.15%;padding:46px;text-align:left;border-width:4px;box-shadow:18px 20px 0 rgba(0,124,125,.3)}}.pf-community::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:22px;background:var(--teal)}}.pf-logo-image{{display:block;width:min(330px,82%);height:110px;object-fit:contain;object-position:left center}}.pf-community .pf-action{{margin-top:44px;font-size:43px}}.pf-community .pf-dest{{font-size:18px}}.lib-track span.lib-long{{font-size:54px;letter-spacing:-.055em;padding:0 8px}}
.callout-align-right.callout-below{{transform:translate(-100%,14px)}}.callout-align-right.callout-above{{transform:translate(-100%,calc(-100% - 14px))}}
</style></head><body><div id="root" data-composition-id="vcg-visual-plan" data-start="0" data-width="{width}" data-height="{height}" data-duration="{render_duration:.4f}" data-fps="{fps}"><div class="base"></div><video id="main-video" class="clip" src="source.mp4" muted playsinline data-start="0" data-duration="{render_duration:.4f}" data-track-index="0"></video><audio id="main-audio" src="source.mp4" data-start="0" data-duration="{render_duration:.4f}" data-track-index="10" data-volume="1"></audio>{''.join(clip_markup)}{''.join(audio_markup)}<script src="vendor/gsap.min.js"></script><script>(function(){{window.__timelines=window.__timelines||{{}};var tl=gsap.timeline({{paused:true}});{''.join(timeline_lines)}window.__timelines["vcg-visual-plan"]=tl;}})();</script></div></body></html>'''
    (public / "index.html").write_text(index_html, encoding="utf-8")
    return public, render_duration


def render_visual_plan(
    plan_path: Path,
    output_path: Path,
    *,
    start_sec: float | None = None,
    end_sec: float | None = None,
    quality: str = "standard",
    purpose: str = "range",
    progress: ProgressCallback | None = None,
) -> Path:
    progress = progress or (lambda _value, _message: None)
    if quality not in {"draft", "standard", "high"}:
        raise ValueError("Unknown render quality.")
    if purpose not in {"range", "review", "final"}:
        raise ValueError("Unknown visual render purpose.")
    plan = load_visual_plan(plan_path)
    gate_report = visual_production_gate_report(plan_path, plan)
    render_plan_hash = gate_report["planHash"]
    if purpose == "review" and not gate_report["canRenderReview"]:
        raise ValueError("Review render blocked: " + " ".join(gate_report["messages"]))
    if purpose == "final" and not gate_report["canDeliver"]:
        raise ValueError("Final delivery blocked: " + " ".join(gate_report["messages"]))

    runtime_root, _runtime_entry, _composition = active_visual_runtime(plan_path, plan)
    if purpose == "range" and runtime_root is not None:
        raise ValueError("Custom HyperFrames projects use the live runtime preview for representative review; range rendering would create a second composition path.")
    if purpose == "final":
        runtime_root, _runtime_entry, _composition = active_visual_runtime(plan_path, plan)
    if runtime_root is None:
        runtime_root, _duration = build_hyperframes_composition(
            plan_path,
            start_sec=start_sec,
            end_sec=end_sec,
            progress=progress,
        )

    if purpose in {"review", "final"}:
        progress(36, "Running HyperFrames lint, runtime, and strict layout gates...")
        commands = run_hyperframes_production_checks(
            runtime_root,
            inspection_times=semantic_layout_inspection_times(plan),
        )
        record_layout_inspection(plan_path, commands=commands)
    progress(44, "Rendering the registered HyperFrames composition...")
    repo = project_root()
    cli = repo / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
    if not cli.is_file():
        raise RuntimeError("HyperFrames is not installed. Run npm install before rendering visual projects.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_only_path = output_path.with_name(f".{output_path.stem}-{uuid.uuid4().hex[:8]}-video-only{output_path.suffix}")
    verified_stage_path = output_path.with_name(f".{output_path.stem}-{uuid.uuid4().hex[:8]}-verified{output_path.suffix}")
    command = [str(cli), "render", str(runtime_root), "--output", str(video_only_path), "--quality", quality, "--strict", "--skill", "talking-head-recut"]
    render_environment = os.environ.copy()
    media_tool_directories = {
        str(find_ffmpeg().parent),
        str(find_ffprobe().parent) if find_ffprobe() is not None else "",
    }
    render_environment["PATH"] = os.pathsep.join(
        [directory for directory in media_tool_directories if directory]
        + [render_environment.get("PATH", "")]
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=hidden_subprocess_flags(),
            env=render_environment,
        )
        captured: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            captured.append(line)
            render_percent = _hyperframes_progress_percent(line)
            if render_percent is not None:
                value = 44 + round(render_percent * 0.5)
                progress(min(94, value), "Rendering visual-production frames...")
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"HyperFrames render failed. {''.join(captured)[-1800:]}")
        if not video_only_path.is_file() or video_only_path.stat().st_size == 0:
            raise RuntimeError("HyperFrames reported success but produced no output video.")

        progress(95, "Attaching and verifying the locked-cut audio...")
        locked_source = resolve_project_path(find_visual_root(plan_path), plan["source"]["video"])
        range_duration = None
        range_start = None
        if purpose == "range":
            full_duration = float(plan["composition"]["durationSec"])
            range_start = max(0.0, float(start_sec or 0.0))
            range_end = min(full_duration, float(end_sec if end_sec is not None else full_duration))
            range_duration = range_end - range_start
        remux_locked_audio(
            video_only_path,
            locked_source,
            verified_stage_path,
            start_sec=range_start,
            duration_sec=range_duration,
        )
        progress(98, "Verifying video, duration, frame rate, and locked-cut audio...")
        delivery_metadata = verify_delivered_media(
            verified_stage_path,
            locked_source,
            {**plan["composition"], **({"durationSec": range_duration} if range_duration is not None else {})},
            full_length=purpose in {"review", "final"},
        )
        current_plan = load_visual_plan(plan_path)
        current_gate_report = visual_production_gate_report(plan_path, current_plan)
        if current_gate_report["planHash"] != render_plan_hash:
            raise RuntimeError(
                "The visual plan changed while the export was running. "
                "The verified render was not published; export the current plan again."
            )
        if purpose == "final" and not current_gate_report["canDeliver"]:
            raise RuntimeError(
                "Final export became blocked while rendering. "
                + " ".join(current_gate_report["messages"])
            )
        published_path = publish_verified_render(verified_stage_path, output_path)
    finally:
        video_only_path.unlink(missing_ok=True)
        verified_stage_path.unlink(missing_ok=True)
    if purpose == "review":
        record_review_revision(plan_path, runtime_root, published_path)
    elif purpose == "final":
        record_final_revision(plan_path, published_path)
        progress(99, "Saving treatment screenshots and library usage...")
        try:
            from app.core.story_assets import record_treatment_usage

            library_curation = {"status": "complete", **record_treatment_usage(plan_path, published_path)}
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            library_curation = {
                "status": "failed",
                "treatmentsRecorded": 0,
                "candidates": 0,
                "introducedTreatmentIds": [],
                "error": str(exc),
            }
        write_delivery_manifest(
            plan_path,
            published_path,
            locked_source,
            delivery_metadata,
            library_curation=library_curation,
        )
    progress(100, "Final video verified and ready.")
    return published_path


def semantic_layout_inspection_times(plan: dict) -> list[float]:
    """Return voice-anchored moments when every visible semantic item is fully readable."""
    times = {
        round(float(item["fullyVisibleSec"]), 4)
        for cue in plan.get("cues", [])
        if cue.get("enabled", True)
        for item in cue.get("semanticItems", [])
        if item.get("fullyVisibleSec") is not None
    }
    return sorted(times)


def run_hyperframes_production_checks(
    runtime_root: Path,
    *,
    inspection_times: list[float] | None = None,
) -> list[str]:
    repo = project_root()
    cli = repo / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
    if not cli.is_file():
        raise RuntimeError("HyperFrames is not installed. Run npm install before rendering visual projects.")
    inspect_arguments = ["inspect", str(runtime_root), "--json", "--strict"]
    anchored_times = sorted({round(float(value), 4) for value in inspection_times or [] if float(value) >= 0})
    if anchored_times:
        inspect_arguments.extend(["--at", ",".join(f"{value:g}" for value in anchored_times)])
    checks = [
        ("lint", ["lint", str(runtime_root), "--json"]),
        ("validate", ["validate", str(runtime_root), "--json"]),
        ("inspect", inspect_arguments),
    ]
    completed: list[str] = []
    for name, arguments in checks:
        result = subprocess.run(
            [str(cli), *arguments],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=hidden_subprocess_flags(),
        )
        if result.returncode != 0:
            details = (result.stdout or result.stderr or "").strip()
            raise RuntimeError(f"HyperFrames {name} production gate failed. {details[-2000:]}")
        completed.append(name)
    return completed
