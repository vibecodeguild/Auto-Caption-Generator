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
from pathlib import Path
from typing import Callable

from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe
from app.core.process_utils import hidden_subprocess_flags
from app.core.settings import project_root


VISUAL_PLAN_VERSION = 2
BRAND_ID = "vcg-white-editorial"
MODULE_IDS = {
    "punchline-reveal",
    "source-footage-hold",
    "speaker-side-panel",
    "progress-scale",
    "dependency-stack",
    "dual-comparison",
}
CUE_KINDS = {"module", "asset", "composition"}
ANCHOR_TYPES = {"spoken", "scene-relative", "unanchored"}
COMMON_MODULE_PARAMETERS = {
    "reviewLabel", "editorialPurpose", "recipeId", "opacity", "transitionIn", "transitionOut",
    "speakerSafety", "visualFamily", "candidateTreatmentIds", "selectionRationale",
    "planningSuggestionId", "approvedTreatmentId", "meaningfulChanges", "approvalEvidence",
}
MODULE_PARAMETER_KEYS = {
    "punchline-reveal": COMMON_MODULE_PARAMETERS | {"text", "kicker", "accentColor"},
    "source-footage-hold": COMMON_MODULE_PARAMETERS,
    "speaker-side-panel": COMMON_MODULE_PARAMETERS | {"text", "kicker", "accentColor", "side", "panelWidth", "videoBounds", "frameStyle", "items"},
    "progress-scale": COMMON_MODULE_PARAMETERS | {"text", "kicker", "startLabel", "targetLabel", "accentColor", "milestones"},
    "dependency-stack": COMMON_MODULE_PARAMETERS | {"text", "kicker", "nodes", "accentColor"},
    "dual-comparison": COMMON_MODULE_PARAMETERS | {"kicker", "leftTitle", "rightTitle", "leftItems", "rightItems", "leftColor", "rightColor"},
}
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


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "visual-project"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


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
        "source": {"video": source_ref, "transcript": transcript_ref},
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
    list_fields = ["nodes"] if module_id == "dependency-stack" else ["leftItems", "rightItems"] if module_id == "dual-comparison" else ["items"] if module_id == "speaker-side-panel" else []
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
    validate_visual_plan(plan, root)
    return plan


def save_visual_plan(plan_path: Path, plan: dict) -> dict:
    root = find_visual_root(plan_path)
    plan = normalize_visual_plan(plan)
    plan.setdefault("project", {})["updatedAt"] = datetime.now(timezone.utc).isoformat()
    validate_visual_plan(plan, root)
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
    resolve_project_path(root, (plan.get("source") or {}).get("video", ""))

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
    }


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        return []
    try:
        data = json.loads(suggestions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["The visual suggestions audit cannot be read."]
    reuse_audit = (data.get("coverage") or {}).get("reuseAudit") or {}
    contract_version = reuse_audit.get("contractVersion")
    if contract_version not in {2, 3}:
        return []

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
        realized_id = cue.get("moduleId") if suggestion.get("moduleId") else parameters.get("recipeId")
        if selected_id != realized_id:
            issues.append(f"{suggestion_id} cue does not use its approved treatment {selected_id}.")
        if contract_version == 3:
            for key in ("meaningfulChanges", "approvalEvidence"):
                if parameters.get(key) != suggestion.get(key):
                    issues.append(f"{suggestion_id} cue does not preserve its approved {key} contract.")
            if parameters.get("planningSuggestionId") != suggestion_id:
                issues.append(f"{suggestion_id} cue is not linked back to its approved scene packet.")
            approved_id = (suggestion.get("decision") or {}).get("selectedTreatmentId")
            if parameters.get("approvedTreatmentId") != approved_id:
                issues.append(f"{suggestion_id} cue does not preserve its approved treatment-map decision.")
        issues.extend(_speaker_safety_metadata_issues(suggestion_id, suggestion.get("speakerSafety"), float(suggestion.get("endSec") or 0) - float(suggestion.get("startSec") or 0)))
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
                    if overlay is not None and _normalized_bounds_intersect(protected, overlay):
                        issues.append(
                            f"{suggestion_id} places rendered graphics over protected content: "
                            f"{region.get('label') or 'important screen region'}."
                        )
    return issues


def visual_planning_gate_issues(plan_path: Path, plan: dict) -> list[str]:
    """Block production until every contract-v3 planning decision is approved and traceable."""
    suggestions_path = find_visual_root(plan_path) / "visual-production" / "visual-suggestions.json"
    if not suggestions_path.is_file():
        return []
    try:
        data = json.loads(suggestions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["The visual suggestions approval contract cannot be read."]
    reuse = (data.get("coverage") or {}).get("reuseAudit") or {}
    if reuse.get("contractVersion") != 3:
        return []
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


def _speaker_safety_metadata_issues(suggestion_id: str, safety: object, duration: float) -> list[str]:
    if not isinstance(safety, dict) or safety.get("checked") is not True:
        return [f"{suggestion_id} is missing its completed speaker-safety audit."]
    try:
        absence = float(safety.get("maxSpeakerAbsenceSec"))
    except (TypeError, ValueError):
        return [f"{suggestion_id} has an invalid speaker-absence duration."]
    if absence < 0 or absence > 2:
        return [f"{suggestion_id} hides the speaker for more than two seconds."]
    if safety.get("mode") == "brief-full-frame-hit":
        return [] if duration <= 2.01 else [f"{suggestion_id} uses a full-frame hit longer than two seconds."]
    speaker = _safe_normalized_bounds(safety.get("speakerBounds"))
    overlays = safety.get("overlayOcclusionBounds")
    if speaker is None or not isinstance(overlays, list):
        return [f"{suggestion_id} is missing normalized speaker or overlay bounds."]
    issues = []
    for value in overlays:
        overlay = _safe_normalized_bounds(value)
        if overlay is None:
            issues.append(f"{suggestion_id} has invalid overlay occlusion bounds.")
        elif _normalized_bounds_intersect(speaker, overlay):
            issues.append(f"{suggestion_id} places rendered graphics over the protected speaker bounds.")
    return issues


def _safe_normalized_bounds(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        bounds = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    if bounds["x"] < 0 or bounds["y"] < 0 or bounds["width"] <= 0 or bounds["height"] <= 0 or bounds["x"] + bounds["width"] > 1 or bounds["y"] + bounds["height"] > 1:
        return None
    return bounds


def _normalized_bounds_intersect(left: dict[str, float], right: dict[str, float]) -> bool:
    return not (
        left["x"] + left["width"] <= right["x"]
        or right["x"] + right["width"] <= left["x"]
        or left["y"] + left["height"] <= right["y"]
        or right["y"] + right["height"] <= left["y"]
    )


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
    reopen = gates.get("deliveryReopen") if isinstance(gates.get("deliveryReopen"), dict) else None
    reopen_verified = bool(
        reopen and revision and revision.get("status") == "delivered"
        and reopen.get("planHash") == plan_hash
        and reopen.get("revisionNumber") == revision.get("number")
    )
    timing_anchored = not unanchored
    active_review_count = sum(1 for item in plan.get("reviews", []) if str(item.get("note") or "").strip())
    can_render_review = representative_approved and timing_anchored and not overflow_files and not visual_safety_issues and not planning_approval_issues
    can_deliver = timing_anchored and not overflow_files and not visual_safety_issues and not planning_approval_issues and active_review_count == 0
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


def _module_markup(cue: dict, element_id: str, start: float, duration: float, track: int) -> str:
    params = cue.get("parameters") or {}
    module_id = cue["moduleId"]
    text = html.escape(str(params.get("text") or "EDIT THIS TEXT"))
    kicker = html.escape(str(params.get("kicker") or "VCG / VISUAL"))
    accent_color = html.escape(str(params.get("accentColor") or "#FF00CE"))
    common = (
        f'id="{element_id}" class="clip module module-{module_id}" '
        f'data-start="{start:.4f}" data-duration="{duration:.4f}" data-track-index="{track}"'
    )
    if module_id == "source-footage-hold":
        return ""
    if module_id == "punchline-reveal":
        return f'<section {common} style="--cue-accent:{accent_color}"><div class="module-fill"><div class="grid"></div><div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div><div class="punchline" data-semantic-path="parameters.text">{text}</div><div class="rule"></div></div></section>'
    if module_id == "speaker-side-panel":
        return f'<section {common} style="--cue-accent:{accent_color}"><div class="side-copy"><div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div><div class="side-title" data-semantic-path="parameters.text">{text}</div></div><div class="video-outline"></div></section>'
    if module_id == "progress-scale":
        start_label = html.escape(str(params.get("startLabel") or "START"))
        target_label = html.escape(str(params.get("targetLabel") or "TARGET"))
        return f'<section {common}><div class="module-fill"><div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div><div class="stat-title" data-semantic-path="parameters.text">{text}</div><div class="scale"><div class="scale-fill"></div><div class="scale-marker"></div><div class="scale-labels"><span data-semantic-path="parameters.startLabel">{start_label}</span><span data-semantic-path="parameters.targetLabel">{target_label}</span></div></div><div class="stat-video-outline"></div></div></section>'
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
            f'<div class="comparison-canvas"><div class="comparison-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
            f'<div class="comparison-column comparison-left"><h2 data-semantic-path="parameters.leftTitle">{left_title}</h2><ul>{left_markup}</ul></div>'
            f'<div class="comparison-speaker-outline"></div>'
            f'<div class="comparison-column comparison-right"><h2 data-semantic-path="parameters.rightTitle">{right_title}</h2><ul>{right_markup}</ul></div>'
            f'</div></section>'
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
            markup = _module_markup(cue, element_id, start, duration, track)
            if markup:
                clip_markup.append(markup)
            module_id = cue["moduleId"]
            params = cue.get("parameters") or {}
            transition_in = params.get("transitionIn", "editorial-snap")
            transition_out = params.get("transitionOut", "fade")
            enter = min(0.45, duration / 3)
            exit_duration = min(0.35, duration / 4)
            if markup:
                if transition_in == "none":
                    timeline_lines.append(f'tl.set("#{element_id}", {{opacity:1,x:0}}, {start:.4f});')
                elif transition_in == "fade":
                    timeline_lines.append(f'tl.fromTo("#{element_id}", {{opacity:0}}, {{opacity:1,duration:{enter:.3f},ease:"power2.out"}}, {start:.4f});')
                else:
                    distance = -70 if transition_in == "editorial-snap" else -35
                    timeline_lines.append(f'tl.fromTo("#{element_id}", {{opacity:0,x:{distance}}}, {{opacity:1,x:0,duration:{enter:.3f},ease:"power3.out"}}, {start:.4f});')
                if transition_out != "none" and duration > exit_duration + enter:
                    exit_x = 35 if transition_out == "slide" else 0
                    timeline_lines.append(f'tl.to("#{element_id}", {{opacity:0,x:{exit_x},duration:{exit_duration:.3f},ease:"power2.in"}}, {(start + duration - exit_duration):.4f});')
                timeline_lines.extend(_semantic_timeline_lines(cue, element_id, range_start, range_end, start))
            if module_id == "punchline-reveal":
                timeline_lines.append(f'tl.to("#main-video", {{opacity:0,duration:0.12}}, {start:.4f});')
                timeline_lines.append(f'tl.to("#main-video", {{opacity:1,duration:0.18}}, {(start + duration - 0.18):.4f});')
            elif module_id == "speaker-side-panel":
                timeline_lines.append(f'tl.to("#main-video", {{scale:0.48,x:{width * .48:.2f},y:{height * .26:.2f},duration:0.5,ease:"power3.inOut"}}, {start:.4f});')
                timeline_lines.append(f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:0.45,ease:"power3.inOut"}}, {(start + duration - 0.45):.4f});')
            elif module_id == "progress-scale":
                timeline_lines.append(f'tl.to("#main-video", {{scale:0.365,x:{width * .5625:.2f},y:{height * .1574:.2f},duration:0.5,ease:"power3.inOut"}}, {start:.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} .scale-fill", {{scaleX:0}}, {{scaleX:1,duration:{max(.2, duration - .8):.3f},ease:"power2.inOut"}}, {(start + .4):.4f});')
                timeline_lines.append(f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:0.45,ease:"power3.inOut"}}, {(start + duration - 0.45):.4f});')
            elif module_id == "dual-comparison":
                square_size = min(width * .25, height * .445)
                speaker_scale = .68
                pre_transform_square = square_size / speaker_scale
                inset_x = (width - pre_transform_square) / 2
                inset_y = (height - pre_transform_square) / 2
                timeline_lines.append(f'tl.to("#main-video", {{clipPath:"inset({inset_y:.2f}px {inset_x:.2f}px {inset_y:.2f}px {inset_x:.2f}px)",scale:{speaker_scale},transformOrigin:"center center",zIndex:4,duration:0.5,ease:"power3.inOut"}}, {start:.4f});')
                timeline_lines.append(f'tl.fromTo("#{element_id} .comparison-column", {{opacity:0,y:24}}, {{opacity:1,y:0,duration:0.38,stagger:0.08,ease:"power2.out"}}, {(start + .28):.4f});')
                timeline_lines.append(f'tl.to("#main-video", {{clipPath:"inset(0px 0px 0px 0px)",scale:1,transformOrigin:"center center",zIndex:1,duration:0.45,ease:"power3.inOut"}}, {(start + duration - 0.45):.4f});')
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
            if transition_in == "none":
                timeline_lines.append(f'tl.set("#{element_id}", {{opacity:{target_opacity:.3f},scale:{target_scale:.3f},x:0}}, {start:.4f});')
            elif transition_in == "slide":
                timeline_lines.append(f'tl.fromTo("#{element_id}", {{opacity:0,x:-35,scale:{target_scale:.3f}}}, {{opacity:{target_opacity:.3f},x:0,duration:{enter_duration:.3f},ease:"power2.out"}}, {start:.4f});')
            else:
                timeline_lines.append(f'tl.fromTo("#{element_id}", {{opacity:0,scale:{target_scale * .96:.3f}}}, {{opacity:{target_opacity:.3f},scale:{target_scale:.3f},duration:{enter_duration:.3f},ease:"power2.out"}}, {start:.4f});')
            if transition_out != "none" and duration > .4:
                exit_duration = min(.3, duration / 4)
                exit_x = 35 if transition_out == "slide" else 0
                timeline_lines.append(f'tl.to("#{element_id}", {{opacity:0,x:{exit_x},duration:{exit_duration:.3f},ease:"power2.in"}}, {(start + duration - exit_duration):.4f});')

    font_faces = "".join(
        f'@font-face{{font-family:"Montserrat";src:url("fonts/Montserrat-{weight}.woff2") format("woff2");font-weight:{weight};font-display:block;}}'
        for weight in (400, 600, 700, 800, 900)
        if (public / "fonts" / f"Montserrat-{weight}.woff2").is_file()
    )
    index_html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><style>
{font_faces}
:root{{--white:#fff;--paper:#fbfbfd;--ink:#1a1a2e;--body:#4a4a5a;--line:#dedee6;--magenta:#ff00ce;--magenta-deep:#c700a1;--magenta-tint:#fff0fb;--teal:#007c7d;--teal-tint:#e6f5f5;}}
*{{box-sizing:border-box}}html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden;background:#fff;font-family:"Montserrat",sans-serif}}#root{{position:relative;width:{width}px;height:{height}px;overflow:hidden}}[data-semantic-path]{{opacity:0}}.base{{position:absolute;inset:0;background:var(--white);z-index:0}}#main-video{{position:absolute;left:0;top:0;width:{width}px;height:{height}px;object-fit:cover;transform-origin:0 0;z-index:1}}#main-audio{{position:absolute;width:1px;height:1px;opacity:0}}.clip{{position:absolute;z-index:3;overflow:hidden}}.imported{{z-index:5}}.module{{inset:0}}.module-fill{{position:absolute;inset:0;background:var(--white);padding:7%}}.grid{{position:absolute;inset:0;opacity:.28;background-image:linear-gradient(rgba(26,26,46,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(26,26,46,.06) 1px,transparent 1px);background-size:96px 96px}}.kicker{{position:relative;color:var(--cue-accent,var(--teal));font-size:24px;font-weight:800;letter-spacing:.2em;text-transform:uppercase}}.punchline{{position:relative;margin-top:13%;max-width:78%;color:var(--cue-accent,var(--magenta));font-size:148px;font-weight:900;line-height:.88;letter-spacing:-.06em}}.rule{{position:relative;margin-top:36px;width:38%;height:10px;background:var(--ink)}}.module-speaker-side-panel{{background:transparent}}.side-copy{{position:absolute;left:0;top:0;width:43%;height:100%;background:var(--white);padding:10% 4%;border-top:12px solid var(--cue-accent,var(--teal))}}.side-title{{margin-top:28px;color:var(--ink);font-size:76px;font-weight:900;line-height:.95;letter-spacing:-.05em}}.video-outline{{position:absolute;left:48%;top:26%;width:48%;height:48%;border:4px solid var(--ink);box-shadow:20px 20px 0 color-mix(in srgb,var(--cue-accent,var(--magenta)) 18%,white)}}.stat-title{{position:relative;margin-top:8%;max-width:48%;color:var(--ink);font-size:118px;font-weight:900;line-height:.9;letter-spacing:-.06em}}.scale{{position:absolute;left:7%;right:7%;bottom:11%;height:70px}}.scale::before{{content:"";position:absolute;left:0;right:0;top:0;height:16px;background:var(--line)}}.scale-fill{{position:absolute;left:0;right:0;top:0;height:16px;background:linear-gradient(90deg,var(--teal),var(--magenta));transform-origin:left center}}.scale-marker{{position:absolute;right:0;top:-15px;width:7px;height:48px;background:var(--ink)}}.scale-labels{{display:flex;justify-content:space-between;padding-top:28px;color:var(--body);font-size:18px;font-weight:700}}.stat-video-outline{{position:absolute;left:56.25%;top:15.74%;width:36.5%;height:36.5%;border:4px solid var(--ink);box-shadow:18px 18px 0 var(--magenta-tint)}}.dependency-panel{{position:absolute;left:0;top:0;width:38%;height:100%;background:rgba(255,255,255,.98);border-right:3px solid var(--ink);padding:6% 3%}}.dependency-title{{margin-top:24px;color:var(--ink);font-size:58px;font-weight:900;line-height:.95;letter-spacing:-.05em}}.nodes{{display:grid;gap:22px;margin-top:48px}}.node{{border:3px solid var(--ink);background:#fff;padding:22px 26px;color:var(--ink);font-size:25px;font-weight:800}}.comparison-canvas{{position:absolute;inset:0;background:var(--white);display:grid;grid-template-columns:1fr 520px 1fr;gap:30px;padding:92px 70px 60px}}.comparison-kicker{{position:absolute;top:38px;left:0;right:0;text-align:center;color:var(--body);font-size:22px;font-weight:800;letter-spacing:.18em;text-transform:uppercase}}.comparison-column{{padding:48px 28px 26px;border-top:12px solid var(--left-accent);background:linear-gradient(180deg,color-mix(in srgb,var(--left-accent) 12%,white),white 40%)}}.comparison-right{{border-color:var(--right-accent);background:linear-gradient(180deg,color-mix(in srgb,var(--right-accent) 12%,white),white 40%)}}.comparison-column h2{{margin:0 0 34px;color:var(--left-accent);font-size:70px;font-weight:900;line-height:.9;letter-spacing:-.05em}}.comparison-right h2{{color:var(--right-accent)}}.comparison-column ul{{list-style:none;margin:0;padding:0;display:grid;gap:20px}}.comparison-column li{{border-left:7px solid var(--left-accent);padding:13px 14px;color:var(--ink);font-size:28px;font-weight:750;line-height:1.08}}.comparison-right li{{border-color:var(--right-accent)}}.comparison-speaker-outline{{width:480px;height:480px;align-self:center;justify-self:center;border:5px solid var(--ink);box-shadow:0 20px 48px rgba(26,26,46,.2);z-index:4;pointer-events:none}}
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

            recorded_treatments = record_treatment_usage(plan_path, published_path)
            library_curation = {"status": "complete", "treatmentsRecorded": recorded_treatments}
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            library_curation = {"status": "failed", "treatmentsRecorded": 0, "error": str(exc)}
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
