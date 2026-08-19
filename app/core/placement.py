"""Stage 3 Placement — lines + reveal frames, lock, full-render gate.

See docs/vcg-graphics-process/placement.md and app/core/placement_roles.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
# Full-episode Final encode workspace + published delivery (locked-cut audio remuxed).
FINAL_DIRNAME = "working/placement-final"
FINAL_PLAN_FILENAME = "visual-plan.final.json"
FINAL_RECEIPT = "final-receipt.json"
FINAL_JOB_FILENAME = "render-job.json"
FINAL_OUTPUT_REL = "exports/final-video.mp4"

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
    from app.core.masterbeater import sort_beats_by_timeline

    reviewed = load_masterbeater_reviewed(project_root)
    original = load_masterbeater_output(project_root)
    working = reviewed if reviewed is not None else original
    if working is None:
        return []
    return sort_beats_by_timeline(
        [b for b in (working.get("beats") or []) if isinstance(b, dict) and b.get("id")]
    )


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
    if "pointer" in keys:
        motion["pointer"] = "below"
    if engine_id == "source-punch-zoom":
        motion.setdefault("focusX", 0.5)
        motion.setdefault("focusY", 0.42)
        motion.setdefault("zoom", 1.35)
        motion.setdefault("settleSec", 0.45)
        # visual-plan.schema.json: motion enum is in | out | in-out (not "punch").
        motion.setdefault("motion", "in-out")
        # zoomInFrame / zoomOutFrame filled in draft_placement_for_beat once span is known.
    return {k: v for k, v in motion.items() if k in keys}


# Default ui-callout ring (upper-right demo region) — matches prior draw fallback.
_UI_CALLOUT_DEFAULT_BOUNDS = {"x": 0.55, "y": 0.12, "width": 0.35, "height": 0.18}


def _default_meta(engine_id: str, *, index_among_type: int) -> dict[str, Any]:
    spec = get_engine_placement_spec(engine_id)
    keys = set(spec.get("meta_keys") or [])
    meta: dict[str, Any] = {}
    if "stepNumber" in keys:
        meta["stepNumber"] = index_among_type + 1
    if "numberLabel" in keys:
        # Free string so operators can choose "2" or "02".
        meta["numberLabel"] = str(index_among_type + 1)
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
    # ui-callout ring geometry (normalized 0–1 upper-left + size).
    if "x" in keys:
        meta["x"] = _UI_CALLOUT_DEFAULT_BOUNDS["x"]
    if "y" in keys:
        meta["y"] = _UI_CALLOUT_DEFAULT_BOUNDS["y"]
    if "width" in keys:
        meta["width"] = _UI_CALLOUT_DEFAULT_BOUNDS["width"]
    if "height" in keys:
        meta["height"] = _UI_CALLOUT_DEFAULT_BOUNDS["height"]
    return {k: v for k, v in meta.items() if k in keys}


def _expand_ui_callout_bounds_into_meta(row: dict[str, Any]) -> dict[str, Any]:
    """Surface nested targetBounds as craft meta knobs for older placements."""

    out = dict(row)
    if str(out.get("engineId") or "") != "ui-callout":
        return out
    meta = dict(out.get("meta") or {})
    motion = out.get("motion") if isinstance(out.get("motion"), dict) else {}
    nested = motion.get("targetBounds") if isinstance(motion.get("targetBounds"), dict) else None
    if nested is None and isinstance(meta.get("targetBounds"), dict):
        nested = meta.get("targetBounds")
    for key in ("x", "y", "width", "height"):
        if key in meta and meta[key] not in (None, ""):
            continue
        if nested is not None and nested.get(key) is not None:
            meta[key] = nested[key]
        else:
            meta.setdefault(key, _UI_CALLOUT_DEFAULT_BOUNDS[key])
    meta.pop("targetBounds", None)
    out["meta"] = meta
    return out


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

    if engine_id in {"source-punch-zoom", "brand-cta-lockup"}:
        # Punch zoom: motion-only. Brand CTA: join line + link are brand-fixed.
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
        elif engine_id == "numbered-phrase-reveal":
            # Optional title stays empty by default; phrase gets the beat words.
            lines.append(empty_line("title", text="", reveal_frame=start))
            lines.append(
                empty_line(
                    "text",
                    text=words or "Phrase",
                    reveal_frame=start + max(1, span // 4),
                )
            )
        elif engine_id == "ui-callout":
            lines.append(empty_line("label", text=words or "UI", reveal_frame=start))
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
    from app.core.visual_production import canonicalize_engine_id

    engine_id = str(usage.get("engineId") or resolve_engine_id(usage_id) or "").strip()
    if not engine_id:
        engine_id = usage_id
    engine_id = canonicalize_engine_id(engine_id)

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

    if engine_id == "source-punch-zoom":
        # Absolute locked-cut frames when the camera move starts.
        # Zoom in at beat start; zoom out ~15% of the span before beat end (min 1f gap).
        span = max(1, end - start)
        motion = dict(motion or {})
        motion.setdefault("zoomInFrame", start)
        motion.setdefault("zoomOutFrame", max(start + 1, end - max(1, span // 6)))

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
    # Transcript time order — matches Masterbeater + Final cue sort.
    clean.sort(
        key=lambda r: (
            int(r.get("startFrame") or 0),
            int(r.get("endFrameExclusive") or 0),
            str(r.get("beatId") or ""),
        )
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
            # Locked content is kept; still rewrite retired engine ids so Place can
            # return interfaces without KeyError (speaker-side-panel → dependency-stack).
            placements.append(normalize_placement_engine(dict(prior)))
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
            placements.append(normalize_placement_engine(drafted))

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

    interfaces: dict[str, Any] = {}
    for p in placements:
        eid = str(p.get("engineId") or "").strip()
        if not eid or eid in interfaces:
            continue
        try:
            interfaces[eid] = placement_interface_summary(eid)
        except KeyError:
            interfaces[eid] = {"engineId": eid, "error": "unknown engine"}

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
        "engineInterfaces": interfaces,
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


def _filter_lines_to_engine_slots(engine_id: str, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop retired slots (e.g. brand-cta logoText) so craft UI matches the interface."""

    try:
        spec = get_engine_placement_spec(engine_id)
    except KeyError:
        return list(lines)
    fixed = {str(s) for s in (spec.get("fixed_line_slots") or [])}
    list_slot = spec.get("list_slot")
    list_prefix = f"{list_slot}." if list_slot else None
    out: list[dict[str, Any]] = []
    for row in lines:
        slot = str(row.get("slot") or "")
        if slot in fixed:
            out.append(row)
        elif list_prefix and slot.startswith(list_prefix):
            out.append(row)
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
        row["lines"] = _filter_lines_to_engine_slots(
            str(row.get("engineId") or ""),
            _normalize_lines(payload.get("lines")),
        )
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
    ordered = list(by_id.values())

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
    by_beat: dict[str, Any] = {}
    for b in beats:
        if not isinstance(b, dict) or not b.get("beatId"):
            continue
        row = normalize_placement_engine(dict(b))
        eid = str(row.get("engineId") or "")
        if eid and isinstance(row.get("lines"), list):
            row["lines"] = _filter_lines_to_engine_slots(eid, list(row["lines"]))
        # Retired brand-cta asset knobs — not placement craft.
        if eid == "brand-cta-lockup" and isinstance(row.get("assets"), dict):
            assets = dict(row["assets"])
            assets.pop("logoAssetId", None)
            row["assets"] = assets
        row = _expand_ui_callout_bounds_into_meta(row)
        by_beat[str(row["beatId"])] = row

    interfaces: dict[str, Any] = {}
    for b in by_beat.values():
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
    # Same engine-compose recipe Final uses — one version, both surfaces.
    from app.core.visual_production import ENGINE_COMPOSE_RECIPE

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
        # Shared with Final fingerprint. Bump ENGINE_COMPOSE_RECIPE in
        # visual_production.py when engine draw/timeline/dock math changes.
        "engineComposeRecipe": ENGINE_COMPOSE_RECIPE,
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


def _coerce_bool_param(value: Any, *, default: bool = True) -> bool:
    """Accept true bools plus common UI text/number forms from placement knobs."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


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
        # Absolute frame anchors (when each camera move starts). Keep integers ≥ 0.
        for key in ("zoomInFrame", "zoomOutFrame"):
            if key not in out:
                continue
            try:
                out[key] = max(0, int(round(float(out[key]))))
            except (TypeError, ValueError):
                out.pop(key, None)

    if eid == "numbered-step-intro":
        # Placement knobs are free-text in the UI; coerce before schema oneOf.
        if "stepNumber" in out:
            try:
                out["stepNumber"] = max(1, min(99, int(round(float(out["stepNumber"])))))
            except (TypeError, ValueError):
                out["stepNumber"] = 1
        if "showNumber" in out:
            out["showNumber"] = _coerce_bool_param(out.get("showNumber"), default=True)
        side = str(out.get("side") or "").strip().lower()
        if side and side not in {"left", "right"}:
            out["side"] = "left"

    if eid == "numbered-phrase-reveal":
        # Schema wants string fields. Meta knobs often arrive as numbers (2) or null
        # from the craft UI; without coercion every module oneOf branch fails and
        # jsonschema best_match reports the misleading last branch (assetId required).
        if "numberLabel" in out and out["numberLabel"] is not None:
            out["numberLabel"] = str(out["numberLabel"])
        elif "numberLabel" not in out or out.get("numberLabel") is None:
            out["numberLabel"] = "1"
        for key in ("title", "text"):
            if key not in out or out[key] is None:
                out[key] = ""
            elif not isinstance(out[key], str):
                out[key] = str(out[key])

    if eid == "intro-credentials":
        # Name + thankYou must be strings for schema oneOf; nodes list of strings.
        for key in ("text", "thankYou"):
            if key not in out or out[key] is None:
                out[key] = ""
            elif not isinstance(out[key], str):
                out[key] = str(out[key])
        nodes = out.get("nodes")
        if nodes is None:
            out["nodes"] = []
        elif isinstance(nodes, list):
            out["nodes"] = [str(v) for v in nodes if str(v).strip()]
        else:
            out["nodes"] = [str(nodes)] if str(nodes).strip() else []

    if eid == "tradeoff-meter":
        # Meta knobs arrive as strings from the craft UI ("0.8") — schema wants number.
        if "value" in out:
            try:
                out["value"] = max(0.0, min(1.0, float(out["value"])))
            except (TypeError, ValueError):
                out["value"] = 0.5
        side = str(out.get("side") or "").strip().lower()
        if side and side not in {"left", "right"}:
            out["side"] = "left"

    if eid == "ui-callout":
        # Craft knobs are flat x/y/width/height (strings from UI). Schema wants nested
        # targetBounds; strip flats so unevaluatedProperties does not reject the cue.
        defaults = dict(_UI_CALLOUT_DEFAULT_BOUNDS)
        nested = out.get("targetBounds") if isinstance(out.get("targetBounds"), dict) else {}
        assembled: dict[str, float] = {}
        for key in ("x", "y", "width", "height"):
            raw = out.get(key, nested.get(key, defaults[key]))
            try:
                assembled[key] = float(raw)
            except (TypeError, ValueError):
                assembled[key] = float(defaults[key])
        assembled["x"] = max(0.0, min(0.98, assembled["x"]))
        assembled["y"] = max(0.0, min(0.98, assembled["y"]))
        assembled["width"] = max(0.02, min(1.0 - assembled["x"], assembled["width"]))
        assembled["height"] = max(0.02, min(1.0 - assembled["y"], assembled["height"]))
        out["targetBounds"] = assembled
        for key in ("x", "y", "width", "height"):
            out.pop(key, None)
        # Detail line retired from craft (label-only).
        out.pop("detail", None)
        pointer = str(out.get("pointer") or "below").strip().lower()
        out["pointer"] = "above" if pointer == "above" else "below"

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


def normalize_placement_engine(placement: dict[str, Any]) -> dict[str, Any]:
    """Rewrite retired engine/usage ids on a placement row (e.g. speaker-side-panel → dependency-stack)."""

    from app.core.visual_production import RETIRED_ENGINE_ALIASES, canonicalize_engine_id

    if not isinstance(placement, dict):
        return placement
    raw = str(placement.get("engineId") or "").strip()
    raw_usage = str(placement.get("usageId") or "").strip()
    live = canonicalize_engine_id(raw) if raw else ""
    live_usage = RETIRED_ENGINE_ALIASES.get(raw_usage, raw_usage)
    if (not live or live == raw) and live_usage == raw_usage:
        return placement
    out = dict(placement)
    if live and live != raw:
        out["engineId"] = live
    if live_usage and live_usage != raw_usage:
        out["usageId"] = live_usage
        # Drop shelf name that belonged to the retired card.
        if str(out.get("displayName") or "").strip().lower().startswith("speaker side panel"):
            out["displayName"] = "Dependency Stack"
    if (raw == "speaker-side-panel" or live_usage == "dependency-stack" and raw_usage == "speaker-side-panel") and (
        live == "dependency-stack" or live_usage == "dependency-stack"
    ):
        lines: list[dict[str, Any]] = []
        for line in placement.get("lines") or []:
            if not isinstance(line, dict):
                continue
            row = dict(line)
            slot = str(row.get("slot") or "")
            if slot.startswith("items."):
                row["slot"] = "nodes." + slot.split(".", 1)[1]
            lines.append(row)
        if lines or placement.get("lines"):
            out["lines"] = lines
        if not out.get("engineId") or out.get("engineId") == "speaker-side-panel":
            out["engineId"] = "dependency-stack"
    return out


def build_cue_preview_payload(placement: dict[str, Any], *, fps: float = 30.0) -> dict[str, Any]:
    """Engine cue for a single placement (live Tier B preview / final package)."""

    placement = normalize_placement_engine(placement)
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


# ---------------------------------------------------------------------------
# Full-episode Final (all locked placements → one HyperFrames encode)
# ---------------------------------------------------------------------------


def final_workspace_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / FINAL_DIRNAME


def final_output_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / FINAL_OUTPUT_REL


def final_job_path_for_project(project_root: Path) -> Path:
    return final_workspace_for_project(project_root) / FINAL_JOB_FILENAME


def _working_placement_document(root: Path) -> dict[str, Any] | None:
    try:
        reviewed = load_placement_reviewed(root)
        if reviewed is not None:
            return reviewed
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    try:
        return load_placement_original(root)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _placement_beats_ready_for_final(root: Path) -> list[dict[str, Any]]:
    """Return ordered locked placement rows, or raise if Final is not ready."""

    working = _working_placement_document(root)
    if not working:
        raise ValueError("No placements yet. Run Place and lock every assigned beat first.")
    beats = [b for b in (working.get("beats") or []) if isinstance(b, dict) and b.get("beatId")]
    if not beats:
        raise ValueError("No placement beats to render.")
    unlocked = [str(b.get("beatId")) for b in beats if not b.get("locked")]
    if unlocked:
        sample = ", ".join(unlocked[:6])
        more = f" (+{len(unlocked) - 6} more)" if len(unlocked) > 6 else ""
        raise ValueError(
            f"Final requires every assigned placement locked. Still unlocked: {sample}{more}."
        )
    return beats


def _cue_from_placement_for_final(
    placement: dict[str, Any],
    *,
    fps: float,
    full_duration: float,
) -> dict[str, Any]:
    """Absolute-timeline cue for full-episode package (graphic Ends = undock)."""

    placement = normalize_placement_engine(placement)
    cue_payload = build_cue_preview_payload(placement, fps=fps)
    engine_id = str(cue_payload.get("moduleId") or placement.get("engineId") or "").strip()
    cue_start = max(0.0, min(full_duration - 0.05, float(cue_payload["startSec"])))
    cue_end = max(cue_start + 0.05, min(full_duration, float(cue_payload["endSec"])))
    cue_params = dict(cue_payload.get("parameters") or {})
    cue = {
        "id": str(cue_payload.get("id") or f"cue-{placement.get('beatId') or 'beat'}"),
        "kind": "module",
        "moduleId": engine_id,
        "startSec": cue_start,
        "endSec": cue_end,
        "enabled": True,
        "parameters": cue_params,
        "semanticItems": list(cue_payload.get("semanticItems") or []),
    }
    for item in cue["semanticItems"]:
        if not isinstance(item, dict):
            continue
        spoken = float(item.get("spokenStartSec") or cue_start)
        fully = float(item.get("fullyVisibleSec") or spoken)
        spoken = max(cue_start, min(cue_end - 0.02, spoken))
        fully = max(spoken, min(cue_end, fully))
        item["spokenStartSec"] = spoken
        item["fullyVisibleSec"] = fully
    return cue


def _merge_plan_assets(project_root: Path, cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        engine_id = str(cue.get("moduleId") or "")
        params = cue.get("parameters") if isinstance(cue.get("parameters"), dict) else {}
        for asset in _stage_plan_assets_for_preview(project_root, engine_id=engine_id, params=params):
            aid = str(asset.get("id") or "")
            if aid:
                by_id[aid] = asset
    return list(by_id.values())


def _final_fingerprint(
    beats: list[dict[str, Any]],
    *,
    source_rel: str,
    source_sha: str,
    fps: float,
    duration_sec: float,
    quality: str,
) -> str:
    # Must include ENGINE_COMPOSE_RECIPE so Final cannot reuse an encode built
    # with older engine/dock code while placement preview already rebuilt.
    from app.core.visual_production import ENGINE_COMPOSE_RECIPE

    payload = {
        "sourceRel": source_rel,
        "sourceSha256": source_sha,
        "fps": round(float(fps), 4),
        "durationSec": round(float(duration_sec), 4),
        "quality": quality,
        "engineComposeRecipe": ENGINE_COMPOSE_RECIPE,
        "beats": [
            {
                "beatId": b.get("beatId"),
                "engineId": b.get("engineId"),
                "startFrame": b.get("startFrame"),
                "endFrameExclusive": b.get("endFrameExclusive"),
                "lines": b.get("lines"),
                "meta": b.get("meta"),
                "assets": b.get("assets"),
                "motion": b.get("motion"),
                "locked": b.get("locked"),
            }
            for b in beats
        ],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def build_placement_final_plan(
    manifest_path: Path,
    manifest: dict,
    *,
    quality: str = "standard",
) -> dict[str, Any]:
    """Assemble a full-duration visual plan from all locked placements (no encode)."""

    from app.core.file_utils import sha256_file
    from app.core.visual_production import (
        VISUAL_PLAN_VERSION,
        probe_visual_source,
        validate_visual_plan,
    )

    root = video_project_root(manifest_path)
    beats = _placement_beats_ready_for_final(root)
    source_path = preferred_stage_source(manifest_path, manifest)
    if not source_path.is_file():
        raise FileNotFoundError(
            "No locked cut / stage source video for Final. Export the locked cut first."
        )
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
        raise RuntimeError("Could not probe locked-cut duration for Final.")

    quality = str(quality or "standard").strip().lower() or "standard"
    if quality not in {"draft", "standard", "high"}:
        raise ValueError("Unknown Final quality. Use draft, standard, or high.")

    cues: list[dict[str, Any]] = []
    for row in beats:
        placement = normalize_placement_engine(dict(row))
        engine_id = str(placement.get("engineId") or "").strip()
        if not engine_id:
            raise ValueError(f"Placement {placement.get('beatId')!r} has no engineId.")
        cues.append(
            _cue_from_placement_for_final(placement, fps=fps, full_duration=full_duration)
        )
    # Stable draw order: earlier start first.
    cues.sort(key=lambda c: (float(c.get("startSec") or 0.0), str(c.get("id") or "")))

    plan_assets = _merge_plan_assets(root, cues)
    source_sha = sha256_file(source_path)
    fingerprint = _final_fingerprint(
        beats,
        source_rel=source_rel,
        source_sha=source_sha,
        fps=fps,
        duration_sec=full_duration,
        quality=quality,
    )

    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "schemaVersion": VISUAL_PLAN_VERSION,
        "project": {
            "id": f"placement-final-{fingerprint}",
            "name": "Placement final · full episode",
            "createdAt": now,
            "updatedAt": now,
        },
        "source": {
            "video": source_rel,
            "transcript": "",
            "videoSha256": source_sha,
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
        "cues": cues,
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

    work = final_workspace_for_project(root)
    work.mkdir(parents=True, exist_ok=True)
    plan_path = work / FINAL_PLAN_FILENAME
    validate_visual_plan(plan, root)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "planPath": str(plan_path),
        "plan": plan,
        "sourcePath": str(source_path),
        "sourceRel": source_rel,
        "sourceSha256": source_sha,
        "fingerprint": fingerprint,
        "cueCount": len(cues),
        "placementCount": len(beats),
        "durationSec": full_duration,
        "fps": fps,
        "width": width,
        "height": height,
        "quality": quality,
        "outputPath": str(final_output_path_for_project(root)),
    }


class FinalRenderCanceled(RuntimeError):
    """Raised when the operator cancels an in-flight placement Final."""


def _placement_final_workers() -> str:
    """Parallel Chrome capture workers for HyperFrames Final.

    Default ``4`` matches HyperFrames guidance (sweet spot). Override with
    ``PLACEMENT_FINAL_WORKERS`` (number or ``auto``).
    """

    raw = str(os.environ.get("PLACEMENT_FINAL_WORKERS") or "4").strip().lower()
    if raw == "auto":
        return "auto"
    try:
        count = int(raw)
    except ValueError:
        return "4"
    return str(max(1, min(8, count)))


def _placement_final_use_gpu() -> bool:
    """NVENC/AMF/QSV encode when available. Disable with PLACEMENT_FINAL_GPU=0."""

    raw = str(os.environ.get("PLACEMENT_FINAL_GPU") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def build_placement_final_render_command(
    *,
    node: str,
    cli_js: Path,
    runtime_root: Path,
    output_path: Path,
    quality: str,
) -> list[str]:
    """HyperFrames CLI argv for placement Final (shared engines, GPU + workers)."""

    command = [
        str(node),
        str(cli_js),
        "render",
        str(runtime_root),
        "--output",
        str(output_path),
        "--quality",
        quality,
        "--workers",
        _placement_final_workers(),
        "--skill",
        "talking-head-recut",
    ]
    if _placement_final_use_gpu():
        command.append("--gpu")
    return command


def render_placement_final_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    quality: str = "standard",
    force: bool = True,
    progress: Callable[[int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process: Callable[[subprocess.Popen[str] | None], None] | None = None,
) -> dict[str, Any]:
    """Full-episode Final: HyperFrames encode of locked placements + locked-cut audio remux.

    Does not re-normalize audio. Whatever audio is on the locked cut (including
    optional Stage 5 normalize from the transcript editor) is stream-copied.

    ``force`` defaults to True so an existing ``exports/final-video.mp4`` never
    blocks a new export (receipt reuse is opt-in for identical fingerprints only).

    ``cancel_check`` / ``on_process`` let the API surface cancel a running
    HyperFrames tree without a parallel encode path.
    """

    from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe
    from app.core.process_utils import hidden_subprocess_flags, terminate_process_tree
    from app.core.settings import project_root
    from app.core.visual_production import (
        build_hyperframes_composition,
        _hyperframes_progress_percent,
        publish_verified_render,
        remux_locked_audio,
        verify_delivered_media,
    )

    progress = progress or (lambda _value, _message: None)
    cancel_check = cancel_check or (lambda: False)
    on_process = on_process or (lambda _proc: None)

    def _raise_if_canceled() -> None:
        if cancel_check():
            raise FinalRenderCanceled("Final render canceled.")

    root = video_project_root(manifest_path)
    progress(2, "Assembling locked placements into a full-episode plan...")
    _raise_if_canceled()
    assembled = build_placement_final_plan(manifest_path, manifest, quality=quality)
    plan_path = Path(assembled["planPath"])
    source_path = Path(assembled["sourcePath"])
    fingerprint = str(assembled["fingerprint"])
    quality = str(assembled["quality"])
    full_duration = float(assembled["durationSec"])
    output_path = Path(assembled["outputPath"])

    work = final_workspace_for_project(root)
    receipt_path = work / FINAL_RECEIPT
    # Optional reuse only: Stage 3 Final always force-rebuilds so an existing
    # exports/final-video.mp4 cannot short-circuit a deliberate re-export.
    if not force and output_path.is_file() and receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            receipt_out = Path(str(receipt.get("outputPath") or "")).expanduser()
            try:
                receipt_out_resolved = receipt_out.resolve()
            except OSError:
                receipt_out_resolved = receipt_out
            output_ok = (
                receipt_out_resolved == output_path.resolve()
                or receipt_out.name == output_path.name
            )
            size_ok = output_path.stat().st_size > 0
            if (
                isinstance(receipt, dict)
                and receipt.get("fingerprint") == fingerprint
                and receipt.get("quality") == quality
                and output_ok
                and size_ok
            ):
                progress(100, "Final already published for this locked placement set.")
                return {
                    "ok": True,
                    "reused": True,
                    "outputPath": str(output_path),
                    "fingerprint": fingerprint,
                    "cueCount": assembled["cueCount"],
                    "durationSec": full_duration,
                    "quality": quality,
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    _raise_if_canceled()
    progress(8, "Building full-episode HyperFrames composition...")
    workspace = work / "hyperframes"
    runtime_root, render_duration = build_hyperframes_composition(
        plan_path,
        start_sec=0.0,
        end_sec=full_duration,
        workspace_override=workspace,
        progress=lambda pct, msg: progress(8 + int(max(0, min(100, pct)) * 0.28), msg),
        include_source_audio=True,
    )
    if not (runtime_root / "index.html").is_file():
        raise RuntimeError("HyperFrames Final composition was not written.")

    _raise_if_canceled()
    progress(40, "Rendering full-episode graphics (GPU encode when available)...")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to render the placement Final.")
    cli_js = project_root() / "node_modules" / "hyperframes" / "dist" / "cli.js"
    if not cli_js.is_file():
        raise RuntimeError("HyperFrames CLI not found. Run npm install.")

    video_only = work / f".final-video-only-{uuid.uuid4().hex[:8]}.mp4"
    verified_stage = work / f".final-verified-{uuid.uuid4().hex[:8]}.mp4"
    env = os.environ.copy()
    media_dirs = [str(find_ffmpeg().parent)]
    if find_ffprobe() is not None:
        media_dirs.append(str(find_ffprobe().parent))
    env["PATH"] = os.pathsep.join(media_dirs + [env.get("PATH", "")])
    # No --strict: OS font-local declarations and residual GSAP lint must not block
    # episode delivery (library samples use the same non-strict render path). Engine
    # timelines still avoid overlapping scaleX / bubble / flame tweens for clean motion.
    # Same engines as placement preview; --gpu + workers only speed the encode/capture.
    command = build_placement_final_render_command(
        node=node,
        cli_js=cli_js,
        runtime_root=runtime_root,
        output_path=video_only,
        quality=quality,
    )
    process: subprocess.Popen[str] | None = None
    published: Path | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=str(project_root()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=hidden_subprocess_flags(),
            env=env,
        )
        on_process(process)
        captured: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            if cancel_check():
                terminate_process_tree(process)
                raise FinalRenderCanceled("Final render canceled.")
            captured.append(line)
            render_percent = _hyperframes_progress_percent(line)
            if render_percent is not None:
                value = 40 + round(render_percent * 0.5)
                progress(min(90, value), "Rendering placement Final frames...")
        return_code = process.wait()
        on_process(None)
        process = None
        if cancel_check():
            raise FinalRenderCanceled("Final render canceled.")
        if return_code != 0 or not video_only.is_file() or video_only.stat().st_size == 0:
            raise RuntimeError(
                "HyperFrames Final render failed. " + ("".join(captured)[-1800:])
            )

        _raise_if_canceled()
        progress(92, "Attaching locked-cut audio (stream copy, no re-normalize)...")
        remux_locked_audio(video_only, source_path, verified_stage)
        _raise_if_canceled()
        progress(96, "Verifying video duration and locked-cut audio identity...")
        plan = assembled["plan"]
        verify_delivered_media(
            verified_stage,
            source_path,
            plan["composition"],
            full_length=True,
        )
        published = publish_verified_render(verified_stage, output_path)
    except FinalRenderCanceled:
        if process is not None:
            terminate_process_tree(process)
            on_process(None)
        raise
    finally:
        if process is not None:
            on_process(None)
        video_only.unlink(missing_ok=True)
        verified_stage.unlink(missing_ok=True)

    if published is None:
        raise RuntimeError("Final render did not produce an output path.")

    receipt = {
        "fingerprint": fingerprint,
        "quality": quality,
        "outputPath": str(published),
        "sourcePath": str(source_path),
        "sourceSha256": assembled["sourceSha256"],
        "cueCount": assembled["cueCount"],
        "placementCount": assembled["placementCount"],
        "durationSec": full_duration,
        "renderDurationSec": float(render_duration),
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "audio": "locked-cut-stream-copy",
        "gpu": _placement_final_use_gpu(),
        "workers": _placement_final_workers(),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    progress(100, "Final video ready.")
    return {
        "ok": True,
        "reused": False,
        "outputPath": str(published),
        "fingerprint": fingerprint,
        "cueCount": assembled["cueCount"],
        "placementCount": assembled["placementCount"],
        "durationSec": full_duration,
        "quality": quality,
        "receiptPath": str(receipt_path),
    }
