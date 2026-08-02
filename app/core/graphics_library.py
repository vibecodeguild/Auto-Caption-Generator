"""Private Graphics Library — usages (when/where) + engine samples.

Public product code only. Catalog content and sample media live outside the Git
checkout under a user-configured private root (default: Creator Library sibling).

Authority (see docs/vcg-graphics-process/architecture.md):
  - Usage = library entry (when/where, status, sample/poster). Has-a engineId.
  - Engine = sole draw implementation (MODULE_IDS / visual_production).
  - Placement / assignment = later episode work.
  - Seed kit / treatment menus = destroyed as production selection/draw paths.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.editorial_beats import BEAT_TYPES
from app.core.file_utils import is_within, sha256_file, slug
from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe
from app.core.process_utils import hidden_subprocess_flags
from app.core.settings import project_root
from app.core.story_assets import default_creator_library, treatment_library_path
from app.core.visual_production import (
    MODULE_IDS,
    MODULE_PARAMETER_KEYS,
    build_hyperframes_composition,
    probe_visual_source,
    remux_locked_audio,
    validate_visual_plan,
)

# Private folder holding one recorded OBS layout clip per layout id (full frame).
LAYOUT_CLIPS_DIRNAME = "layout-clips"

LIBRARY_SCHEMA_VERSION = 1
GOLDEN_RECORD_VERSION = LIBRARY_SCHEMA_VERSION  # legacy alias
INDEX_FILENAME = "graphics-library.json"
LEGACY_INDEX_FILENAME = "golden-record.json"
# Flat workflow: design as candidate → promote to golden. No reject/approved clutter.
STATUSES = frozenset({"candidate", "golden"})
DEMO_BEDS = frozenset({"talking-head", "screen-share", "either"})
REUSE_POLICIES = frozenset({"repeat-safe", "limited", "intentional-series", "once"})

# Product-owned usage fields (when/where + proof + engine reference).
USAGE_STORED_KEYS = frozenset(
    {
        "id",
        "displayName",
        "status",
        "engineId",
        "allowedLayouts",
        "beatTypes",
        "sample",
        "createdAt",
        "updatedAt",
    }
)
# End-pass scrub: drop from private JSON on load/save (noise / dual contracts).
USAGE_SCRUB_KEYS = frozenset(
    {
        "buildable",
        "demoBed",
        "reusePolicy",
        "purpose",
        "parameters",
        "implementationId",
        "family",
        "visualFamily",
        "contentCapacity",
        "motionProfile",
        "tags",
        "lockedDefault",
        "preferredIntents",
        "intents",
        "rating",
        "notes",
        "history",
        "supersededBy",
    }
)
# Display order matches docs/vcg-graphics-process/beat-universe.md
BEAT_TYPE_ORDER: tuple[str, ...] = (
    "hook",
    "setup",
    "punchline",
    "aftershock",
    "callback",
    "proof",
    "context",
    "cta",
    "example",
    "prompt",
    "list",
    "structure",
    "ui",
)
assert set(BEAT_TYPE_ORDER) == set(BEAT_TYPES)
ALLOWED_LAYOUT_IDS = frozenset(
    {
        "full-screen-talking",
        "talking-left",
        "talking-right",
        "talking-bottom-left",
        "talking-bottom-right",
        "talking-top-left",
        "talking-top-right",
        "computer-screen-only",
    }
)
# Production policy: only creator-promoted golden graphics.
PRODUCTION_STATUS_POLICIES = frozenset({"golden-only"})
ProgressCallback = Callable[[int, str], None]


def normalize_status(status: Any) -> str:
    """Map legacy statuses onto candidate | golden."""

    value = str(status or "candidate").strip().lower()
    if value == "golden":
        return "golden"
    return "candidate"


def normalize_beat_types(value: Any) -> list[str]:
    """Closed VCG beat universe only; order stable; duplicates dropped."""

    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        beat = str(item or "").strip()
        if beat in BEAT_TYPES and beat not in cleaned:
            cleaned.append(beat)
    return sorted(cleaned, key=lambda beat: BEAT_TYPE_ORDER.index(beat))


def production_status_set(policy: str = "golden-only") -> frozenset[str]:
    """Which usage statuses are eligible for episode production selection."""

    if policy not in PRODUCTION_STATUS_POLICIES:
        raise ValueError(f"Unknown production status policy: {policy!r}")
    return frozenset({"golden"})


# Draw-interface keys that are cue/cook residue — not shown as engine content help.
_ENGINE_INTERFACE_HIDE = frozenset(
    {
        "approvalEvidence",
        "approvedTreatmentId",
        "candidateTreatmentIds",
        "editorialPurpose",
        "meaningfulChanges",
        "planningSuggestionId",
        "recipeId",
        "reviewLabel",
        "selectionRationale",
        "speakerSafety",
        "visualFamily",
        "opacity",
        "transitionIn",
        "transitionOut",
    }
)


def engine_interface_keys(engine_id: str) -> list[str]:
    """Content-facing draw keys for an engine (passthrough for library UI)."""

    allowed = MODULE_PARAMETER_KEYS.get(engine_id) or set()
    return sorted(key for key in allowed if key not in _ENGINE_INTERFACE_HIDE)


def resolve_engine_id(usage_or_engine_id: str, root: Path | None = None) -> str | None:
    """Resolve a usage id or engine id to a runtime engine id, or None."""

    key = str(usage_or_engine_id or "").strip()
    if not key:
        return None
    try:
        entry = _raw_entry(key, root)
        engine_id = str(entry.get("engineId") or entry.get("implementationId") or key).strip()
        if engine_id in MODULE_IDS:
            return engine_id
    except (OSError, ValueError, FileNotFoundError):
        pass
    return key if key in MODULE_IDS else None


# Engines that need screen UI visible to make sense as a demo.
SCREEN_SHARE_MODULE_IDS = frozenset(
    {
        "ui-callout",
        "source-punch-zoom",
        "windows-prompt-typing",
    }
)

# Demo copy is content-neutral product vocabulary for local samples only.
_DEMO_COPY: dict[str, dict[str, Any]] = {
    # 7-22 joke card: custom image + caption box (demo image staged in sample render).
    "punchline-reveal": {
        "kicker": "RARE MARKETING SKILL",
        "text": "WORD LAYOUT DARK ARTS",
        "imageAssetId": "demo-joke-image",
    },
    "speaker-side-panel": {
        "kicker": "SECTION",
        "text": "HOW DO YOU START?",
        "side": "left",
        "frameStyle": "hairline",
        "items": ["No secret course", "Build in public", "Ship weekly"],
    },
    "progress-scale": {
        "kicker": "PROGRESS",
        "text": "FROM ZERO TO SHIPPED",
        "startLabel": "IDEA",
        "targetLabel": "SHIPPED",
        "milestones": ["Brief", "Build", "Ship"],
    },
    "dependency-stack": {
        "text": "WHAT YOU NEED",
        "nodes": ["Transcript", "Locked cut", "Graphics kit"],
    },
    "numbered-example-card": {
        "kicker": "EXAMPLE",
        "exampleNumber": 1,
        "totalExamples": 10,
        "titleLines": ["TURN ROUGH NOTES", "INTO A CLEAR GUIDE"],
        "accentLineIndex": 0,
        "tags": ["GROK", "WORD"],
    },
    # Sample defaults: stronger/slower in-out arc so the full camera path is obvious.
    "source-punch-zoom": {
        "focusX": 0.42,
        "focusY": 0.38,
        "zoom": 1.45,
        "settleSec": 1.0,
        "motion": "in-out",
    },
    "ui-callout": {
        "label": "Click here",
        "detail": "Primary action",
        "targetBounds": {"x": 0.18, "y": 0.22, "width": 0.28, "height": 0.12},
        "pointer": "below",
    },
    "kinetic-word-punctuation": {
        "phrase": "JUST START",
        "anchor": "top",
        "side": "left",
    },
    "numbered-step-intro": {
        "stepNumber": 1,
        "title": "OPEN THE ADD-IN",
        "action": "DO THIS FIRST",
        "side": "left",
        "showNumber": True,
    },
    "problem-card-triptych": {
        "cards": ["Too slow", "Too generic", "Too risky"],
    },
    "speaker-rise-callouts": {
        "thesis": "YOU ALREADY HAVE THE SKILL",
        "callouts": ["Ship", "Teach", "Compound", "Build", "Learn", "Lead"],
        "accentCalloutIndex": 0,
    },
    "tradeoff-meter": {
        "kicker": "TRADEOFF",
        "leftLabel": "CONTROL",
        "rightLabel": "SPEED",
        "value": 0.62,
        "verdict": "Prefer speed with a golden kit",
        "side": "left",
    },
    "brand-cta-lockup": {
        "logoText": "Community",
        "action": "JOIN THE COMMUNITY",
        "destination": "your.community.url",
    },
    "windows-prompt-typing": {
        "appName": "Windows PowerShell",
        "prompt": "Rewrite this slide so a first-time reader gets the point in five seconds",
        "side": "left",
    },
    "robot-cheer": {
        "text": "Vibe coding",
        "tagline": "FOR THE WIN!",
    },
    "robot-defiant": {
        "text": "Damn the Man!",
    },
    "robot-roast": {
        "text": "He's lowkey cheap",
    },
    "robot-rocket-sign": {
        "text": "LINK IN DESCRIPTION",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_graphics_library_root() -> Path:
    """Private Graphics Library root (usages + samples)."""

    configured = os.environ.get("VCG_GRAPHICS_LIBRARY") or os.environ.get("VCG_GOLDEN_RECORD")
    if configured:
        return Path(configured).expanduser().resolve()
    library = default_creator_library()
    modern = (library / "graphics-library").resolve()
    legacy = (library / "golden-record").resolve()
    # Prefer modern name; keep using existing private folder if only legacy exists.
    if modern.is_dir() or not legacy.is_dir():
        return modern
    return legacy


def default_golden_record_root() -> Path:
    """Legacy alias for default_graphics_library_root()."""

    return default_graphics_library_root()


def settings_path(root: Path | None = None) -> Path:
    return (root or default_graphics_library_root()) / "settings.json"


def index_path(root: Path | None = None) -> Path:
    """Resolved index path (modern or legacy filename if only that exists)."""

    root = (root or default_graphics_library_root()).resolve()
    modern = root / INDEX_FILENAME
    legacy = root / LEGACY_INDEX_FILENAME
    if modern.is_file():
        return modern
    if legacy.is_file():
        return legacy
    return modern


def _assert_private_root(root: Path) -> None:
    root = root.expanduser().resolve()
    if is_within(root, project_root()):
        raise ValueError("The Graphics Library must live outside the public Git checkout.")


def empty_index() -> dict[str, Any]:
    return {
        "schemaVersion": LIBRARY_SCHEMA_VERSION,
        "updatedAt": _now(),
        "rootLabel": "Graphics Library",
        "entries": [],
    }


def scrub_usage_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize one usage: engineId + product fields only (end-pass scrub)."""

    if not isinstance(entry, dict):
        return entry
    engine_id = str(
        entry.get("engineId") or entry.get("implementationId") or entry.get("id") or ""
    ).strip()
    # Prefer known engine id when present.
    if engine_id not in MODULE_IDS:
        fallback = str(entry.get("id") or "").strip()
        if fallback in MODULE_IDS:
            engine_id = fallback
    cleaned: dict[str, Any] = {}
    for key in USAGE_STORED_KEYS:
        if key in entry:
            cleaned[key] = entry[key]
    cleaned["id"] = str(entry.get("id") or cleaned.get("id") or engine_id)
    cleaned["displayName"] = str(
        cleaned.get("displayName") or entry.get("displayName") or cleaned["id"]
    )
    cleaned["status"] = normalize_status(entry.get("status"))
    cleaned["engineId"] = engine_id or cleaned["id"]
    cleaned["beatTypes"] = normalize_beat_types(entry.get("beatTypes"))
    layouts = entry.get("allowedLayouts") if "allowedLayouts" in entry else cleaned.get("allowedLayouts")
    if isinstance(layouts, list):
        cleaned["allowedLayouts"] = [
            str(item) for item in layouts if str(item) in ALLOWED_LAYOUT_IDS
        ]
    else:
        cleaned["allowedLayouts"] = list(cleaned.get("allowedLayouts") or [])
    if "sample" not in cleaned:
        cleaned["sample"] = entry.get("sample")
    if "createdAt" not in cleaned:
        cleaned["createdAt"] = entry.get("createdAt") or _now()
    if "updatedAt" not in cleaned:
        cleaned["updatedAt"] = entry.get("updatedAt") or cleaned["createdAt"]
    # Explicitly drop scrub keys even if present.
    for key in USAGE_SCRUB_KEYS:
        cleaned.pop(key, None)
    return cleaned


def load_settings(root: Path | None = None) -> dict[str, Any]:
    path = settings_path(root)
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "layoutClips": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid Graphics Library settings.")
    data.setdefault("layoutClips", {})
    return data


def save_settings(settings: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    _assert_private_root(root)
    root.mkdir(parents=True, exist_ok=True)
    path = settings_path(root)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return settings


def load_graphics_library(root: Path | None = None) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    path = index_path(root)
    if not path.is_file():
        return empty_index()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != LIBRARY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported Graphics Library version: {data.get('schemaVersion')}")
    if not isinstance(data.get("entries"), list):
        raise ValueError("Graphics Library index entries must be an array.")
    data["entries"] = [
        scrub_usage_entry(entry) if isinstance(entry, dict) else entry for entry in data["entries"]
    ]
    return data


def load_golden_record(root: Path | None = None) -> dict[str, Any]:
    """Legacy alias for load_graphics_library()."""

    return load_graphics_library(root)


def save_graphics_library(document: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    _assert_private_root(root)
    if document.get("schemaVersion") != LIBRARY_SCHEMA_VERSION:
        raise ValueError("Invalid Graphics Library schemaVersion.")
    if not isinstance(document.get("entries"), list):
        raise ValueError("Graphics Library index entries must be an array.")
    document = {
        **document,
        "rootLabel": document.get("rootLabel") or "Graphics Library",
        "entries": [
            scrub_usage_entry(entry) if isinstance(entry, dict) else entry
            for entry in document["entries"]
        ],
        "updatedAt": _now(),
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "examples").mkdir(parents=True, exist_ok=True)
    (root / "quarantine").mkdir(parents=True, exist_ok=True)
    # Always write the modern index name; retire legacy filename if present.
    path = root / INDEX_FILENAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    legacy = root / LEGACY_INDEX_FILENAME
    if legacy.is_file() and legacy.resolve() != path.resolve():
        try:
            legacy.unlink()
        except OSError:
            pass
    return document


def save_golden_record(document: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Legacy alias for save_graphics_library()."""

    return save_graphics_library(document, root)


def create_graphics_library(
    root: Path | None = None,
    *,
    root_label: str = "Graphics Library",
) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    _assert_private_root(root)
    if index_path(root).is_file():
        return load_graphics_library(root)
    document = empty_index()
    document["rootLabel"] = root_label
    return save_graphics_library(document, root)


def create_golden_record(
    root: Path | None = None,
    *,
    root_label: str = "Graphics Library",
) -> dict[str, Any]:
    """Legacy alias for create_graphics_library()."""

    return create_graphics_library(root, root_label=root_label)


def load_module_catalog() -> list[dict[str, Any]]:
    catalog_path = project_root() / "visual-production" / "modules" / "catalog.json"
    if not catalog_path.is_file():
        # Modules may only exist as runtime IDs when the private folder is gitignored.
        return [{"id": module_id, "family": module_id, "intents": [], "allowedLayouts": [], "reusePolicy": "limited"} for module_id in sorted(MODULE_IDS)]
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    modules = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(modules, list):
        raise ValueError("Module catalog is invalid.")
    return modules


def resolve_sample_layout_id(entry: dict[str, Any], layout_id: str | None = None) -> str:
    """Choose layout for a sample render from request or usage allowedLayouts."""

    allowed = [
        str(item)
        for item in (entry.get("allowedLayouts") or [])
        if str(item) in ALLOWED_LAYOUT_IDS
    ]
    requested = str(layout_id or "").strip()
    if requested:
        if requested not in ALLOWED_LAYOUT_IDS:
            raise ValueError(f"Unknown layout id: {requested}")
        if allowed and requested not in allowed:
            raise ValueError(
                f"Layout {requested!r} is not in this usage's allowedLayouts "
                f"({', '.join(allowed)})."
            )
        return requested
    if allowed:
        return allowed[0]
    return "full-screen-talking"


def layout_clips_dir(root: Path | None = None) -> Path:
    return (root or default_graphics_library_root()).resolve() / LAYOUT_CLIPS_DIRNAME


def layout_clip_path(layout_id: str, root: Path | None = None) -> Path:
    if layout_id not in ALLOWED_LAYOUT_IDS:
        raise ValueError(f"Unknown layout id: {layout_id}")
    return layout_clips_dir(root) / f"{layout_id}.mp4"


def list_layout_clips(root: Path | None = None) -> dict[str, Any]:
    """Report which of the eight OBS layout clips are present on disk."""

    root = (root or default_graphics_library_root()).resolve()
    clips: list[dict[str, Any]] = []
    for layout_id in sorted(ALLOWED_LAYOUT_IDS):
        path = layout_clip_path(layout_id, root)
        present = path.is_file() and path.stat().st_size > 0
        item: dict[str, Any] = {
            "layoutId": layout_id,
            "relativePath": f"{LAYOUT_CLIPS_DIRNAME}/{layout_id}.mp4",
            "present": present,
        }
        if present:
            item["path"] = str(path)
            item["bytes"] = path.stat().st_size
        clips.append(item)
    present_ids = [item["layoutId"] for item in clips if item["present"]]
    missing_ids = [item["layoutId"] for item in clips if not item["present"]]
    return {
        "root": str(layout_clips_dir(root)),
        "clips": clips,
        "present": present_ids,
        "missing": missing_ids,
        "complete": len(missing_ids) == 0,
    }


def import_layout_clip(
    layout_id: str,
    source_path: str | Path,
    *,
    root: Path | None = None,
    start_sec: float = 0.0,
    duration_sec: float | None = None,
) -> dict[str, Any]:
    """Copy/trim a recorded OBS layout clip into the private library folder.

    Layout clips are full-frame recordings of each OBS scene. Sample render uses
    them as the locked source; the engine still decides where the graphic sits.
    """

    if layout_id not in ALLOWED_LAYOUT_IDS:
        raise ValueError(f"Unknown layout id: {layout_id}")
    root = (root or default_graphics_library_root()).resolve()
    _assert_private_root(root)
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Layout clip source not found: {source}")
    dest = layout_clip_path(layout_id, root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if start_sec < 0:
        raise ValueError("start_sec must be >= 0.")
    # Full copy when no trim window; otherwise extract a short window for samples.
    if duration_sec is None and start_sec == 0.0:
        shutil.copy2(source, dest)
    else:
        duration = float(duration_sec if duration_sec is not None else 12.0)
        if duration < 4 or duration > 30:
            raise ValueError("duration_sec must be between 4 and 30 for trimmed layout clips.")
        command = [
            str(find_ffmpeg()),
            "-y",
            "-ss",
            f"{start_sec:.4f}",
            "-i",
            str(source),
            "-t",
            f"{duration:.4f}",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            creationflags=hidden_subprocess_flags(),
        )
        if result.returncode != 0 or not dest.is_file():
            raise RuntimeError(
                f"Could not import layout clip for {layout_id}. "
                + ((result.stderr or result.stdout)[-1200:])
            )
    settings = load_settings(root)
    clips = settings.setdefault("layoutClips", {})
    clips[layout_id] = {
        "relativePath": f"{LAYOUT_CLIPS_DIRNAME}/{layout_id}.mp4",
        "importedAt": _now(),
        "sourcePath": str(source),
    }
    settings["updatedAt"] = _now()
    save_settings(settings, root)
    return list_layout_clips(root)


def _entry_shell(module: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    stamp = now or _now()
    engine_id = str(module["id"])
    layouts = [str(item) for item in (module.get("allowedLayouts") or []) if str(item) in ALLOWED_LAYOUT_IDS]
    # v1 convenience: usage id defaults to engine id; composition allows them to diverge later.
    return scrub_usage_entry(
        {
            "id": engine_id,
            "displayName": str(module.get("name") or engine_id.replace("-", " ").title()),
            "status": "candidate",
            "engineId": engine_id,
            "allowedLayouts": layouts,
            "beatTypes": normalize_beat_types(module.get("beatTypes")),
            "sample": None,
            "createdAt": stamp,
            "updatedAt": stamp,
        }
    )


def ensure_candidate_usages_from_engines(
    root: Path | None = None,
    *,
    include_unbuildable: bool = False,
) -> dict[str, Any]:
    """Ensure each known engine has a **candidate usage** row in the library.

    Does not draw graphics. Does not promote to golden. Only creates/updates
    shelf entries (when/where shells) so the creator can sample and promote.
    Safe to run repeatedly.
    """

    root = (root or default_graphics_library_root()).resolve()
    document = create_graphics_library(root)
    by_id = {str(entry["id"]): entry for entry in document["entries"]}
    now = _now()
    created = 0
    for module in load_module_catalog():
        module_id = str(module.get("id") or "")
        if not module_id:
            continue
        if not include_unbuildable and module_id not in MODULE_IDS:
            continue
        if module_id in by_id:
            # Refresh engine link / layouts that do not overwrite creator status.
            entry = by_id[module_id]
            entry["engineId"] = str(entry.get("engineId") or module_id)
            if entry["engineId"] not in MODULE_IDS:
                entry["engineId"] = module_id
            if module.get("allowedLayouts") and not entry.get("allowedLayouts"):
                entry["allowedLayouts"] = [
                    str(item) for item in module["allowedLayouts"] if str(item) in ALLOWED_LAYOUT_IDS
                ]
            if module.get("beatTypes") and not entry.get("beatTypes"):
                entry["beatTypes"] = normalize_beat_types(module.get("beatTypes"))
            by_id[module_id] = scrub_usage_entry(entry)
            continue
        entry = _entry_shell(module, now=now)
        document["entries"].append(entry)
        by_id[module_id] = entry
        created += 1
    # Ensure every runtime MODULE_IDS is present even if catalog file is incomplete.
    for module_id in sorted(MODULE_IDS):
        if module_id not in by_id:
            document["entries"].append(_entry_shell({"id": module_id}, now=now))
            created += 1
    save_graphics_library(document, root)
    return {
        "created": created,
        "total": len(document["entries"]),
        "root": str(root),
    }


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def import_treatment_harvest(root: Path | None = None) -> dict[str, Any]:
    """Import harvest previews into candidate usages when possible.

    Never auto-promotes to golden. Skips engines not in MODULE_IDS.
    Does not import rating/notes/history.
    """

    root = (root or default_graphics_library_root()).resolve()
    document = create_graphics_library(root)
    ensure_candidate_usages_from_engines(root)
    document = load_graphics_library(root)
    by_id = {str(entry["id"]): entry for entry in document["entries"]}

    library_root = default_creator_library()
    sources: list[tuple[str, list[dict]]] = []
    active = _load_json_if_exists(treatment_library_path())
    if active and isinstance(active.get("treatments"), list):
        sources.append(("active", active["treatments"]))
    removed = _load_json_if_exists(library_root / "quarantine-unbuildable-2026-07-25" / "treatments-removed.json")
    if removed and isinstance(removed.get("quarantined"), list):
        sources.append(("quarantine", removed["quarantined"]))
    before = _load_json_if_exists(library_root / "quarantine-unbuildable-2026-07-25" / "treatments.json.before")
    if before and isinstance(before.get("treatments"), list):
        sources.append(("before", before["treatments"]))

    imported = 0
    skipped = 0
    for _source_name, treatments in sources:
        for treatment in treatments:
            treatment_id = str(treatment.get("id") or "")
            if not treatment_id:
                continue
            if treatment_id not in MODULE_IDS:
                skipped += 1
                continue
            entry = by_id.get(treatment_id)
            if entry is None:
                entry = _entry_shell({"id": treatment_id})
                document["entries"].append(entry)
                by_id[treatment_id] = entry
            # Never auto-promote to golden; harvest stays candidate until creator promotes.
            entry["status"] = normalize_status(entry.get("status"))
            # Copy previews into examples when present and sample missing.
            if not (entry.get("sample") or {}).get("relativePath"):
                if _try_copy_harvest_preview(library_root, treatment, entry, root):
                    entry["updatedAt"] = _now()
                    imported += 1

    save_graphics_library(document, root)
    return {
        "imported": imported,
        "skippedUnbuildable": skipped,
        "total": len(document["entries"]),
        "root": str(root),
    }


def _try_copy_harvest_preview(
    library_root: Path,
    treatment: dict[str, Any],
    entry: dict[str, Any],
    golden_root: Path,
) -> bool:
    treatment_id = str(treatment["id"])
    candidates = [
        library_root / "recipe-previews" / f"{treatment_id}.png",
        library_root / "quarantine-unbuildable-2026-07-25" / "recipe-previews" / f"{treatment_id}.png",
        library_root / "motion-previews" / f"{treatment_id}.mp4",
        library_root / "quarantine-unbuildable-2026-07-25" / "motion-previews" / f"{treatment_id}.mp4",
    ]
    usage = treatment.get("usage") or []
    if isinstance(usage, list):
        for item in usage:
            if not isinstance(item, dict):
                continue
            for key in ("previewPath", "motionPreviewPath"):
                rel = str(item.get(key) or "")
                if rel:
                    candidates.append(library_root / rel)

    example_dir = golden_root / "examples" / treatment_id
    sample_path = example_dir / "sample.mp4"
    poster_path = example_dir / "poster.png"
    example_dir.mkdir(parents=True, exist_ok=True)
    sample_copied = False
    poster_copied = False
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() in {".mp4", ".webm", ".mov"} and not sample_path.is_file():
            shutil.copy2(candidate, sample_path)
            sample_copied = True
        if candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and not poster_path.is_file():
            shutil.copy2(candidate, poster_path)
            poster_copied = True
    if sample_copied or poster_copied:
        duration = None
        if sample_path.is_file():
            try:
                duration = float(probe_visual_source(sample_path)["durationSec"])
            except Exception:
                duration = None
        entry["sample"] = {
            "relativePath": f"examples/{treatment_id}/sample.mp4" if sample_path.is_file() else None,
            "posterRelativePath": f"examples/{treatment_id}/poster.png" if poster_path.is_file() else None,
            "durationSec": duration,
            "hasAudio": bool(sample_path.is_file()),
            "source": "harvest-import",
        }
        return True
    return False


def _raw_entry(entry_id: str, root: Path | None = None) -> dict[str, Any]:
    """Load a usage entry as stored (no public-view filtering)."""

    root = (root or default_graphics_library_root()).resolve()
    document = load_graphics_library(root)
    for entry in document["entries"]:
        if entry.get("id") == entry_id:
            return entry
    raise ValueError(f"Graphics library usage not found: {entry_id}")


def get_entry(entry_id: str, root: Path | None = None) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    return entry_public_view(_raw_entry(entry_id, root), root)


def update_entry(entry_id: str, updates: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    document = load_graphics_library(root)
    entry = next((item for item in document["entries"] if item.get("id") == entry_id), None)
    if entry is None:
        raise ValueError(f"Graphics library usage not found: {entry_id}")
    # Accept legacy implementationId as alias for engineId from older clients.
    if "engineId" not in updates and "implementationId" in updates:
        updates = {**updates, "engineId": updates["implementationId"]}
    allowed = {
        "displayName",
        "status",
        "beatTypes",
        "allowedLayouts",
        "engineId",
    }
    # Dropped fields are ignored if a client still sends them (scrub strips storage).
    changed = {key: updates[key] for key in updates if key in allowed}
    if "status" in changed and changed["status"] not in STATUSES:
        raise ValueError(f"Invalid status: {changed['status']}")
    if "beatTypes" in changed:
        raw = changed["beatTypes"]
        if not isinstance(raw, list):
            raise ValueError("beatTypes must be a string array of approved beat types.")
        for item in raw:
            beat = str(item or "").strip()
            if beat and beat not in BEAT_TYPES:
                raise ValueError(f"Invalid beat type: {beat}")
        changed["beatTypes"] = normalize_beat_types(raw)
    if "displayName" in changed:
        name = str(changed["displayName"] or "").strip()
        if not name:
            raise ValueError("displayName must be a non-empty string.")
        changed["displayName"] = name
    if "engineId" in changed:
        engine_id = str(changed["engineId"] or "").strip()
        if not engine_id:
            raise ValueError("engineId must be a non-empty string.")
        if engine_id not in MODULE_IDS:
            raise ValueError(f"Unknown engine id: {engine_id}")
        changed["engineId"] = engine_id
    if "allowedLayouts" in changed:
        layouts = changed["allowedLayouts"]
        if not isinstance(layouts, list):
            raise ValueError("allowedLayouts must be a string array.")
        cleaned: list[str] = []
        for item in layouts:
            layout = str(item)
            if layout not in ALLOWED_LAYOUT_IDS:
                raise ValueError(f"Invalid layout id: {layout}")
            if layout not in cleaned:
                cleaned.append(layout)
        changed["allowedLayouts"] = cleaned
    entry.update(changed)
    scrubbed = scrub_usage_entry(entry)
    entry.clear()
    entry.update(scrubbed)
    entry["updatedAt"] = _now()
    for index, item in enumerate(document["entries"]):
        if item is entry or (isinstance(item, dict) and item.get("id") == entry_id):
            document["entries"][index] = entry
            break
    save_graphics_library(document, root)
    return entry_public_view(entry, root)


def resolve_media_path(entry_id: str, kind: str, root: Path | None = None) -> Path:
    root = (root or default_graphics_library_root()).resolve()
    entry = get_entry(entry_id, root)
    sample = entry.get("sample") or {}
    if kind == "sample":
        rel = sample.get("relativePath")
    elif kind == "poster":
        rel = sample.get("posterRelativePath")
    else:
        raise ValueError("Media kind must be sample or poster.")
    if not rel:
        raise ValueError(f"No {kind} registered for {entry_id}.")
    path = (root / str(rel)).resolve()
    if not is_within(path, root):
        raise ValueError("Media path escapes the Graphics Library root.")
    if not path.is_file():
        raise ValueError(f"Media file missing: {rel}")
    return path


def entry_public_view(entry: dict[str, Any], root: Path) -> dict[str, Any]:
    """API-facing usage with media flags and live engine interface passthrough."""

    sample = entry.get("sample") or {}
    sample_rel = sample.get("relativePath")
    poster_rel = sample.get("posterRelativePath")
    has_sample = bool(sample_rel and (root / str(sample_rel)).is_file())
    has_poster = bool(poster_rel and (root / str(poster_rel)).is_file())
    engine_id = str(
        entry.get("engineId") or entry.get("implementationId") or entry.get("id") or ""
    ).strip()
    # Dropped / non-product fields may still exist on private JSON until end-pass scrub.
    public = {
        key: value
        for key, value in entry.items()
        if key
        not in {
            "buildable",
            "demoBed",
            "reusePolicy",
            "purpose",
            "parameters",  # not authority — use engineInterface
            "implementationId",  # use engineId
            "family",
            "visualFamily",
            "contentCapacity",
            "motionProfile",
            "tags",
            "lockedDefault",
            "preferredIntents",
            "intents",
        }
    }
    public["engineId"] = engine_id if engine_id else str(entry.get("id") or "")
    return {
        **public,
        "engineInterface": engine_interface_keys(public["engineId"]),
        "hasSample": has_sample,
        "hasPoster": has_poster,
        "sampleUrl": f"/api/graphics-library/usages/{entry['id']}/media/sample" if has_sample else None,
        "posterUrl": f"/api/graphics-library/usages/{entry['id']}/media/poster" if has_poster else None,
    }


def get_production_graphics(
    root: Path | None = None,
    *,
    policy: str = "golden-only",
    require_buildable: bool = False,
) -> dict[str, Any]:
    """Return the production-selectable usage set (status golden by default).

    Empty set is valid — callers must not invent a parallel menu.
    ``require_buildable`` is accepted for call-site compatibility and ignored.
    """

    del require_buildable  # dropped — do not filter production set on legacy flag
    root = (root or default_graphics_library_root()).resolve()
    exists = index_path(root).is_file()
    allowed_statuses = production_status_set(policy)
    if not exists:
        return {
            "root": str(root),
            "exists": False,
            "policy": policy,
            "allowedStatuses": sorted(allowed_statuses),
            "graphics": [],
            "ids": [],
            "count": 0,
            "empty": True,
            "emptyReason": "no-graphics-library",
            "message": (
                "No Graphics Library connected. Create or choose a folder and promote usages to golden."
            ),
        }

    document = load_graphics_library(root)
    usages: list[dict[str, Any]] = []
    for entry in document["entries"]:
        status = str(entry.get("status") or "candidate")
        if status not in allowed_statuses:
            continue
        usage_id = str(entry.get("id") or "")
        engine_id = str(entry.get("engineId") or entry.get("implementationId") or usage_id)
        usages.append(
            {
                "id": usage_id,
                "displayName": entry.get("displayName") or usage_id,
                "status": status,
                "engineId": engine_id,
                "allowedLayouts": list(entry.get("allowedLayouts") or []),
                "beatTypes": normalize_beat_types(entry.get("beatTypes")),
            }
        )

    usages.sort(key=lambda item: str(item["id"]))
    ids = [str(item["id"]) for item in usages]
    empty = len(usages) == 0
    if empty:
        empty_reason = "no-golden-status"
        message = (
            "No production-selectable usages yet. Open Graphics Library, review samples, "
            "and mark trusted usages as golden."
        )
    else:
        empty_reason = None
        message = f"{len(usages)} golden usage(s) available under policy {policy!r}."

    return {
        "root": str(root),
        "exists": True,
        "policy": policy,
        "allowedStatuses": sorted(allowed_statuses),
        "usages": usages,
        "graphics": usages,  # legacy alias for callers
        "ids": ids,
        "count": len(usages),
        "empty": empty,
        "emptyReason": empty_reason,
        "message": message,
    }


def get_production_usages(
    root: Path | None = None,
    *,
    policy: str = "golden-only",
) -> dict[str, Any]:
    """Alias: production set is golden usages from the Graphics Library."""

    return get_production_graphics(root, policy=policy)


def summary(root: Path | None = None) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    exists = index_path(root).is_file()
    document = load_graphics_library(root) if exists else empty_index()
    counts: dict[str, int] = {}
    for entry in document["entries"]:
        status = str(entry.get("status") or "candidate")
        counts[status] = counts.get(status, 0) + 1
    with_sample = 0
    for entry in document["entries"]:
        sample = entry.get("sample") or {}
        rel = sample.get("relativePath")
        if rel and (root / str(rel)).is_file():
            with_sample += 1
    settings = load_settings(root) if exists or root.is_dir() else load_settings(root)
    production = get_production_graphics(root, policy="golden-only")
    return {
        "root": str(root),
        "exists": exists,
        "rootLabel": document.get("rootLabel"),
        "updatedAt": document.get("updatedAt"),
        "entryCount": len(document["entries"]),
        "statusCounts": counts,
        "withSample": with_sample,
        "settings": settings,
        "productionSet": {
            "policy": production["policy"],
            "count": production["count"],
            "ids": production["ids"],
            "empty": production["empty"],
            "emptyReason": production.get("emptyReason"),
            "message": production["message"],
        },
        "entries": [entry_public_view(entry, root) for entry in document["entries"]],
        "layoutClips": list_layout_clips(root),
    }


def library_metrics(root: Path | None = None) -> dict[str, Any]:
    """Counts of library usages by beat type and by allowed layout.

    Each usage may list multiple beat types / layouts; it is counted once per
    listed id. Untagged rows are tracked separately so empty metadata is visible.
    """

    from app.core.editorial_layout import LAYOUT_IDS

    root = (root or default_graphics_library_root()).resolve()
    exists = index_path(root).is_file()
    document = load_graphics_library(root) if exists else empty_index()
    entries = [entry for entry in document.get("entries") or [] if isinstance(entry, dict)]

    beat_order = sorted(BEAT_TYPES)
    layout_order = sorted(LAYOUT_IDS)

    def _empty_bucket(keys: list[str]) -> dict[str, dict[str, int]]:
        return {key: {"total": 0, "golden": 0, "candidate": 0} for key in keys}

    by_beat = _empty_bucket(beat_order)
    by_layout = _empty_bucket(layout_order)
    untagged_beats = {"total": 0, "golden": 0, "candidate": 0}
    untagged_layouts = {"total": 0, "golden": 0, "candidate": 0}

    def _bump(bucket: dict[str, int], status: str) -> None:
        bucket["total"] += 1
        if status == "golden":
            bucket["golden"] += 1
        else:
            bucket["candidate"] += 1

    for entry in entries:
        status = str(entry.get("status") or "candidate")
        if status not in STATUSES:
            status = "candidate"
        beats = [
            str(item).strip()
            for item in (entry.get("beatTypes") or [])
            if str(item).strip()
        ]
        layouts = [
            str(item).strip()
            for item in (entry.get("allowedLayouts") or [])
            if str(item).strip()
        ]
        if not beats:
            _bump(untagged_beats, status)
        else:
            for beat in beats:
                if beat not in by_beat:
                    by_beat[beat] = {"total": 0, "golden": 0, "candidate": 0}
                _bump(by_beat[beat], status)
        if not layouts:
            _bump(untagged_layouts, status)
        else:
            for layout in layouts:
                if layout not in by_layout:
                    by_layout[layout] = {"total": 0, "golden": 0, "candidate": 0}
                _bump(by_layout[layout], status)

    def _rows(mapping: dict[str, dict[str, int]], order: list[str]) -> list[dict[str, Any]]:
        keys = list(order) + [key for key in mapping if key not in order]
        rows = [
            {"id": key, **mapping[key]}
            for key in keys
            if key in mapping
        ]
        rows.sort(key=lambda row: (-int(row["total"]), str(row["id"])))
        return rows

    return {
        "root": str(root),
        "exists": exists,
        "entryCount": len(entries),
        "byBeatType": _rows(by_beat, beat_order),
        "byLayout": _rows(by_layout, layout_order),
        "untaggedBeatTypes": untagged_beats,
        "untaggedLayouts": untagged_layouts,
    }


def configure_demo_beds(
    *,
    talking_head: dict[str, Any] | None = None,
    screen_share: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    _assert_private_root(root)
    root.mkdir(parents=True, exist_ok=True)
    settings = load_settings(root)
    beds = settings.setdefault("demoBeds", {})
    if talking_head is not None:
        beds["talking-head"] = _normalize_bed_config(talking_head, "talking-head")
    if screen_share is not None:
        beds["screen-share"] = _normalize_bed_config(screen_share, "screen-share")
    settings["updatedAt"] = _now()
    return save_settings(settings, root)


def _normalize_bed_config(config: dict[str, Any], bed_id: str) -> dict[str, Any]:
    source = Path(str(config.get("sourcePath") or "")).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Demo bed {bed_id} source video not found: {source}")
    start = float(config.get("startSec") or 0.0)
    duration = float(config.get("durationSec") or 12.0)
    if start < 0:
        raise ValueError("Demo bed startSec must be >= 0.")
    if duration < 6 or duration > 20:
        raise ValueError("Demo bed durationSec must be between 6 and 20.")
    return {
        "sourcePath": str(source),
        "startSec": start,
        "durationSec": duration,
        "label": str(config.get("label") or bed_id),
    }


def _demo_parameters(module_id: str) -> dict[str, Any]:
    """Default content for library samples. Engine CSS owns graphic placement."""

    params = dict(_DEMO_COPY.get(module_id) or {})
    params.setdefault("reviewLabel", module_id)
    params.setdefault("editorialPurpose", f"Graphics Library sample for {module_id}.")
    params.setdefault("opacity", 1)
    params.setdefault("transitionIn", "editorial-snap")
    params.setdefault("transitionOut", "fade")
    params.setdefault("accentColor", "#FF00CE")
    allowed = MODULE_PARAMETER_KEYS.get(module_id) or set()
    return {key: value for key, value in params.items() if key in allowed}


def _semantic_items_for_cue(
    cue: dict[str, Any],
    *,
    reveal_stagger_sec: float = 0.0,
) -> list[dict[str, Any]]:
    """Build semantic anchors for a library sample cue.

    When ``reveal_stagger_sec`` > 0, each visible field (thesis, callouts, rows, …)
    is spaced so sample motion can be read — not production voice locking.
    """

    from app.core.visual_production import _module_semantic_texts

    required = _module_semantic_texts(cue)
    start = float(cue["startSec"])
    end = float(cue["endSec"])
    stagger = max(0.0, float(reveal_stagger_sec or 0.0))
    module_id = str(cue.get("moduleId") or "")
    items = []
    for index, (path, text, label) in enumerate(required):
        spoken = start + (index * stagger if stagger > 0 else 0.0)
        # Keep fully-visible within the cue window.
        spoken = min(spoken, max(start, end - 0.35))
        fully = min(end, spoken + (0.35 if stagger > 0 else 0.4))
        # Prompt typing needs a long fully-visible window so sample letters type out
        # instead of snapping in over the default 0.4s semantic settle.
        if module_id == "windows-prompt-typing" and path == "parameters.prompt":
            prompt_len = max(1, sum(1 for char in str(text) if char != "\n"))
            type_span = max(3.0, prompt_len * 0.075)
            spoken = min(start + 0.9, max(start, end - type_span - 0.5))
            fully = min(end - 0.4, spoken + type_span)
            fully = max(fully, spoken + 1.0)
        items.append(
            {
                "id": f"{cue['id']}-sem-{index + 1}",
                "label": label,
                "text": text,
                "parameterPath": path,
                "phrase": text,
                "anchorType": "unanchored",
                "spokenStartSec": spoken,
                "fullyVisibleSec": fully,
            }
        )
    return items


def _hyperframes_cli_js() -> Path:
    repo = project_root()
    cli_js = repo / "node_modules" / "hyperframes" / "dist" / "cli.js"
    if cli_js.is_file():
        return cli_js
    raise RuntimeError("HyperFrames CLI not found. Run npm install.")


def _extract_poster(video_path: Path, poster_path: Path, *, at_sec: float = 3.0) -> None:
    command = [
        str(find_ffmpeg()),
        "-y",
        "-ss",
        f"{at_sec:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(poster_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0 or not poster_path.is_file():
        raise RuntimeError(f"Could not extract poster. {(result.stderr or result.stdout)[-800:]}")


def render_entry_sample(
    entry_id: str,
    *,
    root: Path | None = None,
    quality: str = "draft",
    progress: ProgressCallback | None = None,
    force: bool = False,
    layout_id: str | None = None,
) -> dict[str, Any]:
    """Render a short sample for one usage into private examples/.

    Uses a recorded full-frame layout clip for ``layout_id`` as the source video.
    The engine decides where the graphic sits — layout does not move the graphic.
    """

    progress = progress or (lambda _p, _m: None)
    root = (root or default_graphics_library_root()).resolve()
    _assert_private_root(root)
    document = load_graphics_library(root)
    entry = next((item for item in document["entries"] if item.get("id") == entry_id), None)
    if entry is None:
        raise ValueError(f"Graphics library usage not found: {entry_id}")
    module_id = str(entry.get("engineId") or entry.get("implementationId") or entry_id)
    if module_id not in MODULE_IDS:
        raise ValueError(
            f"Usage {entry_id} has no runtime engine for engineId {module_id!r}."
        )

    sample_layout = resolve_sample_layout_id(entry, layout_id)

    example_dir = root / "examples" / entry_id
    sample_out = example_dir / "sample.mp4"
    poster_out = example_dir / "poster.png"
    receipt_out = example_dir / "source-receipt.json"
    existing_sample = entry.get("sample") if isinstance(entry.get("sample"), dict) else {}
    same_layout = str(existing_sample.get("layoutId") or "") == sample_layout
    if sample_out.is_file() and not force and same_layout:
        progress(100, "Sample already exists.")
        return entry_public_view(entry, root)

    layout_source = layout_clip_path(sample_layout, root)
    if not layout_source.is_file():
        missing = list_layout_clips(root)["missing"]
        raise ValueError(
            f"No recorded layout clip for {sample_layout!r}. "
            f"Save a full-frame OBS recording to "
            f"{LAYOUT_CLIPS_DIRNAME}/{sample_layout}.mp4 under the Graphics Library root. "
            f"Missing clips: {', '.join(missing) or 'none'}."
        )

    progress(5, f"Using layout clip {sample_layout}...")
    meta = probe_visual_source(layout_source)
    duration = float(meta["durationSec"])
    width = int(meta.get("width") or 1920)
    height = int(meta.get("height") or 1080)
    if width >= height:
        width, height = 1920, 1080
    fps = float(meta.get("fps") or 30)

    # Mini private project for this sample render.
    work = root / "working" / "sample-renders" / entry_id
    if work.exists():
        shutil.rmtree(work)
    (work / "source").mkdir(parents=True)
    (work / "visual-production").mkdir(parents=True)
    (work / ".vcg-private").write_text("private\n", encoding="utf-8")
    source_rel = "source/layout.mp4"
    shutil.copy2(layout_source, work / source_rel)

    params = _demo_parameters(module_id)
    plan_assets: list[dict[str, Any]] = []
    # Joke-image punchline sample: stage the brand demo illustration as a plan asset.
    if module_id == "punchline-reveal" and params.get("imageAssetId"):
        from app.core.visual_production import brand_joke_demo_image_path

        demo_src = brand_joke_demo_image_path()
        if not demo_src.is_file():
            raise RuntimeError(f"Missing brand joke demo image at {demo_src}")
        demo_rel = f"source/{demo_src.name}"
        shutil.copy2(demo_src, work / demo_rel)
        asset_id = str(params["imageAssetId"])
        plan_assets.append(
            {
                "id": asset_id,
                "name": "Joke demo image",
                "path": demo_rel,
                "mediaType": "image",
                "durationSec": None,
                "hasTransparency": False,
            }
        )
    # Library samples: slow multi-item reveals so staggered motion is visible (~1s each).
    sample_reveal_stagger_sec = 1.0
    list_keys = (
        "callouts",
        "rows",
        "steps",
        "cards",
        "bubbles",
        "commands",
        "nodes",
        "items",
        "lines",
        "words",
        "stops",
        "milestones",
        "leftItems",
        "rightItems",
    )
    reveal_count = 0
    for key in list_keys:
        value = params.get(key)
        if isinstance(value, list):
            reveal_count = max(reveal_count, len(value))
    cue_start = 1.0
    if module_id == "source-punch-zoom":
        # Camera sample must show the full arc: punch in → short hold → pull out.
        # Older samples used a long hold + tiny settle, so the return-to-full looked missing.
        params["transitionIn"] = "none"
        params["transitionOut"] = "none"
        settle = float(params.get("settleSec") or 1.0)
        hold = 1.4
        cue_end = min(duration - 0.08, cue_start + settle + hold + settle + 0.25)
    elif module_id == "progress-scale":
        # Bar draw (readable stop hits) + 2.5s full-stage linger after fill, then exit.
        milestone_n = len(params.get("milestones") or []) or 3
        fill_sec = max(3.5, milestone_n * 1.25)
        hold_after_fill = 2.5
        lead_and_exit = 1.2
        cue_end = min(
            duration - 0.08,
            cue_start + lead_and_exit + fill_sec + hold_after_fill,
        )
        if cue_end <= cue_start + 4.0:
            cue_end = min(duration - 0.05, cue_start + max(6.0, duration * 0.75))
    elif module_id == "problem-card-triptych":
        # 3 sequential cards (~1s each) + 2s last settles white + 2s all-white linger.
        card_n = len(params.get("cards") or []) or 3
        cue_end = min(
            duration - 0.08,
            cue_start + 0.4 + card_n * sample_reveal_stagger_sec + 2.0 + 2.0 + 0.5,
        )
        if cue_end <= cue_start + 6.0:
            cue_end = min(duration - 0.05, cue_start + max(8.0, duration * 0.8))
    elif module_id == "dependency-stack":
        # Video dock + sequential nodes (up to 6) + settle/linger after last.
        node_n = len(params.get("nodes") or []) or 3
        cue_end = min(
            duration - 0.08,
            cue_start + 0.5 + node_n * sample_reveal_stagger_sec + 2.0 + 2.0 + 0.5,
        )
        if cue_end <= cue_start + 6.0:
            cue_end = min(duration - 0.05, cue_start + max(9.0, duration * 0.85))
    elif module_id in {"robot-cheer", "robot-defiant", "robot-roast"}:
        # Entrance (~0.75–0.85s) + hard 3s hold after drawn + short exit.
        from app.core.visual_production import ROBOT_HOLD_AFTER_DRAWN_SEC

        entrance = 0.85 if module_id == "robot-roast" else 0.75
        cue_end = min(
            duration - 0.08,
            cue_start + entrance + ROBOT_HOLD_AFTER_DRAWN_SEC + 0.35,
        )
    elif module_id == "robot-rocket-sign":
        from app.core.visual_production import ROBOT_ROCKET_MIN_CUE_SEC

        cue_end = min(duration - 0.08, cue_start + ROBOT_ROCKET_MIN_CUE_SEC)
    elif module_id == "brand-cta-lockup":
        # Band + logo + copy + mid-cue URL land (~5.6s) + short hold/exit.
        cue_end = min(duration - 0.08, cue_start + 8.5)
    elif module_id == "windows-prompt-typing":
        # Dock + terminal fade + letter-by-letter type (~13 cps) + hold finished line + exit.
        prompt_text = str(params.get("prompt") or "")
        char_n = sum(1 for char in prompt_text.replace("\r\n", "\n") if char != "\n")
        type_sec = max(3.5, char_n * 0.075)
        cue_end = min(duration - 0.08, cue_start + 0.95 + type_sec + 1.6 + 0.55)
        if cue_end <= cue_start + 6.0:
            cue_end = min(duration - 0.05, cue_start + max(8.0, duration * 0.8))
    else:
        # Thesis/shell + N staggered items + hold so the last chip is readable.
        min_cue_span = 1.0 + (reveal_count * sample_reveal_stagger_sec if reveal_count else 3.0) + 2.0
        cue_end = min(duration - 0.08, max(cue_start + min_cue_span, min(duration - 0.5, cue_start + 8.0)))
        if cue_end <= cue_start + 2.0:
            cue_end = min(duration - 0.05, cue_start + max(4.0, duration * 0.7))
    cue = {
        "id": f"cue-{entry_id}",
        "kind": "module",
        "moduleId": module_id,
        "startSec": cue_start,
        "endSec": cue_end,
        "enabled": True,
        "parameters": params,
    }
    cue["semanticItems"] = _semantic_items_for_cue(
        cue,
        reveal_stagger_sec=sample_reveal_stagger_sec if reveal_count else 0.0,
    )

    now = _now()
    plan = {
        "schemaVersion": 2,
        "project": {
            "id": uuid.uuid4().hex,
            "name": f"library-sample-{entry_id}",
            "createdAt": now,
            "updatedAt": now,
        },
        "source": {
            "video": source_rel,
            "transcript": "",
            "videoSha256": sha256_file(work / source_rel),
        },
        "composition": {
            "width": width,
            "height": height,
            "fps": fps,
            "durationSec": duration,
            "brandId": "vcg-white-editorial",
        },
        "assets": plan_assets,
        "customCompositions": [],
        "protectedFootage": [],
        "cues": [cue],
        "revisions": {"activeRevision": None, "items": []},
        "productionGates": {
            "representativeApproval": None,
            "fullReviewApproval": None,
            "layoutInspection": None,
            "deliveryReopen": None,
        },
        "reviews": [],
        "reviewHistory": [],
    }
    plan_path = work / "visual-production" / "visual-plan.sample.json"
    validate_visual_plan(plan, work)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    progress(20, "Building HyperFrames composition...")
    workspace = work / "hyperframes"
    runtime_root, render_duration = build_hyperframes_composition(
        plan_path,
        start_sec=0.0,
        end_sec=duration,
        workspace_override=workspace,
        progress=lambda pct, msg: progress(20 + int(pct * 0.25), msg),
        sample_reveal_stagger_sec=sample_reveal_stagger_sec,
    )

    progress(50, "Rendering sample frames...")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to render Graphics Library samples.")
    cli_js = _hyperframes_cli_js()
    video_only = work / "video-only.mp4"
    env = os.environ.copy()
    media_dirs = [str(find_ffmpeg().parent)]
    if find_ffprobe() is not None:
        media_dirs.append(str(find_ffprobe().parent))
    env["PATH"] = os.pathsep.join(media_dirs + [env.get("PATH", "")])
    command = [
        node,
        str(cli_js),
        "render",
        str(runtime_root),
        "--output",
        str(video_only),
        "--quality",
        quality,
    ]
    rendered = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project_root()),
        env=env,
        creationflags=hidden_subprocess_flags(),
    )
    if rendered.returncode != 0 or not video_only.is_file():
        raise RuntimeError(
            "HyperFrames sample render failed. "
            + ((rendered.stderr or rendered.stdout or "")[-1800:])
        )

    progress(85, "Muxing layout clip audio...")
    example_dir.mkdir(parents=True, exist_ok=True)
    # Always rewrite outputs when forcing so poster/sample cannot stay stale.
    if force:
        for path in (sample_out, poster_out):
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
    remux_locked_audio(
        video_only,
        work / source_rel,
        sample_out,
        start_sec=0.0,
        duration_sec=duration,
    )
    progress(92, "Extracting poster frame...")
    # Camera moves: grab a frame after the pull-out so the thumb is not stuck mid-zoom.
    if module_id == "source-punch-zoom":
        poster_at = min(duration - 0.05, max(0.5, float(cue_end) + 0.15))
    else:
        poster_at = min(3.0, max(0.5, duration / 2))
    _extract_poster(sample_out, poster_out, at_sec=poster_at)
    if not poster_out.is_file():
        raise RuntimeError("Poster was not written after sample render.")

    rendered_at = _now()
    receipt = {
        "entryId": entry_id,
        "moduleId": module_id,
        "layoutId": sample_layout,
        "layoutClip": str(layout_source),
        "cue": {"startSec": cue_start, "endSec": cue_end, "parameters": params},
        "renderDurationSec": render_duration,
        "quality": quality,
        "createdAt": rendered_at,
    }
    receipt_out.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    entry["sample"] = {
        "relativePath": f"examples/{entry_id}/sample.mp4",
        "posterRelativePath": f"examples/{entry_id}/poster.png",
        "durationSec": float(probe_visual_source(sample_out)["durationSec"]),
        "hasAudio": True,
        "source": "rendered",
        "layoutId": sample_layout,
        "renderedAt": rendered_at,
    }
    entry["updatedAt"] = rendered_at
    scrubbed = scrub_usage_entry(entry)
    entry.clear()
    entry.update(scrubbed)
    entry["updatedAt"] = rendered_at
    save_graphics_library(document, root)
    progress(100, "Sample ready.")
    return entry_public_view(entry, root)


def render_missing_samples(
    *,
    root: Path | None = None,
    quality: str = "draft",
    force: bool = False,
    entry_ids: list[str] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    root = (root or default_graphics_library_root()).resolve()
    document = load_graphics_library(root)
    ids = entry_ids or [
        str(entry["id"])
        for entry in document["entries"]
        if str(entry.get("engineId") or entry.get("implementationId") or entry.get("id") or "")
        in MODULE_IDS
    ]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for index, entry_id in enumerate(ids):
        def _progress(pct: int, message: str, _index=index, _id=entry_id) -> None:
            if progress:
                overall = int(((index + pct / 100) / max(1, len(ids))) * 100)
                progress(overall, f"[{_index + 1}/{len(ids)}] {_id}: {message}")

        try:
            entry = render_entry_sample(
                entry_id,
                root=root,
                quality=quality,
                force=force,
                progress=_progress,
            )
            results.append({"id": entry_id, "ok": True, "hasSample": entry.get("hasSample")})
        except Exception as exc:  # noqa: BLE001 — collect per-entry failures for overnight batch
            errors.append({"id": entry_id, "error": str(exc)})
            if progress:
                progress(
                    int(((index + 1) / max(1, len(ids))) * 100),
                    f"[{index + 1}/{len(ids)}] {entry_id}: FAILED — {exc}",
                )
    return {
        "rendered": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
        "root": str(root),
    }


def configure_default_vcg_demo_beds_from_project(
    project_path: Path,
    *,
    root: Path | None = None,
    talking_start: float = 0.0,
    talking_duration: float = 12.0,
    screen_start: float = 80.0,
    screen_duration: float = 12.0,
) -> dict[str, Any]:
    """Operator helper: point beds at a private project's locked cut.

    Paths stay in private settings only — never written into the public repo.
    """

    project_path = project_path.expanduser().resolve()
    locked = project_path / "exports" / "locked-cut.mp4"
    if not locked.is_file():
        raise ValueError(f"Locked cut not found: {locked}")
    return configure_demo_beds(
        talking_head={
            "sourcePath": str(locked),
            "startSec": talking_start,
            "durationSec": talking_duration,
            "label": f"{project_path.name} talking-head",
        },
        screen_share={
            "sourcePath": str(locked),
            "startSec": screen_start,
            "durationSec": screen_duration,
            "label": f"{project_path.name} screen-share",
        },
        root=root,
    )
