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
from typing import Any, Callable

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

# --- Engine registry: single source of truth for every engine's interface -----
#
# One entry per engine, declared next to the draw code that honors it. Each
# entry owns BOTH:
#   • "placement" — the placement interface: how Stage 3 instantiates this
#     design. fixed_line_slots are ordered human-copy slots (text + revealFrame
#     each); list_slot is an optional repeating slot with list_min/list_max
#     bounds; meta/asset/motion keys are the per-episode knobs the engine
#     exposes. Everything the Placement studio shows is derived from here.
#   • "legacy_parameter_keys" — draw-accepted keys placement must NEVER expose.
#     Today that is only "kicker" chrome awaiting the deferred D5 CSS cleanup.
#
# MODULE_IDS and MODULE_PARAMETER_KEYS are DERIVED from this registry below —
# do not hand-edit parallel lists. app/core/placement_roles.py is a thin
# adapter over this registry: it owns placement policy (e.g. never emit
# kicker) but declares no engine facts of its own.
#
# Design authority: docs/vcg-graphics-process/architecture.md §3.
ENGINE_REGISTRY: dict[str, dict[str, Any]] = {
    # One engine = one look: joke card only (required imageAssetId + text;
    # head docks left, art right). There is no text-only mode — kinetic
    # phrase work uses kinetic-word-punctuation.
    "punchline-reveal": {
        "placement": {
            "fixed_line_slots": ["text"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            # Graphic end is placement endFrameExclusive (default = beat end), not a
            # meta duration. Trim the span earlier to undock before the beat ends.
            "meta_keys": [],
            "asset_keys": ["imageAssetId"],  # required — joke card is the only mode
            "motion_keys": ["accentColor"],
            "notes": (
                "Joke card only (image + caption, head docks left). "
                "Stage/dock starts at the beat; Title reveal is when the whole card "
                "(borders + image + caption) lands. Graphic ends at placement "
                "endFrameExclusive (default beat end) — trim earlier to return to "
                "full talking-head before the beat ends. Not a text-only kinetic."
            ),
        },
        # kicker / holdSec: accepted-and-ignored so old plans still validate.
        "legacy_parameter_keys": {"kicker", "holdSec"},
    },
    # retired 2026-08: speaker-side-panel — duplicative of dependency-stack
    # (see RETIRED_ENGINE_ALIASES). Do not re-add without product approval.
    "progress-scale": {
        "placement": {
            "fixed_line_slots": ["text", "startLabel", "targetLabel"],
            "list_slot": "milestones",
            "list_min": 0,
            "list_max": 8,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": ["accentColor"],
            "notes": (
                "No kicker. Title + Start/Target labels + milestone stops. "
                "Bar fill reaches each stop at that stop's reveal frame."
            ),
        },
        "legacy_parameter_keys": {"kicker"},
    },
    # No kicker. Title (`text`) + up to 6 stack nodes; video floats into right frame.
    "dependency-stack": {
        "placement": {
            "fixed_line_slots": ["text"],
            "list_slot": "nodes",
            "list_min": 0,
            "list_max": 6,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": [],
            "notes": (
                "Title + stack nodes. Each node lands at its line revealFrame "
                "(placement anchors are not redistributed)."
            ),
        },
    },
    "numbered-example-card": {
        "placement": {
            "fixed_line_slots": [],
            "list_slot": "titleLines",
            "list_min": 1,
            "list_max": 8,
            "meta_keys": ["exampleNumber", "totalExamples", "accentLineIndex"],
            "asset_keys": [],
            "motion_keys": ["accentColor", "tags"],
            "notes": "No kicker. Body is title lines only.",
        },
        "legacy_parameter_keys": {"kicker"},
    },
    # Screen-share motion / callouts (without these, long demos go bare).
    "source-punch-zoom": {
        "placement": {
            "fixed_line_slots": [],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            # zoomInFrame / zoomOutFrame: absolute locked-cut frames when the camera
            # move *starts* (default = beat start / near beat end). settleSec = move length.
            "motion_keys": [
                "focusX",
                "focusY",
                "zoom",
                "settleSec",
                "motion",
                "zoomInFrame",
                "zoomOutFrame",
            ],
            "notes": (
                "Motion-only camera punch. Zoom in / zoom out frames are absolute on "
                "the locked cut; default motion is in-out."
            ),
        },
    },
    "ui-callout": {
        "placement": {
            "fixed_line_slots": ["label"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            # Craft knobs (normalized 0–1): upper-left + size. Assembled to targetBounds.
            "meta_keys": ["x", "y", "width", "height"],
            "asset_keys": [],
            "motion_keys": ["pointer", "accentColor"],
            "notes": (
                "Ring a screen region (label only). Meta x/y = upper-left (0–1); "
                "width/height size the rectangle. Assembled to targetBounds for draw. "
                "Use placement Grid toggle to aim tenths on the live preview."
            ),
        },
        # Nested bounds + retired detail still accepted from samples / older plans.
        "legacy_parameter_keys": {"targetBounds", "detail"},
    },
    # Ported July-22 families: edge-anchored overlays that leave UI readable.
    "kinetic-word-punctuation": {
        "placement": {
            "fixed_line_slots": ["phrase"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": ["side", "anchor", "accentColor"],
            "notes": (
                "Single kinetic phrase. Magenta stamp (box + words) lands together "
                "at phrase revealFrame — not an empty pink shell at beat start."
            ),
        },
    },
    "numbered-step-intro": {
        "placement": {
            "fixed_line_slots": ["title", "action"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": ["stepNumber", "showNumber"],
            "asset_keys": [],
            "motion_keys": ["side"],
            "notes": "",
        },
    },
    "problem-card-triptych": {
        "placement": {
            "fixed_line_slots": ["cards.0", "cards.1", "cards.2"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": [],
            "notes": (
                "Exactly three cards. Each lands at its line revealFrame "
                "(placement anchors are not redistributed)."
            ),
        },
    },
    "speaker-rise-callouts": {
        "placement": {
            "fixed_line_slots": ["thesis"],
            "list_slot": "callouts",
            "list_min": 0,
            "list_max": 8,
            "meta_keys": ["accentCalloutIndex"],
            "asset_keys": [],
            "motion_keys": [],
            "notes": (
                "Thesis + up to 8 callouts around the speaker. "
                "Each lands at its line revealFrame (not auto-staggered over placement)."
            ),
        },
    },
    "tradeoff-meter": {
        "placement": {
            "fixed_line_slots": ["leftLabel", "rightLabel", "verdict"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": ["value"],
            "asset_keys": [],
            "motion_keys": ["side"],
            "notes": (
                "No kicker. Meter value is meta 0–1. Knob sits fixed at value; fill "
                "grows to it when the verdict line reveals (placement revealFrame)."
            ),
        },
        "legacy_parameter_keys": {"kicker"},
    },
    "brand-cta-lockup": {
        "placement": {
            # No craft lines — join text + link are brand-fixed forever (see
            # DEFAULT_BRAND_CTA_*). Placement only times the beat span / Ends.
            "fixed_line_slots": [],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": [],
            "notes": (
                "Brand-fixed CTA: join line + skool link are not placement fields. "
                "Logo is brand-fixed. Time the beat with Ends only."
            ),
        },
        # Still accepted on old plans / library samples; draw ignores overrides.
        "legacy_parameter_keys": {
            "logoText",
            "logoAssetId",
            "side",
            "action",
            "destination",
        },
    },
    "windows-prompt-typing": {
        "placement": {
            "fixed_line_slots": ["prompt"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": ["appName"],
            "asset_keys": [],
            "motion_keys": ["side"],
            "notes": "Prompt is one timed line (typing channel).",
        },
    },
    # VCG mascot overlays (cheer / defiant / roast).
    "robot-cheer": {
        "placement": {
            "fixed_line_slots": ["text", "tagline"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": [],
            "notes": "Bubble + optional energy tagline (not a kicker eyebrow).",
        },
    },
    "robot-defiant": {
        "placement": {
            "fixed_line_slots": ["text"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": [],
            "notes": "",
        },
    },
    "robot-roast": {
        "placement": {
            "fixed_line_slots": ["text"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": [],
            "notes": "",
        },
    },
    # Soft CTA: rocket fly-by with placard (description / prior video pointer).
    "robot-rocket-sign": {
        "placement": {
            "fixed_line_slots": ["text"],
            "list_slot": None,
            "list_min": 0,
            "list_max": 0,
            "meta_keys": [],
            "asset_keys": [],
            "motion_keys": [],
            "notes": "Placard line on rocket CTA.",
        },
    },
}

# Derived view — the set of production engine ids. Never hand-edit.
MODULE_IDS = set(ENGINE_REGISTRY)
# Retired engines still seen in old placements / library usages → live engine.
# Placement + draw normalize through canonicalize_engine_id().
RETIRED_ENGINE_ALIASES: dict[str, str] = {
    # Side panel (title + bullets + docked head) was duplicative of dependency-stack.
    "speaker-side-panel": "dependency-stack",
}
ROBOT_MODULE_IDS = frozenset({"robot-cheer", "robot-defiant", "robot-roast"})
# Engine-fixed: after the mascot is fully drawn, max on-screen hold before exit.
ROBOT_HOLD_AFTER_DRAWN_SEC = 3.0
# Rocket soft-CTA gag is longer than standing robots (misfire + pound + blast).
ROBOT_ROCKET_MIN_CUE_SEC = 6.5
# Optional private community wordmark for brand-cta-lockup (lives under gitignored internal/).
BRAND_SKOOL_LOGO_STAGED_NAME = "brand-skool-logo.svg"
# Brand-fixed CTA copy — not placement-crafted (product lock for VCG episodes).
DEFAULT_BRAND_CTA_LOGO_TEXT = "Community"
DEFAULT_BRAND_CTA_ACTION = "JOIN THE FREE VIBE CODE GUILD COMMUNITY"
DEFAULT_BRAND_CTA_DESTINATION = "skool.com/vibecodeguild"


def brand_skool_logo_path() -> Path:
    """Private logo path (not tracked by git). Missing is fine until a local brand pack exists."""
    return project_root() / "internal" / "brand" / "skool-logo.svg"


def brand_joke_demo_image_path() -> Path:
    """Default illustration for library samples of the 7-22 joke image card."""
    return project_root() / "internal" / "brand" / "joke-demo.png"


CUE_KINDS = {"module", "asset", "composition"}
ANCHOR_TYPES = {"spoken", "scene-relative", "unanchored"}
COMMON_MODULE_PARAMETERS = {
    "reviewLabel", "editorialPurpose", "recipeId", "opacity", "transitionIn", "transitionOut",
    "speakerSafety", "visualFamily", "candidateTreatmentIds", "selectionRationale",
    "planningSuggestionId", "approvedTreatmentId", "meaningfulChanges", "approvalEvidence",
    # Layout-aware sample / placement free region (normalized bounds).
    "placementBounds",
}
def _derive_engine_parameter_keys(entry: dict[str, Any]) -> set[str]:
    """Draw-accepted keys = common + everything the placement interface exposes + legacy.

    Single-source rule: an engine's parameters are whatever its registry entry
    declares. There is no second hand-maintained key list to drift.
    """

    placement = entry["placement"]
    keys = set(COMMON_MODULE_PARAMETERS)
    for slot in placement["fixed_line_slots"]:
        # cards.0 / cards.1 / cards.2 → parameter key "cards"
        keys.add(str(slot).split(".", 1)[0])
    if placement["list_slot"]:
        keys.add(str(placement["list_slot"]))
    keys.update(placement["meta_keys"])
    keys.update(placement["asset_keys"])
    keys.update(placement["motion_keys"])
    keys.update(entry.get("legacy_parameter_keys") or ())
    return keys


# Derived view — allowed draw parameters per engine. Never hand-edit.
MODULE_PARAMETER_KEYS = {
    engine_id: _derive_engine_parameter_keys(entry)
    for engine_id, entry in ENGINE_REGISTRY.items()
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


def probe_has_audio_stream(path: Path) -> bool:
    """True when the media file carries at least one audio stream."""
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise RuntimeError("FFprobe is required to inspect audio streams.")
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
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
        raise RuntimeError(f"Could not inspect audio streams in {path.name}. {details[-600:]}")
    try:
        return bool(json.loads(result.stdout).get("streams"))
    except json.JSONDecodeError:
        return False


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


def canonicalize_engine_id(module_id: str | None) -> str:
    """Map retired engine ids to the live replacement (identity if still active)."""
    mid = str(module_id or "").strip()
    return RETIRED_ENGINE_ALIASES.get(mid, mid)


def normalize_cue_engine(cue: dict) -> dict:
    """Rewrite a cue that still names a retired engine so draw/placement can run.

    speaker-side-panel → dependency-stack: title stays ``text``; ``items`` become ``nodes``.
    """
    if not isinstance(cue, dict) or cue.get("kind") != "module":
        return cue
    raw_id = str(cue.get("moduleId") or "").strip()
    live_id = canonicalize_engine_id(raw_id)
    if live_id == raw_id:
        return cue
    out = dict(cue)
    out["moduleId"] = live_id
    params = dict(out.get("parameters") or {})
    if raw_id == "speaker-side-panel" and live_id == "dependency-stack":
        items = params.get("items")
        if isinstance(items, list) and not isinstance(params.get("nodes"), list):
            params["nodes"] = [str(v) for v in items if str(v).strip()]
        params.pop("items", None)
        params.pop("kicker", None)
        params.pop("frameStyle", None)
        params.pop("panelWidth", None)
        params.pop("videoBounds", None)
        out["parameters"] = params
        # Semantic paths from old drafts used parameters.items.*
        remapped: list[dict] = []
        for item in out.get("semanticItems") or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            path = str(row.get("parameterPath") or "")
            if path.startswith("parameters.items."):
                row["parameterPath"] = "parameters.nodes." + path.rsplit(".", 1)[-1]
            elif path == "parameters.kicker":
                continue
            remapped.append(row)
        if remapped or out.get("semanticItems"):
            out["semanticItems"] = remapped
    return out


def _module_semantic_texts(cue: dict) -> list[tuple[str, str, str]]:
    """Return every visible module string that requires an explicit reveal anchor."""
    if cue.get("kind") != "module":
        return []
    cue = normalize_cue_engine(cue)
    params = cue.get("parameters") if isinstance(cue.get("parameters"), dict) else {}
    module_id = cue.get("moduleId")
    fields: list[tuple[str, str]] = []
    if module_id in {"punchline-reveal", "progress-scale"}:
        fields.extend([("parameters.kicker", str(params.get("kicker") or "")), ("parameters.text", str(params.get("text") or ""))])
    if module_id == "dependency-stack":
        fields.append(("parameters.text", str(params.get("text") or "")))
    if module_id in ROBOT_MODULE_IDS or module_id == "robot-rocket-sign":
        fields.append(("parameters.text", str(params.get("text") or "")))
        if module_id == "robot-cheer":
            fields.append(("parameters.tagline", str(params.get("tagline") or "")))
    if module_id == "progress-scale":
        fields.extend([("parameters.startLabel", str(params.get("startLabel") or "")), ("parameters.targetLabel", str(params.get("targetLabel") or ""))])
    if module_id == "numbered-example-card":
        fields.append(("parameters.kicker", str(params.get("kicker") or "")))
    if module_id in PORTED_MODULE_IDS:
        for key in ("kicker", "thesis", "phrase", "title", "action", "payoff", "verdict", "rank",
                    "leftLabel", "rightLabel", "logoText", "destination", "appName", "prompt", "claim"):
            if key in MODULE_PARAMETER_KEYS.get(module_id, set()):
                fields.append((f"parameters.{key}", str(params.get(key) or "")))
    if module_id == "ui-callout":
        fields.append(("parameters.label", str(params.get("label") or "")))
    list_fields = (
        ["nodes"] if module_id == "dependency-stack"
        else ["milestones"] if module_id == "progress-scale"
        else ["titleLines"] if module_id == "numbered-example-card"
        else ["cards"] if module_id == "problem-card-triptych"
        else ["callouts"] if module_id == "speaker-rise-callouts"
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
        if not cue.get("enabled", True):
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


# Empty: July-22 library families retired; remaining edge graphics live in PORTED.
LIBRARY_MODULE_IDS: set[str] = set()
# Ported catalog families with dedicated markup paths (subset of MODULE_IDS).
PORTED_MODULE_IDS = {
    "kinetic-word-punctuation",
    "numbered-step-intro",
    "problem-card-triptych",
    "speaker-rise-callouts",
    "tradeoff-meter",
    "brand-cta-lockup",
    "windows-prompt-typing",
}


def _ported_markup(
    module_id: str,
    params: dict,
    common: str,
    accent: str,
    kicker: str,
    staged_assets: dict[str, str] | None = None,
) -> str:
    """Markup for ported catalog families (brand language from successful VCG projects)."""
    side = str(params.get("side")) if str(params.get("side")) in SIDE_ANCHORS else "right"
    open_tag = f'<section {common} style="--cue-accent:{accent}">'
    kick = f'<div class="lib-kicker" data-semantic-path="parameters.kicker">{kicker}</div>'

    def accent_at(key: str) -> int:
        return int(_number(params.get(key), -1, -1, 9))

    if module_id == "kinetic-word-punctuation":
        phrase = html.escape(str(params.get("phrase") or "THIS"))
        # Default high on frame — emphasis stamps should sit above the face band.
        anchor = str(params.get("anchor")) if str(params.get("anchor")) in {"top", "middle", "bottom"} else "top"
        return (f'{open_tag}<div class="pf-kinetic pf-k-{anchor} pf-{side}">'
                f'<span data-semantic-path="parameters.phrase">{phrase}</span></div></section>')

    if module_id == "numbered-step-intro":
        number = int(_number(params.get("stepNumber"), 1, 1, 99))
        show_number = params.get("showNumber") is not False
        title = html.escape(str(params.get("title") or ""))
        action = html.escape(str(params.get("action") or ""))
        # Number + title share one teal headline row (same size/weight/color).
        number_markup = f'<div class="pf-step-num">{number:02d}</div>' if show_number else ""
        no_number = " pf-step-no-num" if not show_number else ""
        return (
            f'{open_tag}<div class="pf-card pf-step-intro{no_number} pf-{side}">'
            f'<div class="pf-step-headline">'
            f'{number_markup}'
            f'<div class="pf-step-title" data-semantic-path="parameters.title">{title}</div>'
            f'</div>'
            f'<div class="pf-step-action" data-semantic-path="parameters.action">{action}</div>'
            f'</div></section>'
        )

    if module_id == "problem-card-triptych":
        # Three sequential point cards only (no eyebrow). Number left, copy right;
        # pink active / white settled; type inherits for contrast.
        cards = _strings(params.get("cards"), 3)
        body = "".join(
            f'<div class="pf-tri-card" data-card-index="{index}">'
            f'<i>{index + 1:02d}</i>'
            f'<span data-semantic-path="parameters.cards.{index}">{html.escape(card)}</span></div>'
            for index, card in enumerate(cards)
        )
        return f'{open_tag}<div class="pf-triptych"><div class="pf-tri-row">{body}</div></div></section>'

    if module_id == "speaker-rise-callouts":
        thesis = html.escape(str(params.get("thesis") or ""))
        # Up to 8 emphasis words/phrases around the speaker + one thesis bar.
        # Positions are edge/face-clear (CSS nth-child) — never center over the head.
        callouts = _strings(params.get("callouts"), 8)
        marked = accent_at("accentCalloutIndex")
        body = "".join(
            f'<div class="pf-rise-item{" lib-accent" if index == marked else ""}" '
            f'data-callout-index="{index}" '
            f'data-semantic-path="parameters.callouts.{index}">{html.escape(call)}</div>'
            for index, call in enumerate(callouts)
        )
        return (f'{open_tag}<div class="pf-rise-thesis" data-semantic-path="parameters.thesis">{thesis}</div>'
                f'<div class="pf-rise">{body}</div></section>')

    if module_id == "tradeoff-meter":
        left_label = html.escape(str(params.get("leftLabel") or "EASY"))
        right_label = html.escape(str(params.get("rightLabel") or "CONTROL"))
        verdict = html.escape(str(params.get("verdict") or ""))
        value_frac = _number(params.get("value"), 0.5, 0, 1)
        value_pct = value_frac * 100.0
        # Knob is fixed at the value marker; only the fill grows toward it.
        return (
            f'{open_tag}<div class="pf-card pf-{side}">'
            f'<div class="pf-meter">'
            f'<div class="pf-meter-fill" style="width:100%;transform:scaleX(0);transform-origin:left center"></div>'
            f'<div class="pf-meter-knob" style="left:{value_pct:.2f}%"></div>'
            f'</div>'
            f'<div class="pf-meter-labels">'
            f'<span data-semantic-path="parameters.leftLabel">{left_label}</span>'
            f'<span data-semantic-path="parameters.rightLabel">{right_label}</span>'
            f'</div>'
            f'<div class="pf-verdict" data-semantic-path="parameters.verdict">{verdict}</div>'
            f'</div></section>'
        )

    if module_id == "brand-cta-lockup":
        # Community CTA stage: white stage, teal left band, logo + join line + URL pill,
        # talking head docked in the right frame. Join line + link are brand-fixed forever
        # (not placement fields). Optional logoAssetId still stages private wordmark art.
        logo = html.escape(DEFAULT_BRAND_CTA_LOGO_TEXT)
        logo_asset_id = str(params.get("logoAssetId") or "")
        staged_logo = (staged_assets or {}).get(logo_asset_id) if logo_asset_id else None
        if logo_asset_id and not staged_logo:
            raise ValueError(f"brand-cta-lockup references unknown logoAssetId: {logo_asset_id}")
        logo_src = html.escape(staged_logo or BRAND_SKOOL_LOGO_STAGED_NAME)
        action = html.escape(DEFAULT_BRAND_CTA_ACTION)
        destination = html.escape(DEFAULT_BRAND_CTA_DESTINATION)
        return (
            f'{open_tag}'
            f'<div class="community-stage">'
            # White stage with a punched hole so #main-video shows in the right frame.
            # Do not put a solid full-bleed bg under that hole — it paints the window white.
            f'<div class="community-mask" aria-hidden="true"></div>'
            f'<div class="community-band" aria-hidden="true"></div>'
            f'<img class="community-logo" src="assets/{logo_src}" alt="{logo}" />'
            f'<div class="community-copy">{action}</div>'
            f'<div class="community-url">{destination}</div>'
            f'<div class="community-video-outline" aria-hidden="true"></div>'
            f'</div></section>'
        )

    if module_id == "windows-prompt-typing":
        # Full stage: talking head cover-docks RIGHT (dependency-stack frame);
        # Windows terminal fades in on the LEFT and types the prompt like a CLI.
        # Typed text starts empty; GSAP writes textContent letter-by-letter.
        # Caret is CSS ::after on .prompt-typed-text (same inline box as the glyphs) so it
        # always trails the last character — including when the line wraps. A sibling
        # <span class="prompt-cursor"> does NOT track wrapped lines in Chromium.
        app_name = html.escape(str(params.get("appName") or "Windows PowerShell"))
        full_prompt = str(params.get("prompt") or "").replace("\r\n", "\n").replace("\r", "\n")
        full_attr = html.escape(full_prompt, quote=True)
        return (
            f'{open_tag}'
            f'<div class="prompt-stage">'
            f'<div class="prompt-mask" aria-hidden="true"></div>'
            f'<div class="prompt-terminal">'
            f'<div class="prompt-titlebar">'
            f'<span class="prompt-app" data-semantic-path="parameters.appName">{app_name}</span>'
            # Windows caption buttons (min / max / close) — not Mac traffic lights.
            f'<span class="prompt-win-controls" aria-hidden="true">'
            f'<span class="win-btn win-min">&#x2013;</span>'
            f'<span class="win-btn win-max">&#x25A1;</span>'
            f'<span class="win-btn win-close">&#x2715;</span>'
            f'</span>'
            f'</div>'
            f'<div class="prompt-body">'
            f'<div class="prompt-line">'
            f'<span class="prompt-prefix" aria-hidden="true">PS C:\\&gt;&nbsp;</span>'
            f'<span class="prompt-typed" data-semantic-path="parameters.prompt" '
            f'data-full-prompt="{full_attr}">'
            f'<span class="prompt-typed-text"></span>'
            f'</span>'
            f'</div></div></div>'
            f'<div class="prompt-video-outline" aria-hidden="true"></div>'
            f'</div></section>'
        )

    raise ValueError(f"Unknown ported module id: {module_id}")


def _strings(value: object, limit: int) -> list[str]:
    return [str(item) for item in value[:limit]] if isinstance(value, list) else []


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


def _robot_svg_cheer() -> str:
    """Teal VCG robot — raised fists, happy yell (recovered from original HyperFrames)."""
    return (
        '<svg class="robot-svg robot-svg-cheer" width="300" height="380" viewBox="0 0 320 400" '
        'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<g class="robot-body">'
        '<rect x="116" y="338" width="42" height="32" rx="13" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<rect x="162" y="338" width="42" height="32" rx="13" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<g transform="rotate(-26 120 224)">'
        '<rect x="104" y="96" width="32" height="134" rx="16" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<circle cx="120" cy="98" r="23" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '</g>'
        '<g transform="rotate(26 200 224)">'
        '<rect x="184" y="96" width="32" height="134" rx="16" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<circle cx="200" cy="98" r="23" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '</g>'
        '<rect x="112" y="212" width="96" height="124" rx="26" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<rect x="138" y="240" width="44" height="60" rx="11" fill="#FF00CE"/>'
        '<circle cx="152" cy="270" r="7" fill="#fff"/><circle cx="168" cy="270" r="7" fill="#fff"/>'
        '<line x1="160" y1="78" x2="160" y2="46" stroke="#1A1A2E" stroke-width="7" stroke-linecap="round"/>'
        '<circle cx="160" cy="36" r="12" fill="#FF00CE"/>'
        '<rect x="100" y="78" width="120" height="106" rx="26" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<path d="M124 118 q15 -17 30 0" fill="none" stroke="#1A1A2E" stroke-width="8" stroke-linecap="round"/>'
        '<path d="M166 118 q15 -17 30 0" fill="none" stroke="#1A1A2E" stroke-width="8" stroke-linecap="round"/>'
        '<circle cx="118" cy="150" r="11" fill="#FF00CE" opacity="0.55"/>'
        '<circle cx="202" cy="150" r="11" fill="#FF00CE" opacity="0.55"/>'
        '<ellipse cx="160" cy="150" rx="30" ry="22" fill="#1A1A2E"/>'
        '<path d="M136 155 a24 16 0 0 0 48 0 z" fill="#FF00CE"/>'
        '</g></svg>'
    )


def _robot_svg_defiant() -> str:
    """Teal VCG robot — angry brows, raised fist pump."""
    return (
        '<svg class="robot-svg robot-svg-defiant" width="300" height="394" viewBox="0 0 320 420" '
        'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<g class="robot-body">'
        '<rect x="116" y="358" width="42" height="32" rx="13" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<rect x="162" y="358" width="42" height="32" rx="13" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<rect x="86" y="240" width="30" height="94" rx="15" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<circle cx="101" cy="336" r="21" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<rect x="112" y="234" width="96" height="126" rx="26" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<rect x="138" y="262" width="44" height="60" rx="11" fill="#FF00CE"/>'
        '<circle cx="152" cy="292" r="7" fill="#fff"/><circle cx="168" cy="292" r="7" fill="#fff"/>'
        '<g class="robot-fist">'
        '<rect x="196" y="72" width="30" height="168" rx="15" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<circle cx="211" cy="70" r="24" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<line x1="200" y1="62" x2="222" y2="62" stroke="#1A1A2E" stroke-width="4" stroke-linecap="round"/>'
        '</g>'
        '<line x1="160" y1="100" x2="160" y2="68" stroke="#1A1A2E" stroke-width="7" stroke-linecap="round"/>'
        '<circle cx="160" cy="58" r="12" fill="#FF00CE"/>'
        '<rect x="100" y="100" width="120" height="106" rx="26" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '<line x1="120" y1="130" x2="150" y2="144" stroke="#1A1A2E" stroke-width="9" stroke-linecap="round"/>'
        '<line x1="200" y1="130" x2="170" y2="144" stroke="#1A1A2E" stroke-width="9" stroke-linecap="round"/>'
        '<circle cx="140" cy="158" r="6" fill="#1A1A2E"/><circle cx="180" cy="158" r="6" fill="#1A1A2E"/>'
        '<ellipse cx="160" cy="180" rx="28" ry="20" fill="#1A1A2E"/>'
        '<path d="M137 184 a23 15 0 0 0 46 0 z" fill="#FF00CE"/>'
        '</g></svg>'
    )


def _robot_svg_roast() -> str:
    """Teal VCG robot — laughing, pointing left at the host."""
    return (
        '<svg class="robot-svg robot-svg-roast" width="640" height="660" viewBox="0 0 600 660" '
        'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<g class="robot-body">'
        '<rect x="232" y="548" width="74" height="44" rx="20" fill="#007C7D" stroke="#1A1A2E" stroke-width="8"/>'
        '<rect x="300" y="548" width="74" height="44" rx="20" fill="#007C7D" stroke="#1A1A2E" stroke-width="8"/>'
        '<g transform="rotate(22 398 372)">'
        '<rect x="378" y="368" width="44" height="160" rx="22" fill="#007C7D" stroke="#1A1A2E" stroke-width="8"/>'
        '</g>'
        '<rect x="212" y="348" width="184" height="214" rx="38" fill="#007C7D" stroke="#1A1A2E" stroke-width="8"/>'
        '<rect x="252" y="392" width="104" height="112" rx="18" fill="#FF00CE"/>'
        '<circle cx="288" cy="448" r="9" fill="#fff"/><circle cx="320" cy="448" r="9" fill="#fff"/>'
        '<g class="robot-point">'
        '<rect x="66" y="378" width="158" height="42" rx="21" fill="#007C7D" stroke="#1A1A2E" stroke-width="8"/>'
        '<circle cx="78" cy="399" r="36" fill="#007C7D" stroke="#1A1A2E" stroke-width="8"/>'
        '<rect x="14" y="386" width="62" height="26" rx="13" fill="#007C7D" stroke="#1A1A2E" stroke-width="7"/>'
        '</g>'
        '<line x1="305" y1="150" x2="305" y2="104" stroke="#1A1A2E" stroke-width="8" stroke-linecap="round"/>'
        '<circle cx="305" cy="90" r="16" fill="#FF00CE"/>'
        '<rect x="205" y="148" width="200" height="172" rx="42" fill="#007C7D" stroke="#1A1A2E" stroke-width="8"/>'
        '<path d="M246 236 q28 -32 56 0" fill="none" stroke="#1A1A2E" stroke-width="11" stroke-linecap="round"/>'
        '<path d="M306 236 q28 -32 56 0" fill="none" stroke="#1A1A2E" stroke-width="11" stroke-linecap="round"/>'
        '<circle cx="238" cy="272" r="15" fill="#FF00CE" opacity="0.55"/>'
        '<circle cx="372" cy="272" r="15" fill="#FF00CE" opacity="0.55"/>'
        '<ellipse cx="305" cy="286" rx="46" ry="32" fill="#1A1A2E"/>'
        '<path d="M268 292 a37 24 0 0 0 74 0 z" fill="#FF00CE"/>'
        '</g></svg>'
    )


def _robot_rocket_svg() -> str:
    """Teal robot on a white rocket; placard type is HTML-overlaid for crisp Montserrat.

    Face layers (normal / confused / shocked) are swapped in the gag timeline.
    Fist is the circle at the *end* of the arm (not the shoulder).
    """
    return (
        '<svg class="rocket-svg" viewBox="0 0 520 320" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<g class="rocket-smoke" opacity="0">'
        '<ellipse class="rocket-puff rocket-puff-a" cx="48" cy="210" rx="22" ry="16" fill="#2a2a32"/>'
        '<ellipse class="rocket-puff rocket-puff-b" cx="28" cy="228" rx="28" ry="18" fill="#1a1a2e"/>'
        '<ellipse class="rocket-puff rocket-puff-c" cx="10" cy="242" rx="18" ry="12" fill="#3a3a46"/>'
        '</g>'
        '<g class="rocket-flame">'
        '<ellipse class="rocket-flame-core" cx="72" cy="198" rx="36" ry="18" fill="#FF00CE"/>'
        '<ellipse class="rocket-flame-outer" cx="58" cy="198" rx="28" ry="12" fill="#ff6ae0" opacity="0.85"/>'
        '</g>'
        # White hull for contrast against the talking-head / white stage.
        '<g class="rocket-hull">'
        '<path d="M90 160 L90 236 L300 236 Q360 198 300 160 Z" fill="#FFFFFF" stroke="#1A1A2E" stroke-width="7"/>'
        '<path d="M300 160 Q390 160 440 198 Q390 236 300 236 Z" fill="#F4F4F8" stroke="#1A1A2E" stroke-width="7"/>'
        '<path d="M100 160 L130 128 L170 160 Z" fill="#FF00CE" stroke="#1A1A2E" stroke-width="6"/>'
        '<path d="M100 236 L130 268 L170 236 Z" fill="#FF00CE" stroke="#1A1A2E" stroke-width="6"/>'
        '<circle cx="250" cy="198" r="28" fill="#e6f5f5" stroke="#1A1A2E" stroke-width="6"/>'
        '<circle cx="250" cy="198" r="14" fill="#FF00CE"/>'
        '</g>'
        '<g class="rocket-sign-art">'
        '<rect x="300" y="48" width="200" height="72" rx="12" fill="#FFFFFF" stroke="#1A1A2E" stroke-width="6"/>'
        '<rect x="300" y="48" width="200" height="72" rx="12" fill="none" stroke="#FF00CE" stroke-width="4"/>'
        '<line x1="360" y1="120" x2="280" y2="175" stroke="#1A1A2E" stroke-width="7" stroke-linecap="round"/>'
        '</g>'
        # Rider: head floats with a clear air gap over the body (VCG robot silhouette).
        '<g class="rocket-rider">'
        '<rect x="175" y="128" width="70" height="72" rx="16" fill="#007C7D" stroke="#1A1A2E" stroke-width="6"/>'
        '<rect x="192" y="146" width="36" height="34" rx="8" fill="#FF00CE"/>'
        '<circle cx="204" cy="163" r="5" fill="#fff"/><circle cx="216" cy="163" r="5" fill="#fff"/>'
        # Antenna sits on head
        '<line x1="210" y1="58" x2="210" y2="38" stroke="#1A1A2E" stroke-width="6" stroke-linecap="round"/>'
        '<circle cx="210" cy="32" r="9" fill="#FF00CE"/>'
        # Head (gap between y=110 head bottom and y=128 body top)
        '<rect x="168" y="52" width="84" height="58" rx="16" fill="#007C7D" stroke="#1A1A2E" stroke-width="6"/>'
        # --- faces (mutually exclusive opacity) ---
        '<g class="rocket-face-normal">'
        '<circle cx="190" cy="78" r="5" fill="#1A1A2E"/><circle cx="230" cy="78" r="5" fill="#1A1A2E"/>'
        '<path d="M198 92 q12 10 24 0" fill="none" stroke="#1A1A2E" stroke-width="5" stroke-linecap="round"/>'
        '</g>'
        '<g class="rocket-face-confused" opacity="0">'
        # Quizzical brows + small o mouth
        '<line x1="178" y1="68" x2="200" y2="74" stroke="#1A1A2E" stroke-width="5" stroke-linecap="round"/>'
        '<line x1="242" y1="66" x2="220" y2="74" stroke="#1A1A2E" stroke-width="5" stroke-linecap="round"/>'
        '<circle cx="190" cy="82" r="5" fill="#1A1A2E"/><circle cx="230" cy="84" r="5" fill="#1A1A2E"/>'
        '<circle cx="210" cy="96" r="7" fill="none" stroke="#1A1A2E" stroke-width="5"/>'
        '</g>'
        '<g class="rocket-face-shocked" opacity="0">'
        # Wide eyes + open O mouth
        '<ellipse cx="190" cy="78" rx="11" ry="13" fill="#FFFFFF" stroke="#1A1A2E" stroke-width="5"/>'
        '<ellipse cx="230" cy="78" rx="11" ry="13" fill="#FFFFFF" stroke="#1A1A2E" stroke-width="5"/>'
        '<circle cx="192" cy="80" r="4" fill="#1A1A2E"/><circle cx="232" cy="80" r="4" fill="#1A1A2E"/>'
        '<ellipse cx="210" cy="98" rx="12" ry="10" fill="#1A1A2E"/>'
        '<ellipse cx="210" cy="100" rx="7" ry="5" fill="#FF00CE"/>'
        '</g>'
        # Arm: shoulder is the top of the rect; fist circle is at the bottom end.
        '<g class="rocket-fist" transform-origin="252 130">'
        '<rect x="242" y="128" width="20" height="58" rx="10" fill="#007C7D" stroke="#1A1A2E" stroke-width="5"/>'
        '<circle cx="252" cy="192" r="16" fill="#007C7D" stroke="#1A1A2E" stroke-width="5"/>'
        '</g>'
        '</g>'
        '</svg>'
    )


def _robot_rocket_markup(params: dict, common: str) -> str:
    """Soft CTA: robot on rocket flies L→R with a short sign line."""
    line = html.escape(str(params.get("text") or "LINK IN DESCRIPTION"))
    return (
        f'<section {common}>'
        f'<div class="rocket-stage">'
        f'<div class="rocket-rig">'
        f'{_robot_rocket_svg()}'
        f'<div class="rocket-sign-board" data-semantic-path="parameters.text">{line}</div>'
        f'</div></div></section>'
    )


def _robot_module_markup(module_id: str, params: dict, common: str) -> str:
    """Transparent mascot overlay: bubble + SVG robot (cheer left, defiant left, roast right)."""
    if module_id == "robot-rocket-sign":
        return _robot_rocket_markup(params, common)
    line = html.escape(str(params.get("text") or "EDIT THIS LINE"))
    if module_id == "robot-cheer":
        tagline = html.escape(str(params.get("tagline") or "FOR THE WIN!"))
        bubble = (
            f'<div class="robot-bubble">'
            f'<span data-semantic-path="parameters.text">{line}</span> '
            f'<span class="robot-hl" data-semantic-path="parameters.tagline">{tagline}</span> &#127881;'
            f'<div class="robot-tail"></div></div>'
        )
        stage = "robot-stage-left"
        svg = _robot_svg_cheer()
    elif module_id == "robot-defiant":
        bubble = (
            f'<div class="robot-bubble">'
            f'<span data-semantic-path="parameters.text">{line}</span> &#9994;'
            f'<div class="robot-tail"></div></div>'
        )
        stage = "robot-stage-left"
        svg = _robot_svg_defiant()
    elif module_id == "robot-roast":
        bubble = (
            f'<div class="robot-bubble robot-bubble-roast">'
            f'<span data-semantic-path="parameters.text">{line}</span> &#128514;'
            f'<div class="robot-tail"></div></div>'
        )
        stage = "robot-stage-right"
        svg = _robot_svg_roast()
    else:
        raise ValueError(f"Unknown robot module: {module_id}")
    return (
        f'<section {common}>'
        f'<div class="robot-stage {stage}">'
        f'<div class="robot-wrap">'
        f'{bubble}{svg}'
        f'</div></div></section>'
    )


def _module_markup(
    cue: dict,
    element_id: str,
    start: float,
    duration: float,
    track: int,
    staged_assets: dict[str, str] | None = None,
) -> str:
    cue = normalize_cue_engine(cue)
    params = cue.get("parameters") or {}
    module_id = cue["moduleId"]
    text = html.escape(str(params.get("text") or "EDIT THIS TEXT"))
    kicker = html.escape(str(params.get("kicker") or "VCG / VISUAL"))
    accent_color = html.escape(str(params.get("accentColor") or "#FF00CE"))
    common = (
        f'id="{element_id}" class="clip module module-{module_id}" '
        f'data-start="{start:.4f}" data-duration="{duration:.4f}" data-track-index="{track}"'
    )
    if module_id in ROBOT_MODULE_IDS or module_id == "robot-rocket-sign":
        return _robot_module_markup(module_id, params, common)
    safe_overlay_style = _speaker_safe_overlay_style(params)
    if module_id == "punchline-reveal":
        # Single product look: 7-22 joke card (image required). No alternate text-only mode.
        image_asset_id = str(params.get("imageAssetId") or "").strip()
        if not image_asset_id:
            raise ValueError(
                "punchline-reveal requires imageAssetId (joke-card engine). "
                "Use kinetic-word-punctuation for text-only kinetic phrases."
            )
        staged_image = (staged_assets or {}).get(image_asset_id)
        if not staged_image:
            raise ValueError(f"punchline-reveal references unknown imageAssetId: {image_asset_id}")
        # Transposed dependency-stack: talking head docks left; image+copy on the right.
        # No kicker (D5): the caption is the Title line only.
        return (
            f'<section {common} style="--cue-accent:{accent_color}">'
            f'<div class="joke-stage">'
            f'<div class="joke-mask" aria-hidden="true"></div>'
            f'<div class="joke-video-outline" aria-hidden="true"></div>'
            f'<div class="joke-panel">'
            f'<div class="joke-card">'
            f'<img class="joke-image" src="assets/{html.escape(staged_image)}" alt="" />'
            f'<div class="joke-copy">'
            f'<div class="joke-line" data-semantic-path="parameters.text">{text}</div>'
            f'</div></div></div></div></section>'
        )
    if module_id == "progress-scale":
        # Full white stage (base is white): copy on the left, source video framed
        # upper-right in .stat-video-outline. Not an overlay card over full-frame video.
        # Milestone stops sit at the same bar fractions the fill travels (0…1).
        start_label = html.escape(str(params.get("startLabel") or "START"))
        target_label = html.escape(str(params.get("targetLabel") or "TARGET"))
        milestones = params.get("milestones") if isinstance(params.get("milestones"), list) else []
        milestone_items = milestones[:4]
        count = len(milestone_items)
        milestone_parts: list[str] = []
        for index, item in enumerate(milestone_items):
            frac = index / max(count - 1, 1) if count > 1 else 0.5
            if count == 1:
                align = "translateX(-50%)"
            elif index == 0:
                align = "translateX(0)"
            elif index == count - 1:
                align = "translateX(-100%)"
            else:
                align = "translateX(-50%)"
            milestone_parts.append(
                f'<span class="scale-milestone" data-milestone-index="{index}" '
                f'data-semantic-path="parameters.milestones.{index}" '
                f'style="left:{frac * 100:.4f}%;transform:{align}">'
                f'{html.escape(str(item))}</span>'
            )
        milestones_markup = (
            f'<div class="scale-milestones">{"".join(milestone_parts)}</div>'
            if milestone_parts
            else ""
        )
        return (
            f'<section {common} style="--cue-accent:{accent_color}">'
            f'<div class="progress-stage">'
            f'<div class="kicker" data-semantic-path="parameters.kicker">{kicker}</div>'
            f'<div class="stat-title" data-semantic-path="parameters.text">{text}</div>'
            f'<div class="progress-track-block">'
            f'{milestones_markup}'
            f'<div class="scale"><div class="scale-fill"></div>'
            f'<div class="scale-labels">'
            f'<span data-semantic-path="parameters.startLabel">{start_label}</span>'
            f'<span data-semantic-path="parameters.targetLabel">{target_label}</span>'
            f'</div></div></div>'
            f'<div class="stat-video-outline" aria-hidden="true"></div>'
            f'</div></section>'
        )
    if module_id == "source-punch-zoom":
        # Pure camera move on the source. It renders no overlay at all, which is what makes it
        # usable over a demonstration that must stay readable.
        return f'<section {common}></section>'
    if module_id in PORTED_MODULE_IDS:
        return _ported_markup(module_id, params, common, accent_color, kicker, staged_assets)
    if module_id == "ui-callout":
        label = html.escape(str(params.get("label") or "THIS"))
        target = normalized_bounds(params.get("targetBounds"))
        if target is None:
            # Placement craft sends flat meta knobs; library samples may nest.
            try:
                target = normalized_bounds(
                    {
                        "x": float(params.get("x")),
                        "y": float(params.get("y")),
                        "width": float(params.get("width")),
                        "height": float(params.get("height")),
                    }
                )
            except (TypeError, ValueError):
                target = None
        target = target or {"x": 0.55, "y": 0.12, "width": 0.35, "height": 0.18}
        pointer = "above" if str(params.get("pointer")) == "above" else "below"
        left, top = target["x"] * 100, target["y"] * 100
        wide, tall = target["width"] * 100, target["height"] * 100
        label_top = (target["y"] + target["height"]) * 100 if pointer == "below" else target["y"] * 100
        align_right = target["x"] + target["width"] > .78
        label_left = (target["x"] + target["width"]) * 100 if align_right else left
        alignment_class = " callout-align-right" if align_right else ""
        return (
            f'<section {common} style="--cue-accent:{accent_color}">'
            f'<div class="callout-ring" style="left:{left:.3f}%;top:{top:.3f}%;width:{wide:.3f}%;height:{tall:.3f}%"></div>'
            f'<div class="callout-label callout-{pointer}{alignment_class}" style="left:{label_left:.3f}%;top:{label_top:.3f}%">'
            f'<span class="callout-text" data-semantic-path="parameters.label">{label}</span></div>'
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
        place = normalized_bounds(params.get("placementBounds"))
        place_style = (
            f'left:{place["x"] * 100:.3f}%;top:{place["y"] * 100:.3f}%;'
            f'width:{place["width"] * 100:.3f}%;height:{place["height"] * 100:.3f}%;'
            if place
            else ""
        )
        card_style = f' style="{place_style}"' if place_style else ""
        return (
            f'<section {common} style="--cue-accent:{accent_color}">'
            f'<div class="example-card"{card_style}>'
            f'<div class="example-rail"><div class="example-number">{number:02d}</div><div class="example-rail-label">EXAMPLE</div></div>'
            f'<div class="example-body">'
            f'<div class="example-head"><span class="kicker" data-semantic-path="parameters.kicker">{kicker}</span>'
            f'<span class="example-count">{number:02d} / {total:02d}</span></div>'
            f'<div class="example-rule"></div>'
            f'<div class="example-lines">{line_markup}</div>'
            f'<div class="example-foot"><span class="example-tags">{tag_markup}</span><span class="example-pips">{pips}</span></div>'
            f'</div></div></section>'
        )
    if module_id == "dependency-stack":
        # Left title + sequential stack; talking head covers into a tall right frame
        # (sides of the full-frame source are cropped by a white mask hole).
        title = html.escape(str(params.get("text") or "WHAT YOU NEED"))
        nodes = _strings(params.get("nodes"), 6)
        node_markup = "".join(
            f'<div class="dep-node" data-node-index="{index}" '
            f'data-semantic-path="parameters.nodes.{index}">{html.escape(node)}</div>'
            for index, node in enumerate(nodes)
        )
        return (
            f'<section {common} style="--cue-accent:{accent_color}">'
            f'<div class="dependency-stage">'
            f'<div class="dependency-mask" aria-hidden="true"></div>'
            f'<div class="dependency-panel">'
            f'<div class="dependency-title" data-semantic-path="parameters.text">{title}</div>'
            f'<div class="nodes">{node_markup}</div>'
            f'</div>'
            f'<div class="dependency-video-outline" aria-hidden="true"></div>'
            f'</div></section>'
        )
    raise ValueError(f"Unknown visual module: {module_id}")


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


def _punchline_title_content_at(
    cue: dict,
    *,
    range_start: float,
    start: float,
    duration: float,
) -> float:
    """Composition-local time when the whole right joke card should land.

    Driven by the Title line's ``parameters.text`` semantic anchor. Stage/dock
    (white + head + head outline) always starts at the beat (``start``). At this
    time the card borders, image, and caption enter together.
    """

    content_at = start
    for semantic in cue.get("semanticItems") or []:
        if not isinstance(semantic, dict):
            continue
        if str(semantic.get("parameterPath") or "") != "parameters.text":
            continue
        try:
            spoken = float(semantic.get("spokenStartSec") or 0.0)
        except (TypeError, ValueError):
            spoken = 0.0
        content_at = max(spoken, range_start) - range_start
        break
    # Keep a little room before cue end for content entrance + exit.
    return max(start, min(content_at, start + max(0.0, duration - 0.8)))


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


def _replace_directory_tree(path: Path) -> bool:
    """Remove a directory tree, surviving Windows file locks (WinError 32).

    Live HyperFrames players often keep ``public/source.mp4`` open. ``rmtree``
    then fails mid-delete. Renaming the tree out of the way frees the path name
    so a fresh workspace can be created; the stale rename is deleted best-effort.

    Returns True when ``path`` no longer exists, False when locks prevent clear.
    Callers must not treat False as fatal — claim a sibling workspace instead.
    """

    path = Path(path)
    if not path.exists():
        return True
    try:
        shutil.rmtree(path)
        return not path.exists()
    except OSError:
        pass
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    stale = parent / f".{path.name}.stale-{uuid.uuid4().hex[:10]}"
    try:
        path.rename(stale)
    except OSError:
        # Last resort: try to move just the locked media and leave the rest.
        for locked_name in ("source.mp4",):
            locked = path / "public" / locked_name
            if locked.is_file():
                try:
                    locked.rename(parent / f".{locked_name}.stale-{uuid.uuid4().hex[:8]}")
                except OSError:
                    pass
        try:
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass
        return not path.exists()
    # Best-effort cleanup of the renamed tree (may still be locked briefly).
    try:
        shutil.rmtree(stale, ignore_errors=True)
    except OSError:
        pass
    return not path.exists()


def _claim_empty_workspace(path: Path) -> Path:
    """Return an empty directory path ready for a HyperFrames workspace write.

    Prefer ``path``. If it already exists, try to clear it (rename-aside on
    Windows locks). If the live preview still holds files open, divert to a
    unique sibling so the build never fails with "file in use".
    """

    path = Path(path)
    if not path.exists():
        return path
    if _replace_directory_tree(path):
        return path
    sibling = path.parent / f"{path.name}-w{uuid.uuid4().hex[:10]}"
    # Extremely unlikely collision; one more try keeps the contract.
    if sibling.exists():
        sibling = path.parent / f"{path.name}-w{uuid.uuid4().hex[:12]}"
    return sibling


def build_hyperframes_composition(
    plan_path: Path,
    *,
    start_sec: float | None = None,
    end_sec: float | None = None,
    workspace_override: Path | None = None,
    progress: ProgressCallback | None = None,
    # Library samples only: seconds between multi-item reveals (lists, callouts, etc.).
    # Production keeps engine defaults when this is None.
    sample_reveal_stagger_sec: float | None = None,
    # Placement live preview omits #main-audio: the HyperFrames transport derives its
    # master clock from in-composition audio and can pin (freeze) on it mid-play.
    # With no audio element the clock is pure monotonic time and cannot freeze; the
    # studio plays speech through an app-owned <audio> instead. Renders keep True.
    include_source_audio: bool = True,
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
    # Wipe prior workspace when possible. On Windows a live hyperframes-player may
    # still hold public/source.mp4 open — if clear fails, divert to a sibling path
    # instead of erroring out of placement preview / sample rebuilds.
    workspace = _claim_empty_workspace(workspace)
    if not _is_within(workspace, root):
        raise ValueError("HyperFrames workspace must stay inside the private visual project.")
    public = workspace / "public"
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

    # Community CTA uses the optional private wordmark when no logoAssetId is set.
    if any(
        cue.get("kind") == "module" and cue.get("moduleId") == "brand-cta-lockup"
        for cue in plan.get("cues", [])
        if cue.get("enabled", True)
    ):
        skool_logo = brand_skool_logo_path()
        if not skool_logo.is_file():
            raise RuntimeError(f"Missing private community logo at {skool_logo}")
        shutil.copy2(skool_logo, public / "assets" / BRAND_SKOOL_LOGO_STAGED_NAME)

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
        cue = normalize_cue_engine(cue)
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
            # Engines that own full enter/exit skip the shell slide.
            owns_shell = (
                module_id in ROBOT_MODULE_IDS
                or module_id
                in {
                    "brand-cta-lockup",
                    "robot-rocket-sign",
                    "windows-prompt-typing",
                    "punchline-reveal",
                    # Stamp owns enter at phrase reveal (box + words together).
                    "kinetic-word-punctuation",
                }
            )
            if owns_shell:
                transition_in = "none"
                transition_out = "none"
            else:
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
                # Speaker-rise drives its own sequential reveals (thesis, then each word).
                # Skip generic semantic opacity tweens so they cannot flatten the sequence.
                # Modules that own their reveal sequence must not also run generic
                # semantic opacity tweens (those flatten the intended timing).
                skip_semantic = {
                    "speaker-rise-callouts",
                    "progress-scale",
                    "problem-card-triptych",
                    "dependency-stack",
                    "brand-cta-lockup",
                    "robot-rocket-sign",
                    "windows-prompt-typing",
                    "punchline-reveal",  # joke card owns kicker/line reveals
                    # Phrase opacity is owned by the stamp reveal (not a separate fade).
                    "kinetic-word-punctuation",
                    *ROBOT_MODULE_IDS,
                }
                if module_id not in skip_semantic:
                    timeline_lines.extend(_semantic_timeline_lines(cue, element_id, range_start, range_end, start))
                elif module_id == "progress-scale":
                    # Title + end labels use normal semantic timing. Milestones are
                    # owned by the progress-scale block below (fill reaches each stop
                    # at that stop's reveal frame).
                    non_milestone = [
                        item
                        for item in cue.get("semanticItems", [])
                        if not str(item.get("parameterPath") or "").startswith("parameters.milestones.")
                    ]
                    if non_milestone:
                        filtered = dict(cue)
                        filtered["semanticItems"] = non_milestone
                        timeline_lines.extend(
                            _semantic_timeline_lines(filtered, element_id, range_start, range_end, start)
                        )
                elif module_id == "problem-card-triptych":
                    # Cards own their reveal (pink handoff). Skip generic semantic opacity.
                    pass
                elif module_id == "dependency-stack":
                    # Title may use semantic timing; nodes are the pink handoff sequence.
                    non_nodes = [
                        item
                        for item in cue.get("semanticItems", [])
                        if not str(item.get("parameterPath") or "").startswith("parameters.nodes.")
                    ]
                    if non_nodes:
                        filtered = dict(cue)
                        filtered["semanticItems"] = non_nodes
                        timeline_lines.extend(
                            _semantic_timeline_lines(filtered, element_id, range_start, range_end, start)
                        )
            if module_id == "punchline-reveal":
                # Joke card only: dock head LEFT, image + caption panel from the right.
                # Must match .joke-video-outline / .joke-mask (left tall frame).
                #
                # Timing contract:
                # - Beat start: white stage, head docks left, mask + head outline only.
                # - Title reveal: the whole right card lands together — black borders
                #   (card + caption plate), image, and Title line. No empty shell first.
                # - Graphic ends at cue end = placement endFrameExclusive (default beat
                #   end). Trim that span earlier to undock back to full talking-head.
                video_left, video_top = 0.08, 0.10
                video_w, video_h = 0.42, 0.78
                video_scale = max(video_w, video_h)
                face_center_x = 0.47
                video_x = (video_left + video_w / 2) - face_center_x * video_scale
                video_y = video_top
                video_in, video_out = 0.55, 0.42
                panel = f'#{element_id} .joke-panel'
                card = f'#{element_id} .joke-card'
                img = f'#{element_id} .joke-image'
                line = f'#{element_id} .joke-line'
                chrome = f'#{element_id} .joke-mask, #{element_id} .joke-video-outline'
                exit_d = min(0.32, max(0.22, duration * 0.12))

                content_at = _punchline_title_content_at(
                    cue,
                    range_start=range_start,
                    start=start,
                    duration=duration,
                )
                # Caption fade finishes slightly after image starts — "fully shown".
                content_shown = content_at + 0.40
                # Exit at placement span end (cue duration). No separate holdSec.
                cue_end = start + duration
                end_at = cue_end
                if end_at < content_shown + 0.2:
                    # Span was cut very tight after Title — still exit at cue end.
                    end_at = cue_end

                # Card shell, image, and caption stay hidden until Title.
                timeline_lines.append(
                    f'tl.set("#{element_id} [data-semantic-path]", {{opacity:0}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{img}", {{opacity:0}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{panel}", {{opacity:0}}, {start:.4f});'
                )

                # --- Beat start: stage move + head chrome only ---
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:{video_scale:.4f},'
                    f'x:{width * video_x:.2f},y:{height * video_y:.2f},'
                    f'duration:{video_in:.3f},ease:"power3.inOut"}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .joke-mask", {{opacity:0}}, '
                    f'{{opacity:1,duration:0.28,ease:"power2.out"}}, {entry_start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .joke-video-outline", {{opacity:0}}, '
                    f'{{opacity:1,duration:0.35,ease:"power2.out"}}, {(start + 0.12):.4f});'
                )

                # --- Title reveal: whole card (borders + image + caption) ---
                timeline_lines.append(
                    f'tl.fromTo("{panel}", {{opacity:0,x:70}}, '
                    f'{{opacity:1,x:0,duration:0.52,ease:"power3.out",immediateRender:false}}, '
                    f'{content_at:.4f});'
                )
                img_settle = max(0.55, min(1.1, end_at - content_at - 0.25))
                timeline_lines.append(
                    f'tl.fromTo("{img}", {{opacity:0,scale:1.08,x:18}}, '
                    f'{{opacity:1,scale:1,x:0,duration:{img_settle:.3f},'
                    f'ease:"sine.inOut",immediateRender:false}}, {content_at:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("{line}", {{opacity:0,y:18}}, '
                    f'{{opacity:1,y:0,duration:0.38,ease:"power2.out",immediateRender:false}}, '
                    f'{content_at:.4f});'
                )

                # --- Exit ---
                timeline_lines.append(
                    f'tl.to("{panel}", {{opacity:0,x:48,duration:{exit_d:.3f},ease:"power2.in"}}, '
                    f'{(end_at - exit_d):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{chrome}", '
                    f'{{opacity:0,duration:{exit_d:.3f},ease:"power2.in"}}, '
                    f'{(end_at - exit_d):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:{video_out:.3f},'
                    f'ease:"power3.inOut"}}, {max(start, end_at - video_out):.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{card}", {{opacity:0}}, {end_at:.4f});'
                )
            elif module_id == "speaker-rise-callouts":
                # Placement contract: thesis + each callout land at their revealFrame
                # (semanticItems). Never auto-stagger over placement anchors — that
                # packed words near the end of the beat and ignored craft frames.
                # Unanchored / library samples still stagger after the thesis.
                callouts = _strings(params.get("callouts"), 8)
                stagger = (
                    float(sample_reveal_stagger_sec)
                    if sample_reveal_stagger_sec is not None and sample_reveal_stagger_sec > 0
                    else 0.45
                )
                stagger = max(0.2, min(2.0, stagger))
                latest = start + duration - exit_duration - 0.35

                def _rise_spoken(path: str) -> float | None:
                    match = next(
                        (
                            item
                            for item in cue.get("semanticItems", [])
                            if str(item.get("parameterPath") or "") == path
                        ),
                        None,
                    )
                    if match is None:
                        return None
                    try:
                        spoken = float(match.get("spokenStartSec") or 0.0)
                    except (TypeError, ValueError):
                        spoken = 0.0
                    return max(spoken, range_start) - range_start

                thesis_spoken = _rise_spoken("parameters.thesis")
                thesis_at = (
                    max(start, min(latest, thesis_spoken))
                    if thesis_spoken is not None
                    else start + 0.08
                )
                callout_times: list[float] = []
                anchored_count = 0
                for index in range(len(callouts)):
                    spoken_local = _rise_spoken(f"parameters.callouts.{index}")
                    if spoken_local is not None:
                        callout_times.append(max(start + 0.08, min(latest, spoken_local)))
                        anchored_count += 1
                    else:
                        callout_times.append(thesis_at + 0.7 + index * stagger)
                if anchored_count == 0 and callout_times:
                    for index in range(len(callout_times)):
                        appear_at = thesis_at + 0.7 + index * stagger
                        if appear_at > latest:
                            appear_at = max(
                                thesis_at + 0.35,
                                latest
                                - (len(callout_times) - 1 - index) * min(stagger, 0.35),
                            )
                        callout_times[index] = appear_at
                else:
                    # Placement path: keep frames; small monotonic gap only.
                    min_gap = 0.08
                    for index in range(1, len(callout_times)):
                        callout_times[index] = max(
                            callout_times[index], callout_times[index - 1] + min_gap
                        )
                        callout_times[index] = min(callout_times[index], latest)

                # Keep children hidden until their beat (CSS also starts data-semantic-path at 0).
                timeline_lines.append(
                    f'tl.set("#{element_id} .pf-rise-thesis, #{element_id} .pf-rise-item", '
                    f'{{opacity:0,y:18}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .pf-rise-thesis", '
                    f'{{opacity:0,y:-18,scale:0.96}}, '
                    f'{{opacity:1,y:0,scale:1,duration:0.42,ease:"power3.out",'
                    f'immediateRender:false}}, {thesis_at:.4f});'
                )
                for index in range(len(callouts)):
                    appear_at = callout_times[index]
                    item_sel = (
                        f'#{element_id} .pf-rise-item[data-callout-index=\\"{index}\\"]'
                    )
                    timeline_lines.append(
                        f'tl.fromTo("{item_sel}", '
                        f'{{opacity:0,y:26,scale:0.9}}, '
                        f'{{opacity:1,y:0,scale:1,duration:0.4,ease:"power2.out",'
                        f'immediateRender:false}}, {appear_at:.4f});'
                    )
                exit_at = start + duration - exit_duration
                timeline_lines.append(
                    f'tl.to("#{element_id} .pf-rise-thesis, #{element_id} .pf-rise-item", '
                    f'{{opacity:0,duration:{exit_duration:.3f},ease:"power2.in"}}, {exit_at:.4f});'
                )
            elif module_id == "dependency-stack":
                # Tall right video window (CSS hole + outline). Cover-scale crops the
                # sides of the full-frame talking head into a skinnier portrait frame.
                # Must match .dependency-video-outline / .dependency-mask in runtime.css.
                #
                # Placement contract: each node lands at its revealFrame (via semantic
                # items). Never redistribute even spacing over placement anchors —
                # that made bullets ignore the craft panel frames.
                video_left, video_top = 0.50, 0.10
                video_w, video_h = 0.42, 0.78
                video_scale = max(video_w, video_h)
                # Source talking head sits slightly left of geometric center; bias the
                # cover crop so the face reads centered in the portrait hole.
                face_center_x = 0.46
                video_x = (video_left + video_w / 2) - face_center_x * video_scale
                video_y = video_top
                video_in, video_out = 0.55, 0.45
                settle_after_last_sec = 2.0
                linger_all_white_sec = 2.0
                pink, white_bg, ink = "#ff00ce", "#ffffff", "#1a1a2e"
                nodes = _strings(params.get("nodes"), 6)
                node_count = len(nodes)
                node_stagger = (
                    float(sample_reveal_stagger_sec)
                    if sample_reveal_stagger_sec is not None and sample_reveal_stagger_sec > 0
                    else 0.85
                )
                node_stagger = max(0.35, min(2.0, node_stagger))
                node_times: list[float] = []
                anchored_count = 0
                for index in range(node_count):
                    path = f"parameters.nodes.{index}"
                    match = next(
                        (
                            item
                            for item in cue.get("semanticItems", [])
                            if str(item.get("parameterPath") or "") == path
                        ),
                        None,
                    )
                    if match is not None:
                        try:
                            spoken = float(match.get("spokenStartSec") or 0.0)
                        except (TypeError, ValueError):
                            spoken = 0.0
                        appear_at = max(spoken, range_start) - range_start
                        # Honor placement frame; only keep after a brief dock settle.
                        node_times.append(max(start + 0.12, appear_at))
                        anchored_count += 1
                    else:
                        node_times.append(start + 0.45 + index * node_stagger)
                # Monotonic order — small gap when placement-driven so tight frames stay close.
                min_gap = 0.08 if anchored_count > 0 else 0.35
                for index in range(1, len(node_times)):
                    node_times[index] = max(node_times[index], node_times[index - 1] + min_gap)
                if node_times and anchored_count == 0 and node_count > 1:
                    # Library / unanchored samples only: compress evenly if settle won't fit.
                    latest_need = (
                        node_times[-1] + settle_after_last_sec + linger_all_white_sec + video_out
                    )
                    if latest_need > start + duration:
                        budget = max(
                            0.8,
                            duration - video_out - settle_after_last_sec - linger_all_white_sec - 0.45,
                        )
                        step = budget / max(node_count - 1, 1)
                        node_times = [start + 0.45 + index * step for index in range(node_count)]
                elif node_times and anchored_count > 0:
                    # Placement path: keep node frames; shrink pink-settle / linger to fit.
                    room_after = max(
                        0.4,
                        (start + duration - video_out) - node_times[-1],
                    )
                    settle_after_last_sec = min(settle_after_last_sec, max(0.3, room_after * 0.45))
                    linger_all_white_sec = min(
                        linger_all_white_sec,
                        max(0.15, room_after - settle_after_last_sec - 0.05),
                    )
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:{video_scale:.4f},'
                    f'x:{width * video_x:.2f},y:{height * video_y:.2f},'
                    f'duration:{video_in:.3f},ease:"power3.inOut"}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .dependency-panel", {{opacity:0,x:-36}}, '
                    f'{{opacity:1,x:0,duration:0.45,ease:"power3.out"}}, {entry_start:.4f});'
                )
                # Title starts hidden; non-node semantic timeline (above) reveals at Title frame.
                # Do not force opacity:1 at entry — that ignored placement Title timing.
                timeline_lines.append(
                    f'tl.set("#{element_id} .dependency-title", {{opacity:0}}, {start:.4f});'
                )
                if node_count:
                    timeline_lines.append(
                        f'tl.set("#{element_id} .dep-node", {{opacity:0,y:56}}, {start:.4f});'
                    )
                for index in range(node_count):
                    appear_at = node_times[index]
                    node_sel = f'#{element_id} .dep-node[data-node-index=\\"{index}\\"]'
                    timeline_lines.append(
                        f'tl.fromTo("{node_sel}", {{opacity:0,y:56}}, '
                        f'{{opacity:1,y:0,duration:0.42,ease:"power2.out",immediateRender:false}}, '
                        f'{appear_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.set("{node_sel}", {{opacity:1}}, {appear_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("{node_sel}", {{backgroundColor:"{pink}",color:"#ffffff",'
                        f'borderColor:"{pink}",duration:0.18,ease:"power1.out"}}, {appear_at:.4f});'
                    )
                    if index > 0:
                        prev_sel = f'#{element_id} .dep-node[data-node-index=\\"{index - 1}\\"]'
                        timeline_lines.append(
                            f'tl.to("{prev_sel}", {{backgroundColor:"{white_bg}",color:"{ink}",'
                            f'borderColor:"{ink}",duration:0.28,ease:"power1.out"}}, {appear_at:.4f});'
                        )
                if node_count:
                    last_sel = f'#{element_id} .dep-node[data-node-index=\\"{node_count - 1}\\"]'
                    settle_at = node_times[-1] + settle_after_last_sec
                    settle_at = min(settle_at, start + duration - video_out - linger_all_white_sec)
                    settle_at = max(settle_at, node_times[-1] + 0.25)
                    timeline_lines.append(
                        f'tl.to("{last_sel}", {{backgroundColor:"{white_bg}",color:"{ink}",'
                        f'borderColor:"{ink}",duration:0.3,ease:"power1.out"}}, {settle_at:.4f});'
                    )
                restore_at = start + duration - video_out
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:{video_out:.3f},ease:"power3.inOut"}}, '
                    f'{restore_at:.4f});'
                )
            elif module_id == "progress-scale":
                # Match .stat-video-outline in runtime.css (upper-right window).
                # main-video uses transform-origin:0 0, so scale + x/y land in the frame.
                #
                # Fill + milestone stops are driven by placement reveal frames
                # (semanticItems → parameters.milestones.*). The bar reaches stop i
                # when bullet/stop i reveals — not a free-running linear fill.
                video_x = 0.5625
                video_y = 0.12
                video_scale = 0.365
                video_in = 0.5
                video_out = 0.45
                hold_after_fill = 2.5
                milestones = params.get("milestones") if isinstance(params.get("milestones"), list) else []
                milestone_count = min(4, len(milestones))
                raw_times: list[float | None] = []
                for index in range(milestone_count):
                    path = f"parameters.milestones.{index}"
                    match = next(
                        (
                            item
                            for item in cue.get("semanticItems", [])
                            if str(item.get("parameterPath") or "") == path
                        ),
                        None,
                    )
                    if match is not None:
                        try:
                            spoken = float(match.get("spokenStartSec") or 0.0)
                        except (TypeError, ValueError):
                            spoken = 0.0
                        appear_at = max(spoken, range_start) - range_start
                        raw_times.append(max(start + 0.2, appear_at))
                    else:
                        raw_times.append(None)

                milestone_times: list[float] = []
                if milestone_count and all(t is None for t in raw_times):
                    # No placement anchors — even spacing (legacy sample / library path).
                    fill_lead = 0.45
                    min_fill = 1.2
                    available = max(min_fill, duration - fill_lead - video_out)
                    if available < min_fill + hold_after_fill:
                        hold_after_fill = max(1.5, available - min_fill)
                    fill_duration = max(min_fill, duration - fill_lead - hold_after_fill - video_out)
                    fill_start = start + fill_lead
                    milestone_times = [
                        fill_start + (index / max(milestone_count - 1, 1)) * fill_duration
                        for index in range(milestone_count)
                    ]
                elif milestone_count:
                    # Fill missing anchors by even steps between known neighbors.
                    fill_lead = 0.45
                    min_fill = 1.2
                    available = max(min_fill, duration - fill_lead - video_out)
                    if available < min_fill + hold_after_fill:
                        hold_after_fill = max(1.5, available - min_fill)
                    fill_duration = max(min_fill, duration - fill_lead - hold_after_fill - video_out)
                    fill_start = start + fill_lead
                    fallback = [
                        fill_start + (index / max(milestone_count - 1, 1)) * fill_duration
                        for index in range(milestone_count)
                    ]
                    milestone_times = [
                        raw if raw is not None else fallback[index]
                        for index, raw in enumerate(raw_times)
                    ]
                    # Monotonic + room after dock.
                    milestone_times[0] = max(milestone_times[0], start + 0.35)
                    for index in range(1, milestone_count):
                        milestone_times[index] = max(
                            milestone_times[index],
                            milestone_times[index - 1] + 0.2,
                        )
                    # Keep last stop before restore/exit.
                    last_cap = start + duration - video_out - 0.35
                    if milestone_times[-1] > last_cap and milestone_count > 1:
                        budget = max(0.6, last_cap - milestone_times[0])
                        step = budget / max(milestone_count - 1, 1)
                        milestone_times = [
                            milestone_times[0] + index * step for index in range(milestone_count)
                        ]

                fill_end = (
                    milestone_times[-1]
                    if milestone_times
                    else start + max(1.2, duration * 0.5)
                )
                restore_at = min(start + duration - video_out, fill_end + hold_after_fill)
                restore_at = max(restore_at, fill_end + 0.4)

                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:{video_scale:.4f},'
                    f'x:{width * video_x:.2f},y:{height * video_y:.2f},'
                    f'duration:{video_in:.3f},ease:"power3.inOut"}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("#{element_id} .scale-fill", {{scaleX:0}}, {start:.4f});'
                )
                if milestone_count:
                    # Opacity only — never animate transform/y (inline left/translateX
                    # places each stop on the bar fraction the fill reaches).
                    timeline_lines.append(
                        f'tl.set("#{element_id} .scale-milestone", {{opacity:0}}, {start:.4f});'
                    )
                    prev_t = start + 0.2
                    prev_frac = 0.0
                    for index in range(milestone_count):
                        frac = (
                            index / max(milestone_count - 1, 1)
                            if milestone_count > 1
                            else 1.0
                        )
                        appear_at = milestone_times[index]
                        seg = max(0.05, appear_at - prev_t)
                        # Grow the bar to this stop by the stop's reveal time.
                        timeline_lines.append(
                            f'tl.to("#{element_id} .scale-fill", '
                            f'{{scaleX:{frac:.4f},duration:{seg:.3f},ease:"none"}}, '
                            f'{prev_t:.4f});'
                        )
                        timeline_lines.append(
                            f'tl.fromTo("#{element_id} .scale-milestone[data-milestone-index=\\"{index}\\"]", '
                            f'{{opacity:0}}, '
                            f'{{opacity:1,duration:0.18,ease:"power2.out",immediateRender:false}}, '
                            f'{appear_at:.4f});'
                        )
                        prev_t = appear_at
                        prev_frac = frac
                    # Ensure we end fully filled if last stop is not at 1.0 (single stop).
                    if prev_frac < 0.999:
                        timeline_lines.append(
                            f'tl.to("#{element_id} .scale-fill", '
                            f'{{scaleX:1,duration:0.2,ease:"none"}}, {prev_t:.4f});'
                        )
                else:
                    # No stops — still grow the bar once over the mid-cue.
                    fill_duration = max(1.0, duration - 0.45 - hold_after_fill - video_out)
                    timeline_lines.append(
                        f'tl.fromTo("#{element_id} .scale-fill", {{scaleX:0}}, '
                        f'{{scaleX:1,duration:{fill_duration:.3f},ease:"none"}}, '
                        f'{(start + 0.45):.4f});'
                    )
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:{video_out:.3f},ease:"power3.inOut"}}, '
                    f'{restore_at:.4f});'
                )
            elif module_id == "source-punch-zoom":
                # One camera engine, three paths (placement picks path; default in-out):
                #   in     — full → tight at zoomInFrame, hold tight for the cue
                #   out    — start tight → full at zoomOutFrame
                #   in-out — full → tight at zoomInFrame → hold → full at zoomOutFrame
                # zoomInFrame / zoomOutFrame are absolute locked-cut frames (when the
                # move *starts*). Missing values fall back to cue start / near cue end.
                focus_x = _number(params.get("focusX"), 0.5, 0, 1) * 100
                focus_y = _number(params.get("focusY"), 0.5, 0, 1) * 100
                zoom = _number(params.get("zoom"), 1.25, 1.02, MAX_PUNCH_ZOOM)
                settle = _number(params.get("settleSec"), 0.6, 0.2, max(0.3, duration / 2))
                motion = str(params.get("motion") or "in-out").strip().lower().replace("_", "-")
                if motion not in {"in", "out", "in-out"}:
                    motion = "in-out"
                origin = f'"{focus_x:.2f}% {focus_y:.2f}%"'
                # Keep settle from eating the whole cue when short.
                settle = min(settle, max(0.2, duration * 0.45))
                cue_end = start + duration
                fps_local = max(1.0, float(fps))

                def _punch_frame_local(raw: object, *, default_local: float) -> float:
                    if raw is None or raw == "":
                        return default_local
                    try:
                        frame_abs = float(raw)
                    except (TypeError, ValueError):
                        return default_local
                    # Absolute frame → composition-local seconds.
                    local = frame_abs / fps_local - range_start
                    return max(start, min(cue_end - 0.05, local))

                default_out_local = max(start + settle, cue_end - settle)
                zoom_in_at = _punch_frame_local(params.get("zoomInFrame"), default_local=start)
                zoom_out_at = _punch_frame_local(
                    params.get("zoomOutFrame"),
                    default_local=default_out_local,
                )
                # Ensure room for the settle tween and a sensible order.
                zoom_in_at = min(zoom_in_at, cue_end - settle - 0.05)
                zoom_in_at = max(start, zoom_in_at)
                zoom_out_at = max(zoom_out_at, zoom_in_at + settle)
                zoom_out_at = min(zoom_out_at, cue_end - settle)
                if zoom_out_at < zoom_in_at + settle:
                    zoom_out_at = min(cue_end - settle, zoom_in_at + settle)

                if motion == "in":
                    timeline_lines.append(
                        f'tl.to("#main-video", {{scale:{zoom:.4f},transformOrigin:{origin},'
                        f'duration:{settle:.3f},ease:"power2.inOut"}}, {zoom_in_at:.4f});'
                    )
                    # Hold tight for the rest of the cue; clean reset after so the next cue starts full.
                    timeline_lines.append(
                        f'tl.set("#main-video", {{scale:1,transformOrigin:{origin}}}, '
                        f'{cue_end:.4f});'
                    )
                elif motion == "out":
                    timeline_lines.append(
                        f'tl.set("#main-video", {{scale:{zoom:.4f},transformOrigin:{origin}}}, {start:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("#main-video", {{scale:1,transformOrigin:{origin},'
                        f'duration:{settle:.3f},ease:"power2.inOut"}}, {zoom_out_at:.4f});'
                    )
                else:  # in-out
                    timeline_lines.append(
                        f'tl.to("#main-video", {{scale:{zoom:.4f},transformOrigin:{origin},'
                        f'duration:{settle:.3f},ease:"power2.inOut"}}, {zoom_in_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("#main-video", {{scale:1,transformOrigin:{origin},'
                        f'duration:{settle:.3f},ease:"power2.inOut"}}, {zoom_out_at:.4f});'
                    )
            elif module_id == "problem-card-triptych":
                # Sequence:
                #   1) each card enters pink as the “active” point at its revealFrame
                #   2) previous card settles white when the next appears
                #   3) after the last card enters, it settles white (settle shrinks if needed)
                #   4) all-white linger, then exit
                # Placement contract: never even-redistribute over craft frames.
                settle_after_last_sec = 2.0
                linger_all_white_sec = 2.0
                pink = "#ff00ce"
                white_bg = "#fbfbfd"
                ink = "#1a1a2e"
                teal = "#007c7d"
                cards = _strings(params.get("cards"), 3)
                card_count = len(cards)
                card_stagger = (
                    float(sample_reveal_stagger_sec)
                    if sample_reveal_stagger_sec is not None and sample_reveal_stagger_sec > 0
                    else 0.85
                )
                card_stagger = max(0.35, min(2.0, card_stagger))
                card_times: list[float] = []
                anchored_count = 0
                for index in range(card_count):
                    path = f"parameters.cards.{index}"
                    match = next(
                        (
                            item
                            for item in cue.get("semanticItems", [])
                            if str(item.get("parameterPath") or "") == path
                        ),
                        None,
                    )
                    if match is not None:
                        try:
                            spoken = float(match.get("spokenStartSec") or 0.0)
                        except (TypeError, ValueError):
                            spoken = 0.0
                        appear_at = max(spoken, range_start) - range_start
                        # Honor placement frame; only keep after a brief stage settle.
                        card_times.append(max(start + 0.12, appear_at))
                        anchored_count += 1
                    else:
                        card_times.append(start + 0.28 + index * card_stagger)
                # Monotonic order — small gap when placement-driven so tight frames stay close.
                min_gap = 0.08 if anchored_count > 0 else 0.35
                for index in range(1, len(card_times)):
                    card_times[index] = max(card_times[index], card_times[index - 1] + min_gap)
                if card_times and anchored_count == 0 and card_count > 1:
                    # Library / unanchored samples only: compress evenly if settle won't fit.
                    latest_need = (
                        card_times[-1]
                        + settle_after_last_sec
                        + linger_all_white_sec
                        + exit_duration
                    )
                    if latest_need > start + duration:
                        budget = max(
                            0.8,
                            duration
                            - exit_duration
                            - settle_after_last_sec
                            - linger_all_white_sec
                            - 0.28,
                        )
                        step = budget / max(card_count - 1, 1)
                        card_times = [start + 0.28 + index * step for index in range(card_count)]
                elif card_times and anchored_count > 0:
                    # Placement path: keep card frames; shrink pink-settle / linger to fit.
                    room_after = max(
                        0.4,
                        (start + duration - exit_duration) - card_times[-1],
                    )
                    settle_after_last_sec = min(
                        settle_after_last_sec, max(0.3, room_after * 0.45)
                    )
                    linger_all_white_sec = min(
                        linger_all_white_sec,
                        max(0.15, room_after - settle_after_last_sec - 0.05),
                    )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .pf-triptych", {{opacity:0,y:16}}, '
                    f'{{opacity:1,y:0,duration:0.4,ease:"power3.out"}}, {entry_start:.4f});'
                )
                if card_count:
                    timeline_lines.append(
                        f'tl.set("#{element_id} .pf-tri-card", {{opacity:0,y:18}}, {start:.4f});'
                    )
                for index in range(card_count):
                    appear_at = card_times[index]
                    card_sel = f'#{element_id} .pf-tri-card[data-card-index=\\"{index}\\"]'
                    timeline_lines.append(
                        f'tl.fromTo("{card_sel}", {{opacity:0,y:18}}, '
                        f'{{opacity:1,y:0,duration:0.34,ease:"power2.out",immediateRender:false}}, '
                        f'{appear_at:.4f});'
                    )
                    # Force copy visible (CSS zeros [data-semantic-path] until spoken/generic reveals).
                    timeline_lines.append(
                        f'tl.set("{card_sel} span", {{opacity:1}}, {appear_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("{card_sel}", {{backgroundColor:"{pink}",color:"#ffffff",'
                        f'duration:0.18,ease:"power1.out"}}, {appear_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("{card_sel} i, {card_sel} span", {{color:"#ffffff",duration:0.18}}, '
                        f'{appear_at:.4f});'
                    )
                    if index > 0:
                        prev_sel = f'#{element_id} .pf-tri-card[data-card-index=\\"{index - 1}\\"]'
                        timeline_lines.append(
                            f'tl.to("{prev_sel}", {{backgroundColor:"{white_bg}",color:"{ink}",'
                            f'duration:0.28,ease:"power1.out"}}, {appear_at:.4f});'
                        )
                        timeline_lines.append(
                            f'tl.to("{prev_sel} i", {{color:"{teal}",duration:0.28}}, {appear_at:.4f});'
                        )
                        timeline_lines.append(
                            f'tl.to("{prev_sel} span", {{color:"{ink}",duration:0.28}}, {appear_at:.4f});'
                        )
                if card_count:
                    last_sel = f'#{element_id} .pf-tri-card[data-card-index=\\"{card_count - 1}\\"]'
                    settle_at = card_times[-1] + settle_after_last_sec
                    # Keep settle before exit so the all-white linger is visible.
                    settle_at = min(
                        settle_at, start + duration - exit_duration - linger_all_white_sec
                    )
                    settle_at = max(settle_at, card_times[-1] + 0.25)
                    timeline_lines.append(
                        f'tl.to("{last_sel}", {{backgroundColor:"{white_bg}",color:"{ink}",'
                        f'duration:0.3,ease:"power1.out"}}, {settle_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("{last_sel} i", {{color:"{teal}",duration:0.3}}, {settle_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("{last_sel} span", {{color:"{ink}",duration:0.3}}, {settle_at:.4f});'
                    )
                timeline_lines.append(
                    f'tl.to("#{element_id} .pf-triptych", {{opacity:0,duration:0.28,ease:"power2.in"}}, '
                    f'{(start + duration - exit_duration):.4f});'
                )
                timeline_lines.append(
                    f'tl.set("#{element_id} .pf-triptych", {{opacity:0}}, {(start + duration):.4f});'
                )
            elif module_id == "windows-prompt-typing":
                # Head docks into the right tall frame (same geometry as dependency-stack).
                # Terminal fades in on the left; prompt characters type like a CLI while spoken.
                video_left, video_top = 0.50, 0.10
                video_w, video_h = 0.42, 0.78
                video_scale = max(video_w, video_h)
                face_center_x = 0.46
                video_x = (video_left + video_w / 2) - face_center_x * video_scale
                video_y = video_top
                video_in, video_out = 0.55, 0.45
                raw_prompt = str(params.get("prompt") or "").replace("\r\n", "\n").replace("\r", "\n")
                type_count = len(raw_prompt)
                # Readable CLI pace (~12–14 chars/sec). Speech window may be shorter;
                # never collapse a multi-char prompt into a flash.
                min_type_duration = max(1.2, type_count * 0.075) if type_count else 0.5
                type_start = start + 0.9
                type_end = start + duration - video_out - 0.45
                prompt_match = next(
                    (
                        item
                        for item in cue.get("semanticItems", [])
                        if str(item.get("parameterPath") or "") == "parameters.prompt"
                    ),
                    None,
                )
                if prompt_match is not None:
                    spoken = float(prompt_match.get("spokenStartSec") or 0.0)
                    fully = float(prompt_match.get("fullyVisibleSec") or spoken)
                    # Timeline is composition-local (0 = range_start), same as other engines.
                    type_start = max(start + 0.85, max(spoken, range_start) - range_start)
                    speech_end = max(fully, range_start) - range_start
                    # Prefer speech end when it actually covers typing; otherwise use min pace.
                    if speech_end >= type_start + min_type_duration * 0.85:
                        type_end = speech_end
                    else:
                        type_end = type_start + min_type_duration
                # Library samples / short cues: type at readable pace, then hold finished line.
                type_end = max(type_end, type_start + min_type_duration)
                type_end = min(type_end, start + duration - video_out - 0.35)
                if type_end <= type_start + 0.4 and type_count > 0:
                    type_start = start + 0.85
                    type_end = min(
                        start + duration - video_out - 0.35,
                        type_start + min_type_duration,
                    )
                type_duration = max(0.4, type_end - type_start)
                # Force typed shell visible (CSS zeros [data-semantic-path] until set).
                timeline_lines.append(
                    f'tl.set("#{element_id} .prompt-app, #{element_id} .prompt-typed, '
                    f'#{element_id} .prompt-typed-text, #{element_id} .prompt-prefix", '
                    f'{{opacity:1}}, {entry_start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("#{element_id} .prompt-typed-text", {{textContent:""}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:{video_scale:.4f},'
                    f'x:{width * video_x:.2f},y:{height * video_y:.2f},'
                    f'duration:{video_in:.3f},ease:"power3.inOut"}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .prompt-mask", {{opacity:0}}, '
                    f'{{opacity:1,duration:0.28,ease:"power2.out"}}, {entry_start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .prompt-terminal", {{opacity:0,y:18,scale:0.98}}, '
                    f'{{opacity:1,y:0,scale:1,duration:0.5,ease:"power3.out",'
                    f'transformOrigin:"left center",immediateRender:false}}, {(start + 0.2):.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .prompt-video-outline", {{opacity:0}}, '
                    f'{{opacity:1,duration:0.35,ease:"power2.out"}}, {(start + 0.15):.4f});'
                )
                if type_count > 0:
                    # Progressive textContent — seek-safe. Caret is ::after on this node
                    # so it rides the last glyph even when the string wraps to line 2+.
                    step = type_duration / type_count
                    for index in range(1, type_count + 1):
                        appear_at = type_start + (index - 1) * step
                        partial = json.dumps(raw_prompt[:index])
                        timeline_lines.append(
                            f'tl.set("#{element_id} .prompt-typed-text", '
                            f'{{textContent:{partial}}}, {appear_at:.4f});'
                        )
                restore_at = start + duration - video_out
                exit_d = 0.28
                timeline_lines.append(
                    f'tl.to("#{element_id} .prompt-stage > *", {{opacity:0,duration:{exit_d:.3f},'
                    f'ease:"power2.in"}}, {(start + duration - exit_d):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:{video_out:.3f},'
                    f'ease:"power3.inOut"}}, {restore_at:.4f});'
                )
            elif module_id == "brand-cta-lockup":
                # Community CTA stage:
                # full white stage, teal band wipe, logo + join line + URL pill,
                # talking head cover-scaled into the right tall frame.
                # Frame matches .community-video-outline / .community-mask (58.85%/10.2%/35.9%/78.7%).
                video_left, video_top = 0.5885, 0.1019
                video_w, video_h = 0.3594, 0.7870
                video_scale = max(video_w, video_h)
                face_center_x = 0.47
                video_x = (video_left + video_w / 2) - face_center_x * video_scale
                video_y = video_top
                video_in, video_out = 0.55, 0.4
                exit_d = 0.28
                timeline_lines.append(
                    f'tl.set("#{element_id} [data-semantic-path]", {{opacity:1}}, {entry_start:.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:{video_scale:.4f},'
                    f'x:{width * video_x:.2f},y:{height * video_y:.2f},'
                    f'duration:{video_in:.3f},ease:"power3.inOut"}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .community-mask", {{opacity:0}}, '
                    f'{{opacity:1,duration:0.25,ease:"power2.out"}}, {entry_start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .community-band", '
                    f'{{scaleX:0,opacity:1}}, '
                    f'{{scaleX:1,opacity:1,duration:0.72,ease:"power4.out",'
                    f'transformOrigin:"left center",immediateRender:false}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .community-logo", {{x:-70,opacity:0}}, '
                    f'{{x:0,opacity:1,duration:0.55,ease:"expo.out",immediateRender:false}}, '
                    f'{(start + 0.2):.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .community-copy", {{y:58,opacity:0}}, '
                    f'{{y:0,opacity:1,duration:0.58,ease:"back.out(1.35)",immediateRender:false}}, '
                    f'{(start + 0.55):.4f});'
                )
                # URL lands mid-cue (matches 7-20 spoken "link" beat when present).
                url_at = start + min(5.6, max(1.4, duration * 0.35))
                url_match = next(
                    (
                        item
                        for item in cue.get("semanticItems", [])
                        if str(item.get("parameterPath") or "") == "parameters.destination"
                    ),
                    None,
                )
                if url_match is not None:
                    spoken = float(url_match.get("spokenStartSec") or 0.0)
                    url_at = max(start + 1.0, max(spoken, range_start) - range_start)
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .community-url", {{scale:0.65,opacity:0}}, '
                    f'{{scale:1,opacity:1,duration:0.42,ease:"back.out(1.9)",'
                    f'transformOrigin:"left center",immediateRender:false}}, {url_at:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("#{element_id} .community-video-outline", {{opacity:0}}, '
                    f'{{opacity:1,duration:0.35,ease:"power2.out"}}, {(start + 0.15):.4f});'
                )
                restore_at = start + duration - video_out
                timeline_lines.append(
                    f'tl.to("#{element_id} .community-stage > *", {{opacity:0,duration:{exit_d:.3f},'
                    f'ease:"power2.in"}}, {(start + duration - exit_d):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#main-video", {{scale:1,x:0,y:0,duration:{video_out:.3f},'
                    f'ease:"power3.inOut"}}, {restore_at:.4f});'
                )
            elif module_id == "robot-rocket-sign":
                # Soft CTA gag (L→R), slightly slower for readability:
                #   1) blast in fast to ~1/3
                #   2) misfire: black puffs + slow crawl; face → confused
                #   3) linger confused ~1s mid-screen
                #   4) couple of fist smacks on the hull
                #   5) face → shocked, full-force exit off the right
                rig = f'#{element_id} .rocket-rig'
                smoke = f'#{element_id} .rocket-smoke'
                flame = f'#{element_id} .rocket-flame'
                fist = f'#{element_id} .rocket-fist'
                face_n = f'#{element_id} .rocket-face-normal'
                face_c = f'#{element_id} .rocket-face-confused'
                face_s = f'#{element_id} .rocket-face-shocked'
                # Pixel flight path (GSAP x is not % of stage). Larger rig → start farther off-left.
                x_start = -0.42 * width
                x_third = 0.12 * width
                x_mid = 0.32 * width
                x_end = 1.20 * width
                y_lane = 0.04 * height  # shifted up
                # Ideal gag clock (seconds from cue start) — slower than first pass.
                t_fast_end = 0.55
                t_misfire_end = 1.85
                t_confused_end = 2.95  # ~1.1s confused linger
                t_pound_end = 3.85     # a couple of smacks
                t_exit_end = 4.65
                ideal_total = t_exit_end
                scale = min(1.0, max(0.55, (duration - 0.05) / ideal_total)) if duration < ideal_total else 1.0

                def _t(sec: float) -> float:
                    return start + sec * scale

                timeline_lines.append(
                    f'tl.set("#{element_id} [data-semantic-path]", {{opacity:1}}, {entry_start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{rig}", {{x:{x_start:.1f},y:{y_lane:.1f},opacity:1,rotation:-6}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{smoke}", {{opacity:0}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{face_n}", {{opacity:1}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{face_c}, {face_s}", {{opacity:0}}, {start:.4f});'
                )
                # 1) Fast entry to 1/3
                timeline_lines.append(
                    f'tl.to("{rig}", {{x:{x_third:.1f},rotation:-3,duration:{0.55 * scale:.3f},'
                    f'ease:"power3.out"}}, {_t(0):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{flame}", {{scale:1.15,transformOrigin:"100% 50%",duration:0.14,'
                    f'repeat:3,yoyo:true,ease:"sine.inOut"}}, {_t(0):.4f});'
                )
                # 2) Misfire: puffs + slow to middle + confused face
                timeline_lines.append(
                    f'tl.to("{smoke}", {{opacity:1,duration:0.14,ease:"power1.out"}}, {_t(t_fast_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{face_n}", {{opacity:0}}, {_t(t_fast_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{face_c}", {{opacity:1}}, {_t(t_fast_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#{element_id} .rocket-puff-a", {{x:-18,y:10,scale:1.35,opacity:0.35,'
                    f'duration:{1.15 * scale:.3f},ease:"power1.out"}}, {_t(t_fast_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#{element_id} .rocket-puff-b", {{x:-28,y:16,scale:1.5,opacity:0.25,'
                    f'duration:{1.2 * scale:.3f},ease:"power1.out"}}, {_t(t_fast_end + 0.1):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("#{element_id} .rocket-puff-c", {{x:-22,y:22,scale:1.4,opacity:0.2,'
                    f'duration:{1.25 * scale:.3f},ease:"power1.out"}}, {_t(t_fast_end + 0.16):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{flame}", {{scale:0.5,opacity:0.4,duration:{0.4 * scale:.3f},'
                    f'ease:"power2.inOut"}}, {_t(t_fast_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{rig}", {{x:{x_mid:.1f},rotation:4,'
                    f'duration:{(t_misfire_end - t_fast_end) * scale:.3f},'
                    f'ease:"power1.inOut"}}, {_t(t_fast_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{rig}", {{y:"+=12",duration:0.14,repeat:7,yoyo:true,ease:"sine.inOut"}}, '
                    f'{_t(t_fast_end):.4f});'
                )
                # 3) Confused linger mid-screen
                timeline_lines.append(
                    f'tl.to("{rig}", {{x:{x_mid:.1f},rotation:2,'
                    f'duration:{(t_confused_end - t_misfire_end) * scale:.3f},'
                    f'ease:"none"}}, {_t(t_misfire_end):.4f});'
                )
                # 4) A couple of solid smacks (fist is at arm end; pivot at shoulder)
                timeline_lines.append(
                    f'tl.to("{fist}", {{rotation:42,transformOrigin:"50% 0%",'
                    f'duration:0.12,repeat:3,yoyo:true,ease:"power2.inOut"}}, '
                    f'{_t(t_confused_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{rig}", {{x:"+=10",rotation:7,duration:0.1,repeat:3,yoyo:true,'
                    f'ease:"power1.inOut"}}, {_t(t_confused_end + 0.02):.4f});'
                )
                # 5) Shocked face + full force blast off right
                timeline_lines.append(
                    f'tl.set("{face_c}", {{opacity:0}}, {_t(t_pound_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{face_s}", {{opacity:1}}, {_t(t_pound_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{smoke}", {{opacity:0,duration:0.14}}, {_t(t_pound_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{flame}", {{scale:1.95,opacity:1,duration:0.2,ease:"power2.out"}}, '
                    f'{_t(t_pound_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{rig}", {{x:{x_end:.1f},y:{(y_lane - 0.03 * height):.1f},rotation:-12,'
                    f'duration:{(t_exit_end - t_pound_end) * scale:.3f},ease:"power3.in"}}, '
                    f'{_t(t_pound_end):.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{rig}", {{opacity:0}}, {_t(t_exit_end):.4f});'
                )
            elif module_id in ROBOT_MODULE_IDS:
                # Recovered mascot motion: wrap enters, bubble pops, robot loops bounce.
                # Hard cap: at most ROBOT_HOLD_AFTER_DRAWN_SEC after fully drawn, then exit
                # (even if the placement cue is longer). Shorter cues still exit at cue end.
                exit_d = 0.28
                if module_id == "robot-roast":
                    drawn_at = start + 0.35 + 0.5  # bubble land
                    bounce_at = start + 0.85
                    bounce_period = 0.5
                else:
                    drawn_at = start + 0.28 + 0.45  # bubble land
                    bounce_at = start + 0.65
                    bounce_period = 0.42 if module_id == "robot-cheer" else 0.4
                hold_end = drawn_at + ROBOT_HOLD_AFTER_DRAWN_SEC
                exit_at = min(start + duration - exit_d, hold_end)
                exit_at = max(exit_at, drawn_at + 0.35)
                hold = max(0.35, exit_at - bounce_at)
                bounce_repeats = max(1, int(hold / bounce_period))
                wrap = f'#{element_id} .robot-wrap'
                bubble = f'#{element_id} .robot-bubble'
                body = f'#{element_id} .robot-body'
                timeline_lines.append(
                    f'tl.set("#{element_id} [data-semantic-path]", {{opacity:1}}, {entry_start:.4f});'
                )
                if module_id == "robot-roast":
                    timeline_lines.append(
                        f'tl.fromTo("{wrap}", {{x:90,opacity:0}}, '
                        f'{{x:0,opacity:1,duration:0.55,ease:"power3.out"}}, {entry_start:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.fromTo("{bubble}", {{scale:0,opacity:0}}, '
                        f'{{scale:1,opacity:1,duration:0.5,ease:"back.out(1.8)",'
                        f'transformOrigin:"60% 100%",immediateRender:false}}, {(start + 0.35):.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("{body}", {{y:"-=16",duration:0.5,repeat:{bounce_repeats},'
                        f'yoyo:true,ease:"sine.inOut"}}, {bounce_at:.4f});'
                    )
                    point_reps = max(1, int(hold / 0.4))
                    timeline_lines.append(
                        f'tl.to("#{element_id} .robot-point", {{rotation:-13,svgOrigin:"216 400",'
                        f'duration:0.4,repeat:{point_reps},yoyo:true,ease:"sine.inOut"}}, '
                        f'{bounce_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.to("{bubble}", {{rotation:2.5,transformOrigin:"60% 100%",'
                        f'duration:0.55,repeat:{max(1, bounce_repeats - 1)},yoyo:true,'
                        f'ease:"sine.inOut"}}, {(bounce_at + 0.1):.4f});'
                    )
                else:
                    timeline_lines.append(
                        f'tl.fromTo("{wrap}", {{y:60,opacity:0}}, '
                        f'{{y:0,opacity:1,duration:0.5,ease:"power3.out"}}, {entry_start:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.fromTo("{bubble}", {{scale:0,opacity:0}}, '
                        f'{{scale:1,opacity:1,duration:0.45,ease:"back.out(1.9)",'
                        f'transformOrigin:"20% 100%",immediateRender:false}}, {(start + 0.28):.4f});'
                    )
                    if module_id == "robot-cheer":
                        timeline_lines.append(
                            f'tl.to("{body}", {{y:"-=18",duration:0.42,repeat:{bounce_repeats},'
                            f'yoyo:true,ease:"sine.inOut"}}, {bounce_at:.4f});'
                        )
                        timeline_lines.append(
                            f'tl.to("{bubble}", {{scale:1.04,transformOrigin:"20% 100%",'
                            f'duration:0.42,repeat:{bounce_repeats},yoyo:true,ease:"sine.inOut"}}, '
                            f'{bounce_at:.4f});'
                        )
                    else:
                        # robot-defiant: body bounce + fist pump + bubble wiggle
                        timeline_lines.append(
                            f'tl.to("{body}", {{y:"-=12",duration:0.4,repeat:{bounce_repeats},'
                            f'yoyo:true,ease:"sine.inOut"}}, {bounce_at:.4f});'
                        )
                        fist_reps = max(2, int(hold / 0.3))
                        timeline_lines.append(
                            f'tl.to("#{element_id} .robot-fist", {{y:"-=24",duration:0.3,'
                            f'repeat:{fist_reps},yoyo:true,ease:"power1.inOut"}}, '
                            f'{bounce_at:.4f});'
                        )
                        timeline_lines.append(
                            f'tl.to("{bubble}", {{rotation:-2.5,transformOrigin:"20% 100%",'
                            f'duration:0.4,repeat:{bounce_repeats},yoyo:true,ease:"sine.inOut"}}, '
                            f'{bounce_at:.4f});'
                        )
                timeline_lines.append(
                    f'tl.to("{wrap}", {{opacity:0,duration:{exit_d:.3f},ease:"power2.in"}}, '
                    f'{exit_at:.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{wrap}", {{opacity:0}}, {(exit_at + exit_d):.4f});'
                )
            elif module_id == "kinetic-word-punctuation":
                # Magenta stamp: pink box + phrase land together at phrase revealFrame.
                # Previously the shell entered at beat start while [data-semantic-path]
                # kept the words at opacity 0 until semantic reveal — empty pink box.
                phrase_at = start
                for item in cue.get("semanticItems") or []:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("parameterPath") or "") != "parameters.phrase":
                        continue
                    try:
                        spoken = float(item.get("spokenStartSec") or 0.0)
                    except (TypeError, ValueError):
                        spoken = 0.0
                    phrase_at = max(spoken, range_start) - range_start
                    break
                phrase_at = max(start, min(start + max(duration - 0.05, 0.0), phrase_at))
                drift = 44 if str(params.get("side")) == "right" else -44
                phrase_sel = f'#{element_id} [data-semantic-path="parameters.phrase"]'
                stamp_sel = f"#{element_id} .pf-kinetic"
                # Words are opaque inside the stamp; the stamp is the only reveal surface.
                timeline_lines.append(
                    f"tl.set('{phrase_sel}', {{opacity:1,y:0}}, {start:.4f});"
                )
                timeline_lines.append(
                    f'tl.set("{stamp_sel}", {{opacity:0}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("{stamp_sel}", {{opacity:0,x:{drift},scale:0.97}}, '
                    f'{{opacity:1,x:0,scale:1,duration:0.44,ease:"power3.out",'
                    f'immediateRender:false}}, {phrase_at:.4f});'
                )
                exit_at = start + duration - 0.28
                if duration > 0.5:
                    timeline_lines.append(
                        f'tl.to("{stamp_sel}", {{opacity:0,duration:0.28,ease:"power2.in"}}, '
                        f'{exit_at:.4f});'
                    )
                    timeline_lines.append(
                        f'tl.set("{stamp_sel}", {{opacity:0}}, {(start + duration):.4f});'
                    )
            elif module_id == "tradeoff-meter":
                # Fixed knob at value; fill grows toward it and arrives at verdict reveal.
                # Fill uses scaleX → value (not 1.0). Linear ease; fill_end == verdict_at.
                value_frac = _number(params.get("value"), 0.5, 0, 1)
                drift = 44 if str(params.get("side")) == "right" else -44
                latest = start + duration - exit_duration - 0.05

                def _tradeoff_spoken(path: str) -> float | None:
                    match = next(
                        (
                            item
                            for item in cue.get("semanticItems", [])
                            if str(item.get("parameterPath") or "") == path
                        ),
                        None,
                    )
                    if match is None:
                        return None
                    try:
                        spoken = float(match.get("spokenStartSec") or 0.0)
                    except (TypeError, ValueError):
                        spoken = 0.0
                    return max(spoken, range_start) - range_start

                left_at = _tradeoff_spoken("parameters.leftLabel")
                right_at = _tradeoff_spoken("parameters.rightLabel")
                verdict_at = _tradeoff_spoken("parameters.verdict")
                if verdict_at is None:
                    verdict_at = start + max(0.8, duration * 0.55)
                fill_end = max(start + 0.35, min(latest, verdict_at))
                # Prefer starting after labels; always finish exactly at fill_end.
                label_ready = start + 0.25
                for t in (left_at, right_at):
                    if t is not None:
                        label_ready = max(label_ready, t + 0.12)
                earliest = start + 0.12
                preferred = max(earliest, label_ready)
                if fill_end - preferred >= 0.35:
                    fill_start = preferred
                else:
                    fill_start = max(earliest, fill_end - min(2.5, max(0.35, fill_end - earliest)))
                fill_dur = max(0.05, min(2.5, fill_end - fill_start))
                fill_start = fill_end - fill_dur  # hard lock: end == verdict

                card_sel = f"#{element_id} .pf-card"
                fill_sel = f"#{element_id} .pf-meter-fill"
                timeline_lines.append(
                    f'tl.fromTo("{card_sel}", {{opacity:0,x:{drift},scale:0.97}}, '
                    f'{{opacity:1,x:0,scale:1,duration:0.44,ease:"power3.out"}}, '
                    f'{entry_start:.4f});'
                )
                # Labels + verdict: generic semantic path (not in skip_semantic).
                # Knob is static in markup at value%; only fill animates.
                timeline_lines.append(
                    f'tl.set("{fill_sel}", {{scaleX:0,transformOrigin:"left center"}}, {start:.4f});'
                )
                timeline_lines.append(
                    f'tl.fromTo("{fill_sel}", {{scaleX:0,transformOrigin:"left center"}}, '
                    f'{{scaleX:{value_frac:.4f},duration:{fill_dur:.3f},ease:"none",'
                    f'immediateRender:false}}, {fill_start:.4f});'
                )
                timeline_lines.append(
                    f'tl.to("{card_sel}", {{opacity:0,duration:0.28,ease:"power2.in"}}, '
                    f'{(start + duration - 0.28):.4f});'
                )
                timeline_lines.append(
                    f'tl.set("{card_sel}", {{opacity:0}}, {(start + duration):.4f});'
                )
            elif module_id in PORTED_MODULE_IDS and module_id not in {
                "brand-cta-lockup",
                "windows-prompt-typing",
                "kinetic-word-punctuation",  # stamp timing owned above
                "speaker-rise-callouts",  # thesis + callouts own placement timing above
                "tradeoff-meter",  # meter fill owned above (syncs to verdict frame)
            }:
                shell = ".pf-card, #%s .pf-triptych, #%s .pf-window, #%s .pf-sunrise" % ((element_id,) * 3)
                kids = (".pf-path-row, #%s .pf-pin-row, "
                        "#%s .pf-payoff, #%s .pf-verdict, #%s .pf-final-action") % ((element_id,) * 4)
                drift = 44 if str(params.get("side")) == "right" else -44
                # Production default ~0.1s. Library samples slow this and also stagger semantic
                # anchors (~1s); skip the group kids tween in sample mode so it does not fight
                # per-item semantic reveals on the same nodes.
                sample_mode = sample_reveal_stagger_sec is not None and sample_reveal_stagger_sec > 0
                kid_stagger = max(0.05, min(2.0, float(sample_reveal_stagger_sec))) if sample_mode else 0.1
                timeline_lines.append(f'tl.fromTo("#{element_id} {shell}", {{opacity:0,x:{drift},scale:0.97}}, {{opacity:1,x:0,scale:1,duration:0.44,ease:"power3.out"}}, {entry_start:.4f});')
                if not sample_mode:
                    timeline_lines.append(f'tl.fromTo("#{element_id} {kids}", {{opacity:0,y:18}}, {{opacity:1,y:0,duration:0.35,stagger:{kid_stagger:.3f},ease:"power2.out"}}, {(start + .24):.4f});')
                timeline_lines.append(f'tl.to("#{element_id} {shell}", {{opacity:0,duration:0.28,ease:"power2.in"}}, {(start + duration - 0.28):.4f});')
                timeline_lines.append(f'tl.set("#{element_id} {shell}", {{opacity:0}}, {(start + duration):.4f});')
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
    source_audio_markup = (
        f'<audio id="main-audio" src="source.mp4" data-start="0" data-duration="{render_duration:.4f}" data-track-index="10" data-volume="1"></audio>'
        if include_source_audio
        else ""
    )
    index_html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><style>
{font_faces}
:root{{--white:#fff;--paper:#fbfbfd;--ink:#1a1a2e;--body:#4a4a5a;--line:#dedee6;--magenta:#ff00ce;--magenta-deep:#c700a1;--magenta-tint:#fff0fb;--teal:#007c7d;--teal-tint:#e6f5f5;}}
.cue-motion{{position:absolute;inset:0;width:100%;height:100%;}}
{runtime_css}
.pf-step-no-num{{padding-top:38px}}.pf-step-no-num .pf-step-title{{margin-top:0}}.pf-community{{top:7.2%;width:33.85%;min-height:48.15%;padding:46px;text-align:left;border-width:4px;box-shadow:18px 20px 0 rgba(0,124,125,.3)}}.pf-community::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:22px;background:var(--teal)}}.pf-logo-image{{display:block;width:min(330px,82%);height:110px;object-fit:contain;object-position:left center}}.pf-community .pf-action{{margin-top:44px;font-size:43px}}.pf-community .pf-dest{{font-size:18px}}
.callout-align-right.callout-below{{transform:translate(-100%,14px)}}.callout-align-right.callout-above{{transform:translate(-100%,calc(-100% - 14px))}}
</style></head><body><div id="root" data-composition-id="vcg-visual-plan" data-start="0" data-width="{width}" data-height="{height}" data-duration="{render_duration:.4f}" data-fps="{fps}"><div class="base"></div><video id="main-video" class="clip" src="source.mp4" muted playsinline data-start="0" data-duration="{render_duration:.4f}" data-track-index="0"></video>{source_audio_markup}{''.join(clip_markup)}{''.join(audio_markup)}<script src="vendor/gsap.min.js"></script><script>(function(){{window.__timelines=window.__timelines||{{}};var tl=gsap.timeline({{paused:true}});{''.join(timeline_lines)}window.__timelines["vcg-visual-plan"]=tl;}})();</script></div></body></html>'''
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
