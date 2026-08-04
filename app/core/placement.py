"""Stage 3 Placement — lines + reveal frames, lock, full-render gate.

See docs/vcg-graphics-process/placement.md and app/core/placement_roles.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.assignment import (
    load_assignment_original,
    load_assignment_reviewed,
    list_golden_usages,
)
from app.core.graphics_library import resolve_engine_id
from app.core.masterbeater import (
    load_masterbeater_output,
    load_masterbeater_reviewed,
)
from app.core.placement_roles import (
    empty_line,
    get_engine_placement_spec,
    lines_to_engine_parameters,
    list_fixed_and_list_slots,
    placement_interface_summary,
    slot_to_parameter_path,
)
from app.core.video_project import preferred_stage_source, video_project_root

OUTPUT_FILENAME = "placement.json"
REVIEWED_FILENAME = "placement-reviewed.json"
LEDGER_FILENAME = "placement-edit-ledger.json"
PREVIEW_DIRNAME = "working/placement-preview"
PREVIEW_RECEIPT = "preview-receipt.json"

SCHEMA_VERSION = 1
SOURCE_ALGORITHM = "algorithm"
SOURCE_HUMAN = "human"


def output_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / OUTPUT_FILENAME


def reviewed_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / REVIEWED_FILENAME


def ledger_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / LEDGER_FILENAME


def _working_masterbeater_beats(project_root: Path) -> list[dict[str, Any]]:
    reviewed = load_masterbeater_reviewed(project_root)
    original = load_masterbeater_output(project_root)
    working = reviewed if reviewed is not None else original
    if working is None:
        return []
    return [b for b in (working.get("beats") or []) if isinstance(b, dict) and b.get("id")]


def _masterbeater_beat_by_id(project_root: Path, beat_id: str) -> dict[str, Any] | None:
    want = str(beat_id or "").strip()
    if not want:
        return None
    for beat in _working_masterbeater_beats(project_root):
        if str(beat.get("id") or "") == want:
            return beat
    return None


def _beat_end_frame_exclusive(beat: dict[str, Any] | None, *, fallback: int) -> int:
    """Natural speech-beat end (not the trimmed graphic undock frame)."""

    if not isinstance(beat, dict):
        return max(1, int(fallback))
    end = beat.get("endFrameExclusive")
    if end is None and beat.get("endFrame") is not None:
        end = int(beat["endFrame"]) + 1
    try:
        end_i = int(end if end is not None else fallback)
    except (TypeError, ValueError):
        end_i = int(fallback)
    return max(1, end_i)


def _working_assignment_rows(project_root: Path) -> list[dict[str, Any]]:
    reviewed = load_assignment_reviewed(project_root)
    original = load_assignment_original(project_root)
    working = reviewed if reviewed is not None else original
    if working is None:
        return []
    return [r for r in (working.get("beats") or []) if isinstance(r, dict) and r.get("beatId")]


def load_placement_original(project_root: Path) -> dict | None:
    path = output_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_placement_reviewed(project_root: Path) -> dict | None:
    path = reviewed_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_placement_ledger(project_root: Path) -> dict[str, Any]:
    path = ledger_path_for_project(project_root)
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "agent": "placement-edit-ledger",
            "originalFile": OUTPUT_FILENAME,
            "reviewedFile": REVIEWED_FILENAME,
            "entries": [],
            "entryCount": 0,
        }
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Placement ledger must be a JSON object.")
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    return data


def write_placement_original(project_root: Path, document: dict[str, Any]) -> Path:
    path = output_path_for_project(project_root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_placement_reviewed(project_root: Path, document: dict[str, Any]) -> Path:
    path = reviewed_path_for_project(project_root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_placement_ledger(project_root: Path, ledger: dict[str, Any]) -> Path:
    path = ledger_path_for_project(project_root)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _split_words_text(words_text: str, *, max_parts: int = 6) -> list[str]:
    text = " ".join(str(words_text or "").split()).strip()
    if not text:
        return []
    # Prefer newlines, then sentence-ish splits.
    if "\n" in str(words_text or ""):
        parts = [p.strip() for p in str(words_text).splitlines() if p.strip()]
        if parts:
            return parts[:max_parts]
    # Clause split on period / em dash / semicolon
    parts = re.split(r"(?<=[.!?])\s+|\s+[—–-]\s+", text)
    parts = [p.strip(" .") for p in parts if p and p.strip(" .")]
    if len(parts) >= 2:
        return parts[:max_parts]
    # Word chunks for long phrases
    words = text.split()
    if len(words) <= 8:
        return [text]
    chunk = max(3, len(words) // min(max_parts, 4))
    out: list[str] = []
    for i in range(0, len(words), chunk):
        out.append(" ".join(words[i : i + chunk]))
        if len(out) >= max_parts:
            break
    return out or [text]


def _default_motion(engine_id: str, layout_id: str | None) -> dict[str, Any]:
    motion: dict[str, Any] = {}
    spec = get_engine_placement_spec(engine_id)
    keys = set(spec.get("motion_keys") or [])
    layout = str(layout_id or "")
    if "side" in keys:
        # Prefer graphic on free side of big-face layouts.
        if "right" in layout and "bottom" not in layout and "top" not in layout:
            motion["side"] = "left"
        elif "left" in layout and "bottom" not in layout and "top" not in layout:
            motion["side"] = "right"
        else:
            motion["side"] = "left"
    if "anchor" in keys:
        motion["anchor"] = "top"
    if engine_id == "source-punch-zoom":
        motion.setdefault("focusX", 0.5)
        motion.setdefault("focusY", 0.42)
        motion.setdefault("zoom", 1.35)
        motion.setdefault("settleSec", 0.45)
        # visual-plan.schema.json: motion enum is in | out | in-out (not "punch").
        motion.setdefault("motion", "in-out")
    return {k: v for k, v in motion.items() if k in keys}


def _default_meta(engine_id: str, *, index_among_type: int) -> dict[str, Any]:
    spec = get_engine_placement_spec(engine_id)
    keys = set(spec.get("meta_keys") or [])
    meta: dict[str, Any] = {}
    if "stepNumber" in keys:
        meta["stepNumber"] = index_among_type + 1
    if "showNumber" in keys:
        meta["showNumber"] = True
    if "exampleNumber" in keys:
        meta["exampleNumber"] = index_among_type + 1
    if "totalExamples" in keys:
        meta["totalExamples"] = max(1, index_among_type + 1)
    if "value" in keys:
        meta["value"] = 0.5
    if "appName" in keys:
        meta["appName"] = "Grok"
    return {k: v for k, v in meta.items() if k in keys}


# Library sample / live-preview stand-in for the 7-22 joke image card path.
DEMO_JOKE_IMAGE_ASSET_ID = "demo-joke-image"
# Per-project store for placement instance images (joke art, logos, …).
PLACEMENT_IMAGE_DIRNAME = "assets/placement"
PLACEMENT_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _placement_image_dir(project_root: Path) -> Path:
    return Path(project_root) / PLACEMENT_IMAGE_DIRNAME


def _find_placement_image(project_root: Path, asset_id: str) -> Path | None:
    """Resolve an imported placement image by asset id (file stem)."""

    stem = str(asset_id or "").strip()
    if not stem:
        return None
    image_dir = _placement_image_dir(project_root)
    for ext in PLACEMENT_IMAGE_EXTENSIONS:
        candidate = image_dir / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def import_placement_image(manifest_path: Path, source: Path) -> dict[str, Any]:
    """Copy an image into the project's placement store; returns its asset id.

    Asset id = sanitized file stem. Placements reference the id in their assets
    bag (e.g. imageAssetId); previews and renders resolve it from the store.
    """

    root = video_project_root(manifest_path)
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Image not found: {source}")
    ext = source.suffix.lower()
    if ext not in PLACEMENT_IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image type {ext!r}. Use png/jpg/jpeg/gif/webp.")
    stem = re.sub(r"[^a-z0-9-]+", "-", source.stem.lower()).strip("-") or "image"
    if stem == DEMO_JOKE_IMAGE_ASSET_ID:
        stem = f"{stem}-custom"
    image_dir = _placement_image_dir(root)
    image_dir.mkdir(parents=True, exist_ok=True)
    asset_id = stem
    dest = image_dir / f"{asset_id}{ext}"
    counter = 2
    # Same-name imports overwrite only when the bytes match; otherwise suffix.
    while dest.is_file() and dest.stat().st_size != source.stat().st_size:
        asset_id = f"{stem}-{counter}"
        dest = image_dir / f"{asset_id}{ext}"
        counter += 1
    shutil.copy2(source, dest)
    return {"assetId": asset_id, "fileName": dest.name, "sourceName": source.name}


def _default_assets(engine_id: str) -> dict[str, Any]:
    """Default asset bag required by single-mode engines (e.g. punchline joke card)."""

    spec = get_engine_placement_spec(engine_id)
    keys = set(spec.get("asset_keys") or [])
    assets: dict[str, Any] = {}
    if engine_id == "punchline-reveal" and "imageAssetId" in keys:
        # Required: punchline-reveal is only the joke-card look (no text-only mode).
        assets["imageAssetId"] = DEMO_JOKE_IMAGE_ASSET_ID
    return {k: v for k, v in assets.items() if k in keys}


def _ensure_engine_assets_for_preview(engine_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Ensure required assets for single-mode engines when drafts omitted them."""

    out = dict(params)
    if engine_id == "punchline-reveal" and not str(out.get("imageAssetId") or "").strip():
        out["imageAssetId"] = DEMO_JOKE_IMAGE_ASSET_ID
    return out


def _stage_plan_assets_for_preview(
    project_root: Path,
    *,
    engine_id: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Copy engine image/logo stand-ins into the project so HyperFrames can stage them."""

    from app.core.visual_production import brand_joke_demo_image_path

    plan_assets: list[dict[str, Any]] = []
    image_id = str(params.get("imageAssetId") or "").strip()
    if engine_id == "punchline-reveal" and image_id:
        # Imported project image first; the brand demo art is the fallback so a
        # missing/renamed image degrades to a visible placeholder, never a break.
        source = _find_placement_image(project_root, image_id)
        display_name = f"Joke image · {image_id}"
        if source is None:
            source = brand_joke_demo_image_path()
            display_name = "Punchline joke image (demo)"
            if not source.is_file():
                raise RuntimeError(
                    f"punchline-reveal needs the joke-card image, but {source} is missing."
                )
        asset_dir = Path(project_root) / PREVIEW_DIRNAME / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"{image_id}{source.suffix.lower() or '.png'}"
        dest = asset_dir / dest_name
        if not dest.is_file() or dest.stat().st_size != source.stat().st_size:
            shutil.copy2(source, dest)
        rel = f"{PREVIEW_DIRNAME}/assets/{dest_name}".replace("\\", "/")
        plan_assets.append(
            {
                "id": image_id,
                "name": display_name,
                "path": rel,
                "mediaType": "image",
                "durationSec": None,
                "hasTransparency": False,
            }
        )
    return plan_assets


def draft_lines_for_engine(
    engine_id: str,
    beat: dict[str, Any],
    *,
    start_frame: int,
    end_frame_exclusive: int,
    index_among_type: int = 0,
) -> list[dict[str, Any]]:
    """Deterministic line draft for one engine + beat."""

    fixed, list_slot, list_min, list_max = list_fixed_and_list_slots(engine_id)
    words = str(beat.get("wordsText") or beat.get("span") or beat.get("label") or "").strip()
    start = int(start_frame)
    end = max(start + 1, int(end_frame_exclusive))
    span = end - start

    lines: list[dict[str, Any]] = []

    if engine_id == "source-punch-zoom":
        return []

    # Fixed slots first
    if fixed:
        if engine_id == "problem-card-triptych":
            parts = _split_words_text(words, max_parts=3)
            while len(parts) < 3:
                parts.append(parts[-1] if parts else "Card")
            for i, slot in enumerate(fixed):
                lines.append(empty_line(slot, text=parts[i], reveal_frame=start + int(span * i / 3)))
        elif engine_id == "progress-scale":
            parts = _split_words_text(words, max_parts=3)
            title = parts[0] if parts else "PROGRESS"
            start_l = parts[1] if len(parts) > 1 else "Start"
            target_l = parts[2] if len(parts) > 2 else "Goal"
            lines.append(empty_line("text", text=title, reveal_frame=start))
            lines.append(empty_line("startLabel", text=start_l, reveal_frame=start))
            lines.append(empty_line("targetLabel", text=target_l, reveal_frame=start))
        elif engine_id == "tradeoff-meter":
            parts = _split_words_text(words, max_parts=3)
            lines.append(empty_line("leftLabel", text=parts[0] if parts else "A", reveal_frame=start))
            lines.append(
                empty_line("rightLabel", text=parts[1] if len(parts) > 1 else "B", reveal_frame=start)
            )
            lines.append(
                empty_line(
                    "verdict",
                    text=parts[2] if len(parts) > 2 else (parts[0] if parts else "Pick"),
                    reveal_frame=start + max(1, span // 2),
                )
            )
        elif engine_id == "brand-cta-lockup":
            parts = _split_words_text(words, max_parts=3)
            lines.append(
                empty_line("logoText", text=parts[0] if parts else "Community", reveal_frame=start)
            )
            lines.append(
                empty_line(
                    "action",
                    text=parts[1] if len(parts) > 1 else "JOIN",
                    reveal_frame=start,
                )
            )
            lines.append(
                empty_line(
                    "destination",
                    text=parts[2] if len(parts) > 2 else "link",
                    reveal_frame=start,
                )
            )
        elif engine_id == "numbered-step-intro":
            parts = _split_words_text(words, max_parts=2)
            lines.append(empty_line("title", text=parts[0] if parts else "Step", reveal_frame=start))
            lines.append(
                empty_line(
                    "action",
                    text=parts[1] if len(parts) > 1 else words or "Do this",
                    reveal_frame=start + max(1, span // 3),
                )
            )
        elif engine_id == "ui-callout":
            parts = _split_words_text(words, max_parts=2)
            lines.append(empty_line("label", text=parts[0] if parts else "UI", reveal_frame=start))
            lines.append(
                empty_line(
                    "detail",
                    text=parts[1] if len(parts) > 1 else words or "",
                    reveal_frame=start + max(1, span // 4),
                )
            )
        elif engine_id == "robot-cheer":
            lines.append(empty_line("text", text=words or "YES", reveal_frame=start))
            lines.append(empty_line("tagline", text="LET'S GO", reveal_frame=start))
        else:
            # First fixed slot gets full words; extra fixed slots empty unless list fills.
            primary = fixed[0]
            lines.append(empty_line(primary, text=words, reveal_frame=start))
            for slot in fixed[1:]:
                lines.append(empty_line(slot, text="", reveal_frame=start))

    # List slots
    if list_slot:
        max_n = max(list_min, min(list_max or 6, 6))
        if not fixed:
            # titleLines-only engines
            parts = _split_words_text(words, max_parts=max_n) or [words or "Line"]
            n = max(list_min, len(parts))
            for i in range(n):
                text = parts[i] if i < len(parts) else parts[-1]
                fr = start + (int(span * i / max(1, n)) if n > 1 else 0)
                lines.append(empty_line(f"{list_slot}.{i}", text=text, reveal_frame=fr))
        else:
            # Title already set; bullets from split of remaining / full text
            parts = _split_words_text(words, max_parts=max_n + 1)
            # Drop first if used as title
            body_parts = parts[1:] if len(parts) > 1 else (parts if not words else [])
            if not body_parts and words and fixed:
                # single blob as one list item
                body_parts = [words] if list_min >= 1 or list_max > 0 else []
            if list_min and not body_parts:
                body_parts = [words or "Item"]
            n = min(max_n, max(list_min, len(body_parts)))
            for i in range(n):
                text = body_parts[i] if i < len(body_parts) else body_parts[-1]
                fr = start + (int(span * (i + 1) / max(1, n + 1)) if n else 0)
                lines.append(empty_line(f"{list_slot}.{i}", text=text, reveal_frame=fr))

    if not lines and fixed:
        lines.append(empty_line(fixed[0], text=words, reveal_frame=start))

    return lines


def draft_placement_for_beat(
    beat: dict[str, Any],
    assignment_row: dict[str, Any],
    *,
    usages_by_id: dict[str, dict[str, Any]],
    layout_id: str | None,
    index_among_type: int,
    locked: bool = False,
) -> dict[str, Any] | None:
    """Build one placement row, or None if unassigned."""

    beat_id = str(beat.get("id") or "").strip()
    usage_id = assignment_row.get("usageId")
    if not beat_id or not usage_id:
        return None
    usage_id = str(usage_id).strip()
    usage = usages_by_id.get(usage_id) or {}
    engine_id = str(usage.get("engineId") or resolve_engine_id(usage_id) or "").strip()
    if not engine_id:
        engine_id = usage_id

    try:
        get_engine_placement_spec(engine_id)
    except KeyError:
        # Unknown engine — still store shell so UI can show error.
        pass

    start = int(beat.get("startFrame") or 0)
    end = beat.get("endFrameExclusive")
    if end is None and beat.get("endFrame") is not None:
        end = int(beat["endFrame"]) + 1
    end = int(end if end is not None else start + 1)
    if end <= start:
        end = start + 1

    try:
        lines = draft_lines_for_engine(
            engine_id,
            beat,
            start_frame=start,
            end_frame_exclusive=end,
            index_among_type=index_among_type,
        )
        meta = _default_meta(engine_id, index_among_type=index_among_type)
        motion = _default_motion(engine_id, layout_id)
        assets = _default_assets(engine_id)
    except KeyError:
        lines = [empty_line("text", text=str(beat.get("wordsText") or ""), reveal_frame=start)]
        meta = {}
        motion = {}
        assets = {}

    return {
        "beatId": beat_id,
        "usageId": usage_id,
        "engineId": engine_id,
        "locked": bool(locked),
        "startFrame": start,
        "endFrameExclusive": end,
        "lines": lines,
        "meta": meta,
        "assets": assets,
        "motion": motion,
        "source": SOURCE_ALGORITHM,
        "displayName": usage.get("displayName") or usage_id,
        "beatType": beat.get("beatType"),
        "wordsText": beat.get("wordsText"),
    }


def build_placement_document(
    placements: list[dict[str, Any]],
    *,
    project_root: Path,
    role: str = "original",
) -> dict[str, Any]:
    clean: list[dict[str, Any]] = []
    for row in placements:
        if not isinstance(row, dict) or not row.get("beatId"):
            continue
        clean.append(
            {
                "beatId": str(row["beatId"]),
                "usageId": row.get("usageId"),
                "engineId": row.get("engineId"),
                "locked": bool(row.get("locked")),
                "startFrame": int(row.get("startFrame") or 0),
                "endFrameExclusive": int(row.get("endFrameExclusive") or 1),
                "lines": list(row.get("lines") or []),
                "meta": dict(row.get("meta") or {}),
                "assets": dict(row.get("assets") or {}),
                "motion": dict(row.get("motion") or {}),
                "source": str(row.get("source") or SOURCE_ALGORITHM),
                "displayName": row.get("displayName"),
                "beatType": row.get("beatType"),
                "wordsText": row.get("wordsText"),
            }
        )
    locked_n = sum(1 for r in clean if r.get("locked"))
    return {
        "agent": "placement" if role == "original" else "placement-reviewed",
        "schemaVersion": SCHEMA_VERSION,
        "role": role,
        "projectRoot": str(project_root),
        "placementCount": len(clean),
        "lockedCount": locked_n,
        "unlockedCount": len(clean) - locked_n,
        "allLocked": bool(clean) and locked_n == len(clean),
        "beats": clean,
        "notes": (
            "Placement lines use text + revealFrame (absolute frames). "
            "No kickers. Final full render requires allLocked."
        ),
    }


def run_placement_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    library_root: Path | None = None,
) -> dict[str, Any]:
    """Place button: first run writes original+working; re-run skips locked beats."""

    del manifest
    root = video_project_root(manifest_path)
    mb_beats = _working_masterbeater_beats(root)
    if not mb_beats:
        raise FileNotFoundError("No Masterbeater beats. Finish Stage 1 first.")

    assign_rows = _working_assignment_rows(root)
    if not assign_rows:
        raise FileNotFoundError("No assignment. Run Assign (Stage 2) first.")

    assign_by_id = {str(r["beatId"]): r for r in assign_rows if r.get("usageId")}
    if not assign_by_id:
        raise ValueError("Assignment has no usage picks. Assign goldens first.")

    usages = list_golden_usages(library_root=library_root)
    usages_by_id = {str(u["id"]): u for u in usages}

    from app.core.scenelayer import working_layout_by_beat_id

    layout_by_beat = working_layout_by_beat_id(root)

    # Type indices for step/example numbers
    type_counts: dict[str, int] = {}
    mb_by_id = {str(b["id"]): b for b in mb_beats}

    original = load_placement_original(root)
    working_prior = load_placement_reviewed(root) or original
    prior_by_id = {
        str(r["beatId"]): r
        for r in ((working_prior or {}).get("beats") or [])
        if isinstance(r, dict) and r.get("beatId")
    }

    placements: list[dict[str, Any]] = []
    for beat in mb_beats:
        beat_id = str(beat.get("id") or "")
        row = assign_by_id.get(beat_id)
        if not row:
            continue
        prior = prior_by_id.get(beat_id)
        if prior and prior.get("locked"):
            # Locked beats are never overwritten by Place.
            placements.append(dict(prior))
            continue

        btype = str(beat.get("beatType") or "")
        idx = type_counts.get(btype, 0)
        type_counts[btype] = idx + 1
        drafted = draft_placement_for_beat(
            beat,
            row,
            usages_by_id=usages_by_id,
            layout_id=layout_by_beat.get(beat_id),
            index_among_type=idx,
            locked=False,
        )
        if drafted:
            placements.append(drafted)

    if not placements:
        raise ValueError("No placements could be drafted (no assigned beats with usages).")

    first_run = original is None
    if first_run:
        document = build_placement_document(placements, project_root=root, role="original")
        write_placement_original(root, document)
        working_doc = build_placement_document(placements, project_root=root, role="reviewed")
        working_doc["basedOnOriginal"] = True
        working_doc["originalFile"] = OUTPUT_FILENAME
        write_placement_reviewed(root, working_doc)
    else:
        working_doc = build_placement_document(placements, project_root=root, role="reviewed")
        working_doc["basedOnOriginal"] = True
        working_doc["originalFile"] = OUTPUT_FILENAME
        working_doc["reRun"] = True
        write_placement_reviewed(root, working_doc)

    return {
        "ok": True,
        "firstRun": first_run,
        "placementCount": working_doc.get("placementCount"),
        "lockedCount": working_doc.get("lockedCount"),
        "unlockedCount": working_doc.get("unlockedCount"),
        "allLocked": working_doc.get("allLocked"),
        "originalPath": str(output_path_for_project(root)),
        "reviewedPath": str(reviewed_path_for_project(root)),
        "result": working_doc,
        "beats": working_doc.get("beats"),
        "engineInterfaces": {
            p["engineId"]: placement_interface_summary(str(p["engineId"]))
            for p in placements
            if p.get("engineId")
        },
    }


def _normalize_lines(lines: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(lines, list):
        return out
    for row in lines:
        if not isinstance(row, dict):
            continue
        slot = str(row.get("slot") or "").strip()
        if not slot:
            continue
        try:
            rf = int(row.get("revealFrame") or 0)
        except (TypeError, ValueError):
            rf = 0
        out.append(
            {
                "slot": slot,
                "text": str(row.get("text") or ""),
                "revealFrame": rf,
            }
        )
    return out


def append_placement_ledger_entry(
    project_root: Path,
    *,
    beat_id: str,
    op: str,
    detail: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> dict[str, Any]:
    ledger = load_placement_ledger(project_root)
    entries: list[Any] = list(ledger.get("entries") or [])
    entry: dict[str, Any] = {
        "id": f"p-{len(entries) + 1:04d}",
        "at": datetime.now(timezone.utc).isoformat(),
        "op": op,
        "beatId": beat_id,
    }
    if detail:
        entry["detail"] = detail
    if before is not None:
        entry["before"] = before
    if after is not None:
        entry["after"] = after
    entries.append(entry)
    ledger["schemaVersion"] = 1
    ledger["agent"] = "placement-edit-ledger"
    ledger["originalFile"] = OUTPUT_FILENAME
    ledger["reviewedFile"] = REVIEWED_FILENAME
    ledger["entries"] = entries
    ledger["entryCount"] = len(entries)
    ledger["updatedAt"] = entry["at"]
    write_placement_ledger(project_root, ledger)
    return entry


def save_placement_beat_for_video_project(
    manifest_path: Path,
    manifest: dict,
    payload: dict,
) -> dict[str, Any]:
    """Save one beat's placement (lines/meta/lock). Original untouched."""

    del manifest
    root = video_project_root(manifest_path)
    original = load_placement_original(root)
    if original is None:
        raise FileNotFoundError("No placement.json. Press Place first.")

    beat_id = str(payload.get("beatId") or "").strip()
    if not beat_id:
        raise ValueError("beatId is required.")

    working = load_placement_reviewed(root) or original
    rows = [
        dict(r)
        for r in (working.get("beats") or [])
        if isinstance(r, dict) and r.get("beatId")
    ]
    by_id = {str(r["beatId"]): r for r in rows}
    if beat_id not in by_id:
        raise ValueError(f"Unknown placement beatId {beat_id!r}.")

    previous = dict(by_id[beat_id])
    if previous.get("locked") and not payload.get("force") and "locked" not in payload:
        # Allow unlock via locked:false; block content edits while locked unless unlocking.
        if payload.get("locked") is not False:
            raising = any(
                key in payload for key in ("lines", "meta", "assets", "motion", "startFrame", "endFrameExclusive")
            )
            if raising:
                raise ValueError("Beat is locked. Unlock before editing content or timing.")

    row = dict(previous)
    if "lines" in payload:
        row["lines"] = _normalize_lines(payload.get("lines"))
        row["source"] = SOURCE_HUMAN
    if "meta" in payload and isinstance(payload.get("meta"), dict):
        row["meta"] = dict(payload["meta"])
        row["meta"].pop("kicker", None)
        row["source"] = SOURCE_HUMAN
    if "assets" in payload and isinstance(payload.get("assets"), dict):
        row["assets"] = dict(payload["assets"])
        row["source"] = SOURCE_HUMAN
    if "motion" in payload and isinstance(payload.get("motion"), dict):
        row["motion"] = dict(payload["motion"])
        row["source"] = SOURCE_HUMAN
    if "startFrame" in payload:
        row["startFrame"] = int(payload["startFrame"])
        row["source"] = SOURCE_HUMAN
    if "endFrameExclusive" in payload:
        row["endFrameExclusive"] = int(payload["endFrameExclusive"])
        row["source"] = SOURCE_HUMAN
    if "locked" in payload:
        row["locked"] = bool(payload["locked"])

    by_id[beat_id] = row
    ordered = [by_id[str(r["beatId"])] for r in rows if str(r["beatId"]) in by_id]

    working_doc = build_placement_document(ordered, project_root=root, role="reviewed")
    working_doc["basedOnOriginal"] = True
    working_doc["originalFile"] = OUTPUT_FILENAME
    working_doc["edited"] = True
    write_placement_reviewed(root, working_doc)

    op = "lock" if payload.get("locked") is True else "unlock" if payload.get("locked") is False else "edit"
    ledger_entry = append_placement_ledger_entry(
        root,
        beat_id=beat_id,
        op=op,
        detail=str(payload.get("detail") or "").strip() or None,
        before={"locked": previous.get("locked"), "lineCount": len(previous.get("lines") or [])},
        after={"locked": row.get("locked"), "lineCount": len(row.get("lines") or [])},
    )

    engine_id = str(row.get("engineId") or "")
    engine_params = None
    try:
        if engine_id:
            engine_params = lines_to_engine_parameters(
                engine_id,
                list(row.get("lines") or []),
                meta=row.get("meta") if isinstance(row.get("meta"), dict) else {},
                assets=row.get("assets") if isinstance(row.get("assets"), dict) else {},
                motion=row.get("motion") if isinstance(row.get("motion"), dict) else {},
            )
    except Exception:
        engine_params = None

    return {
        "ok": True,
        "role": "reviewed",
        "edited": True,
        "beatId": beat_id,
        "placement": row,
        "engineParameters": engine_params,
        "result": working_doc,
        "beats": working_doc.get("beats"),
        "lockedCount": working_doc.get("lockedCount"),
        "unlockedCount": working_doc.get("unlockedCount"),
        "allLocked": working_doc.get("allLocked"),
        "ledgerEntry": ledger_entry,
        "ledgerEntryCount": int(load_placement_ledger(root).get("entryCount") or 0),
        "finalRenderReady": bool(working_doc.get("allLocked")),
    }


def placement_status_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    library_root: Path | None = None,
) -> dict[str, Any]:
    del manifest
    root = video_project_root(manifest_path)
    original = None
    reviewed = None
    try:
        original = load_placement_original(root)
    except (OSError, json.JSONDecodeError):
        original = None
    try:
        reviewed = load_placement_reviewed(root)
    except (OSError, json.JSONDecodeError):
        reviewed = None

    working = reviewed if reviewed is not None else original
    ledger_path = ledger_path_for_project(root)
    ledger_entry_count = 0
    if ledger_path.is_file():
        try:
            ledger = load_placement_ledger(root)
            ledger_entry_count = int(ledger.get("entryCount") or len(ledger.get("entries") or []))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            ledger_entry_count = 0

    beats = list((working or {}).get("beats") or []) if working else []
    locked_n = sum(1 for b in beats if isinstance(b, dict) and b.get("locked"))
    by_beat = {
        str(b["beatId"]): b for b in beats if isinstance(b, dict) and b.get("beatId")
    }

    interfaces: dict[str, Any] = {}
    for b in beats:
        if not isinstance(b, dict):
            continue
        eid = str(b.get("engineId") or "")
        if eid and eid not in interfaces:
            try:
                interfaces[eid] = placement_interface_summary(eid)
            except KeyError:
                interfaces[eid] = {"engineId": eid, "error": "unknown engine"}

    return {
        "ok": True,
        "originalPath": str(output_path_for_project(root)),
        "originalExists": original is not None,
        "reviewedPath": str(reviewed_path_for_project(root)),
        "reviewedExists": reviewed is not None,
        "ledgerPath": str(ledger_path),
        "ledgerExists": ledger_path.is_file(),
        "ledgerEntryCount": ledger_entry_count,
        "placementCount": len(beats),
        "lockedCount": locked_n,
        "unlockedCount": len(beats) - locked_n,
        "allLocked": bool(beats) and locked_n == len(beats),
        "finalRenderReady": bool(beats) and locked_n == len(beats),
        "result": working,
        "byBeatId": by_beat,
        "engineInterfaces": interfaces,
    }


def preview_workspace_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / PREVIEW_DIRNAME


def _prune_stale_placement_preview_workspaces(
    preview_root: Path,
    *,
    keep_fingerprint: str,
    keep_recent: int = 6,
) -> None:
    """Best-effort cleanup of old per-fingerprint HyperFrames preview folders.

    Keeps the active fingerprint plus a few recent dirs. Never raises — locked
    Windows media files are skipped.
    """

    base = Path(preview_root) / "hyperframes"
    if not base.is_dir():
        return
    keep_fp = str(keep_fingerprint or "").strip()
    try:
        entries = [p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return
    # Prefer newest mtime among non-keep dirs for retention.
    ranked = sorted(
        entries,
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    retained = 0
    for path in ranked:
        # Keep the canonical fingerprint folder and any Windows divert siblings
        # (``{fingerprint}-w{suffix}``) from the same build family.
        if keep_fp and (path.name == keep_fp or path.name.startswith(f"{keep_fp}-w")):
            continue
        if retained < keep_recent:
            retained += 1
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass
    # Also drop any .stale-* leftovers from rename recovery.
    try:
        for path in base.iterdir():
            if path.name.startswith(".") and "stale" in path.name:
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass
    except OSError:
        pass


def _placement_preview_fingerprint(
    placement: dict[str, Any],
    *,
    source_rel: str,
    fps: float,
    beat_end_frame_exclusive: int | None = None,
) -> str:
    payload = {
        "beatId": placement.get("beatId"),
        "engineId": placement.get("engineId"),
        "startFrame": int(placement.get("startFrame") or 0),
        # Graphic undock (placement Ends). Separate from preview window end.
        "endFrameExclusive": int(placement.get("endFrameExclusive") or 0),
        "beatEndFrameExclusive": int(
            beat_end_frame_exclusive
            if beat_end_frame_exclusive is not None
            else (placement.get("endFrameExclusive") or 0)
        ),
        "lines": placement.get("lines") or [],
        "meta": placement.get("meta") or {},
        "assets": placement.get("assets") or {},
        "motion": placement.get("motion") or {},
        "source": source_rel,
        "fps": round(float(fps), 3),
        # Bump when default asset/layout recipe for an engine changes (invalidates cache).
        # 3: no #main-audio in preview compositions (monotonic transport clock; the
        #    studio plays speech via an app-owned audio element instead).
        # 4: punchline-reveal redesign — kicker removed; end via endFrameExclusive; custom
        #    placement images stage from assets/placement/.
        # 5: stage/dock at beat start; Title reveal = image + caption only (not whole card).
        # 6: same contract; force rebuild of Claude-era caches that delayed the whole stage.
        # 7: preview range = full beat; placement endFrameExclusive only ends the graphic cue.
        "previewRecipe": 7,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _resolve_working_placement_row(project_root: Path, beat_id: str) -> dict[str, Any]:
    original = load_placement_original(project_root)
    reviewed = load_placement_reviewed(project_root)
    working = reviewed if reviewed is not None else original
    if working is None:
        raise FileNotFoundError("No placement draft. Press Place first.")
    for row in working.get("beats") or []:
        if isinstance(row, dict) and str(row.get("beatId") or "") == beat_id:
            return dict(row)
    raise ValueError(f"No placement for beat {beat_id!r}.")


def _apply_preview_overrides(
    row: dict[str, Any],
    *,
    lines: list | None = None,
    meta: dict | None = None,
    assets: dict | None = None,
    motion: dict | None = None,
    start_frame: int | None = None,
    end_frame_exclusive: int | None = None,
) -> dict[str, Any]:
    out = dict(row)
    if lines is not None:
        out["lines"] = _normalize_lines(lines)
    if meta is not None and isinstance(meta, dict):
        clean = dict(meta)
        clean.pop("kicker", None)
        out["meta"] = clean
    if assets is not None and isinstance(assets, dict):
        out["assets"] = dict(assets)
    if motion is not None and isinstance(motion, dict):
        out["motion"] = dict(motion)
    if start_frame is not None:
        out["startFrame"] = int(start_frame)
    if end_frame_exclusive is not None:
        out["endFrameExclusive"] = int(end_frame_exclusive)
    start = int(out.get("startFrame") or 0)
    end = int(out.get("endFrameExclusive") or start + 1)
    if end <= start:
        out["endFrameExclusive"] = start + 1
    return out


def _semantic_items_for_placement_cue(
    cue: dict[str, Any],
    placement: dict[str, Any],
    *,
    fps: float,
) -> list[dict[str, Any]]:
    """Reveal-aware semantic items that satisfy visual-plan validation."""

    from app.core.graphics_library import _semantic_items_for_cue

    items = _semantic_items_for_cue(cue, reveal_stagger_sec=0.0)
    start_sec = float(cue["startSec"])
    end_sec = float(cue["endSec"])
    start_f = int(placement.get("startFrame") or 0)
    by_path: dict[str, float] = {}
    for line in placement.get("lines") or []:
        if not isinstance(line, dict):
            continue
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        path = slot_to_parameter_path(str(line.get("slot") or ""))
        try:
            rf = int(line.get("revealFrame") if line.get("revealFrame") is not None else start_f)
        except (TypeError, ValueError):
            rf = start_f
        spoken = max(start_sec, min(end_sec - 0.05, rf / max(fps, 1.0)))
        by_path[path] = spoken

    for item in items:
        path = str(item.get("parameterPath") or "")
        if path not in by_path:
            continue
        spoken = by_path[path]
        item["spokenStartSec"] = spoken
        item["fullyVisibleSec"] = min(end_sec, max(spoken + 0.05, spoken + 0.35))
        item["anchorType"] = "spoken"
        item["phrase"] = str(item.get("text") or item.get("phrase") or "")
    return items


def _sanitize_engine_parameters_for_plan(engine_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Coerce placement params so visual-plan.schema.json oneOf accepts the cue.

    Invalid enums/list lengths fail every module branch and jsonschema best_match
    often reports the last branches (`assetId` / `compositionId`) — unhelpful.
    """

    out = dict(params)
    eid = str(engine_id or "").strip()

    if eid == "source-punch-zoom":
        motion = str(out.get("motion") or "").strip()
        if motion not in {"in", "out", "in-out"}:
            # Legacy drafts used "punch"; schema + engine path use in-out.
            out["motion"] = "in-out"
        for key, default, lo, hi in (
            ("focusX", 0.5, 0.0, 1.0),
            ("focusY", 0.42, 0.0, 1.0),
            ("zoom", 1.35, 1.02, 2.0),
            ("settleSec", 0.45, 0.2, 5.0),
        ):
            try:
                val = float(out.get(key, default))
            except (TypeError, ValueError):
                val = default
            out[key] = max(lo, min(hi, val))

    # Clamp known list lengths to schema / placement contracts.
    list_caps = {
        "titleLines": 8,  # numbered-example-card (schema aligned with placement list_max)
        "nodes": 6,
        "items": 12,
        "callouts": 8,
        "milestones": 8,
        "cards": 3,
        "tags": 4,
    }
    for key, cap in list_caps.items():
        if key in out and isinstance(out[key], list) and len(out[key]) > cap:
            out[key] = list(out[key][:cap])

    if "accentLineIndex" in out:
        try:
            idx = int(out["accentLineIndex"])
        except (TypeError, ValueError):
            idx = 0
        n_lines = len(out["titleLines"]) if isinstance(out.get("titleLines"), list) else 0
        if n_lines > 0:
            out["accentLineIndex"] = max(-1, min(n_lines - 1, idx))
        else:
            out["accentLineIndex"] = max(-1, min(7, idx))

    return out


def build_cue_preview_payload(placement: dict[str, Any], *, fps: float = 30.0) -> dict[str, Any]:
    """Engine cue for a single placement (live Tier B preview / final package)."""

    engine_id = str(placement.get("engineId") or "")
    start_f = int(placement.get("startFrame") or 0)
    end_f = int(placement.get("endFrameExclusive") or start_f + 1)
    if end_f <= start_f:
        end_f = start_f + 1
    fps = float(fps) if fps else 30.0
    start_sec = start_f / fps
    end_sec = end_f / fps
    # Ensure positive cue duration for engines with multi-phase motion.
    if end_sec <= start_sec:
        end_sec = start_sec + 1.0 / fps
    assets_bag = (
        placement.get("assets") if isinstance(placement.get("assets"), dict) else {}
    )
    params = lines_to_engine_parameters(
        engine_id,
        list(placement.get("lines") or []),
        meta=placement.get("meta") if isinstance(placement.get("meta"), dict) else {},
        assets=assets_bag,
        motion=placement.get("motion") if isinstance(placement.get("motion"), dict) else {},
    )
    # Drop blank asset ids, then fill golden-matching defaults (joke image card, etc.).
    for key in ("imageAssetId", "logoAssetId"):
        if key in params and not str(params.get(key) or "").strip():
            params.pop(key, None)
    params = _ensure_engine_assets_for_preview(engine_id, params)
    # Coerce values that break visual-plan.schema.json (misleading oneOf → "assetId required").
    params = _sanitize_engine_parameters_for_plan(engine_id, params)

    cue = {
        "id": f"cue-{placement.get('beatId') or 'beat'}",
        "kind": "module",
        "moduleId": engine_id,
        "startSec": start_sec,
        "endSec": end_sec,
        "enabled": True,
        "parameters": params,
        "semanticItems": [],
    }
    cue["semanticItems"] = _semantic_items_for_placement_cue(cue, placement, fps=fps)
    return {
        **cue,
        "startFrame": start_f,
        "endFrameExclusive": end_f,
        "usageId": placement.get("usageId"),
        "beatId": placement.get("beatId"),
        "locked": bool(placement.get("locked")),
    }


def build_placement_live_preview(
    manifest_path: Path,
    manifest: dict,
    *,
    beat_id: str,
    lines: list | None = None,
    meta: dict | None = None,
    assets: dict | None = None,
    motion: dict | None = None,
    start_frame: int | None = None,
    end_frame_exclusive: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build a single-beat HyperFrames composition for live Tier B placement preview.

    No final encode — HTML + GSAP composition only, scrubbed in the browser.
    """

    from app.core.file_utils import sha256_file
    from app.core.visual_production import (
        VISUAL_PLAN_VERSION,
        build_hyperframes_composition,
        probe_visual_source,
        validate_visual_plan,
    )

    root = video_project_root(manifest_path)
    beat_id = str(beat_id or "").strip()
    if not beat_id:
        raise ValueError("beatId is required.")

    row = _resolve_working_placement_row(root, beat_id)
    placement = _apply_preview_overrides(
        row,
        lines=lines,
        meta=meta,
        assets=assets,
        motion=motion,
        start_frame=start_frame,
        end_frame_exclusive=end_frame_exclusive,
    )
    engine_id = str(placement.get("engineId") or "").strip()
    if not engine_id:
        raise ValueError(f"Placement {beat_id} has no engineId.")

    source_path = preferred_stage_source(manifest_path, manifest)
    if not source_path.is_file():
        raise FileNotFoundError("No locked cut / stage source video for live preview.")
    try:
        source_rel = source_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Stage source must stay inside the video project.") from exc

    meta_probe = probe_visual_source(source_path)
    fps = float(meta_probe.get("fps") or 30.0) or 30.0
    width = int(meta_probe.get("width") or 1920)
    height = int(meta_probe.get("height") or 1080)
    if width >= height:
        width, height = 1920, 1080
    full_duration = float(meta_probe.get("durationSec") or 0.0)
    if full_duration <= 0:
        raise RuntimeError("Could not probe stage source duration.")

    start_f = int(placement.get("startFrame") or 0)
    # Graphic undock frame (placement Ends). Cue ends here; talking-head continues.
    graphic_end_f = int(placement.get("endFrameExclusive") or start_f + 1)
    if graphic_end_f <= start_f:
        graphic_end_f = start_f + 1
    # Preview composition always covers the full speech beat so trimming Ends only
    # ends the graphic — the player keeps rolling on full-frame talking-head.
    mb_beat = _masterbeater_beat_by_id(root, beat_id)
    beat_end_f = _beat_end_frame_exclusive(mb_beat, fallback=graphic_end_f)
    if beat_end_f < graphic_end_f:
        beat_end_f = graphic_end_f
    if beat_end_f <= start_f:
        beat_end_f = start_f + 1

    start_sec = max(0.0, start_f / fps)
    graphic_end_sec = min(full_duration, graphic_end_f / fps)
    beat_end_sec = min(full_duration, beat_end_f / fps)
    if graphic_end_sec <= start_sec:
        graphic_end_sec = min(full_duration, start_sec + max(1.0 / fps, 0.5))
    if beat_end_sec <= start_sec:
        beat_end_sec = min(full_duration, start_sec + max(1.0 / fps, 0.5))
    # Tiny pad so enter/exit motion is not clipped at the edges.
    range_start = max(0.0, start_sec - 0.05)
    range_end = min(full_duration, beat_end_sec + 0.08)
    if range_end <= range_start:
        range_end = min(full_duration, range_start + 0.5)

    fingerprint = _placement_preview_fingerprint(
        placement,
        source_rel=source_rel,
        fps=fps,
        beat_end_frame_exclusive=beat_end_f,
    )
    preview_root = preview_workspace_for_project(root)
    # Per-fingerprint workspace so switching beats / edits never rmtree a source.mp4
    # still held open by the browser hyperframes-player (Windows WinError 32).
    # build_hyperframes_composition writes index.html under workspace/public/.
    workspace = preview_root / "hyperframes" / fingerprint
    runtime_public = workspace / "public"
    plan_path = preview_root / "visual-plan.preview.json"
    # Receipt lives with the fingerprint folder so beat A stays cacheable after viewing B.
    receipt_path = workspace / PREVIEW_RECEIPT
    entry = runtime_public / "index.html"

    if (
        not force
        and entry.is_file()
        and (runtime_public / "source.mp4").is_file()
        and receipt_path.is_file()
    ):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            if (
                isinstance(receipt, dict)
                and receipt.get("fingerprint") == fingerprint
                and receipt.get("beatId") == beat_id
            ):
                return {
                    "ok": True,
                    "available": True,
                    "reused": True,
                    "beatId": beat_id,
                    "engineId": engine_id,
                    "cacheKey": fingerprint,
                    "durationSec": float(receipt.get("durationSec") or (range_end - range_start)),
                    # Preview window = full beat; graphic may undock earlier.
                    "startFrame": start_f,
                    "endFrameExclusive": int(receipt.get("endFrameExclusive") or beat_end_f),
                    "graphicEndFrameExclusive": int(
                        receipt.get("graphicEndFrameExclusive") or graphic_end_f
                    ),
                    "startSec": start_sec,
                    "endSec": beat_end_sec,
                    "graphicEndSec": graphic_end_sec,
                    "rangeStartSec": float(receipt.get("rangeStartSec") or range_start),
                    "rangeEndSec": float(receipt.get("rangeEndSec") or range_end),
                    "fps": fps,
                    "width": width,
                    "height": height,
                    "workspace": str(runtime_public),
                    "compositionEntry": str(entry),
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    # Cue ends at graphic Ends (undock). Composition range continues to beat end.
    cue_placement = dict(placement)
    cue_placement["endFrameExclusive"] = graphic_end_f
    cue_payload = build_cue_preview_payload(cue_placement, fps=fps)
    # Clamp cue to full source duration for plan validation.
    cue_start = max(0.0, min(full_duration - 0.05, float(cue_payload["startSec"])))
    cue_end = max(cue_start + 0.05, min(full_duration, float(cue_payload["endSec"])))
    # Never let the cue outlast the preview window.
    cue_end = min(cue_end, beat_end_sec)
    cue_params = dict(cue_payload.get("parameters") or {})
    cue = {
        "id": cue_payload["id"],
        "kind": "module",
        "moduleId": engine_id,
        "startSec": cue_start,
        "endSec": cue_end,
        "enabled": True,
        "parameters": cue_params,
        "semanticItems": list(cue_payload.get("semanticItems") or []),
    }
    # Re-clamp semantic items into the cue window after any duration shrink.
    for item in cue["semanticItems"]:
        if not isinstance(item, dict):
            continue
        spoken = float(item.get("spokenStartSec") or cue_start)
        fully = float(item.get("fullyVisibleSec") or spoken)
        spoken = max(cue_start, min(cue_end - 0.02, spoken))
        fully = max(spoken, min(cue_end, fully))
        item["spokenStartSec"] = spoken
        item["fullyVisibleSec"] = fully

    plan_assets = _stage_plan_assets_for_preview(root, engine_id=engine_id, params=cue_params)

    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "schemaVersion": VISUAL_PLAN_VERSION,
        "project": {
            "id": f"placement-preview-{beat_id}",
            "name": f"Placement preview · {beat_id}",
            "createdAt": now,
            "updatedAt": now,
        },
        "source": {
            "video": source_rel,
            "transcript": "",
            "videoSha256": sha256_file(source_path),
        },
        "composition": {
            "width": width,
            "height": height,
            "fps": round(fps, 3),
            "durationSec": full_duration,
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

    preview_root.mkdir(parents=True, exist_ok=True)
    validate_visual_plan(plan, root)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    runtime_root, render_duration = build_hyperframes_composition(
        plan_path,
        start_sec=range_start,
        end_sec=range_end,
        workspace_override=workspace,
        # No in-composition audio: the HyperFrames transport clock pins (freezes) on
        # audio-derived time sources. The studio supplies speech audio itself.
        include_source_audio=False,
    )
    if not (runtime_root / "index.html").is_file():
        raise RuntimeError("HyperFrames placement preview composition was not written.")

    # build_hyperframes_composition may divert to a sibling folder when the preferred
    # fingerprint path is locked by the live player (Windows WinError 32). Receipt
    # and returned workspace always follow the path that was actually written.
    actual_workspace = runtime_root.parent
    receipt_path = actual_workspace / PREVIEW_RECEIPT

    receipt = {
        "fingerprint": fingerprint,
        "beatId": beat_id,
        "engineId": engine_id,
        "durationSec": float(render_duration),
        "rangeStartSec": range_start,
        "rangeEndSec": range_end,
        "startFrame": start_f,
        "endFrameExclusive": beat_end_f,
        "graphicEndFrameExclusive": graphic_end_f,
        "builtAt": now,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _prune_stale_placement_preview_workspaces(preview_root, keep_fingerprint=fingerprint)

    return {
        "ok": True,
        "available": True,
        "reused": False,
        "beatId": beat_id,
        "engineId": engine_id,
        "cacheKey": fingerprint,
        "durationSec": float(render_duration),
        "startFrame": start_f,
        "endFrameExclusive": beat_end_f,
        "graphicEndFrameExclusive": graphic_end_f,
        "startSec": start_sec,
        "endSec": beat_end_sec,
        "graphicEndSec": graphic_end_sec,
        "rangeStartSec": range_start,
        "rangeEndSec": range_end,
        "fps": fps,
        "width": width,
        "height": height,
        "workspace": str(runtime_root),
        "compositionEntry": str(runtime_root / "index.html"),
    }
