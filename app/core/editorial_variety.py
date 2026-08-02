"""Whole-video visual variety for editorial plans (flat graphic-id model).

Rules:
- no consecutive same graphic id without an intentional series;
- no single graphic over ~25% of graphic beats;
- top two graphics may not carry more than ~45% together;
- remaps for face-safety should rotate among alternatives, not collapse
  to one graphic for the whole open.

Flat structure: each Golden Record graphic id is its own standard.
There is no family / tree of variants (no "pick among 5 bullet reveals").
HyperFrames skills are NOT variety authority. App validators own this gate.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# Align with story_assets Approval Contract three.
MAX_TREATMENT_SHARE = 0.25
MAX_TOP_TWO_SHARE = 0.45
MAX_CONSECUTIVE_SAME_GRAPHIC = 1
# Share caps need enough graphic beats; consecutive-id always applies.
MIN_GRAPHICS_FOR_SHARE_CAPS = 6

# Preferred rotation order when a layout forces a face-safe remap.
SAFE_REMAP_CANDIDATES: tuple[str, ...] = (
    "kinetic-word-punctuation",
    "numbered-step-intro",
    "windows-prompt-typing",
    "brand-cta-lockup",
    "source-punch-zoom",
)

# Modules that do not count as "graphic variety" (source-led motion).
NON_GRAPHIC_MODULES: frozenset[str] = frozenset(
    {
        "source-punch-zoom",
    }
)

# Legacy map kept only so old imports of VISUAL_FAMILIES / visual_family do not
# crash. Not used for variety decisions. Flat model: graphic id is the unit.
VISUAL_FAMILIES: dict[str, str] = {}


def visual_family(treatment_or_module_id: str) -> str:
    """Deprecated: family concept removed. Returns the graphic id itself."""

    return str(treatment_or_module_id or "").strip() or "other:unknown"


def _item_graphic_id(item: dict, id_key: str) -> str:
    return str(
        item.get(id_key)
        or item.get("graphicId")
        or item.get("treatmentId")
        or item.get("moduleId")
        or ""
    ).strip()


def _graphic_items(
    items: list[dict],
    *,
    id_key: str,
) -> list[dict]:
    graphics = []
    for item in items:
        identifier = _item_graphic_id(item, id_key)
        if not identifier or identifier in NON_GRAPHIC_MODULES:
            continue
        # Source-led beats with no copy are non-graphic for variety.
        if item.get("beatType") == "source-led-motion" and not item.get("onScreenCopy"):
            continue
        graphics.append(item)
    return graphics


def validate_variety(
    items: list[dict],
    *,
    id_key: str = "graphicId",
    series_key: str = "intentionalSeriesId",
) -> list[dict]:
    """Return variety errors for a sequence of beats (flat graphic-id model)."""

    graphics = _graphic_items(items, id_key=id_key)
    errors: list[dict] = []
    if len(graphics) < 2:
        return errors

    # Consecutive same graphic ban (unless same intentional series).
    prev_id: str | None = None
    prev_series: str | None = None
    streak = 0
    for index, item in enumerate(graphics):
        identifier = _item_graphic_id(item, id_key)
        series = str(item.get(series_key) or "") or None
        if identifier == prev_id and (not series or series != prev_series):
            streak += 1
        else:
            streak = 1
        if streak > MAX_CONSECUTIVE_SAME_GRAPHIC and identifier == prev_id:
            errors.append(
                {
                    "code": "variety-consecutive-graphic",
                    "path": f"/beats/{index}",
                    "id": identifier,
                    "message": (
                        f"Consecutive graphic beats use the same graphic id {identifier!r}. "
                        "Use a different golden graphic, or set the same intentionalSeriesId "
                        "for a deliberate series/callback."
                    ),
                }
            )
        prev_id = identifier
        prev_series = series

    # Share caps — only once the plan is long enough that percentages mean something.
    ids = [_item_graphic_id(item, id_key) for item in graphics]
    counts = Counter(ids)
    total = len(ids)
    if total >= MIN_GRAPHICS_FOR_SHARE_CAPS:
        worst_id, worst_count = counts.most_common(1)[0]
        if worst_count / total > MAX_TREATMENT_SHARE + 1e-9:
            errors.append(
                {
                    "code": "variety-graphic-share",
                    "path": "/beats",
                    "id": worst_id,
                    "count": worst_count,
                    "total": total,
                    "maximumShare": MAX_TREATMENT_SHARE,
                    "message": (
                        f"{worst_id!r} appears {worst_count} of {total} graphic beats "
                        f"({worst_count / total * 100:.0f}%). No single graphic may exceed "
                        f"{MAX_TREATMENT_SHARE * 100:.0f}% — this is the 'same graphic on loop' "
                        f"failure mode."
                    ),
                }
            )

        ranked = counts.most_common(2)
        if len(ranked) >= 2:
            top_two = ranked[0][1] + ranked[1][1]
            if top_two / total > MAX_TOP_TWO_SHARE + 1e-9:
                errors.append(
                    {
                        "code": "variety-top-two-share",
                        "path": "/beats",
                        "ids": [ranked[0][0], ranked[1][0]],
                        "count": top_two,
                        "total": total,
                        "maximumShare": MAX_TOP_TWO_SHARE,
                        "message": (
                            f"{ranked[0][0]!r} and {ranked[1][0]!r} together carry "
                            f"{top_two} of {total} graphics ({top_two / total * 100:.0f}%). "
                            f"Two graphics may not exceed {MAX_TOP_TWO_SHARE * 100:.0f}%."
                        ),
                    }
                )

    return errors


def pick_variety_remap(
    *,
    preferred_module_id: str,
    recent_module_ids: list[str],
    candidates: list[str] | None = None,
) -> str:
    """Choose a face-safe remap that advances variety (flat graphic-id model).

    Prefers candidates that are not the last graphic used and are less-used recently.
    """

    pool = list(candidates or SAFE_REMAP_CANDIDATES)
    if preferred_module_id not in pool:
        pool.insert(0, preferred_module_id)

    recent = [mid for mid in recent_module_ids if mid and mid not in NON_GRAPHIC_MODULES]
    last_id = recent[-1] if recent else None
    recent_counts = Counter(recent)

    def score(module_id: str) -> tuple[int, int, int]:
        # Lower is better.
        same_as_last = 1 if module_id == last_id else 0
        usage = recent_counts.get(module_id, 0)
        pool_index = pool.index(module_id) if module_id in pool else 99
        return (same_as_last, usage, pool_index)

    ranked = sorted(pool, key=score)
    return ranked[0] if ranked else preferred_module_id


def variety_report(items: list[dict], *, id_key: str = "graphicId") -> dict[str, Any]:
    graphics = _graphic_items(items, id_key=id_key)
    ids = [_item_graphic_id(item, id_key) for item in graphics]
    return {
        "graphicCount": len(ids),
        "graphicCounts": dict(Counter(ids)),
        "errors": validate_variety(items, id_key=id_key),
    }
