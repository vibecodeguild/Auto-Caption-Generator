"""Stage 2 Assignment — deal golden Graphics Library usages onto Masterbeater beats.

Deterministic code path (no agent). See docs/vcg-graphics-process/assignment.md.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.graphics_library import (
    ALLOWED_LAYOUT_IDS,
    default_graphics_library_root,
    entry_public_view,
    load_graphics_library,
    normalize_beat_types,
)
from app.core.masterbeater import (
    load_masterbeater_output,
    load_masterbeater_reviewed,
    status_for_video_project as masterbeater_status_for_video_project,
)
from app.core.scenelayer import (
    scenelayer_status_for_video_project,
    working_layout_by_beat_id,
)
from app.core.video_project import video_project_root

# Original algorithm output — never overwritten by UI edits or re-runs.
OUTPUT_FILENAME = "assignment.json"
# Human working copy (overrides + re-dealt algorithm slots).
REVIEWED_FILENAME = "assignment-reviewed.json"
# Append-only human override log.
LEDGER_FILENAME = "assignment-edit-ledger.json"

SCHEMA_VERSION = 1
SOURCE_ALGORITHM = "algorithm"
SOURCE_HUMAN = "human"


def output_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / OUTPUT_FILENAME


def reviewed_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / REVIEWED_FILENAME


def ledger_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / LEDGER_FILENAME


def list_golden_usages(*, library_root: Path | None = None) -> list[dict[str, Any]]:
    """Golden usages with display fields for assignment (beatTypes + poster)."""

    from app.core.visual_production import MODULE_IDS, RETIRED_ENGINE_ALIASES, canonicalize_engine_id

    root = (library_root or default_graphics_library_root()).resolve()
    try:
        document = load_graphics_library(root)
    except (OSError, ValueError, FileNotFoundError):
        return []

    usages: list[dict[str, Any]] = []
    for entry in document.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status") or "candidate") != "golden":
            continue
        usage_id = str(entry.get("id") or "").strip()
        if not usage_id:
            continue
        # Retired shelf cards (e.g. speaker-side-panel) are not production-selectable.
        if usage_id in RETIRED_ENGINE_ALIASES:
            continue
        view = entry_public_view(entry, root)
        engine_id = canonicalize_engine_id(str(view.get("engineId") or usage_id).strip())
        if engine_id not in MODULE_IDS:
            continue
        layouts = [
            str(item)
            for item in (view.get("allowedLayouts") or entry.get("allowedLayouts") or [])
            if str(item) in ALLOWED_LAYOUT_IDS
        ]
        usages.append(
            {
                "id": usage_id,
                "displayName": str(view.get("displayName") or usage_id),
                "engineId": engine_id,
                "beatTypes": normalize_beat_types(view.get("beatTypes")),
                "allowedLayouts": layouts,
                "posterUrl": view.get("posterUrl"),
                "hasPoster": bool(view.get("hasPoster")),
            }
        )
    usages.sort(key=lambda item: str(item["id"]))
    return usages


def eligible_usage_ids_for_beat(
    usages: list[dict[str, Any]],
    *,
    beat_type: str,
    layout_id: str | None,
) -> list[str]:
    """Golden usage ids matching beat type and layout (stable library order)."""

    if not beat_type or not layout_id:
        return []
    out: list[str] = []
    for usage in usages:
        usage_id = str(usage.get("id") or "").strip()
        if not usage_id:
            continue
        if beat_type not in (usage.get("beatTypes") or []):
            continue
        allowed = usage.get("allowedLayouts") or []
        if layout_id not in allowed:
            continue
        if usage_id not in out:
            out.append(usage_id)
    return out


def deal_assignments(
    beats: list[dict[str, Any]],
    usages: list[dict[str, Any]],
    *,
    layout_by_beat: dict[str, str | None] | None = None,
    preserve: dict[str, dict[str, Any]] | None = None,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Deal usageIds using bags keyed by (beatType, layoutId).

    ``preserve`` maps beatId → prior assignment entry; entries with
    ``source == human`` are kept as-is. All other beats are re-dealt.
    Beats without layoutId stay unassigned.
    """

    rng = rng or random.Random()
    preserve = preserve or {}
    layout_by_beat = layout_by_beat or {}
    bags: dict[tuple[str, str], list[str]] = {}
    results: list[dict[str, Any]] = []

    for beat in beats:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or "").strip()
        if not beat_id:
            continue
        beat_type = str(beat.get("beatType") or "").strip()
        layout_id = layout_by_beat.get(beat_id)
        if layout_id is None and "layoutId" in beat:
            layout_id = beat.get("layoutId")
        layout_id = str(layout_id).strip() if layout_id else None

        prior = preserve.get(beat_id)
        if isinstance(prior, dict) and str(prior.get("source") or "") == SOURCE_HUMAN:
            usage_id = prior.get("usageId")
            results.append(
                {
                    "beatId": beat_id,
                    "usageId": usage_id if usage_id else None,
                    "source": SOURCE_HUMAN,
                    "layoutId": layout_id,
                }
            )
            continue

        pool = eligible_usage_ids_for_beat(
            usages, beat_type=beat_type, layout_id=layout_id
        )
        if not pool:
            results.append(
                {
                    "beatId": beat_id,
                    "usageId": None,
                    "source": SOURCE_ALGORITHM,
                    "layoutId": layout_id,
                }
            )
            continue

        bag_key = (beat_type, layout_id or "")
        bag = bags.get(bag_key)
        if not bag:
            bag = list(pool)
            bags[bag_key] = bag
        pick_index = rng.randrange(len(bag))
        usage_id = bag.pop(pick_index)
        results.append(
            {
                "beatId": beat_id,
                "usageId": usage_id,
                "source": SOURCE_ALGORITHM,
                "layoutId": layout_id,
            }
        )

    return results


def _usage_lookup(usages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(u["id"]): u for u in usages if u.get("id")}


def enrich_assignment_beats(
    assignments: list[dict[str, Any]],
    usages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach live displayName / posterUrl for the UI (not persisted authority)."""

    by_id = _usage_lookup(usages)
    enriched: list[dict[str, Any]] = []
    for row in assignments:
        if not isinstance(row, dict):
            continue
        usage_id = row.get("usageId")
        usage = by_id.get(str(usage_id)) if usage_id else None
        item = {
            "beatId": str(row.get("beatId") or ""),
            "usageId": usage_id if usage_id else None,
            "source": str(row.get("source") or SOURCE_ALGORITHM),
        }
        if usage:
            item["displayName"] = usage.get("displayName")
            item["posterUrl"] = usage.get("posterUrl")
            item["engineId"] = usage.get("engineId")
            item["hasPoster"] = usage.get("hasPoster")
        else:
            item["displayName"] = None
            item["posterUrl"] = None
            item["engineId"] = None
            item["hasPoster"] = False
            if usage_id:
                item["missingUsage"] = True
        enriched.append(item)
    return enriched


def build_assignment_document(
    assignments: list[dict[str, Any]],
    *,
    project_root: Path,
    role: str = "original",
    beat_count: int | None = None,
) -> dict[str, Any]:
    """Persistable shape (no poster snapshots)."""

    clean: list[dict[str, Any]] = []
    for row in assignments:
        if not isinstance(row, dict):
            continue
        beat_id = str(row.get("beatId") or "").strip()
        if not beat_id:
            continue
        usage_id = row.get("usageId")
        source = str(row.get("source") or SOURCE_ALGORITHM).strip()
        if source not in {SOURCE_ALGORITHM, SOURCE_HUMAN}:
            source = SOURCE_ALGORITHM
        clean.append(
            {
                "beatId": beat_id,
                "usageId": str(usage_id) if usage_id else None,
                "source": source,
            }
        )
    assigned = sum(1 for r in clean if r.get("usageId"))
    return {
        "agent": "assignment" if role == "original" else "assignment-reviewed",
        "schemaVersion": SCHEMA_VERSION,
        "role": role,
        "projectRoot": str(project_root),
        "beatCount": beat_count if beat_count is not None else len(clean),
        "assignedCount": assigned,
        "unassignedCount": len(clean) - assigned,
        "beats": clean,
        "notes": (
            "Assignment picks golden usageId per Masterbeater beat. "
            "Display names and posters resolve from the live Graphics Library."
        ),
    }


def load_assignment_original(project_root: Path) -> dict | None:
    path = output_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_assignment_reviewed(project_root: Path) -> dict | None:
    path = reviewed_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_assignment_ledger(project_root: Path) -> dict[str, Any]:
    path = ledger_path_for_project(project_root)
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "agent": "assignment-edit-ledger",
            "originalFile": OUTPUT_FILENAME,
            "reviewedFile": REVIEWED_FILENAME,
            "entries": [],
            "entryCount": 0,
        }
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Assignment ledger must be a JSON object.")
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    return data


def write_assignment_original(project_root: Path, document: dict[str, Any]) -> Path:
    path = output_path_for_project(project_root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_assignment_reviewed(project_root: Path, document: dict[str, Any]) -> Path:
    path = reviewed_path_for_project(project_root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_assignment_ledger(project_root: Path, ledger: dict[str, Any]) -> Path:
    path = ledger_path_for_project(project_root)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _working_masterbeater_beats(project_root: Path) -> list[dict[str, Any]]:
    reviewed = load_masterbeater_reviewed(project_root)
    original = load_masterbeater_output(project_root)
    working = reviewed if reviewed is not None else original
    if working is None:
        return []
    beats = working.get("beats") or []
    return [b for b in beats if isinstance(b, dict) and b.get("id")]


def _preserve_map_from_document(document: dict | None) -> dict[str, dict[str, Any]]:
    if not document:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in document.get("beats") or []:
        if not isinstance(row, dict):
            continue
        beat_id = str(row.get("beatId") or "").strip()
        if not beat_id:
            continue
        out[beat_id] = {
            "beatId": beat_id,
            "usageId": row.get("usageId"),
            "source": str(row.get("source") or SOURCE_ALGORITHM),
        }
    return out


def run_assignment_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    library_root: Path | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Run Assign: first run writes original+working; re-run keeps human, re-deals rest."""

    root = video_project_root(manifest_path)
    beats = _working_masterbeater_beats(root)
    if not beats:
        raise FileNotFoundError(
            "No Masterbeater beats found. Finish Stage 1 (masterbeater-beats.json "
            "or reviewed copy) before assignment."
        )

    usages = list_golden_usages(library_root=library_root)
    layout_by_beat = working_layout_by_beat_id(root)
    original = load_assignment_original(root)
    working_prior = load_assignment_reviewed(root) or original

    if original is None:
        # First run: full deal → original + working.
        dealt = deal_assignments(
            beats, usages, layout_by_beat=layout_by_beat, preserve=None, rng=rng
        )
        document = build_assignment_document(
            dealt, project_root=root, role="original", beat_count=len(beats)
        )
        write_assignment_original(root, document)
        working_doc = build_assignment_document(
            dealt, project_root=root, role="reviewed", beat_count=len(beats)
        )
        working_doc["basedOnOriginal"] = True
        working_doc["originalFile"] = OUTPUT_FILENAME
        write_assignment_reviewed(root, working_doc)
        first_run = True
    else:
        # Re-run: preserve human on working copy; original untouched.
        preserve = _preserve_map_from_document(working_prior)
        human_only = {
            bid: row
            for bid, row in preserve.items()
            if str(row.get("source") or "") == SOURCE_HUMAN
        }
        dealt = deal_assignments(
            beats,
            usages,
            layout_by_beat=layout_by_beat,
            preserve=human_only,
            rng=rng,
        )
        working_doc = build_assignment_document(
            dealt, project_root=root, role="reviewed", beat_count=len(beats)
        )
        working_doc["basedOnOriginal"] = True
        working_doc["originalFile"] = OUTPUT_FILENAME
        working_doc["reRun"] = True
        write_assignment_reviewed(root, working_doc)
        first_run = False
        document = original

    enriched = enrich_assignment_beats(working_doc["beats"], usages)
    return {
        "ok": True,
        "firstRun": first_run,
        "originalPath": str(output_path_for_project(root)),
        "reviewedPath": str(reviewed_path_for_project(root)),
        "originalExists": True,
        "reviewedExists": True,
        "beatCount": working_doc.get("beatCount"),
        "assignedCount": working_doc.get("assignedCount"),
        "unassignedCount": working_doc.get("unassignedCount"),
        "goldenUsageCount": len(usages),
        "beats": enriched,
        "result": {
            **working_doc,
            "beats": enriched,
        },
    }


def append_assignment_ledger_entry(
    project_root: Path,
    *,
    beat_id: str,
    from_usage_id: str | None,
    to_usage_id: str | None,
    detail: str | None = None,
) -> dict[str, Any]:
    ledger = load_assignment_ledger(project_root)
    entries: list[Any] = list(ledger.get("entries") or [])
    entry = {
        "id": f"a-{len(entries) + 1:04d}",
        "at": datetime.now(timezone.utc).isoformat(),
        "op": "changeUsage",
        "beatId": beat_id,
        "fromUsageId": from_usage_id,
        "toUsageId": to_usage_id,
    }
    if detail:
        entry["detail"] = detail
    entries.append(entry)
    ledger["schemaVersion"] = 1
    ledger["agent"] = "assignment-edit-ledger"
    ledger["originalFile"] = OUTPUT_FILENAME
    ledger["reviewedFile"] = REVIEWED_FILENAME
    ledger["entries"] = entries
    ledger["entryCount"] = len(entries)
    ledger["updatedAt"] = entry["at"]
    write_assignment_ledger(project_root, ledger)
    return entry


def save_assignment_override_for_video_project(
    manifest_path: Path,
    manifest: dict,
    payload: dict,
    *,
    library_root: Path | None = None,
) -> dict[str, Any]:
    """Human swap of usage on one beat → working copy + ledger. Original untouched."""

    root = video_project_root(manifest_path)
    original = load_assignment_original(root)
    if original is None:
        raise FileNotFoundError(
            f"No assignment.json yet. Press Assign before overriding graphics."
        )

    beat_id = str(payload.get("beatId") or "").strip()
    if not beat_id:
        raise ValueError("beatId is required.")
    if "usageId" not in payload:
        raise ValueError("usageId is required (string or null).")
    usage_id_raw = payload.get("usageId")
    usage_id = str(usage_id_raw).strip() if usage_id_raw else None

    mb_beats = _working_masterbeater_beats(root)
    beat = next((b for b in mb_beats if str(b.get("id")) == beat_id), None)
    if beat is None:
        raise ValueError(f"Unknown beatId {beat_id!r} — not in working Masterbeater beats.")
    beat_type = str(beat.get("beatType") or "").strip()

    usages = list_golden_usages(library_root=library_root)
    by_id = _usage_lookup(usages)
    layout_id = working_layout_by_beat_id(root).get(beat_id)
    if usage_id is not None:
        usage = by_id.get(usage_id)
        if usage is None:
            raise ValueError(f"Usage {usage_id!r} is not a golden library entry.")
        if beat_type not in (usage.get("beatTypes") or []):
            raise ValueError(
                f"Usage {usage_id!r} does not allow beat type {beat_type!r}."
            )
        allowed = usage.get("allowedLayouts") or []
        if layout_id and allowed and layout_id not in allowed:
            raise ValueError(
                f"Usage {usage_id!r} does not allow layout {layout_id!r}."
            )

    working = load_assignment_reviewed(root) or original
    rows = list(working.get("beats") or [])
    by_beat = {
        str(r.get("beatId")): dict(r)
        for r in rows
        if isinstance(r, dict) and r.get("beatId")
    }
    previous = by_beat.get(beat_id) or {"beatId": beat_id, "usageId": None, "source": SOURCE_ALGORITHM}
    from_usage = previous.get("usageId")
    by_beat[beat_id] = {
        "beatId": beat_id,
        "usageId": usage_id,
        "source": SOURCE_HUMAN,
    }

    # Keep order aligned with current Masterbeater beats when possible.
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mb in mb_beats:
        bid = str(mb.get("id") or "")
        if bid in by_beat:
            ordered.append(by_beat[bid])
            seen.add(bid)
    for bid, row in by_beat.items():
        if bid not in seen:
            ordered.append(row)

    working_doc = build_assignment_document(
        ordered, project_root=root, role="reviewed", beat_count=len(mb_beats)
    )
    working_doc["basedOnOriginal"] = True
    working_doc["originalFile"] = OUTPUT_FILENAME
    working_doc["edited"] = True
    write_assignment_reviewed(root, working_doc)

    ledger_entry = append_assignment_ledger_entry(
        root,
        beat_id=beat_id,
        from_usage_id=str(from_usage) if from_usage else None,
        to_usage_id=usage_id,
        detail=str(payload.get("detail") or "").strip() or None,
    )

    # Original must remain unchanged.
    original_path = output_path_for_project(root)
    enriched = enrich_assignment_beats(working_doc["beats"], usages)
    return {
        "ok": True,
        "role": "reviewed",
        "edited": True,
        "originalPath": str(original_path),
        "reviewedPath": str(reviewed_path_for_project(root)),
        "ledgerPath": str(ledger_path_for_project(root)),
        "ledgerEntry": ledger_entry,
        "ledgerEntryCount": int(load_assignment_ledger(root).get("entryCount") or 0),
        "beatCount": working_doc.get("beatCount"),
        "assignedCount": working_doc.get("assignedCount"),
        "unassignedCount": working_doc.get("unassignedCount"),
        "beats": enriched,
        "result": {**working_doc, "beats": enriched},
    }


def eligible_by_beat_type(usages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """UI helper: beat type → eligible golden usage summaries."""

    out: dict[str, list[dict[str, Any]]] = {}
    for usage in usages:
        summary = {
            "id": usage["id"],
            "displayName": usage.get("displayName") or usage["id"],
            "posterUrl": usage.get("posterUrl"),
            "hasPoster": usage.get("hasPoster"),
            "engineId": usage.get("engineId"),
        }
        for beat_type in usage.get("beatTypes") or []:
            key = str(beat_type).strip()
            if not key:
                continue
            bucket = out.setdefault(key, [])
            if not any(item["id"] == summary["id"] for item in bucket):
                bucket.append(summary)
    for key in out:
        out[key].sort(key=lambda item: str(item["id"]))
    return out


def assignment_status_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    library_root: Path | None = None,
) -> dict[str, Any]:
    """Assignment slice for Visual Package status (merged by the API)."""

    del manifest  # project root comes from manifest_path
    root = video_project_root(manifest_path)
    usages = list_golden_usages(library_root=library_root)
    original = None
    reviewed = None
    try:
        original = load_assignment_original(root)
    except (OSError, json.JSONDecodeError):
        original = None
    try:
        reviewed = load_assignment_reviewed(root)
    except (OSError, json.JSONDecodeError):
        reviewed = None

    working = reviewed if reviewed is not None else original
    ledger_entry_count = 0
    ledger_path = ledger_path_for_project(root)
    if ledger_path.is_file():
        try:
            ledger = load_assignment_ledger(root)
            ledger_entry_count = int(ledger.get("entryCount") or len(ledger.get("entries") or []))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            ledger_entry_count = 0

    enriched_beats: list[dict[str, Any]] = []
    assigned_count = 0
    unassigned_count = 0
    if working is not None:
        enriched_beats = enrich_assignment_beats(list(working.get("beats") or []), usages)
        assigned_count = sum(1 for b in enriched_beats if b.get("usageId"))
        unassigned_count = len(enriched_beats) - assigned_count

    by_beat = {str(b["beatId"]): b for b in enriched_beats if b.get("beatId")}

    return {
        "ok": True,
        "originalPath": str(output_path_for_project(root)),
        "originalExists": original is not None,
        "reviewedPath": str(reviewed_path_for_project(root)),
        "reviewedExists": reviewed is not None,
        "ledgerPath": str(ledger_path),
        "ledgerExists": ledger_path.is_file(),
        "ledgerEntryCount": ledger_entry_count,
        "goldenUsageCount": len(usages),
        "beatCount": len(enriched_beats),
        "assignedCount": assigned_count,
        "unassignedCount": unassigned_count,
        "result": (
            {
                **(working or {}),
                "beats": enriched_beats,
            }
            if working is not None
            else None
        ),
        "byBeatId": by_beat,
        "eligibleByBeatType": eligible_by_beat_type(usages),
        "usages": {
            u["id"]: {
                "id": u["id"],
                "displayName": u.get("displayName"),
                "posterUrl": u.get("posterUrl"),
                "hasPoster": u.get("hasPoster"),
                "beatTypes": u.get("beatTypes"),
                "allowedLayouts": u.get("allowedLayouts"),
                "engineId": u.get("engineId"),
            }
            for u in usages
        },
        "layoutByBeatId": working_layout_by_beat_id(root),
    }


def merge_visual_package_status(
    manifest_path: Path,
    manifest: dict,
    *,
    library_root: Path | None = None,
) -> dict[str, Any]:
    """Masterbeater + scenelayer + assignment for one Visual Package GET."""

    from app.core.placement import placement_status_for_video_project

    status = masterbeater_status_for_video_project(manifest_path, manifest)
    status["scenelayer"] = scenelayer_status_for_video_project(manifest_path, manifest)
    status["assignment"] = assignment_status_for_video_project(
        manifest_path, manifest, library_root=library_root
    )
    status["placement"] = placement_status_for_video_project(
        manifest_path, manifest, library_root=library_root
    )
    return status
