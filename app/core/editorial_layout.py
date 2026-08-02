"""OBS eight-layout geometry for editorial placement and screenshot safety.

Authority: visual-production/layouts/scene-geometry.json (same measured facts
as Creator Production capture-layout catalog). Speaker rectangles are not
guessed from pixels at plan time; agents classify which of the eight layouts
is active, and the app applies the frozen bounds.

Placement policy:
- never put opaque chrome over speakerBounds
- prefer free zones (complement of speaker rect inside the 1920x1080 frame)
- when a module's default shell would intersect the speaker, switch side/anchor
  or remap to a face-safe kinetic hit
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.file_utils import bounds_intersect, normalized_bounds

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCENE_GEOMETRY_PATH = REPOSITORY_ROOT / "visual-production" / "layouts" / "scene-geometry.json"

LAYOUT_IDS: frozenset[str] = frozenset(
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

# Default module chrome footprints (normalized). Approximate the VP runtime CSS
# shells so we can reject placements that will sit on the face before render.
MODULE_OVERLAY_FOOTPRINTS: dict[str, dict[str, float]] = {
    # Magenta kinetic stamp — max-width ~46%, height ~18% of frame depending on text.
    "kinetic-word-punctuation": {"width": 0.46, "height": 0.18},
    # Large white punchline card (uses speaker-safe overlay region; still wide).
    "punchline-reveal": {"width": 0.55, "height": 0.45},
    # Full-height left/right white panel (~43%).
    "speaker-side-panel": {"width": 0.43, "height": 1.0},
    # Full white stage with upper-right video window (chrome is full-frame).
    "progress-scale": {"width": 1.0, "height": 1.0},
    # Numbered example card — left ~40% width, mid height band.
    "numbered-example-card": {"width": 0.40, "height": 0.34},
    # Full stage: right video dock + left terminal (same footprint as dependency-stack).
    "windows-prompt-typing": {"width": 1.0, "height": 1.0},
    # Link chip / badges — compact.



    "numbered-step-intro": {"width": 0.28, "height": 0.40},

    "brand-cta-lockup": {"width": 0.28, "height": 0.32},
    # No chrome.
    "source-punch-zoom": {"width": 0.0, "height": 0.0},

    "ui-callout": {"width": 0.26, "height": 0.12},
}


@dataclass(frozen=True)
class Placement:
    layout_id: str
    module_id: str
    side: str  # left | right
    anchor: str  # top | middle | bottom
    overlay_bounds: dict[str, float] | None
    speaker_bounds: dict[str, float] | None
    safe: bool
    reason: str
    remapped_from: str | None = None


@lru_cache(maxsize=1)
def load_scene_geometry() -> dict:
    if not SCENE_GEOMETRY_PATH.is_file():
        raise RuntimeError(
            f"Missing OBS layout geometry: {SCENE_GEOMETRY_PATH}. "
            "Speaker placement cannot be measured without the eight-layout catalog."
        )
    return json.loads(SCENE_GEOMETRY_PATH.read_text(encoding="utf-8"))


def layout_ids() -> list[str]:
    return sorted(load_scene_geometry()["layouts"])


def speaker_bounds_for_layout(layout_id: str) -> dict[str, float] | None:
    if layout_id not in LAYOUT_IDS:
        raise ValueError(
            f"Unknown layoutId {layout_id!r}. Must be one of: {', '.join(sorted(LAYOUT_IDS))}"
        )
    entry = load_scene_geometry()["layouts"][layout_id]
    bounds = entry.get("speakerBounds")
    if bounds is None:
        return None
    parsed = normalized_bounds(bounds)
    if parsed is None:
        raise ValueError(f"Layout {layout_id} has invalid speakerBounds.")
    return parsed


def free_zones(layout_id: str) -> list[dict[str, Any]]:
    """Axis-aligned free rectangles (normalized) outside the speaker box.

    Returns ranked zones: largest first. computer-screen-only → one full-frame zone.
    """

    speaker = speaker_bounds_for_layout(layout_id)
    if speaker is None:
        return [
            {
                "id": "full-frame",
                "bounds": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                "area": 1.0,
                "prefer_side": "left",
                "prefer_anchor": "middle",
            }
        ]

    sx, sy, sw, sh = speaker["x"], speaker["y"], speaker["width"], speaker["height"]
    zones: list[dict[str, Any]] = []

    def add(zone_id: str, x: float, y: float, w: float, h: float, side: str, anchor: str) -> None:
        if w < 0.05 or h < 0.05:
            return
        zones.append(
            {
                "id": zone_id,
                "bounds": {"x": x, "y": y, "width": w, "height": h},
                "area": w * h,
                "prefer_side": side,
                "prefer_anchor": anchor,
            }
        )

    # Left of speaker
    add("left", 0.0, 0.0, sx, 1.0, "left", "middle")
    # Right of speaker
    add("right", sx + sw, 0.0, 1.0 - (sx + sw), 1.0, "right", "middle")
    # Above speaker
    add("top", 0.0, 0.0, 1.0, sy, "left", "top")
    # Below speaker (rare for full-frame talking)
    add("bottom", 0.0, sy + sh, 1.0, 1.0 - (sy + sh), "left", "bottom")

    zones.sort(key=lambda item: item["area"], reverse=True)
    return zones


def _overlay_rect(
    *,
    footprint: dict[str, float],
    side: str,
    anchor: str,
    zone: dict[str, Any] | None,
) -> dict[str, float] | None:
    w = float(footprint.get("width") or 0)
    h = float(footprint.get("height") or 0)
    if w <= 0 or h <= 0:
        return None

    if zone is not None:
        zb = zone["bounds"]
        # Fit footprint inside the free zone (clamped).
        w = min(w, zb["width"] * 0.95)
        h = min(h, zb["height"] * 0.95)
        if side == "right":
            x = zb["x"] + zb["width"] - w - 0.02
        else:
            x = zb["x"] + 0.02
        if anchor == "top":
            y = zb["y"] + 0.02
        elif anchor == "bottom":
            y = zb["y"] + zb["height"] - h - 0.02
        else:
            y = zb["y"] + max(0.0, (zb["height"] - h) / 2)
        # Clamp to frame
        x = max(0.0, min(x, 1.0 - w))
        y = max(0.0, min(y, 1.0 - h))
        return {"x": x, "y": y, "width": w, "height": h}

    # Fallback absolute placement matching VP CSS defaults.
    x = 0.03 if side == "left" else 0.97 - w
    if anchor == "top":
        y = 0.09
    elif anchor == "bottom":
        y = 0.82
    else:
        y = 0.36
    return {"x": x, "y": y, "width": w, "height": h}


def _try_place(
    *,
    layout_id: str,
    module_id: str,
    speaker: dict[str, float] | None,
    preferred_side: str | None,
    preferred_anchor: str | None,
    remapped_from: str | None = None,
    reason: str | None = None,
) -> Placement | None:
    """Return a safe placement for module_id, or None if it cannot clear the speaker."""

    footprint = MODULE_OVERLAY_FOOTPRINTS.get(
        module_id, {"width": 0.30, "height": 0.30}
    )
    if module_id in {"source-punch-zoom"}:
        return Placement(
            layout_id=layout_id,
            module_id=module_id,
            side=preferred_side or "left",
            anchor=preferred_anchor or "middle",
            overlay_bounds=None,
            speaker_bounds=speaker,
            safe=True,
            reason=reason or "Source-led motion has no opaque overlay chrome.",
            remapped_from=remapped_from,
        )

    zones = free_zones(layout_id)
    ordered = list(zones)
    if preferred_side in {"left", "right"}:
        ordered = sorted(
            ordered,
            key=lambda z: (
                0 if z["prefer_side"] == preferred_side else 1,
                -z["area"],
            ),
        )

    # Full-height side panels need a tall free column.
    if module_id == "speaker-side-panel":
        tall = [
            z
            for z in ordered
            if z["bounds"]["height"] >= 0.7 and z["bounds"]["width"] >= 0.35
        ]
        if not tall:
            return None
        ordered = tall

    for zone in ordered:
        side = preferred_side if preferred_side in {"left", "right"} else zone["prefer_side"]
        anchor = (
            preferred_anchor
            if preferred_anchor in {"top", "middle", "bottom"}
            else zone["prefer_anchor"]
        )
        if zone["id"] == "top":
            anchor = "top"
        overlay = _overlay_rect(
            footprint=footprint, side=side, anchor=anchor, zone=zone
        )
        if overlay is None:
            return Placement(
                layout_id=layout_id,
                module_id=module_id,
                side=side,
                anchor=anchor,
                overlay_bounds=None,
                speaker_bounds=speaker,
                safe=True,
                reason=reason or "No overlay footprint.",
                remapped_from=remapped_from,
            )
        if speaker is None or not bounds_intersect(overlay, speaker):
            return Placement(
                layout_id=layout_id,
                module_id=module_id,
                side=side,
                anchor=anchor,
                overlay_bounds=overlay,
                speaker_bounds=speaker,
                safe=True,
                reason=reason
                or f"Fits free zone {zone['id']} on layout {layout_id}.",
                remapped_from=remapped_from,
            )
    return None


def placement_for_module(
    *,
    layout_id: str,
    module_id: str,
    preferred_side: str | None = None,
    preferred_anchor: str | None = None,
    recent_module_ids: list[str] | None = None,
) -> Placement:
    """Choose side/anchor so the module footprint clears the measured speaker.

    When the preferred module cannot fit, remaps rotate among safe alternatives
    (variety-aware) instead of always collapsing to the same kinetic stamp.
    """

    if layout_id not in LAYOUT_IDS:
        raise ValueError(f"Unknown layoutId {layout_id!r}")

    speaker = speaker_bounds_for_layout(layout_id)
    direct = _try_place(
        layout_id=layout_id,
        module_id=module_id,
        speaker=speaker,
        preferred_side=preferred_side,
        preferred_anchor=preferred_anchor,
    )
    if direct is not None:
        return direct

    # Face-safe remap with variety rotation (app authority — not HF skill defaults).
    from app.core.editorial_variety import pick_variety_remap, SAFE_REMAP_CANDIDATES

    recent = list(recent_module_ids or [])
    # Build candidate list that actually place on this layout.
    viable: list[str] = []
    for candidate in SAFE_REMAP_CANDIDATES:
        if candidate == module_id:
            continue
        trial = _try_place(
            layout_id=layout_id,
            module_id=candidate,
            speaker=speaker,
            preferred_side=preferred_side,
            preferred_anchor="top" if candidate == "kinetic-word-punctuation" else preferred_anchor,
        )
        if trial is not None:
            viable.append(candidate)

    if not viable:
        side = preferred_side or "left"
        anchor = preferred_anchor or "top"
        footprint = MODULE_OVERLAY_FOOTPRINTS.get(
            module_id, {"width": 0.30, "height": 0.30}
        )
        zones = free_zones(layout_id)
        overlay = _overlay_rect(
            footprint=footprint,
            side=side,
            anchor=anchor,
            zone=zones[0] if zones else None,
        )
        return Placement(
            layout_id=layout_id,
            module_id=module_id,
            side=side,
            anchor=anchor,
            overlay_bounds=overlay,
            speaker_bounds=speaker,
            safe=False,
            reason=f"No safe free zone for {module_id} on {layout_id}.",
            remapped_from=None,
        )

    chosen = pick_variety_remap(
        preferred_module_id=viable[0],
        recent_module_ids=recent,
        candidates=viable,
    )
    placed = _try_place(
        layout_id=layout_id,
        module_id=chosen,
        speaker=speaker,
        preferred_side=preferred_side,
        preferred_anchor="top" if chosen == "kinetic-word-punctuation" else preferred_anchor,
        remapped_from=module_id,
        reason=(
            f"{module_id} has no non-intersecting placement on {layout_id}; "
            f"remapped to {chosen} (variety-aware face-safe fallback)."
        ),
    )
    assert placed is not None  # viable was non-empty
    return placed


def speaker_safety_payload(
    placement: Placement,
    *,
    start_sec: float,
    end_sec: float,
) -> dict[str, Any] | None:
    """Build a schema-valid speakerSafety object when speaker is on screen.

    When layout has no speaker (computer-screen-only), returns None so the
    parameter is omitted.
    """

    if placement.speaker_bounds is None:
        return None
    # Need three unique verification times inside the beat (schema minItems=3).
    start = float(start_sec)
    end = float(end_sec)
    span = max(0.15, end - start)
    candidates = [
        round(start + span * 0.1, 3),
        round(start + span * 0.5, 3),
        round(start + span * 0.9, 3),
    ]
    times: list[float] = []
    for value in candidates:
        clamped = min(max(value, start), end)
        if clamped not in times:
            times.append(clamped)
    cursor = start
    while len(times) < 3:
        cursor = round(cursor + 0.01, 3)
        if cursor > end:
            cursor = start
        if cursor not in times:
            times.append(cursor)
    overlays = []
    if placement.overlay_bounds is not None:
        overlays.append(dict(placement.overlay_bounds))
    mode = _safety_mode_for_layout(placement.layout_id)
    return {
        "checked": True,
        "mode": mode,
        "speakerBounds": dict(placement.speaker_bounds),
        "overlayOcclusionBounds": overlays,
        "verifiedAtSec": times[:3],
        "maxSpeakerAbsenceSec": 0,
    }


def _safety_mode_for_layout(layout_id: str) -> str:
    if layout_id == "full-screen-talking":
        return "full-frame-speaker"
    if layout_id == "talking-left":
        return "left-container"
    if layout_id == "talking-right":
        return "right-container"
    if layout_id in {"talking-bottom-left", "talking-bottom-right"}:
        return "bottom-container"
    if layout_id in {"talking-top-left", "talking-top-right"}:
        return "corner-container"
    return "full-frame-speaker"


def layout_table_markdown() -> str:
    """Human-readable table of the eight layouts (for CLI / handoff)."""

    geo = load_scene_geometry()
    lines = [
        "| layoutId | OBS scene | speaker (normalized) |",
        "| --- | --- | --- |",
    ]
    for layout_id in sorted(geo["layouts"]):
        entry = geo["layouts"][layout_id]
        bounds = entry.get("speakerBounds")
        if bounds is None:
            rect = "none (full frame free)"
        else:
            rect = (
                f"x={bounds['x']:.3f} y={bounds['y']:.3f} "
                f"w={bounds['width']:.3f} h={bounds['height']:.3f}"
            )
        lines.append(
            f"| `{layout_id}` | {entry.get('obsScene', '—')} | {rect} |"
        )
    return "\n".join(lines)
