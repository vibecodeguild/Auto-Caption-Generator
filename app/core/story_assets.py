from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.ffmpeg_locator import find_ffmpeg
from app.core.file_utils import is_within, sha256_file, slug
from app.core.process_utils import hidden_subprocess_flags
from app.core.settings import project_root, user_data_root
from app.core.visual_production import (
    ASSET_EXTENSIONS,
    MODULE_IDS,
    MODULE_PARAMETER_KEYS,
    VIDEO_EXTENSIONS,
    build_hyperframes_composition,
    find_visual_root,
    load_visual_plan,
    is_screen_share_layout,
    measured_speaker_bounds,
    probe_visual_source,
    resolve_project_path,
    save_visual_plan,
    speaker_safety_issues,
    validate_document_schema,
)


CREATOR_LIBRARY_VERSION = 1
SUGGESTIONS_VERSION = 1
# One contract. Earlier versions existed as a migration ramp and became an opt-out: lowering this
# field switched off the approval contract, the planning gate, and the library harvest at once.
SUGGESTIONS_CONTRACT_VERSION = 3
SUGGESTION_STATUSES = {"proposed", "prepared", "approved", "rejected", "built", "needs-alternatives"}
SUGGESTION_CATEGORIES = {"clean-speaker", "protected-footage", "graphic", "creator-library", "project-asset", "stock", "ai-brief"}
SCENE_LAYOUTS = {
    "full-screen-talking",
    "talking-left",
    "talking-right",
    "talking-bottom-left",
    "talking-top-left",
    "talking-bottom-right",
    "talking-top-right",
    "computer-screen-only",
}
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
TREATMENT_LIBRARY_VERSION = 1
MAX_MEANINGFUL_CHANGE_GAP_SEC = 5.0
# Changes that carry a protected span without putting a graphic over the footage. There is no
# "hold" concept: protected-footage means no overlay may cover the demonstration, and the
# five-second cadence is met with source-level motion instead.
# A protected span renders nothing, so it is a moment the footage carries alone: a click, a
# punchline, a reaction. Beyond this it stops being a protected moment and becomes an unplanned
# chapter, which is how one video ended up 83% empty. To keep a demonstration readable for longer,
# name the region with scenePacket.protectedRegions and put a treatment beside it.
MAX_PROTECTED_SPAN_SEC = 8.0
# Variety ceilings. These hold whatever the plan declares: intentionalRepeat and seriesId can
# excuse a deliberate callback, but they cannot make one device carry the video. A pass that was
# 46% punch zooms and 38% callouts satisfied every per-scene rule because both were marked
# intentional, so the limits that matter are proportions of the whole plan.
MAX_TREATMENT_SHARE = 0.25
MAX_TOP_TWO_SHARE = 0.45
MIN_GRAPHIC_DURATION_SEC = 1.0
SOURCE_LEVEL_CHANGE_KINDS = {
    "punch-zoom",
    "speaker-reframe",
    "composition-change",
    "emphasis-change",
    "ui-action",
    "internal-reveal",
    "chart-change",
}
MEANINGFUL_CHANGE_KINDS = {
    "treatment-enter",
    "internal-reveal",
    "chart-change",
    "ui-action",
    "callout-change",
    "composition-change",
    "speaker-reframe",
    "supporting-visual",
    "punch-zoom",
    "emphasis-change",
    "treatment-exit",
}
APPROVAL_EVIDENCE_READY = {"historical-ready", "sample-ready"}


def default_creator_library() -> Path:
    configured = os.environ.get("VCG_CREATOR_LIBRARY")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Videos" / "VCG Creator Library").resolve()


def creator_library_path() -> Path:
    return default_creator_library() / "library.json"


def treatment_library_path() -> Path:
    return default_creator_library() / "treatments.json"


def load_treatment_library() -> dict:
    path = treatment_library_path()
    if not path.is_file():
        return {"schemaVersion": TREATMENT_LIBRARY_VERSION, "treatments": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != TREATMENT_LIBRARY_VERSION or not isinstance(data.get("treatments"), list):
        raise ValueError("Unsupported treatment-library version.")
    return data


def save_treatment_library(library: dict) -> dict:
    if library.get("schemaVersion") != TREATMENT_LIBRARY_VERSION or not isinstance(library.get("treatments"), list):
        raise ValueError("Invalid treatment-library document.")
    root = default_creator_library()
    if _inside(root, project_root()):
        raise ValueError("The private treatment library must be outside the public Git checkout.")
    root.mkdir(parents=True, exist_ok=True)
    path = treatment_library_path()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return library


def update_treatment_metadata(treatment_id: str, updates: dict) -> tuple[dict, dict]:
    catalog = load_visual_catalog(include_private=False)
    known = {item["id"] for item in [*catalog["modules"], *catalog["recipes"]]}
    if treatment_id not in known:
        raise ValueError("Visual treatment not found.")
    library = load_treatment_library()
    record = next((item for item in library["treatments"] if item.get("id") == treatment_id), None)
    if record is None:
        record = {"id": treatment_id, "createdAt": datetime.now(timezone.utc).isoformat(), "history": []}
        library["treatments"].append(record)
    allowed = {
        "creatorRating",
        "lockedDefault",
        "lockScopes",
        "preferredIntents",
        "allowedLayouts",
        "reusePolicy",
        "notes",
        "archived",
    }
    changed = {key: value for key, value in updates.items() if key in allowed}
    if "creatorRating" in changed:
        rating = int(changed["creatorRating"])
        if rating < 1 or rating > 5:
            raise ValueError("Creator rating must be from 1 to 5.")
        changed["creatorRating"] = rating
    if "allowedLayouts" in changed:
        layouts = changed["allowedLayouts"]
        if not isinstance(layouts, list) or not layouts or any(value not in SCENE_LAYOUTS for value in layouts):
            raise ValueError("Treatment layouts must use the supported eight-layout vocabulary.")
    previous = {key: record.get(key) for key in changed}
    now = datetime.now(timezone.utc).isoformat()
    record.update(changed)
    record["updatedAt"] = now
    if changed:
        record.setdefault("history", []).append({"changedAt": now, "previous": previous, "updates": changed})
    save_treatment_library(library)
    refreshed = load_visual_catalog()
    enriched = next(item for item in [*refreshed["modules"], *refreshed["recipes"]] if item["id"] == treatment_id)
    return enriched, library


def load_creator_library() -> dict:
    path = creator_library_path()
    if not path.is_file():
        return {"schemaVersion": CREATOR_LIBRARY_VERSION, "assets": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != CREATOR_LIBRARY_VERSION:
        raise ValueError(f"Unsupported Creator Library version: {data.get('schemaVersion')}")
    return data


def save_creator_library(library: dict) -> dict:
    root = default_creator_library()
    if _inside(root, project_root()):
        raise ValueError("The private Creator Library must be outside the public Git checkout.")
    for folder in ("ai-footage", "animations", "images", "thumbnails", "metadata"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    path = creator_library_path()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return library


def import_creator_asset(source: Path, metadata: dict | None = None) -> tuple[dict, dict, bool]:
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in ASSET_EXTENSIONS:
        raise ValueError("Choose a supported AI video, animation, or image.")
    checksum = sha256_file(source)
    library = load_creator_library()
    duplicate = next((asset for asset in library["assets"] if asset.get("sha256") == checksum), None)
    if duplicate is not None:
        return duplicate, library, True
    media_type = "video" if source.suffix.lower() in VIDEO_EXTENSIONS else "image"
    category = "ai-footage" if media_type == "video" else "images"
    asset_id = f"creator-{uuid.uuid4().hex[:12]}"
    destination = default_creator_library() / category / f"{asset_id}-{slug(source.stem)}{source.suffix.lower()}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    details = metadata or {}
    duration = None
    width = None
    height = None
    if media_type == "video":
        try:
            probed = probe_visual_source(destination)
            duration, width, height = probed["durationSec"], probed["width"], probed["height"]
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError):
            pass
    now = datetime.now(timezone.utc).isoformat()
    asset = {
        "id": asset_id,
        "name": str(details.get("name") or source.stem.replace("-", " ").replace("_", " ").title()),
        "description": str(details.get("description") or source.stem.replace("-", " ").replace("_", " ")),
        "tags": list(details.get("tags") or _filename_tags(source.stem)),
        "series": str(details.get("series") or ""),
        "tone": list(details.get("tone") or []),
        "provider": str(details.get("provider") or "manual-ai-import"),
        "path": destination.relative_to(default_creator_library()).as_posix(),
        "mediaType": media_type,
        "durationSec": duration,
        "width": width,
        "height": height,
        "importantAction": details.get("importantAction"),
        "audioDefault": details.get("audioDefault", "muted"),
        "favorite": bool(details.get("favorite", False)),
        "archived": False,
        "sha256": checksum,
        "createdAt": now,
        "usageCount": 0,
        "firstUsedAt": None,
        "lastUsedAt": None,
        "usage": [],
    }
    library["assets"].append(asset)
    save_creator_library(library)
    return asset, library, False


def update_creator_asset(asset_id: str, updates: dict) -> tuple[dict, dict]:
    library = load_creator_library()
    asset = next((item for item in library["assets"] if item.get("id") == asset_id), None)
    if asset is None:
        raise ValueError("Creator Library asset not found.")
    for key in ("name", "description", "tags", "series", "tone", "favorite", "archived", "importantAction", "audioDefault", "provider"):
        if key in updates:
            asset[key] = updates[key]
    save_creator_library(library)
    return asset, library


def search_creator_library(query: str = "") -> list[dict]:
    assets = [asset for asset in load_creator_library()["assets"] if not asset.get("archived")]
    terms = set(_tokens(query))
    if not terms:
        return sorted(assets, key=lambda item: (not item.get("favorite", False), -(item.get("usageCount") or 0), item.get("name", "")))
    scored = []
    for asset in assets:
        haystack = " ".join([asset.get("name", ""), asset.get("description", ""), asset.get("series", ""), *asset.get("tags", []), *asset.get("tone", [])])
        score = len(terms.intersection(_tokens(haystack)))
        if score:
            scored.append((score, asset))
    return [asset for _score, asset in sorted(scored, key=lambda item: (-item[0], -(item[1].get("usageCount") or 0)))]


def creator_asset_path(asset_id: str) -> Path:
    asset = next((item for item in load_creator_library()["assets"] if item.get("id") == asset_id), None)
    if asset is None:
        raise ValueError("Creator Library asset not found.")
    path = (default_creator_library() / asset["path"]).resolve()
    if not _inside(path, default_creator_library()) or not path.is_file():
        raise ValueError("Creator Library media is unavailable.")
    return path


def _direct_placement_suggestion(
    plan_path: Path,
    *,
    category: str,
    start_sec: float,
    end_sec: float,
    treatment_id: str,
    purpose: str,
) -> dict:
    """Record media the creator placed by hand as an approved decision.

    The creator dragging an asset onto the timeline *is* the approval, so the decision record
    says so explicitly rather than leaving a cue with no authorising suggestion behind it.
    """
    now = datetime.now(timezone.utc).isoformat()
    start = round(float(start_sec), 3)
    end = round(float(end_sec), 3)
    suggestion = {
        "id": f"placed-{uuid.uuid4().hex[:12]}",
        "status": "built",
        "category": category,
        "timelineLane": "b-roll",
        "startSec": start,
        "endSec": end,
        "editorialPurpose": purpose,
        "scenePacket": {
            "screenshotTimeSec": round((start + end) / 2, 3),
            "purpose": purpose,
            "contentDensity": "creator-selected media",
            "bRollFit": "Chosen by the creator directly against the locked cut.",
            "motionOpportunities": [],
            "spokenBeats": [],
            "protectedRegions": [],
        },
        "meaningfulChanges": [],
        "decision": {
            "status": "approved",
            "selectedTreatmentId": treatment_id,
            "notes": "Placed directly on the timeline by the creator.",
            "decidedBy": "creator-direct-placement",
            "decidedAt": now,
        },
        "rejectionHistory": [],
    }
    data = load_visual_suggestions(plan_path)
    data["suggestions"].append(suggestion)
    save_visual_suggestions(plan_path, data)
    return suggestion


def _authorising_suggestion(
    plan_path: Path,
    suggestion_id: str | None,
    *,
    category: str,
    start_sec: float,
    end_sec: float,
    treatment_id: str,
    purpose: str,
) -> dict:
    if suggestion_id:
        data = load_visual_suggestions(plan_path)
        suggestion = next((item for item in data["suggestions"] if item.get("id") == suggestion_id), None)
        if suggestion is None:
            raise ValueError("Visual suggestion not found.")
        return suggestion
    return _direct_placement_suggestion(
        plan_path,
        category=category,
        start_sec=start_sec,
        end_sec=end_sec,
        treatment_id=treatment_id,
        purpose=purpose,
    )


def freeze_creator_asset(
    plan_path: Path,
    asset_id: str,
    *,
    start_sec: float,
    end_sec: float,
    suggestion_id: str | None = None,
) -> tuple[dict, dict]:
    library = load_creator_library()
    creator = next((item for item in library["assets"] if item.get("id") == asset_id), None)
    if creator is None:
        raise ValueError("Creator Library asset not found.")
    root = find_visual_root(plan_path)
    source = (default_creator_library() / creator["path"]).resolve()
    destination_dir = root / "assets" / "creator-library"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{creator['id']}{source.suffix.lower()}"
    if not destination.is_file() or sha256_file(destination) != creator["sha256"]:
        shutil.copy2(source, destination)
    plan = load_visual_plan(plan_path)
    project_asset_id = f"library-{creator['id']}"
    asset = next((item for item in plan["assets"] if item.get("id") == project_asset_id), None)
    if asset is None:
        asset = {
            "id": project_asset_id,
            "name": creator["name"],
            "path": destination.relative_to(root).as_posix(),
            "mediaType": creator["mediaType"],
            "durationSec": creator.get("durationSec"),
            "hasTransparency": source.suffix.lower() in {".webm", ".png", ".webp"},
            "origin": {"type": "creator-library", "assetId": creator["id"], "sha256": creator["sha256"]},
        }
        plan["assets"].append(asset)
    suggestion = _authorising_suggestion(
        plan_path,
        suggestion_id,
        category="creator-library",
        start_sec=start_sec,
        end_sec=end_sec,
        treatment_id=project_asset_id,
        purpose=f"Creator Library asset: {creator['name']}",
    )
    cue = _asset_cue(asset, start_sec, end_sec, suggestion)
    plan["cues"].append(cue)
    save_visual_plan(plan_path, plan)
    update_suggestion(plan_path, suggestion["id"], {"status": "built", "cueId": cue["id"]})
    now = datetime.now(timezone.utc).isoformat()
    usage = {"projectId": plan["project"]["id"], "timelineStartSec": start_sec, "timelineEndSec": end_sec, "usedAt": now}
    creator["usage"].append(usage)
    creator["usageCount"] = len(creator["usage"])
    creator["firstUsedAt"] = creator.get("firstUsedAt") or now
    creator["lastUsedAt"] = now
    save_creator_library(library)
    return cue, plan


def suggestions_path(plan_path: Path) -> Path:
    return find_visual_root(plan_path) / "visual-production" / "visual-suggestions.json"


def load_visual_suggestions(plan_path: Path) -> dict:
    path = suggestions_path(plan_path)
    if not path.is_file():
        return {"schemaVersion": SUGGESTIONS_VERSION, "suggestions": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    original = json.dumps(data, sort_keys=True, ensure_ascii=False)
    _refresh_suggestion_contract(plan_path, data)
    validate_visual_suggestions(data)
    if json.dumps(data, sort_keys=True, ensure_ascii=False) != original:
        _write_visual_suggestions(path, data, refreshed=True)
    return data


def save_visual_suggestions(plan_path: Path, data: dict) -> dict:
    _refresh_suggestion_contract(plan_path, data)
    validate_visual_suggestions(data)
    path = suggestions_path(plan_path)
    _write_visual_suggestions(path, data, refreshed=True)
    return data


def _participates_in_timeline_contract(suggestion: dict) -> bool:
    """True when a suggestion still occupies a slot in the reviewed visual plan.

    A revision request rejects the selected treatment, not the editorial decision to cover that
    interval. Keeping that unresolved slot in coverage and cadence calculations lets the creator
    save a durable change request while the production gate continues to block rendering until a
    replacement is approved. Bare ``needs-alternatives`` placeholders are not complete decisions
    yet and remain outside the authored contract.
    """
    status = suggestion.get("status")
    if status == "rejected":
        return False
    if status != "needs-alternatives":
        return True
    decision = suggestion.get("decision")
    return isinstance(decision, dict) and decision.get("status") == "revision-requested"


def _write_visual_suggestions(path: Path, data: dict, *, refreshed: bool = False) -> None:
    """Write the decision record. Not a public entry point.

    save_visual_suggestions is the supported way in: it refreshes the app-computed fields before
    validating. Writing around it leaves derived values — approval evidence above all — reflecting
    what the author claimed rather than what is true. Anything written this way is corrected on
    the next load_visual_suggestions, but the guard makes the intent explicit rather than relying
    on that.
    """
    if not refreshed:
        raise RuntimeError(
            "Use save_visual_suggestions to write visual-suggestions.json. It recomputes the "
            "app-owned fields, including approval evidence, before validating."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _refresh_suggestion_contract(plan_path: Path, data: dict) -> None:
    suggestions = [
        item
        for item in data.get("suggestions", [])
        if _participates_in_timeline_contract(item)
    ]
    for suggestion in suggestions:
        if _is_graphic_suggestion(suggestion):
            _refresh_approval_evidence(plan_path, suggestion)
    coverage = data.get("coverage")
    if not isinstance(coverage, dict):
        return
    plan = load_visual_plan(plan_path)
    duration = float(plan["composition"]["durationSec"])
    coverage["runtimeSec"] = duration
    coverage["decisionCounts"] = _decision_counts(suggestions)
    coverage["cadenceAudit"] = _cadence_audit(suggestions, duration)


def _decision_counts(suggestions: list[dict]) -> dict:
    graphics = [item for item in suggestions if _is_graphic_suggestion(item)]
    clean = [item for item in suggestions if item.get("category") == "clean-speaker"]
    protected = [item for item in suggestions if item.get("category") == "protected-footage"]
    b_roll = [
        item
        for item in suggestions
        if item.get("timelineLane") == "b-roll" or item.get("category") in {"stock", "creator-library", "project-asset"}
    ]
    return {
        "timelineDecisions": len(suggestions),
        "graphicTreatments": len(graphics),
        "cleanPerformanceHolds": len(clean),
        "protectedFootageDecisions": len(protected),
        "bRollDecisions": len(b_roll),
        "unresolvedApprovals": sum(1 for item in suggestions if (item.get("decision") or {}).get("status") != "approved"),
    }


def _merged_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1] + 0.001:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _uncovered_intervals(
    start: float,
    end: float,
    covered_intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Return the parts of one interval that no rendered treatment covers."""
    covered = _merged_intervals([
        (max(start, covered_start), min(end, covered_end))
        for covered_start, covered_end in covered_intervals
        if covered_end > start and covered_start < end
    ])
    uncovered: list[tuple[float, float]] = []
    cursor = start
    for covered_start, covered_end in covered:
        if covered_start > cursor + 0.001:
            uncovered.append((cursor, covered_start))
        cursor = max(cursor, covered_end)
    if cursor < end - 0.001:
        uncovered.append((cursor, end))
    return uncovered


def _renders_something(suggestion: dict) -> bool:
    """True when this scene puts an actual rendered treatment on screen.

    A clean-speaker or protected-footage scene with no treatment renders bare source footage.
    Whatever its meaningfulChanges say, nothing happens on screen during it.
    """
    if suggestion.get("moduleId") in (MODULE_IDS - {"source-footage-hold"}):
        return True
    if suggestion.get("recipeId"):
        return True
    return suggestion.get("category") in {"creator-library", "project-asset", "stock", "ai-brief"}


def _cadence_audit(suggestions: list[dict], duration: float) -> dict:
    covered = _merged_intervals([
        (max(0.0, float(item["startSec"])), min(duration, float(item["endSec"])))
        for item in suggestions
    ])
    coverage_violations: list[dict] = []
    cursor = 0.0
    for start, end in covered:
        if start > cursor + 0.05:
            coverage_violations.append({"startSec": round(cursor, 3), "endSec": round(start, 3), "reason": "No editorial visual decision covers this part of the locked cut."})
        cursor = max(cursor, end)
    if cursor < duration - 0.05:
        coverage_violations.append({"startSec": round(cursor, 3), "endSec": round(duration, 3), "reason": "No editorial visual decision covers this part of the locked cut."})

    # The cadence rule applies to the entire runtime, with no exemption anywhere. Protected
    # footage means no overlay may cover it, not that nothing happens: it still earns a punch
    # zoom, reframe, or callout every five seconds.
    cadence_segments: list[tuple[float, float]] = [(0.0, duration)]

    # Only events that actually render count. A meaningfulChange inside a scene with no treatment
    # is a sentence in a JSON file: writing {"kind": "punch-zoom"} against bare source footage
    # produces no movement. Counting those let a plan satisfy the pacing rule while leaving most
    # of the video visually dead.
    events: set[float] = set()
    for item in suggestions:
        if not _renders_something(item):
            continue
        events.add(max(0.0, min(duration, float(item["startSec"]))))
        events.add(max(0.0, min(duration, float(item["endSec"]))))
        for change in item.get("meaningfulChanges", []):
            if isinstance(change, dict):
                try:
                    events.add(max(0.0, min(duration, float(change["timeSec"]))))
                except (KeyError, TypeError, ValueError):
                    pass
    cadence_violations: list[dict] = []
    max_gap = 0.0
    for start, end in cadence_segments:
        points = sorted({start, end, *(value for value in events if start < value < end)})
        for left, right in zip(points, points[1:]):
            gap = right - left
            max_gap = max(max_gap, gap)
            if gap > MAX_MEANINGFUL_CHANGE_GAP_SEC + 0.001:
                cadence_violations.append({
                    "startSec": round(left, 3),
                    "endSec": round(right, 3),
                    "reason": (
                        f"No meaningful visual change is scheduled between {left:.1f}s and "
                        f"{right:.1f}s. Every five seconds needs a graphic, reveal, callout, "
                        "punch zoom, or callout that actually renders."
                    ),
                })
    return {
        "maxAllowedGapSec": MAX_MEANINGFUL_CHANGE_GAP_SEC,
        "maxObservedGapSec": round(max_gap, 3),
        "meaningfulChangeCount": len(events),
        "completeCoverage": not coverage_violations,
        "violations": [*coverage_violations, *cadence_violations],
    }


def approval_sample_path(plan_path: Path, suggestion_id: str, treatment_id: str) -> Path:
    safe_suggestion = slug(suggestion_id)
    safe_treatment = slug(treatment_id)
    return find_visual_root(plan_path) / "previews" / "visual" / "approval-samples" / f"{safe_suggestion}-{safe_treatment}.png"


def approval_sample_receipt_path(sample: Path) -> Path:
    return sample.with_suffix(".receipt.json")


def _write_sample_receipt(sample: Path, *, suggestion_id: str, treatment_id: str) -> None:
    """Sign a sample frame the app rendered, so a drawing cannot stand in for a render."""
    approval_sample_receipt_path(sample).write_text(
        json.dumps({
            "renderedBy": "hyperframes",
            "suggestionId": suggestion_id,
            "treatmentId": treatment_id,
            "sha256": sha256_file(sample),
            "renderedAt": datetime.now(timezone.utc).isoformat(),
        }, indent=2),
        encoding="utf-8",
    )


def sample_receipt_problem(sample: Path, *, suggestion_id: str, treatment_id: str) -> str | None:
    """Return why this sample is not usable as evidence, or None when it is.

    Approval evidence exists so the creator approves the thing that will actually render. A PNG
    with no receipt was produced some other way — by hand, by another tool, or for another
    treatment — and approving it approves nothing.
    """
    if not sample.is_file():
        return "the sample frame is missing"
    receipt_path = approval_sample_receipt_path(sample)
    if not receipt_path.is_file():
        return (
            "the sample frame has no render receipt, so it was not produced by HyperFrames. "
            "Register the treatment and let the app render the sample; a drawing is not evidence"
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "the sample frame's render receipt cannot be read"
    if receipt.get("renderedBy") != "hyperframes":
        return "the sample frame was not rendered by HyperFrames"
    if receipt.get("treatmentId") != treatment_id:
        return f"the sample frame was rendered for {receipt.get('treatmentId')}, not {treatment_id}"
    if receipt.get("suggestionId") != suggestion_id:
        return f"the sample frame was rendered for suggestion {receipt.get('suggestionId')}"
    if receipt.get("sha256") != sha256_file(sample):
        return "the sample frame changed after it was rendered"
    return None


def _refresh_approval_evidence(plan_path: Path, suggestion: dict) -> None:
    selected = str(suggestion.get("moduleId") or suggestion.get("recipeId") or "")
    if not selected:
        suggestion.pop("approvalEvidence", None)
        return
    packet = suggestion.get("scenePacket") if isinstance(suggestion.get("scenePacket"), dict) else {}
    source_time = float(packet.get("screenshotTimeSec") or suggestion["startSec"])
    existing = suggestion.get("approvalEvidence") if isinstance(suggestion.get("approvalEvidence"), dict) else {}
    scene_start = float(suggestion["startSec"])
    scene_end = float(suggestion["endSec"])
    default_representative = min(scene_end, scene_start + min(1.0, max(0.05, (scene_end - scene_start) / 2)))
    representative_time = float(existing.get("representativeTimeSec") or default_representative)
    representative_state = str(existing.get("representativeState") or "Representative resolved treatment state")
    historical = recipe_preview_path(selected, require_recipe=False)
    supplied_ref = str(existing.get("sampleFramePath") or "")
    supplied = None
    if supplied_ref:
        try:
            supplied = resolve_project_path(find_visual_root(plan_path), supplied_ref)
        except ValueError:
            supplied = None
    # A sample only counts when the app rendered it and signed it. Existence of a PNG proves
    # nothing: a hand-drawn mockup at the expected path used to be accepted as evidence.
    expected = approval_sample_path(plan_path, suggestion["id"], selected)
    candidate = supplied if supplied is not None else expected
    receipt_problem = sample_receipt_problem(candidate, suggestion_id=str(suggestion["id"]), treatment_id=selected)
    # A signed exact sample is stronger evidence than a generic historical example. Keeping the
    # historical frame first made scene-specific comparisons look like they still contained the
    # old project's labels even after their parameters were corrected.
    if receipt_problem is None:
        status = "sample-ready"
        sample_ref = candidate.relative_to(find_visual_root(plan_path)).as_posix()
        problem = None
    elif historical is not None:
        status, sample_ref, problem = "historical-ready", None, None
    else:
        status, sample_ref, problem = "sample-required", None, receipt_problem
    evidence = {
        "status": status,
        "selectedTreatmentId": selected,
        "sourceFrameTimeSec": source_time,
        "representativeTimeSec": representative_time,
        "representativeState": representative_state,
    }
    if sample_ref:
        evidence["sampleFramePath"] = sample_ref
    if problem:
        evidence["blockedReason"] = problem
    suggestion["approvalEvidence"] = evidence


def validate_visual_suggestions(data: dict) -> None:
    _validate_visual_suggestion_rules(data)
    # The schema runs after the domain rules so that a rule violation reports the rule rather
    # than a generic path, and still cannot be skipped.
    validate_document_schema("visual-suggestions", data, label="visual-suggestions.json")


def _validate_visual_suggestion_rules(data: dict) -> None:
    if data.get("schemaVersion") != SUGGESTIONS_VERSION:
        raise ValueError("Unsupported visual-suggestions version.")
    coverage = data.get("coverage")
    graphics_present = any(
        _is_graphic_suggestion(item) and _participates_in_timeline_contract(item)
        for item in data.get("suggestions", [])
    )
    if graphics_present and not isinstance(coverage, dict):
        raise ValueError(
            "A plan containing authored graphics needs a coverage block with reuseAudit and bRollAudit. "
            "The audit is how the reuse and B-roll decisions are recorded; it is not optional."
        )
    if coverage is not None:
        if not isinstance(coverage, dict):
            raise ValueError("Visual suggestion coverage must be an object.")
        reuse = coverage.get("reuseAudit")
        b_roll = coverage.get("bRollAudit")
        if not isinstance(reuse, dict) or not isinstance(b_roll, dict):
            raise ValueError("Visual suggestion coverage requires reuseAudit and bRollAudit.")
        for key in ("reusedModuleIds", "reusedRecipeIds", "creatorLibraryQueries", "bespokeRationales"):
            values = reuse.get(key)
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"Visual suggestion reuseAudit {key} must be a list of non-empty strings.")
        if not isinstance(reuse.get("reviewed"), bool) or not isinstance(b_roll.get("reviewed"), bool):
            raise ValueError("Visual suggestion coverage reviewed flags must be booleans.")
        if reuse.get("contractVersion") != SUGGESTIONS_CONTRACT_VERSION:
            raise ValueError(
                f"Visual suggestion reuseAudit contractVersion must be {SUGGESTIONS_CONTRACT_VERSION}. "
                "Lowering it used to disable the approval contract, the planning gate, and the "
                "library harvest; there is only one contract now."
            )
        if b_roll.get("decision") not in {"planned", "not-suitable"} or not str(b_roll.get("rationale") or "").strip():
            raise ValueError("Visual suggestion bRollAudit needs a decision and rationale.")
    ids = set()
    graphic_suggestions = []
    for suggestion in data.get("suggestions", []):
        if not suggestion.get("id") or suggestion["id"] in ids:
            raise ValueError("Every visual suggestion needs a unique id.")
        ids.add(suggestion["id"])
        if suggestion.get("status", "proposed") not in SUGGESTION_STATUSES:
            raise ValueError("Unknown visual suggestion status.")
        if suggestion.get("category") not in SUGGESTION_CATEGORIES:
            raise ValueError("Unknown visual suggestion category.")
        if suggestion.get("timelineLane") not in {None, "graphics", "b-roll", "ai-footage"}:
            raise ValueError("Unknown visual suggestion timeline lane.")
        if float(suggestion.get("endSec") or 0) <= float(suggestion.get("startSec") or 0):
            raise ValueError("Visual suggestion end must be after start.")
        if _participates_in_timeline_contract(suggestion) and _is_graphic_suggestion(suggestion):
            graphic_suggestions.append(suggestion)
    if coverage is not None and coverage["bRollAudit"]["decision"] == "planned":
        if not any(item.get("timelineLane") == "b-roll" or item.get("category") == "stock" for item in data.get("suggestions", [])):
            raise ValueError("A planned B-roll audit requires at least one B-roll suggestion.")
    if coverage is not None:
        if not coverage["reuseAudit"]["reviewed"]:
            raise ValueError(
                "The reuse audit must be completed before the plan is saved. "
                "Marking it unreviewed used to skip every graphic-treatment check."
            )
        has_graphics = bool(graphic_suggestions)
        reused = any(coverage["reuseAudit"][key] for key in ("reusedModuleIds", "reusedRecipeIds", "creatorLibraryQueries"))
        if has_graphics and not reused and not coverage["reuseAudit"]["bespokeRationales"]:
            raise ValueError("A reuse audit with graphic suggestions must record a reused source or a bespoke rationale.")
        _validate_graphic_suggestion_contract(graphic_suggestions, coverage["reuseAudit"])
        _validate_approval_contract(data)


def _is_graphic_suggestion(suggestion: dict) -> bool:
    return suggestion.get("timelineLane") == "graphics" or suggestion.get("category") == "graphic"


def _validate_graphic_suggestion_contract(suggestions: list[dict], reuse_audit: dict) -> None:
    catalog = load_visual_catalog()
    module_ids = {item["id"] for item in catalog["modules"]}
    recipe_ids = {item["id"] for item in catalog["recipes"]}
    valid_treatment_ids = module_ids | recipe_ids
    selected_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    previous: dict | None = None

    for suggestion in sorted(suggestions, key=lambda item: (float(item["startSec"]), float(item["endSec"]))):
        suggestion_id = suggestion["id"]
        selected_ids = [value for value in (suggestion.get("moduleId"), suggestion.get("recipeId")) if value]
        if len(selected_ids) != 1:
            raise ValueError(f"Graphic suggestion {suggestion_id} must select exactly one registered moduleId or recipeId.")
        selected_id = str(selected_ids[0])
        if selected_id not in valid_treatment_ids:
            raise ValueError(f"Graphic suggestion {suggestion_id} selects an unknown treatment: {selected_id}.")
        # moduleId names something the renderer can execute; recipeId names a catalog entry that
        # still needs realizing. Crossing them made an unbuildable recipe look renderable.
        if suggestion.get("moduleId") and selected_id not in module_ids:
            raise ValueError(f"Graphic suggestion {suggestion_id} puts recipe {selected_id} in moduleId; recipes belong in recipeId.")
        if suggestion.get("recipeId") and selected_id not in recipe_ids:
            raise ValueError(f"Graphic suggestion {suggestion_id} puts module {selected_id} in recipeId; modules belong in moduleId.")

        candidates = suggestion.get("candidateTreatmentIds")
        if not isinstance(candidates, list) or any(not isinstance(value, str) or value not in valid_treatment_ids for value in candidates) or len(set(candidates)) < 3:
            raise ValueError(f"Graphic suggestion {suggestion_id} must compare at least three valid module or recipe candidates.")
        if selected_id not in candidates:
            raise ValueError(f"Graphic suggestion {suggestion_id} selected treatment must appear in candidateTreatmentIds.")
        if not str(suggestion.get("selectionRationale") or "").strip():
            raise ValueError(f"Graphic suggestion {suggestion_id} needs a treatment selection rationale.")
        family = str(suggestion.get("visualFamily") or "").strip()
        if not family:
            raise ValueError(f"Graphic suggestion {suggestion_id} needs a visualFamily for repetition checks.")

        _validate_speaker_safety(suggestion)

        intentional_repeat = suggestion.get("intentionalRepeat") is True
        if previous is not None and family == previous["visualFamily"] and not intentional_repeat:
            raise ValueError(
                f"Graphic suggestion {suggestion_id} repeats visual family {family} immediately after {previous['id']}; "
                "choose another family or document an intentional repeat."
            )
        selected_counts[selected_id] = selected_counts.get(selected_id, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1
        if selected_counts[selected_id] > 2 and not intentional_repeat:
            raise ValueError(f"Treatment {selected_id} is used more than twice; later uses must be documented intentional callbacks.")
        if intentional_repeat and not str(suggestion.get("repeatRationale") or "").strip():
            raise ValueError(f"Graphic suggestion {suggestion_id} marks an intentional repeat but has no repeatRationale.")

        if float(suggestion["endSec"]) - float(suggestion["startSec"]) < MIN_GRAPHIC_DURATION_SEC:
            raise ValueError(
                f"Graphic suggestion {suggestion_id} runs for "
                f"{float(suggestion['endSec']) - float(suggestion['startSec']):.2f}s. A graphic that flashes "
                f"for less than {MIN_GRAPHIC_DURATION_SEC:.0f}s reads as a glitch, not a visual event."
            )

        if suggestion.get("moduleId") and selected_id not in reuse_audit["reusedModuleIds"]:
            raise ValueError(f"Graphic suggestion {suggestion_id} module {selected_id} is missing from coverage.reuseAudit.reusedModuleIds.")
        if suggestion.get("recipeId") and selected_id not in reuse_audit["reusedRecipeIds"]:
            raise ValueError(f"Graphic suggestion {suggestion_id} recipe {selected_id} is missing from coverage.reuseAudit.reusedRecipeIds.")
        previous = {"id": suggestion_id, "visualFamily": family}

    _validate_treatment_variety(selected_counts, family_counts)


def _validate_treatment_variety(selected_counts: dict[str, int], family_counts: dict[str, int]) -> None:
    """Bound how much of a plan any one device may carry.

    The per-scene rules are all escapable by declaring intentionalRepeat, which is correct for a
    genuine callback and useless as a variety control: one pass marked 154 of 165 graphics
    intentional and became 46% punch zooms and 38% callouts. These ceilings are proportions of the
    finished plan, so no per-scene flag reaches them.
    """
    total = sum(selected_counts.values())
    if total < 8:
        return
    ranked = sorted(selected_counts.items(), key=lambda item: -item[1])
    worst_id, worst_count = ranked[0]
    if worst_count / total > MAX_TREATMENT_SHARE:
        raise ValueError(
            f"{worst_id} carries {worst_count} of {total} graphics ({worst_count / total * 100:.0f}%). "
            f"No treatment may exceed {MAX_TREATMENT_SHARE * 100:.0f}% of the plan. "
            "Vary the device, not just the copy inside it."
        )
    if len(ranked) >= 2:
        top_two = ranked[0][1] + ranked[1][1]
        if top_two / total > MAX_TOP_TWO_SHARE:
            raise ValueError(
                f"{ranked[0][0]} and {ranked[1][0]} together carry {top_two} of {total} graphics "
                f"({top_two / total * 100:.0f}%). Two devices may not exceed "
                f"{MAX_TOP_TWO_SHARE * 100:.0f}% of the plan; the video reads as the same beat repeating."
            )
    families = sorted(family_counts.items(), key=lambda item: -item[1])
    if families and families[0][1] / total > MAX_TREATMENT_SHARE:
        raise ValueError(
            f"The {families[0][0]} family carries {families[0][1]} of {total} graphics "
            f"({families[0][1] / total * 100:.0f}%). Renaming the treatment does not create variety; "
            f"no visual family may exceed {MAX_TREATMENT_SHARE * 100:.0f}% of the plan."
        )


def _validate_approval_contract(data: dict) -> None:
    coverage = data["coverage"]
    variation = coverage.get("variationAudit")
    if not isinstance(variation, dict) or not isinstance(variation.get("reviewed"), bool):
        raise ValueError("Contract-version-three suggestions require a variationAudit.")
    for key in ("familyCounts", "treatmentCounts"):
        counts = variation.get(key)
        if not isinstance(counts, dict) or any(
            not isinstance(name, str) or not isinstance(count, int) or count < 0
            for name, count in counts.items()
        ):
            raise ValueError(f"Visual suggestion variationAudit {key} must contain non-negative integer counts.")
    if not isinstance(variation.get("intentionalSeriesIds"), list) or not isinstance(variation.get("warnings"), list):
        raise ValueError("Visual suggestion variationAudit needs intentionalSeriesIds and warnings lists.")
    counts = coverage.get("decisionCounts")
    cadence = coverage.get("cadenceAudit")
    if not isinstance(counts, dict):
        raise ValueError("Contract-version-three suggestions require computed decisionCounts.")
    if not isinstance(cadence, dict) or float(cadence.get("maxAllowedGapSec") or 0) != MAX_MEANINGFUL_CHANGE_GAP_SEC:
        raise ValueError("Contract-version-three suggestions require the five-second cadenceAudit.")

    catalog = load_visual_catalog()
    treatments = {item["id"]: item for item in [*catalog["modules"], *catalog["recipes"]]}
    rendered_intervals = [
        (float(item["startSec"]), float(item["endSec"]))
        for item in data.get("suggestions", [])
        if _participates_in_timeline_contract(item) and _renders_something(item)
    ]
    for suggestion in data.get("suggestions", []):
        suggestion_id = str(suggestion.get("id") or "unnamed suggestion")
        is_graphic = _is_graphic_suggestion(suggestion)
        packet = suggestion.get("scenePacket")
        if not isinstance(packet, dict):
            raise ValueError(f"Suggestion {suggestion_id} needs a complete scenePacket.")
        layout = packet.get("layout")
        # Layout drives speaker-geometry lookup and ranked-candidate compatibility, both of which
        # only apply to graphics. Media suggestions must still describe the scene, but the app
        # places b-roll and library assets itself and cannot measure a recording layout.
        if is_graphic and layout not in SCENE_LAYOUTS:
            raise ValueError(f"Suggestion {suggestion_id} uses an unknown scene layout.")
        if not is_graphic and layout is not None and layout not in SCENE_LAYOUTS:
            raise ValueError(f"Suggestion {suggestion_id} uses an unknown scene layout.")
        screenshot_time = _finite_number(packet.get("screenshotTimeSec"), f"Suggestion {suggestion_id} screenshotTimeSec")
        if screenshot_time < float(suggestion["startSec"]) or screenshot_time > float(suggestion["endSec"]):
            raise ValueError(f"Suggestion {suggestion_id} screenshotTimeSec must stay inside the scene.")
        for key in ("purpose", "contentDensity", "bRollFit"):
            if not str(packet.get(key) or "").strip():
                raise ValueError(f"Suggestion {suggestion_id} scenePacket needs {key}.")
        for key in ("motionOpportunities", "spokenBeats", "protectedRegions"):
            if not isinstance(packet.get(key), list):
                raise ValueError(f"Suggestion {suggestion_id} scenePacket needs {key}.")

        if suggestion.get("status") == "rejected":
            continue
        start = float(suggestion["startSec"])
        end = float(suggestion["endSec"])

        # Protected/clean decisions describe what the source must preserve; they do not prohibit
        # a treatment beside that region. Bound only the portions that truly remain bare.
        if suggestion.get("category") in {"protected-footage", "clean-speaker"}:
            uncovered = _uncovered_intervals(start, end, rendered_intervals)
            longest_uncovered = max((gap_end - gap_start for gap_start, gap_end in uncovered), default=0.0)
            if longest_uncovered > MAX_PROTECTED_SPAN_SEC + 0.001:
                raise ValueError(
                    f"Suggestion {suggestion_id} leaves {longest_uncovered:.1f}s of the video with nothing "
                    f"on screen. A protected moment may run at most {MAX_PROTECTED_SPAN_SEC:.0f}s. "
                    "To keep a demonstration readable for longer, put a treatment beside it and list "
                    "the exact area that must stay visible in scenePacket.protectedRegions."
                )

        # On a screen-share layout the frame is mostly application. A graphic there must say which
        # part of the screen has to stay readable, so it can sit beside the demonstration instead
        # of the demonstration being declared off-limits.
        if is_graphic and layout in SCENE_LAYOUTS and is_screen_share_layout(layout):
            if not packet.get("protectedRegions"):
                raise ValueError(
                    f"Graphic suggestion {suggestion_id} runs over {layout}, where the frame is mostly "
                    "application. List the screen area that must stay readable in "
                    "scenePacket.protectedRegions so the graphic can be placed clear of it."
                )

        changes = suggestion.get("meaningfulChanges")
        if not isinstance(changes, list):
            raise ValueError(f"Suggestion {suggestion_id} needs meaningfulChanges, even when the list is empty.")
        for change in changes:
            if not isinstance(change, dict):
                raise ValueError(f"Suggestion {suggestion_id} has an invalid meaningful change.")
            change_time = _finite_number(change.get("timeSec"), f"Suggestion {suggestion_id} meaningful change timeSec")
            if change_time < start or change_time > end:
                raise ValueError(f"Suggestion {suggestion_id} meaningful changes must stay inside the scene.")
            if change.get("kind") not in MEANINGFUL_CHANGE_KINDS or not str(change.get("description") or "").strip():
                raise ValueError(f"Suggestion {suggestion_id} meaningful changes need a supported kind and description.")
        if is_graphic:
            ranked = suggestion.get("rankedCandidates")
            if not isinstance(ranked, list) or len(ranked) < 3:
                raise ValueError(f"Graphic suggestion {suggestion_id} needs at least three rankedCandidates.")
            ranks = set()
            for candidate in ranked:
                if not isinstance(candidate, dict) or candidate.get("treatmentId") not in treatments:
                    raise ValueError(f"Graphic suggestion {suggestion_id} has an unknown ranked candidate.")
                if not isinstance(candidate.get("rank"), int) or candidate["rank"] < 1 or candidate["rank"] in ranks:
                    raise ValueError(f"Graphic suggestion {suggestion_id} candidate ranks must be unique positive integers.")
                ranks.add(candidate["rank"])
                if layout not in treatments[candidate["treatmentId"]].get("allowedLayouts", []):
                    raise ValueError(
                        f"Graphic suggestion {suggestion_id} candidate {candidate['treatmentId']} is not compatible with {layout}."
                    )
                if not str(candidate.get("fitReason") or "").strip():
                    raise ValueError(f"Graphic suggestion {suggestion_id} candidates need fitReason.")
            evidence = suggestion.get("approvalEvidence")
            if not isinstance(evidence, dict):
                raise ValueError(f"Graphic suggestion {suggestion_id} needs approvalEvidence.")
            selected = str(suggestion.get("moduleId") or suggestion.get("recipeId") or "")
            if evidence.get("selectedTreatmentId") != selected:
                raise ValueError(f"Graphic suggestion {suggestion_id} approval evidence must match its selected treatment.")
            if evidence.get("status") not in {"historical-ready", "sample-ready", "sample-required"}:
                raise ValueError(f"Graphic suggestion {suggestion_id} has an invalid approvalEvidence status.")
            for key in ("sourceFrameTimeSec", "representativeTimeSec"):
                value = _finite_number(evidence.get(key), f"Graphic suggestion {suggestion_id} approvalEvidence {key}")
                if value < start or value > end:
                    raise ValueError(f"Graphic suggestion {suggestion_id} approval evidence times must stay inside the scene.")
            if not str(evidence.get("representativeState") or "").strip():
                raise ValueError(f"Graphic suggestion {suggestion_id} approval evidence needs representativeState.")
            if evidence.get("status") == "sample-ready" and not str(evidence.get("sampleFramePath") or "").strip():
                raise ValueError(f"Graphic suggestion {suggestion_id} sample evidence needs sampleFramePath.")
        decision = suggestion.get("decision")
        if not isinstance(decision, dict) or decision.get("status") not in {"pending", "approved", "revision-requested"}:
            raise ValueError(f"Suggestion {suggestion_id} needs a planning decision.")
        if decision.get("status") == "approved":
            selected = str(decision.get("selectedTreatmentId") or suggestion.get("moduleId") or suggestion.get("recipeId") or "")
            current = str(suggestion.get("moduleId") or suggestion.get("recipeId") or "")
            # A Loop B note may swap the treatment. The swap must be re-approved rather than
            # inheriting the approval that was granted for the treatment it replaced.
            if is_graphic and current and selected != current:
                raise ValueError(
                    f"Suggestion {suggestion_id} now selects {current} but still carries an approval for {selected}. "
                    "Re-approve the scene after swapping its treatment."
                )
            if is_graphic and selected not in treatments:
                raise ValueError(f"Suggestion {suggestion_id} approval needs a registered selected treatment.")
            if is_graphic and selected not in {item.get("treatmentId") for item in suggestion.get("rankedCandidates", [])}:
                raise ValueError(f"Suggestion {suggestion_id} approved treatment must be one of its ranked candidates.")
            if not str(decision.get("decidedAt") or "").strip():
                raise ValueError(f"Suggestion {suggestion_id} approved decision needs decidedAt.")
            if is_graphic and (suggestion.get("approvalEvidence") or {}).get("status") not in APPROVAL_EVIDENCE_READY:
                raise ValueError(f"Suggestion {suggestion_id} cannot be approved until its exact visual evidence is ready.")
        history = suggestion.get("rejectionHistory", [])
        if not isinstance(history, list) or any(
            not isinstance(item, dict) or not str(item.get("notes") or "").strip()
            for item in history
        ):
            raise ValueError(f"Suggestion {suggestion_id} has an invalid rejectionHistory.")


def _finite_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be numeric.") from None
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{label} must be finite.")
    return number


def _validate_speaker_safety(suggestion: dict) -> None:
    """Raise on the first speaker-safety problem.

    The rules themselves live in visual_production.speaker_safety_issues so that the suggestion
    validator and the production gate cannot disagree about what is safe.
    """
    issues = speaker_safety_issues(
        f"Graphic suggestion {suggestion['id']}",
        suggestion.get("speakerSafety"),
        (suggestion.get("scenePacket") or {}).get("layout"),
        start_sec=float(suggestion["startSec"]),
        end_sec=float(suggestion["endSec"]),
    )
    if issues:
        raise ValueError(issues[0])


def update_suggestion(plan_path: Path, suggestion_id: str, updates: dict) -> dict:
    data = load_visual_suggestions(plan_path)
    suggestion = next((item for item in data["suggestions"] if item.get("id") == suggestion_id), None)
    if suggestion is None:
        raise ValueError("Visual suggestion not found.")
    suggestion.update(updates)
    reuse = ((data.get("coverage") or {}).get("reuseAudit") or {})
    if reuse:
        active_graphics = [
            item
            for item in data["suggestions"]
            if _is_graphic_suggestion(item) and item.get("status") != "rejected"
        ]
        reuse["reusedModuleIds"] = list(dict.fromkeys(
            str(item["moduleId"]) for item in active_graphics if item.get("moduleId")
        ))
        reuse["reusedRecipeIds"] = list(dict.fromkeys(
            str(item["recipeId"]) for item in active_graphics if item.get("recipeId")
        ))
        variation = data["coverage"].setdefault("variationAudit", {
            "reviewed": False,
            "familyCounts": {},
            "treatmentCounts": {},
            "intentionalSeriesIds": [],
            "warnings": [],
        })
        variation["familyCounts"] = _count_values(str(item.get("visualFamily") or "") for item in active_graphics)
        variation["treatmentCounts"] = _count_values(
            str(item.get("moduleId") or item.get("recipeId") or "")
            for item in active_graphics
        )
    save_visual_suggestions(plan_path, data)
    return suggestion


def _count_values(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def decide_suggestion(
    plan_path: Path,
    suggestion_id: str,
    *,
    action: str,
    notes: str = "",
) -> tuple[dict, dict, dict]:
    data = load_visual_suggestions(plan_path)
    suggestion = next((item for item in data["suggestions"] if item.get("id") == suggestion_id), None)
    if suggestion is None:
        raise ValueError("Visual suggestion not found.")
    if action not in {"approve", "reject", "request-another", "approve-series"}:
        raise ValueError("Unknown planning decision.")
    now = datetime.now(timezone.utc).isoformat()
    selected = suggestion.get("moduleId") or suggestion.get("recipeId")
    if _is_graphic_suggestion(suggestion) and not selected:
        raise ValueError("Choose a ranked visual treatment before approving or rejecting this scene.")

    target_ids = [suggestion_id]
    if action == "approve-series":
        series_id = str(suggestion.get("seriesId") or "")
        if not series_id:
            raise ValueError("This scene is not part of an intentional series.")
        target_ids = [
            item["id"]
            for item in data["suggestions"]
            if item.get("seriesId") == series_id and item.get("status") != "rejected"
        ]

    plan = load_visual_plan(plan_path)
    for item in data["suggestions"]:
        if item.get("id") not in target_ids:
            continue
        item_selected = item.get("moduleId") or item.get("recipeId")
        if action in {"approve", "approve-series"}:
            if _is_graphic_suggestion(item):
                evidence = item.get("approvalEvidence") if isinstance(item.get("approvalEvidence"), dict) else {}
                if evidence.get("status") not in APPROVAL_EVIDENCE_READY:
                    raise ValueError("Prepare the exact one-frame sample or historical treatment example before approving this scene.")
                if evidence.get("selectedTreatmentId") != item_selected:
                    raise ValueError("The approval evidence does not match the selected treatment.")
                _validate_speaker_safety(item)
            item["decision"] = {
                "status": "approved",
                "selectedTreatmentId": item_selected,
                "notes": notes.strip(),
                "decidedAt": now,
            }
            if item.get("status") not in {"built", "prepared"}:
                item["status"] = "approved"
        else:
            reason = notes.strip()
            if not reason:
                raise ValueError("Add a rejection note so the producer knows what to change.")
            item.setdefault("rejectionHistory", []).append({
                "selectedTreatmentId": item_selected,
                "notes": reason,
                "rejectedAt": now,
            })
            item["decision"] = {
                "status": "revision-requested",
                "selectedTreatmentId": item_selected,
                "notes": reason,
                "decidedAt": now,
            }
            item["status"] = "needs-alternatives"
            review = next(
                (
                    value
                    for value in plan.get("reviews", [])
                    if value.get("itemType") == "suggestion" and value.get("itemId") == item["id"]
                ),
                None,
            )
            if review is None:
                plan.setdefault("reviews", []).append({
                    "id": f"review-{uuid.uuid4().hex[:12]}",
                    "itemId": item["id"],
                    "itemType": "suggestion",
                    "startSec": float(item["startSec"]),
                    "endSec": float(item["endSec"]),
                    "note": reason,
                    "directive": "replace-all" if action == "request-another" else "targeted",
                    "status": "changes-requested",
                    "createdAt": now,
                    "updatedAt": now,
                })
            else:
                review.update({
                    "note": reason,
                    "directive": "replace-all" if action == "request-another" else "targeted",
                    "status": "changes-requested",
                    "updatedAt": now,
                })
    save_visual_suggestions(plan_path, data)
    plan = save_visual_plan(plan_path, plan)
    refreshed = next(item for item in data["suggestions"] if item.get("id") == suggestion_id)
    return refreshed, data, plan


def load_visual_catalog(*, include_private: bool = True) -> dict:
    root = project_root() / "visual-production"
    modules = json.loads((root / "modules" / "catalog.json").read_text(encoding="utf-8"))
    recipes = json.loads((root / "recipes" / "catalog.json").read_text(encoding="utf-8"))
    private = {}
    if include_private:
        private = {
            item["id"]: item
            for item in load_treatment_library().get("treatments", [])
            if item.get("id")
        }

    def enrich(item: dict, kind: str) -> dict:
        override = private.get(item["id"], {})
        preview = recipe_preview_path(item["id"], require_recipe=False)
        merged = {
            **item,
            **{
                key: value
                for key, value in override.items()
                if key not in {"id", "history", "createdAt", "updatedAt"}
            },
        }
        merged.update({
            "kind": kind,
            "previewAvailable": preview is not None,
            "motionPreviewAvailable": (default_creator_library() / "motion-previews" / f"{item['id']}.mp4").is_file(),
            "creatorRating": int(merged.get("creatorRating") or 0),
            "lockedDefault": bool(merged.get("lockedDefault", False)),
            "lockScopes": list(merged.get("lockScopes") or []),
            "usageCount": int(merged.get("usageCount") or 0),
        })
        return merged

    return {
        "layouts": sorted(SCENE_LAYOUTS),
        "modules": [enrich(item, "module") for item in modules.get("modules", [])],
        "recipes": [enrich(item, "recipe") for item in recipes.get("recipes", [])],
    }


def _delivered_suggestions(data: dict, plan: dict) -> list[dict]:
    """Select the suggestions that actually survived production, not the ones approved on paper.

    Loop A approves a still frame; Loop B reviews the render. A treatment that was approved from a
    frame and then noted in the full review must not be filed as a good example, so qualification
    is tied to the cue that rendered and to the absence of an unresolved note against it.
    """
    enabled_cues = {cue.get("id") for cue in plan.get("cues", []) if cue.get("enabled", True)}
    noted = {
        (str(review.get("itemType")), str(review.get("itemId")))
        for review in plan.get("reviews", [])
        if str(review.get("note") or "").strip()
    }
    delivered = []
    for suggestion in data.get("suggestions", []):
        decision = suggestion.get("decision") if isinstance(suggestion.get("decision"), dict) else {}
        cue_id = suggestion.get("cueId")
        if decision.get("status") != "approved" or suggestion.get("status") != "built":
            continue
        if cue_id not in enabled_cues:
            continue
        if ("suggestion", str(suggestion.get("id"))) in noted or ("cue", str(cue_id)) in noted:
            continue
        delivered.append(suggestion)
    return delivered


def record_treatment_usage(plan_path: Path, final_render: Path) -> dict:
    """Harvest each delivered treatment into the Creator Library.

    Returns a report rather than a bare count so that "this project introduced nothing new" is
    distinguishable from "the harvest could not run". A harvest that fails is reported as a
    failure; it is never folded into a zero.
    """
    data = load_visual_suggestions(plan_path)
    plan = load_visual_plan(plan_path)
    project_id = str(plan["project"]["id"])
    known_treatments = {
        item["id"] for item in [*load_visual_catalog(include_private=False)["modules"], *load_visual_catalog(include_private=False)["recipes"]]
    }
    selected = {}
    for suggestion in _delivered_suggestions(data, plan):
        decision = suggestion.get("decision") if isinstance(suggestion.get("decision"), dict) else {}
        treatment_id = decision.get("selectedTreatmentId")
        if treatment_id and str(treatment_id) in known_treatments and str(treatment_id) not in selected:
            selected[str(treatment_id)] = suggestion
    existing_ids = {item.get("id") for item in load_treatment_library().get("treatments", [])}
    introduced = sorted(set(selected) - existing_ids)
    if not selected:
        return {"treatmentsRecorded": 0, "candidates": 0, "introducedTreatmentIds": [], "failures": []}

    root = default_creator_library()
    preview_root = root / "recipe-previews"
    history_root = root / "treatment-preview-history" / project_id
    motion_root = root / "motion-previews"
    for directory in (preview_root, history_root, motion_root):
        directory.mkdir(parents=True, exist_ok=True)
    library = load_treatment_library()
    ratings = {
        str(item.get("id")): int(item.get("creatorRating") or 0)
        for item in library.get("treatments", [])
    }
    now = datetime.now(timezone.utc).isoformat()
    recorded = 0
    failures: list[str] = []
    for treatment_id, suggestion in selected.items():
        moment = float((suggestion.get("scenePacket") or {}).get("screenshotTimeSec") or suggestion["startSec"])
        history_preview = history_root / f"{slug(treatment_id)}-{round(moment * 1000):010d}.png"
        latest_preview = preview_root / f"{treatment_id}.png"
        screenshot_command = [
            str(find_ffmpeg()), "-y", "-ss", f"{moment:.4f}", "-i", str(final_render),
            "-frames:v", "1", str(history_preview),
        ]
        screenshot = subprocess.run(
            screenshot_command,
            capture_output=True,
            text=True,
            check=False,
            creationflags=hidden_subprocess_flags(),
        )
        if screenshot.returncode != 0 or not history_preview.is_file():
            failures.append(f"{treatment_id}: could not capture a still frame at {moment:.3f}s.")
            continue
        # The canonical preview Cook ranks against should be the best use, not the newest one.
        # An unrated reuse never displaces a frame the creator already rated.
        if ratings.get(treatment_id, 0) == 0 or not latest_preview.is_file():
            shutil.copy2(history_preview, latest_preview)
        motion_start = max(float(suggestion["startSec"]), min(moment - 0.5, float(suggestion["endSec"]) - 0.1))
        motion_duration = min(2.0, float(suggestion["endSec"]) - motion_start)
        latest_motion = motion_root / f"{treatment_id}.mp4"
        if motion_duration > 0.1:
            subprocess.run(
                [
                    str(find_ffmpeg()), "-y", "-ss", f"{motion_start:.4f}", "-i", str(final_render),
                    "-t", f"{motion_duration:.4f}", "-map", "0:v:0", "-an", "-c:v", "copy",
                    str(latest_motion),
                ],
                capture_output=True,
                text=True,
                check=False,
                creationflags=hidden_subprocess_flags(),
            )
        record = next((item for item in library["treatments"] if item.get("id") == treatment_id), None)
        if record is None:
            record = {"id": treatment_id, "createdAt": now, "history": [], "usage": []}
            library["treatments"].append(record)
        usage = {
            "projectId": project_id,
            "suggestionId": suggestion["id"],
            "startSec": float(suggestion["startSec"]),
            "endSec": float(suggestion["endSec"]),
            "previewPath": history_preview.relative_to(root).as_posix(),
            "motionPreviewPath": latest_motion.relative_to(root).as_posix() if latest_motion.is_file() else None,
            "usedAt": now,
        }
        existing = [
            item
            for item in record.setdefault("usage", [])
            if item.get("projectId") == project_id and item.get("suggestionId") == suggestion["id"]
        ]
        if not existing:
            record["usage"].append(usage)
        record["usageCount"] = len(record["usage"])
        record["lastUsedAt"] = now
        record["updatedAt"] = now
        record["lastProjectId"] = project_id
        recorded += 1
    save_treatment_library(library)
    if failures:
        raise RuntimeError(
            f"Recorded {recorded} of {len(selected)} delivered treatments. " + " ".join(failures)
        )
    return {
        "treatmentsRecorded": recorded,
        "candidates": len(selected),
        "introducedTreatmentIds": introduced,
        "failures": [],
    }


def recipe_preview_path(recipe_id: str, *, require_recipe: bool = False) -> Path | None:
    catalog_path = project_root() / "visual-production" / "recipes" / "catalog.json"
    recipes = json.loads(catalog_path.read_text(encoding="utf-8")).get("recipes", [])
    known = {item.get("id") for item in recipes}
    if not require_recipe:
        module_path = project_root() / "visual-production" / "modules" / "catalog.json"
        known |= {
            item.get("id")
            for item in json.loads(module_path.read_text(encoding="utf-8")).get("modules", [])
        }
    if recipe_id not in known:
        raise ValueError(f"Unknown visual treatment: {recipe_id}.")
    directory = default_creator_library() / "recipe-previews"
    if not directory.is_dir():
        return None
    candidates = [directory / f"{recipe_id}{extension}" for extension in (".png", ".jpg", ".jpeg", ".webp")]
    available = [path for path in candidates if path.is_file()]
    return max(available, key=lambda path: path.stat().st_mtime) if available else None


def suggestion_approval_frame_path(plan_path: Path, suggestion_id: str) -> Path:
    data = load_visual_suggestions(plan_path)
    suggestion = next((item for item in data["suggestions"] if item.get("id") == suggestion_id), None)
    if suggestion is None:
        raise ValueError("Visual suggestion not found.")
    evidence = suggestion.get("approvalEvidence") if isinstance(suggestion.get("approvalEvidence"), dict) else {}
    if evidence.get("status") != "sample-ready":
        raise ValueError("This suggestion does not have a ready one-frame sample.")
    path = resolve_project_path(find_visual_root(plan_path), str(evidence.get("sampleFramePath") or ""))
    if not path.is_file():
        raise ValueError("The approved one-frame sample is missing.")
    return path


def prepare_suggestion_approval_evidence(plan_path: Path, suggestion_id: str) -> tuple[dict, dict]:
    data = load_visual_suggestions(plan_path)
    suggestion = next((item for item in data["suggestions"] if item.get("id") == suggestion_id), None)
    if suggestion is None:
        raise ValueError("Visual suggestion not found.")
    if not _is_graphic_suggestion(suggestion):
        raise ValueError("Only graphic treatments need a visual approval sample.")
    _refresh_approval_evidence(plan_path, suggestion)
    evidence = suggestion.get("approvalEvidence") or {}
    if evidence.get("status") == "historical-ready":
        save_visual_suggestions(plan_path, data)
        return suggestion, data
    selected = str(suggestion.get("moduleId") or suggestion.get("recipeId") or "")
    composition = _registered_composition_for(plan_path, selected)
    if selected in MODULE_IDS:
        destination = _render_registered_module_sample(plan_path, suggestion)
    elif composition is not None:
        destination = _render_registered_composition_sample(plan_path, suggestion, composition)
    else:
        raise ValueError(
            f"{selected} has no historical render and no registered renderer, so no sample frame "
            "can be produced for it. Build it as a HyperFrames composition inside this project and "
            "register it in visual-plan.json under customCompositions with treatmentId "
            f"\"{selected}\" and the real sourceHash, then ask for evidence again. Drawing an "
            "approximation is not evidence: the creator would be approving something other than "
            "what renders."
        )
    # Signed here rather than inside the renderer: the receipt attests that *the app* produced
    # this frame, which is the claim the creator's approval rests on.
    _write_sample_receipt(destination, suggestion_id=str(suggestion_id), treatment_id=selected)
    root = find_visual_root(plan_path)
    suggestion["approvalEvidence"] = {
        **evidence,
        "status": "sample-ready",
        "selectedTreatmentId": selected,
        "sampleFramePath": destination.relative_to(root).as_posix(),
    }
    save_visual_suggestions(plan_path, data)
    return suggestion, data


def _registered_composition_for(plan_path: Path, treatment_id: str) -> dict | None:
    """Find the HyperFrames composition this project registered for a new treatment.

    This is how a treatment that does not exist yet becomes proposable: build it, register it,
    and the app renders its evidence from the same source that will render the video.
    """
    if not treatment_id:
        return None
    plan = load_visual_plan(plan_path)
    return next(
        (item for item in plan.get("customCompositions", []) if item.get("treatmentId") == treatment_id),
        None,
    )


def _render_registered_composition_sample(plan_path: Path, suggestion: dict, composition: dict) -> Path:
    """Snapshot one frame from a registered custom composition."""
    root = find_visual_root(plan_path)
    selected = str(suggestion.get("moduleId") or suggestion.get("recipeId") or "")
    start = float(suggestion["startSec"])
    end = float(suggestion["endSec"])
    evidence = suggestion.get("approvalEvidence") or {}
    representative = max(start, min(end, float(evidence.get("representativeTimeSec") or start + 0.5)))
    runtime_root = resolve_project_path(root, str(composition.get("projectPath") or ""))
    workspace = root / "working" / "approval-samples" / f"{slug(suggestion['id'])}-{slug(selected)}"
    snapshot_dir = workspace / "single-frame"
    destination = approval_sample_path(plan_path, suggestion["id"], selected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cli = project_root() / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
    if not cli.is_file():
        raise RuntimeError("HyperFrames is not installed. Run npm install before preparing approval samples.")
    result = subprocess.run(
        [str(cli), "snapshot", str(runtime_root), "--at", f"{max(0.0, representative - start):.4f}",
         "--no-end", "--output", str(snapshot_dir)],
        cwd=project_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        details = (result.stdout or result.stderr or "").strip()
        raise RuntimeError(f"Could not render a sample from composition {composition.get('id')}. {details[-1500:]}")
    frames = sorted(snapshot_dir.glob("*.png"), key=lambda path: path.stat().st_mtime)
    if not frames:
        raise RuntimeError(f"Composition {composition.get('id')} produced no sample frame.")
    shutil.copy2(frames[-1], destination)
    return destination


def _render_registered_module_sample(plan_path: Path, suggestion: dict) -> Path:
    root = find_visual_root(plan_path)
    plan = load_visual_plan(plan_path)
    selected = str(suggestion.get("moduleId") or "")
    start = float(suggestion["startSec"])
    end = float(suggestion["endSec"])
    evidence = suggestion.get("approvalEvidence") or {}
    representative = max(start, min(end, float(evidence.get("representativeTimeSec") or start + 0.5)))
    allowed = MODULE_PARAMETER_KEYS.get(selected, set())
    supplied = suggestion.get("moduleParameters") or {}
    unsupported = sorted(set(supplied) - allowed)
    if unsupported:
        raise ValueError(
            f"{selected} does not accept {', '.join(unsupported)}. "
            f"It accepts: {', '.join(sorted(allowed))}. "
            "Put scene geometry in speakerSafety, not in moduleParameters."
        )
    parameters = {
        "opacity": 1,
        "transitionIn": "editorial-snap",
        "transitionOut": "fade",
        **supplied,
    }
    if isinstance(suggestion.get("speakerSafety"), dict):
        # Approval evidence must use the same measured safe region that the eventual cue carries.
        # Omitting it made the sample renderer fall back to full-frame module geometry.
        parameters["speakerSafety"] = suggestion["speakerSafety"]
    # Only fill defaults the module actually declares; injecting text into a module without a
    # text parameter made its own sample render fail validation.
    if "text" in allowed:
        parameters.setdefault("text", suggestion.get("proposedText") or suggestion.get("editorialPurpose") or "REPRESENTATIVE GRAPHIC")
    if "kicker" in allowed:
        parameters.setdefault("kicker", "VCG / VISUAL")
    cue = {
        "id": f"approval-sample-{slug(suggestion['id'])}",
        "kind": "module",
        "moduleId": selected,
        "startSec": start,
        "endSec": end,
        "enabled": True,
        "parameters": parameters,
    }
    sample_plan = json.loads(json.dumps(plan))
    sample_plan["cues"] = [cue]
    sample_plan["protectedFootage"] = []
    sample_plan["reviews"] = []
    sample_plan["reviewHistory"] = []
    temp_plan = root / "visual-production" / f".approval-sample-{slug(suggestion['id'])}.json"
    workspace = root / "working" / "approval-samples" / f"{slug(suggestion['id'])}-{slug(selected)}"
    snapshot_dir = workspace / "single-frame"
    destination = approval_sample_path(plan_path, suggestion["id"], selected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        temp_plan.write_text(json.dumps(sample_plan, indent=2, ensure_ascii=False), encoding="utf-8")
        runtime_root, _duration = build_hyperframes_composition(
            temp_plan,
            start_sec=start,
            end_sec=end,
            workspace_override=workspace,
        )
        cli = project_root() / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
        if not cli.is_file():
            raise RuntimeError("HyperFrames is not installed. Run npm install before preparing approval samples.")
        relative_time = max(0.0, representative - start)
        result = subprocess.run(
            [str(cli), "snapshot", str(runtime_root), "--at", f"{relative_time:.4f}", "--no-end", "--output", str(snapshot_dir)],
            cwd=project_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=hidden_subprocess_flags(),
        )
        if result.returncode != 0:
            details = (result.stdout or result.stderr or "").strip()
            raise RuntimeError(f"Could not render the one-frame approval sample. {details[-1500:]}")
        frames = sorted(snapshot_dir.glob("*.png"), key=lambda path: path.stat().st_mtime)
        if not frames:
            raise RuntimeError("HyperFrames did not produce the requested approval sample.")
        shutil.copy2(frames[-1], destination)
    finally:
        if temp_plan.is_file():
            temp_plan.unlink()
    return destination


def treatment_motion_preview_path(treatment_id: str) -> Path | None:
    catalog = load_visual_catalog(include_private=False)
    if treatment_id not in {item["id"] for item in [*catalog["modules"], *catalog["recipes"]]}:
        raise ValueError("Unknown visual treatment.")
    path = default_creator_library() / "motion-previews" / f"{treatment_id}.mp4"
    return path if path.is_file() else None


def create_recipe_suggestion(plan_path: Path, recipe_id: str, *, start_sec: float, end_sec: float) -> dict:
    plan = load_visual_plan(plan_path)
    duration = float(plan["composition"]["durationSec"])
    start = max(0.0, min(float(start_sec), duration - 0.01))
    end = max(start + 0.01, min(float(end_sec), duration))
    catalog = load_visual_catalog()
    recipe = next(
        (item for item in [*catalog["modules"], *catalog["recipes"]] if item.get("id") == recipe_id),
        None,
    )
    if recipe is None:
        raise ValueError(f"Unknown visual treatment: {recipe_id}.")
    # Every catalog family is a registered module now, so the id lands in moduleId. recipeId
    # remains only for a treatment that still needs realizing.
    id_field = "moduleId" if recipe["kind"] == "module" else "recipeId"
    suggestion = {
        "id": f"recipe-{uuid.uuid4().hex[:12]}",
        "status": "needs-alternatives",
        "category": "graphic",
        "timelineLane": "graphics",
        "startSec": round(start, 3),
        "endSec": round(end, 3),
        "editorialPurpose": recipe.get("description") or recipe.get("purpose") or recipe_id,
        id_field: recipe_id,
        "transcriptContext": "Add the exact transcript context and spoken reveal beats during the build.",
        "generationBrief": {
            "recipeName": recipe.get("name") or recipe_id,
            "speakerMode": recipe.get("speakerMode") or recipe.get("family") or "measured container",
            "implementationState": "registered" if recipe["kind"] == "module" else "needs-build",
        },
        "decision": {"status": "pending", "selectedTreatmentId": recipe_id, "notes": ""},
        "rejectionHistory": [],
    }
    data = load_visual_suggestions(plan_path)
    data["suggestions"].append(suggestion)
    save_visual_suggestions(plan_path, data)
    return suggestion


def build_review_prompt(plan_path: Path, review_ids: set[str] | None = None) -> tuple[str, dict, int]:
    plan = load_visual_plan(plan_path)
    notes = [
        item for item in plan.get("reviews", [])
        if str(item.get("note") or "").strip() and (review_ids is None or item.get("id") in review_ids)
    ]
    if not notes:
        return "", plan, 0
    suggestions = load_visual_suggestions(plan_path).get("suggestions", [])
    cues = {item.get("id"): item for item in plan.get("cues", [])}
    suggestions_by_id = {item.get("id"): item for item in suggestions}
    root = find_visual_root(plan_path)
    source = resolve_project_path(root, plan["source"]["video"])
    transcript_ref = str(plan.get("source", {}).get("transcript") or "")
    transcript = resolve_project_path(root, transcript_ref) if transcript_ref else None
    lines = [
        "Revise the existing VCG Visual Production project using only the active review notes below.",
        "Do not redesign, retime, remove, or otherwise change any unnoted scene or item.",
        "Preserve the locked cut and its locked-cut audio.",
        "",
        f"Project root: {root}",
        f"Visual plan: {plan_path.resolve()}",
        f"Suggestions: {suggestions_path(plan_path).resolve()}",
        f"Locked video: {source}",
        f"Transcript: {transcript if transcript is not None else '(not available)'}",
        "",
        "Active review notes:",
    ]
    directive_text = {
        "targeted": "Make only the requested targeted change within this item.",
        "leave-everything-else": "Make this change and leave every other part of this item exactly as it is.",
        "replace-all": "Replace this selected item's entire treatment; do not expand that replacement to other items.",
    }
    now = datetime.now(timezone.utc).isoformat()
    for index, review in enumerate(notes, 1):
        item = cues.get(review["itemId"]) if review["itemType"] == "cue" else suggestions_by_id.get(review["itemId"])
        label = ""
        if item:
            parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
            label = str(parameters.get("reviewLabel") or item.get("moduleId") or item.get("recipeId") or item.get("category") or item.get("kind") or "")
        lines.extend([
            "",
            f"{index}. {review['itemType']} {review['itemId']} ({float(review['startSec']):.3f}s-{float(review['endSec']):.3f}s)",
            f"   Treatment: {label or 'unspecified'}",
            f"   Scope: {directive_text.get(review.get('directive', 'targeted'), directive_text['targeted'])}",
            f"   Note: {str(review['note']).strip()}",
        ])
        review["copiedAt"] = now
    lines.extend([
        "",
        "Completion contract:",
        "- Work from these exact item IDs and timestamps; inspect the transcript and footage for spoken-beat timing.",
        "- Keep each active note in visual-plan.json and set its status to ready-for-review after its revision is saved.",
        "- Do not accept or delete review notes; only the creator's Accept button may archive them.",
        "- Save every plan and suggestion change back into the private project files listed above.",
        "- Realize an unbuilt recipe as a registered module cue or a frozen project overlay asset; do not leave the result only in a disconnected HyperFrames folder.",
        "- Preserve the approved scenePacket, selected treatment, planningSuggestionId, and approvedTreatmentId; do not substitute another family without returning the scene to creator review.",
        "- Keep the speaker visible full-screen or in a container; no continuous absence may exceed two seconds.",
        "- Recheck every protected content region at entry, changing reveals, hold, and exit; no overflow exception may bypass speaker or protected-content safety.",
        "- Verify transitions for one- or two-frame source-footage flashes before handing the revision back.",
    ])
    plan = save_visual_plan(plan_path, plan)
    return "\n".join(lines), plan, len(notes)


def build_nonmedia_suggestion(plan_path: Path, suggestion_id: str) -> tuple[dict, dict]:
    data = load_visual_suggestions(plan_path)
    suggestion = next((item for item in data["suggestions"] if item.get("id") == suggestion_id), None)
    if suggestion is None:
        raise ValueError("Visual suggestion not found.")
    category = suggestion["category"]
    if category not in {"graphic", "clean-speaker", "protected-footage"}:
        raise ValueError("This suggestion needs a media selection before it can be built.")
    if (suggestion.get("decision") or {}).get("status") != "approved":
        raise ValueError("Approve this scene and treatment before building it.")
    if category == "graphic":
        evidence = suggestion.get("approvalEvidence") if isinstance(suggestion.get("approvalEvidence"), dict) else {}
        if evidence.get("status") not in APPROVAL_EVIDENCE_READY:
            raise ValueError("This graphic has no approved historical example or exact sample frame.")
        if evidence.get("selectedTreatmentId") != (suggestion.get("decision") or {}).get("selectedTreatmentId"):
            raise ValueError("This graphic's approval evidence no longer matches its approved treatment.")
    plan = load_visual_plan(plan_path)
    module_id = suggestion.get("moduleId") if category == "graphic" else "source-footage-hold"
    registered_modules = {item["id"] for item in load_visual_catalog()["modules"]}
    if category == "graphic" and suggestion.get("recipeId") and not module_id:
        raise ValueError(
            "This approved recipe still needs a registered HyperFrames composition or frozen overlay asset; "
            "it cannot be replaced with a generic module."
        )
    if module_id not in registered_modules:
        raise ValueError(
            f"Treatment {module_id} is not a registered module, so this scene cannot be built. "
            "Substituting a generic side panel used to hide the mistake inside a rendered video."
        )
    module_parameters = {
        "opacity": 1, "transitionIn": "editorial-snap", "transitionOut": "fade",
        **(suggestion.get("moduleParameters") or {}),
    }
    if module_id != "source-footage-hold":
        allowed = MODULE_PARAMETER_KEYS.get(module_id, set())
        if "text" in allowed:
            module_parameters.setdefault(
                "text",
                suggestion.get("proposedText") or suggestion.get("editorialPurpose") or "EDIT THIS MESSAGE",
            )
        if "kicker" in allowed:
            module_parameters.setdefault("kicker", "VCG / VISUAL")
        module_parameters.update({
            key: suggestion[key]
            for key in (
                "speakerSafety",
                "visualFamily",
                "candidateTreatmentIds",
                "selectionRationale",
                "meaningfulChanges",
                "approvalEvidence",
            )
            if suggestion.get(key) is not None
        })
        module_parameters["planningSuggestionId"] = suggestion_id
        module_parameters["approvedTreatmentId"] = (
            (suggestion.get("decision") or {}).get("selectedTreatmentId")
            or suggestion.get("moduleId")
            or suggestion.get("recipeId")
        )
    cue = {
        "id": f"cue-{uuid.uuid4().hex[:12]}", "kind": "module", "moduleId": module_id,
        "startSec": float(suggestion["startSec"]), "endSec": float(suggestion["endSec"]),
        "enabled": True, "parameters": module_parameters,
    }
    plan["cues"].append(cue)
    if module_id == "source-footage-hold":
        plan.setdefault("protectedFootage", []).append({
            "id": f"protected-{uuid.uuid4().hex[:10]}", "cueId": cue["id"],
            "startSec": cue["startSec"], "endSec": cue["endSec"],
            "reason": suggestion.get("editorialPurpose") or "Protected source-footage moment",
        })
    save_visual_plan(plan_path, plan)
    suggestion.update({"status": "built", "cueId": cue["id"]})
    save_visual_suggestions(plan_path, data)
    return cue, plan


def pexels_settings() -> dict:
    configured = os.environ.get("PEXELS_API_KEY")
    if configured:
        return {"apiKey": configured, "source": "environment"}
    path = user_data_root() / "pexels.json"
    if not path.is_file():
        return {"apiKey": "", "source": "missing"}
    return {"apiKey": json.loads(path.read_text(encoding="utf-8")).get("apiKey", ""), "source": "local-settings"}


def save_pexels_key(api_key: str) -> None:
    value = api_key.strip()
    if len(value) < 10:
        raise ValueError("Enter a valid Pexels API key.")
    path = user_data_root() / "pexels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"apiKey": value}, indent=2), encoding="utf-8")


def search_pexels_videos(brief: dict, *, limit: int = 5) -> list[dict]:
    key = pexels_settings()["apiKey"]
    if not key:
        raise ValueError("Add a free Pexels API key in Visual Production settings first.")
    queries = [*brief.get("literalQueries", []), *brief.get("metaphoricalQueries", [])]
    queries = [str(item).strip() for item in queries if str(item).strip()]
    if not queries and str(brief.get("query") or "").strip():
        queries = [str(brief["query"]).strip()]
    if not queries:
        raise ValueError("This stock suggestion is missing search queries.")
    videos_by_id = {}
    for query_index, query in enumerate(queries[:3]):
        url = "https://api.pexels.com/v1/videos/search?" + urllib.parse.urlencode({"query": query, "orientation": "landscape", "per_page": min(15, max(limit * 2, 8))})
        request = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "VCG-AutoCaption/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        for rank, video in enumerate(data.get("videos", [])):
            item = videos_by_id.setdefault(str(video.get("id")), {"video": video, "queryScore": 0})
            item["queryScore"] += max(0, 3 - query_index) + max(0, 5 - rank) / 10
    candidates = []
    desired = float(brief.get("desiredDurationSec") or 0)
    for item in videos_by_id.values():
        video = item["video"]
        files = [item for item in video.get("video_files", []) if item.get("link") and item.get("width") and item.get("height")]
        files.sort(key=lambda item: (item.get("width", 0) < 1280, abs(item.get("width", 0) - 1920)))
        if not files:
            continue
        best = files[0]
        duration = float(video.get("duration") or 0)
        candidates.append({
            "id": str(video["id"]), "provider": "pexels", "durationSec": duration,
            "width": int(video.get("width") or best.get("width") or 0), "height": int(video.get("height") or best.get("height") or 0),
            "previewUrl": video.get("image"), "downloadUrl": best["link"], "assetPage": video.get("url"),
            "creator": (video.get("user") or {}).get("name", "Pexels creator"),
            "creatorUrl": (video.get("user") or {}).get("url"),
            "score": round(item["queryScore"] + (2 if duration >= desired else 0) + (2 if best.get("width", 0) >= 1280 else 0) - abs(duration - desired) / 30, 3),
        })
    candidates.sort(key=lambda item: -item["score"])
    return candidates[: max(3, min(5, limit))]


def select_pexels_candidate(plan_path: Path, suggestion_id: str, candidate: dict, *, start_sec: float, end_sec: float) -> tuple[dict, dict]:
    if candidate.get("provider") != "pexels" or not str(candidate.get("id") or "").isdigit():
        raise ValueError("Invalid Pexels candidate.")
    download_url = urllib.parse.urlparse(str(candidate.get("downloadUrl") or ""))
    if download_url.scheme != "https" or not (download_url.hostname or "").lower().endswith("pexels.com"):
        raise ValueError("Pexels download URL is not trusted.")
    root = find_visual_root(plan_path)
    stock_root = root / "assets" / "stock"
    video_root, license_root = stock_root / "videos", stock_root / "licenses"
    video_root.mkdir(parents=True, exist_ok=True)
    license_root.mkdir(parents=True, exist_ok=True)
    destination = video_root / f"pexels-{candidate['id']}.mp4"
    if not destination.is_file():
        request = urllib.request.Request(candidate["downloadUrl"], headers={"User-Agent": "VCG-AutoCaption/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    checksum = sha256_file(destination)
    now = datetime.now(timezone.utc).isoformat()
    evidence = {
        "provider": "pexels", "providerAssetId": str(candidate["id"]), "creator": candidate.get("creator"),
        "creatorUrl": candidate.get("creatorUrl"), "assetPage": candidate.get("assetPage"), "downloadUrl": candidate.get("downloadUrl"),
        "downloadedAt": now, "license": "Pexels License", "licensePage": PEXELS_LICENSE_URL,
        "licenseEvidence": "Pexels license page recorded at selection time; content may be used and modified for free, subject to its restrictions.",
        "sha256": checksum, "localFile": destination.relative_to(root).as_posix(),
        "attribution": f"Video by {candidate.get('creator') or 'a Pexels creator'} on Pexels",
        "suggestionId": suggestion_id, "timelineStartSec": start_sec, "timelineEndSec": end_sec,
    }
    (license_root / f"pexels-{candidate['id']}.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    ledger_path = root / "visual-production" / "stock-assets.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {"schemaVersion": 1, "assets": []}
    ledger["assets"] = [item for item in ledger["assets"] if item.get("providerAssetId") != str(candidate["id"])] + [evidence]
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    plan = load_visual_plan(plan_path)
    asset_id = f"pexels-{candidate['id']}"
    asset = next((item for item in plan["assets"] if item.get("id") == asset_id), None)
    if asset is None:
        asset = {"id": asset_id, "name": evidence["attribution"], "path": destination.relative_to(root).as_posix(), "mediaType": "video", "durationSec": candidate.get("durationSec"), "hasTransparency": False, "origin": evidence}
        plan["assets"].append(asset)
    suggestion = _authorising_suggestion(
        plan_path,
        suggestion_id,
        category="stock",
        start_sec=start_sec,
        end_sec=end_sec,
        treatment_id=asset_id,
        purpose=evidence["attribution"],
    )
    cue = _asset_cue(asset, start_sec, end_sec, suggestion)
    plan["cues"].append(cue)
    save_visual_plan(plan_path, plan)
    update_suggestion(plan_path, suggestion["id"], {"status": "built", "selectedCandidate": candidate["id"], "cueId": cue["id"]})
    return cue, plan


def credits_text(plan_path: Path) -> str:
    ledger_path = find_visual_root(plan_path) / "visual-production" / "stock-assets.json"
    if not ledger_path.is_file():
        return ""
    assets = json.loads(ledger_path.read_text(encoding="utf-8")).get("assets", [])
    return "\n".join(dict.fromkeys(f"{item['attribution']} — {item.get('assetPage', '')}" for item in assets))


def _asset_cue(asset: dict, start_sec: float, end_sec: float, suggestion: dict) -> dict:
    """Build an asset cue carrying the receipt that names the suggestion which authorised it.

    Every enabled cue must trace back to an approved planning decision, so the suggestion is
    required rather than optional. Callers that place media directly record the placement as a
    suggestion first; see _direct_placement_suggestion.
    """
    return {
        "id": f"asset-{uuid.uuid4().hex[:12]}", "kind": "asset", "assetId": asset["id"],
        "startSec": start_sec, "endSec": end_sec, "enabled": True,
        "parameters": {
            "x": 0, "y": 0, "width": 100, "height": 100, "opacity": 1, "scale": 1, "rotation": 0,
            "fit": "cover", "muted": True, "volume": 1, "sourceStartSec": 0, "playbackRate": 1,
            "loop": False, "transitionIn": "fade", "transitionOut": "fade",
            "planningSuggestionId": suggestion["id"],
            "approvedTreatmentId": (suggestion.get("decision") or {}).get("selectedTreatmentId") or asset["id"],
        },
    }


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def _filename_tags(value: str) -> list[str]:
    return sorted(set(_tokens(value)))


_inside = is_within
