"""Stage 2 Scenelayer — label each Masterbeater beat with one OBS layout id.

Deterministic: first frame of the beat → one of the eight closed layout ids.
Does not do placement. See docs/vcg-graphics-process/scenelayer.md.
"""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.editorial_layout import LAYOUT_IDS, load_scene_geometry
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.graphics_library import (
    default_graphics_library_root,
    layout_clip_path,
    layout_ref_still_path,
    list_layout_refs,
)
from app.core.masterbeater import (
    load_masterbeater_output,
    load_masterbeater_reviewed,
)
from app.core.process_utils import hidden_subprocess_flags
from app.core.video_project import preferred_stage_source, video_project_root

OUTPUT_FILENAME = "scenelayer.json"
REVIEWED_FILENAME = "scenelayer-reviewed.json"
LEDGER_FILENAME = "scenelayer-edit-ledger.json"

SCHEMA_VERSION = 1
SOURCE_ALGORITHM = "algorithm"
SOURCE_HUMAN = "human"

# Downsample for scoring (wide, short — matches 16:9).
SCORE_W = 80
SCORE_H = 45

# Edge-map MSE below this → trust layout-ref still match.
# (Normalized edge maps: confident hits ~0.1–1.5; weak-but-usable ≲1.9.)
TEMPLATE_CONFIDENT_MSE = 1.9

# Cached edge-map templates: layoutId → flat SCORE_W*SCORE_H normalized floats.
_LAYOUT_TEMPLATES: dict[str, list[float]] | None = None
_LAYOUT_TEMPLATES_ROOT: str | None = None


def output_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / OUTPUT_FILENAME


def reviewed_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / REVIEWED_FILENAME


def ledger_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / LEDGER_FILENAME


def layout_ids_ordered() -> list[str]:
    return sorted(LAYOUT_IDS)


def _working_masterbeater_beats(project_root: Path) -> list[dict[str, Any]]:
    reviewed = load_masterbeater_reviewed(project_root)
    original = load_masterbeater_output(project_root)
    working = reviewed if reviewed is not None else original
    if working is None:
        return []
    return [b for b in (working.get("beats") or []) if isinstance(b, dict) and b.get("id")]


def beat_start_sec(beat: dict[str, Any], fps: float = 30.0) -> float:
    if beat.get("startSec") is not None:
        try:
            return max(0.0, float(beat["startSec"]))
        except (TypeError, ValueError):
            pass
    if beat.get("startFrame") is not None and fps > 0:
        try:
            return max(0.0, float(beat["startFrame"]) / float(fps))
        except (TypeError, ValueError):
            pass
    return 0.0


def extract_frame_rgb(
    video_path: Path,
    time_sec: float,
    *,
    width: int = SCORE_W,
    height: int = SCORE_H,
) -> tuple[bytes, int, int]:
    """Extract one RGB24 frame scaled to width×height via ffmpeg."""

    ffmpeg = find_ffmpeg()
    t = max(0.0, float(time_sec))
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{t:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    expected = width * height * 3
    if completed.returncode != 0 or len(completed.stdout) < expected:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise RuntimeError(
            f"Could not extract frame at {t:.3f}s from {video_path.name}. {detail}"
        )
    return completed.stdout[:expected], width, height


def _luma_grid(rgb: bytes, width: int, height: int) -> list[list[float]]:
    grid: list[list[float]] = []
    for y in range(height):
        row: list[float] = []
        for x in range(width):
            i = (y * width + x) * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            row.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        grid.append(row)
    return grid


def _luma_flat(rgb: bytes, width: int, height: int) -> list[float]:
    flat: list[float] = []
    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            flat.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    return flat


def _mse(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 1e18
    return sum((a[i] - b[i]) ** 2 for i in range(n)) / n


def _normalize_flat(values: list[float]) -> list[float]:
    if not values:
        return values
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(var) + 1e-3
    return [(v - mean) / std for v in values]


def _edge_map_flat(rgb: bytes, width: int, height: int) -> list[float]:
    """Normalized gradient magnitude map — structure of OBS chrome, not scene color."""

    grid = _luma_grid(rgb, width, height)
    raw: list[float] = []
    for y in range(height):
        for x in range(width):
            dx = abs(grid[y][x] - grid[y][x - 1]) if x else 0.0
            dy = abs(grid[y][x] - grid[y - 1][x]) if y else 0.0
            raw.append(dx + dy)
    return _normalize_flat(raw)


def load_layout_templates(
    *,
    library_root: Path | None = None,
    force_reload: bool = False,
) -> dict[str, list[float]]:
    """Edge-map templates from full-frame layout **screenshots** (preferred).

    Product model: one still per OBS layout under Graphics Library
    ``layout-refs/{layoutId}.png``. Compare beat first-frame **structure**
    (edges), not raw pixel color — OBS chrome layout is what matters.

    Temporary fallback: if no still exists, one frame from
    ``layout-clips/{layoutId}.mp4``.
    """

    global _LAYOUT_TEMPLATES, _LAYOUT_TEMPLATES_ROOT
    root = (library_root or default_graphics_library_root()).resolve()
    root_key = str(root)
    if (
        not force_reload
        and _LAYOUT_TEMPLATES is not None
        and _LAYOUT_TEMPLATES_ROOT == root_key
    ):
        return _LAYOUT_TEMPLATES

    templates: dict[str, list[float]] = {}
    for layout_id in LAYOUT_IDS:
        source_path: Path | None = None
        try:
            source_path = layout_ref_still_path(layout_id, root)
        except ValueError:
            continue
        if source_path is None:
            try:
                clip = layout_clip_path(layout_id, root)
            except ValueError:
                continue
            if clip.is_file():
                source_path = clip
        if source_path is None or not source_path.is_file():
            continue
        try:
            t = 0.0 if source_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else 1.0
            rgb, w, h = extract_frame_rgb(source_path, t)
            templates[layout_id] = _edge_map_flat(rgb, w, h)
        except (OSError, RuntimeError, ValueError):
            continue

    _LAYOUT_TEMPLATES = templates
    _LAYOUT_TEMPLATES_ROOT = root_key
    return templates


def template_mse_for_frame(
    rgb: bytes,
    width: int,
    height: int,
    *,
    library_root: Path | None = None,
) -> dict[str, float]:
    """Edge-map MSE vs each layout reference still (lower = better structure match)."""

    templates = load_layout_templates(library_root=library_root)
    if not templates:
        return {}
    edges = _edge_map_flat(rgb, width, height)
    return {lid: _mse(edges, ref) for lid, ref in templates.items()}


def layout_template_coverage(*, library_root: Path | None = None) -> dict[str, Any]:
    """Which layout screenshots exist (for status / operator messaging)."""

    return list_layout_refs(library_root)


def _bounds_to_pixels(
    bounds: dict[str, float] | None,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    if bounds is None:
        return 0, 0, width, height
    x0 = max(0, min(width - 1, int(float(bounds["x"]) * width)))
    y0 = max(0, min(height - 1, int(float(bounds["y"]) * height)))
    x1 = max(x0 + 1, min(width, int((float(bounds["x"]) + float(bounds["width"])) * width)))
    y1 = max(y0 + 1, min(height, int((float(bounds["y"]) + float(bounds["height"])) * height)))
    return x0, y0, x1, y1


def _region_stats(
    grid: list[list[float]],
    bounds: dict[str, float] | None,
) -> tuple[float, float, float]:
    """Return (mean, variance, edge_mean) over normalized bounds or full frame."""

    h = len(grid)
    w = len(grid[0]) if h else 0
    if h == 0 or w == 0:
        return 0.0, 0.0, 0.0

    x0, y0, x1, y1 = _bounds_to_pixels(bounds, w, h)
    values: list[float] = []
    edges: list[float] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            v = grid[y][x]
            values.append(v)
            if x + 1 < x1:
                edges.append(abs(grid[y][x + 1] - v))
            if y + 1 < y1:
                edges.append(abs(grid[y + 1][x] - v))
    if not values:
        return 0.0, 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    edge = sum(edges) / len(edges) if edges else 0.0
    return mean, var, edge


def _column_horizontal_grad(grid: list[list[float]], x: int) -> float:
    h = len(grid)
    w = len(grid[0]) if h else 0
    if h < 2 or x <= 0 or x >= w:
        return 0.0
    total = 0.0
    for y in range(h):
        total += abs(grid[y][x] - grid[y][x - 1])
    return total / h


def _vertical_seam_strength(grid: list[list[float]], x_frac: float) -> float:
    """Composite L/R split strength at x_frac relative to other vertical cuts.

    A gentle full-frame gradient should score low; an OBS big-face hard join
    at mid-frame scores high.
    """

    h = len(grid)
    w = len(grid[0]) if h else 0
    if h < 4 or w < 12:
        return 0.0
    x = max(2, min(w - 3, int(x_frac * w)))
    # Absolute brightness jump across the seam
    jump = 0.0
    for y in range(h):
        left = sum(grid[y][x - 2 : x]) / 2.0
        right = sum(grid[y][x + 1 : x + 3]) / 2.0
        jump += abs(left - right)
    jump /= h
    # How peaked is the horizontal gradient at this column vs the rest of the frame
    peak = _column_horizontal_grad(grid, x)
    other_xs = [2, w // 4, (3 * w) // 4, w - 2]
    other = sum(_column_horizontal_grad(grid, ox) for ox in other_xs if ox != x) / max(
        1, len([ox for ox in other_xs if ox != x])
    )
    peak_ratio = peak / (other + 1e-3)
    # Composite seam: needs both a jump and a localized peak (not a global gradient)
    return jump * max(0.0, peak_ratio - 0.85)


def _rect_border_strength(
    grid: list[list[float]],
    bounds: dict[str, float],
    *,
    layout_id: str | None = None,
) -> float:
    """Hard rectangle border strength — high for OBS PIP windows.

    For known PIP layouts, only score the *inner* edges (toward the stage),
    not the outer frame edges (which pick up letterboxing / UI noise).
    """

    h = len(grid)
    w = len(grid[0]) if h else 0
    if h < 4 or w < 4:
        return 0.0
    x0, y0, x1, y1 = _bounds_to_pixels(bounds, w, h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 0.0

    # Which edges face the main stage for each OBS PIP.
    want_left = want_right = want_top = want_bottom = True
    if layout_id == "talking-bottom-left":
        want_left = want_bottom = False  # outer frame edges
        want_right = want_top = True
    elif layout_id == "talking-bottom-right":
        want_right = want_bottom = False
        want_left = want_top = True
    elif layout_id == "talking-top-left":
        want_left = want_top = False
        want_right = want_bottom = True
    elif layout_id == "talking-top-right":
        want_right = want_top = False
        want_left = want_bottom = True

    samples: list[float] = []
    if want_right and x1 < w:
        for y in range(y0, y1):
            samples.append(abs(grid[y][min(x1, w - 1)] - grid[y][max(0, x1 - 2)]))
    if want_left and x0 > 0:
        for y in range(y0, y1):
            samples.append(abs(grid[y][x0] - grid[y][max(0, x0 - 1)]))
    if want_bottom and y1 < h:
        for x in range(x0, x1):
            samples.append(abs(grid[min(y1, h - 1)][x] - grid[max(0, y1 - 2)][x]))
    if want_top and y0 > 0:
        for x in range(x0, x1):
            samples.append(abs(grid[y0][x] - grid[max(0, y0 - 1)][x]))
    if not samples:
        return 0.0
    return sum(samples) / len(samples)


def _half_bounds(side: str) -> dict[str, float]:
    if side == "left":
        return {"x": 0.0, "y": 0.0, "width": 0.5, "height": 1.0}
    return {"x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0}


def score_layouts_for_frame(
    rgb: bytes,
    width: int,
    height: int,
    *,
    geometry: dict | None = None,
) -> dict[str, float]:
    """Deterministic scores for each layout id (higher = better match).

    Uses OBS geometry as structure, not raw edge density alone:
    - Big face L/R: mid-frame vertical seam + half-frame activity
    - PIP corners: small rect border strength + interior detail (local winner among PIPs)
    - Full-screen talking: no strong mid seam / PIP chrome; subject in measured face box
    - Computer screen: no strong face panel signatures
    """

    geo = geometry or load_scene_geometry()
    layouts = geo.get("layouts") or {}
    grid = _luma_grid(rgb, width, height)
    _, full_var, full_edge = _region_stats(grid, None)

    # Mid split ~ where big-face left/right join (OBS ~0.50).
    mid_seam = _vertical_seam_strength(grid, 0.50)
    _, _, left_edge = _region_stats(grid, _half_bounds("left"))
    _, _, right_edge = _region_stats(grid, _half_bounds("right"))
    half_balance = abs(left_edge - right_edge) / (max(left_edge, right_edge, 1e-3))

    # Per-layout geometry features
    pip_ids = (
        "talking-bottom-left",
        "talking-bottom-right",
        "talking-top-left",
        "talking-top-right",
    )
    features: dict[str, dict[str, float]] = {}
    for layout_id in LAYOUT_IDS:
        entry = layouts.get(layout_id) or {}
        bounds = entry.get("speakerBounds")
        if bounds is None:
            features[layout_id] = {
                "border": 0.0,
                "interior_edge": full_edge,
                "interior_var": full_var,
            }
            continue
        _, var, edge = _region_stats(grid, bounds)
        border = _rect_border_strength(grid, bounds, layout_id=layout_id)
        features[layout_id] = {
            "border": border,
            "interior_edge": edge,
            "interior_var": var,
        }

    max_pip_border = max(features[pid]["border"] for pid in pip_ids)
    max_pip_interior = max(features[pid]["interior_edge"] for pid in pip_ids)
    pip_borders = sorted(features[pid]["border"] for pid in pip_ids)
    second_pip_border = pip_borders[-2] if len(pip_borders) >= 2 else 0.0
    big_left = features["talking-left"]
    big_right = features["talking-right"]
    full_feat = features["full-screen-talking"]
    full_border = full_feat["border"]

    scores: dict[str, float] = {lid: -1e9 for lid in LAYOUT_IDS}

    # --- Family: corner PIPs (hard small windows) ---
    # Real OBS PIPs have a *localized* hard border that beats:
    # - mid-frame big-face seam
    # - the large full-screen face box border (usually soft)
    # - the other three corners (one winner)
    # One corner must clearly dominate the other three (real OBS PIP), not noise.
    pip_localized = max_pip_border > second_pip_border * 1.35
    mean_pip_border = sum(features[pid]["border"] for pid in pip_ids) / 4.0
    # Do not gate on half_balance — bottom PIPs often have uneven L/R screen content.
    pip_family_active = (
        max_pip_border > full_edge * 0.9
        and max_pip_border > full_border * 1.5
        and max_pip_border > mean_pip_border * 1.3
        and pip_localized
        and mid_seam < max_pip_border * 0.55
    )
    if pip_family_active:
        for pid in pip_ids:
            f = features[pid]
            # Localize: this PIP must beat the other three corners on border+interior.
            others = [
                features[o]["border"] * 2.0 + features[o]["interior_edge"]
                for o in pip_ids
                if o != pid
            ]
            other_max = max(others) if others else 0.0
            local = f["border"] * 2.8 + f["interior_edge"] * 1.2
            scores[pid] = local - other_max * 0.55
        # Suppress non-PIP when PIP chrome is clear
        scores["talking-left"] = mid_seam * 0.2
        scores["talking-right"] = mid_seam * 0.2
        scores["full-screen-talking"] = full_feat["interior_edge"] * 0.15
        scores["computer-screen-only"] = full_edge * 0.1 - max_pip_border
        return scores

    # --- Family: big face left / right (strong vertical mid seam) ---
    # Full-screen talking usually has a continuous camera frame without a hard L/R composite seam.
    big_face_active = mid_seam > 2.0 and half_balance > 0.14 and mid_seam > max_pip_border * 0.08
    if big_face_active:
        scores["talking-left"] = (
            mid_seam * 1.8
            + left_edge * 1.3
            - right_edge * 0.4
            + big_left["interior_edge"] * 0.35
        )
        scores["talking-right"] = (
            mid_seam * 1.8
            + right_edge * 1.3
            - left_edge * 0.4
            + big_right["interior_edge"] * 0.35
        )
        scores["full-screen-talking"] = full_feat["interior_edge"] * 0.35 - mid_seam * 0.6
        scores["computer-screen-only"] = full_edge * 0.25 - mid_seam * 0.5
        for pid in pip_ids:
            scores[pid] = features[pid]["border"] * 0.15 - mid_seam * 0.4
        return scores

    # --- Family: full-screen talking vs computer screen ---
    # No strong mid composite seam and no strong PIP chrome.
    # Keep non-winning families near floor so residual border noise cannot win.
    scores["full-screen-talking"] = (
        full_feat["interior_edge"] * 1.8
        + full_feat["interior_var"] * 0.002
        + (1.0 - min(1.0, half_balance)) * full_edge * 0.5
        - mid_seam * 0.25
        - max(0.0, max_pip_border - full_border) * 0.4
    )
    scores["computer-screen-only"] = (
        full_edge * 1.0
        + full_var * 0.001
        - full_feat["interior_edge"] * 0.25
        - mid_seam * 0.2
        - max(0.0, max_pip_border - full_edge * 0.5) * 0.8
    )
    scores["talking-left"] = mid_seam * 0.8 + left_edge * 0.2 - full_feat["interior_edge"] * 0.3
    scores["talking-right"] = mid_seam * 0.8 + right_edge * 0.2 - full_feat["interior_edge"] * 0.3
    for pid in pip_ids:
        # Only a real localized PIP border should compete here
        margin = features[pid]["border"] - full_border
        scores[pid] = margin * 0.35 + features[pid]["interior_edge"] * 0.05 - full_edge * 0.2

    return scores


def classify_layout_from_rgb(
    rgb: bytes,
    width: int,
    height: int,
    *,
    geometry: dict | None = None,
    library_root: Path | None = None,
    min_score_gap: float = 0.0,
) -> str | None:
    """Pick best layout id from frame bytes.

    Prefer Graphics Library **layout-ref stills** matched via edge-map structure
    (OBS chrome), not raw color. Fall back to geometry scoring if no confident still.
    """

    del min_score_gap
    tmpl_mse = template_mse_for_frame(rgb, width, height, library_root=library_root)
    if tmpl_mse:
        ordered_t = sorted(tmpl_mse.items(), key=lambda item: item[1])
        best_id, best_mse = ordered_t[0]
        second_mse = ordered_t[1][1] if len(ordered_t) > 1 else best_mse + 1.0
        # Confident absolute match, or clear winner among the eight stills.
        if best_mse <= TEMPLATE_CONFIDENT_MSE or (
            best_mse < 1.9 and best_mse < second_mse * 0.85
        ):
            return best_id

    scores = score_layouts_for_frame(rgb, width, height, geometry=geometry)
    if not scores:
        return None
    # Soft still prior when moderately close.
    if tmpl_mse:
        for lid, mse in tmpl_mse.items():
            if mse < 2.4:
                scores[lid] = scores.get(lid, 0.0) + (2.5 / (mse + 0.05))
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_id, best_score = ordered[0]
    if not math.isfinite(best_score):
        return None
    return best_id


def load_scenelayer_original(project_root: Path) -> dict | None:
    path = output_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_scenelayer_reviewed(project_root: Path) -> dict | None:
    path = reviewed_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_scenelayer_ledger(project_root: Path) -> dict[str, Any]:
    path = ledger_path_for_project(project_root)
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "agent": "scenelayer-edit-ledger",
            "originalFile": OUTPUT_FILENAME,
            "reviewedFile": REVIEWED_FILENAME,
            "entries": [],
            "entryCount": 0,
        }
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Scenelayer ledger must be a JSON object.")
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    return data


def write_scenelayer_original(project_root: Path, document: dict[str, Any]) -> Path:
    path = output_path_for_project(project_root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_scenelayer_reviewed(project_root: Path, document: dict[str, Any]) -> Path:
    path = reviewed_path_for_project(project_root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_scenelayer_ledger(project_root: Path, ledger: dict[str, Any]) -> Path:
    path = ledger_path_for_project(project_root)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def build_scenelayer_document(
    rows: list[dict[str, Any]],
    *,
    project_root: Path,
    role: str = "original",
    beat_count: int | None = None,
) -> dict[str, Any]:
    clean: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        beat_id = str(row.get("beatId") or "").strip()
        if not beat_id:
            continue
        layout_id = row.get("layoutId")
        layout_s = str(layout_id).strip() if layout_id else None
        if layout_s and layout_s not in LAYOUT_IDS:
            layout_s = None
        source = str(row.get("source") or SOURCE_ALGORITHM).strip()
        if source not in {SOURCE_ALGORITHM, SOURCE_HUMAN}:
            source = SOURCE_ALGORITHM
        clean.append(
            {
                "beatId": beat_id,
                "layoutId": layout_s,
                "source": source,
            }
        )
    labeled = sum(1 for r in clean if r.get("layoutId"))
    return {
        "agent": "scenelayer" if role == "original" else "scenelayer-reviewed",
        "schemaVersion": SCHEMA_VERSION,
        "role": role,
        "projectRoot": str(project_root),
        "beatCount": beat_count if beat_count is not None else len(clean),
        "labeledCount": labeled,
        "unlabeledCount": len(clean) - labeled,
        "beats": clean,
        "notes": (
            "layoutId is one of the eight OBS layouts from the first frame of each beat. "
            "Not used for placement; Assignment filters allowedLayouts with this label."
        ),
    }


def _preserve_human_map(document: dict | None) -> dict[str, dict[str, Any]]:
    if not document:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in document.get("beats") or []:
        if not isinstance(row, dict):
            continue
        beat_id = str(row.get("beatId") or "").strip()
        if not beat_id:
            continue
        if str(row.get("source") or "") != SOURCE_HUMAN:
            continue
        out[beat_id] = {
            "beatId": beat_id,
            "layoutId": row.get("layoutId"),
            "source": SOURCE_HUMAN,
        }
    return out


def classify_beats_from_video(
    beats: list[dict[str, Any]],
    video_path: Path,
    *,
    fps: float = 30.0,
    preserve: dict[str, dict[str, Any]] | None = None,
    geometry: dict | None = None,
    library_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Classify each beat; preserve human rows; cache frames by rounded time."""

    preserve = preserve or {}
    frame_cache: dict[str, tuple[bytes, int, int]] = {}
    results: list[dict[str, Any]] = []
    geo = geometry or load_scene_geometry()
    # Warm layout screenshot templates once per run.
    load_layout_templates(library_root=library_root)

    for beat in beats:
        beat_id = str(beat.get("id") or "").strip()
        if not beat_id:
            continue
        prior = preserve.get(beat_id)
        if prior:
            results.append(
                {
                    "beatId": beat_id,
                    "layoutId": prior.get("layoutId"),
                    "source": SOURCE_HUMAN,
                }
            )
            continue

        t = beat_start_sec(beat, fps=fps)
        cache_key = f"{t:.2f}"
        try:
            if cache_key not in frame_cache:
                frame_cache[cache_key] = extract_frame_rgb(video_path, t)
            rgb, w, h = frame_cache[cache_key]
            layout_id = classify_layout_from_rgb(
                rgb, w, h, geometry=geo, library_root=library_root
            )
        except (OSError, RuntimeError, ValueError):
            layout_id = None

        results.append(
            {
                "beatId": beat_id,
                "layoutId": layout_id,
                "source": SOURCE_ALGORITHM,
            }
        )
    return results


def run_scenelayer_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    geometry: dict | None = None,
) -> dict[str, Any]:
    """Button run: first write original+working; re-run keeps human, reclassifies rest."""

    root = video_project_root(manifest_path)
    beats = _working_masterbeater_beats(root)
    if not beats:
        raise FileNotFoundError(
            "No Masterbeater beats found. Finish Stage 1 before Scenelayer."
        )

    video = preferred_stage_source(manifest_path, manifest)
    if not video.is_file():
        raise FileNotFoundError(f"Review video not found: {video}")

    fps = 30.0
    for beat in beats:
        if beat.get("startFrame") is not None and beat.get("startSec") is not None:
            try:
                sf = float(beat["startFrame"])
                ss = float(beat["startSec"])
                if ss > 0 and sf > 0:
                    fps = sf / ss
                    break
            except (TypeError, ValueError):
                pass
    # Prefer fps from masterbeater working doc if present.
    reviewed_mb = load_masterbeater_reviewed(root) or load_masterbeater_output(root)
    if reviewed_mb and reviewed_mb.get("fps"):
        try:
            fps = float(reviewed_mb["fps"])
        except (TypeError, ValueError):
            pass

    original = load_scenelayer_original(root)
    working_prior = load_scenelayer_reviewed(root) or original

    if original is None:
        rows = classify_beats_from_video(
            beats, video, fps=fps, preserve=None, geometry=geometry
        )
        document = build_scenelayer_document(
            rows, project_root=root, role="original", beat_count=len(beats)
        )
        write_scenelayer_original(root, document)
        working_doc = build_scenelayer_document(
            rows, project_root=root, role="reviewed", beat_count=len(beats)
        )
        working_doc["basedOnOriginal"] = True
        working_doc["originalFile"] = OUTPUT_FILENAME
        write_scenelayer_reviewed(root, working_doc)
        first_run = True
    else:
        human = _preserve_human_map(working_prior)
        rows = classify_beats_from_video(
            beats, video, fps=fps, preserve=human, geometry=geometry
        )
        working_doc = build_scenelayer_document(
            rows, project_root=root, role="reviewed", beat_count=len(beats)
        )
        working_doc["basedOnOriginal"] = True
        working_doc["originalFile"] = OUTPUT_FILENAME
        working_doc["reRun"] = True
        write_scenelayer_reviewed(root, working_doc)
        first_run = False

    return {
        "ok": True,
        "firstRun": first_run,
        "originalPath": str(output_path_for_project(root)),
        "reviewedPath": str(reviewed_path_for_project(root)),
        "originalExists": True,
        "reviewedExists": True,
        "beatCount": working_doc.get("beatCount"),
        "labeledCount": working_doc.get("labeledCount"),
        "unlabeledCount": working_doc.get("unlabeledCount"),
        "beats": working_doc.get("beats"),
        "result": working_doc,
        "layoutIds": layout_ids_ordered(),
    }


def append_scenelayer_ledger_entry(
    project_root: Path,
    *,
    beat_id: str,
    from_layout_id: str | None,
    to_layout_id: str | None,
    detail: str | None = None,
) -> dict[str, Any]:
    ledger = load_scenelayer_ledger(project_root)
    entries: list[Any] = list(ledger.get("entries") or [])
    entry = {
        "id": f"s-{len(entries) + 1:04d}",
        "at": datetime.now(timezone.utc).isoformat(),
        "op": "changeLayout",
        "beatId": beat_id,
        "fromLayoutId": from_layout_id,
        "toLayoutId": to_layout_id,
    }
    if detail:
        entry["detail"] = detail
    entries.append(entry)
    ledger["schemaVersion"] = 1
    ledger["agent"] = "scenelayer-edit-ledger"
    ledger["originalFile"] = OUTPUT_FILENAME
    ledger["reviewedFile"] = REVIEWED_FILENAME
    ledger["entries"] = entries
    ledger["entryCount"] = len(entries)
    ledger["updatedAt"] = entry["at"]
    write_scenelayer_ledger(project_root, ledger)
    return entry


def save_scenelayer_override_for_video_project(
    manifest_path: Path,
    manifest: dict,
    payload: dict,
) -> dict[str, Any]:
    """Human layout dropdown → working + ledger. Original untouched."""

    del manifest
    root = video_project_root(manifest_path)
    original = load_scenelayer_original(root)
    if original is None:
        raise FileNotFoundError(
            "No scenelayer.json yet. Press Scenelayer before overriding layouts."
        )

    beat_id = str(payload.get("beatId") or "").strip()
    if not beat_id:
        raise ValueError("beatId is required.")
    if "layoutId" not in payload:
        raise ValueError("layoutId is required (string or null).")
    layout_raw = payload.get("layoutId")
    layout_id = str(layout_raw).strip() if layout_raw else None
    if layout_id and layout_id not in LAYOUT_IDS:
        raise ValueError(
            f"Unknown layoutId {layout_id!r}. Must be one of: {', '.join(layout_ids_ordered())}"
        )

    mb_beats = _working_masterbeater_beats(root)
    if not any(str(b.get("id")) == beat_id for b in mb_beats):
        raise ValueError(f"Unknown beatId {beat_id!r}.")

    working = load_scenelayer_reviewed(root) or original
    by_beat = {
        str(r.get("beatId")): dict(r)
        for r in (working.get("beats") or [])
        if isinstance(r, dict) and r.get("beatId")
    }
    previous = by_beat.get(beat_id) or {
        "beatId": beat_id,
        "layoutId": None,
        "source": SOURCE_ALGORITHM,
    }
    from_layout = previous.get("layoutId")
    by_beat[beat_id] = {
        "beatId": beat_id,
        "layoutId": layout_id,
        "source": SOURCE_HUMAN,
    }

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

    working_doc = build_scenelayer_document(
        ordered, project_root=root, role="reviewed", beat_count=len(mb_beats)
    )
    working_doc["basedOnOriginal"] = True
    working_doc["originalFile"] = OUTPUT_FILENAME
    working_doc["edited"] = True
    write_scenelayer_reviewed(root, working_doc)

    ledger_entry = append_scenelayer_ledger_entry(
        root,
        beat_id=beat_id,
        from_layout_id=str(from_layout) if from_layout else None,
        to_layout_id=layout_id,
        detail=str(payload.get("detail") or "").strip() or None,
    )

    return {
        "ok": True,
        "role": "reviewed",
        "edited": True,
        "originalPath": str(output_path_for_project(root)),
        "reviewedPath": str(reviewed_path_for_project(root)),
        "ledgerPath": str(ledger_path_for_project(root)),
        "ledgerEntry": ledger_entry,
        "ledgerEntryCount": int(load_scenelayer_ledger(root).get("entryCount") or 0),
        "beatCount": working_doc.get("beatCount"),
        "labeledCount": working_doc.get("labeledCount"),
        "unlabeledCount": working_doc.get("unlabeledCount"),
        "beats": working_doc.get("beats"),
        "result": working_doc,
        "layoutIds": layout_ids_ordered(),
    }


def working_layout_by_beat_id(project_root: Path) -> dict[str, str | None]:
    """Map beatId → layoutId from working scenelayer (reviewed else original)."""

    working = load_scenelayer_reviewed(project_root) or load_scenelayer_original(project_root)
    if not working:
        return {}
    out: dict[str, str | None] = {}
    for row in working.get("beats") or []:
        if not isinstance(row, dict):
            continue
        beat_id = str(row.get("beatId") or "").strip()
        if not beat_id:
            continue
        layout_id = row.get("layoutId")
        out[beat_id] = str(layout_id) if layout_id else None
    return out


def scenelayer_status_for_video_project(
    manifest_path: Path,
    manifest: dict,
) -> dict[str, Any]:
    del manifest
    root = video_project_root(manifest_path)
    original = None
    reviewed = None
    try:
        original = load_scenelayer_original(root)
    except (OSError, json.JSONDecodeError):
        original = None
    try:
        reviewed = load_scenelayer_reviewed(root)
    except (OSError, json.JSONDecodeError):
        reviewed = None

    working = reviewed if reviewed is not None else original
    ledger_path = ledger_path_for_project(root)
    ledger_entry_count = 0
    if ledger_path.is_file():
        try:
            ledger = load_scenelayer_ledger(root)
            ledger_entry_count = int(ledger.get("entryCount") or len(ledger.get("entries") or []))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            ledger_entry_count = 0

    beats = list((working or {}).get("beats") or []) if working else []
    labeled = sum(1 for b in beats if isinstance(b, dict) and b.get("layoutId"))
    by_beat = {
        str(b["beatId"]): b
        for b in beats
        if isinstance(b, dict) and b.get("beatId")
    }
    original_by_beat = {
        str(b["beatId"]): b
        for b in ((original or {}).get("beats") or [])
        if isinstance(b, dict) and b.get("beatId")
    }

    return {
        "ok": True,
        "originalPath": str(output_path_for_project(root)),
        "originalExists": original is not None,
        "reviewedPath": str(reviewed_path_for_project(root)),
        "reviewedExists": reviewed is not None,
        "ledgerPath": str(ledger_path),
        "ledgerExists": ledger_path.is_file(),
        "ledgerEntryCount": ledger_entry_count,
        "beatCount": len(beats),
        "labeledCount": labeled,
        "unlabeledCount": len(beats) - labeled,
        "result": working,
        "byBeatId": by_beat,
        "originalByBeatId": original_by_beat,
        "layoutIds": layout_ids_ordered(),
    }
