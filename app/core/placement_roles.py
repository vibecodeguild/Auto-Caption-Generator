"""Placement content roles — thin adapter over the engine registry. No kickers.

Authority: docs/vcg-graphics-process/placement.md (placement policy) and
docs/vcg-graphics-process/architecture.md §3 (engine interface ownership).

Every engine fact (slots, list bounds, meta/assets/motion knobs) is declared
ONCE in ``ENGINE_REGISTRY`` (app/core/visual_production.py), next to the draw
code. This module owns only placement-layer POLICY:

- the line unit shape (text + revealFrame + slot);
- adapters that map slots → engine ``parameters.*`` at draft/draw time;
- the kicker ban (D5): kicker is retired from the product content model and is
  filtered here even though legacy engine CSS still accepts it.

Do not declare engine interface data in this module — grow the engine's
registry entry instead and placement inherits it.
"""

from __future__ import annotations

from typing import Any

from app.core.visual_production import (
    ENGINE_REGISTRY,
    MODULE_IDS,
    MODULE_PARAMETER_KEYS,
    canonicalize_engine_id,
)

# --- Line unit ----------------------------------------------------------------

# Absolute frame on the locked cut when this line is revealed.
LINE_KEYS = frozenset({"text", "revealFrame", "slot"})


def empty_line(slot: str, *, text: str = "", reveal_frame: int = 0) -> dict[str, Any]:
    return {
        "text": str(text or ""),
        "revealFrame": int(reveal_frame),
        "slot": str(slot),
    }


# --- Engine specs (derived) ---------------------------------------------------

# fixed_line_slots: ordered slots always present (may be empty text).
# list_slot: optional repeating slot prefix; UI allows add/remove (items.0, items.1, …).
# list_min / list_max: bounds for list_slot (None = no list).
# meta_keys / asset_keys / motion_keys: non-line bags (engine param names).


def _derived_spec(engine_id: str) -> dict[str, Any]:
    placement = ENGINE_REGISTRY[engine_id]["placement"]
    return {
        "fixed_line_slots": list(placement["fixed_line_slots"]),
        "list_slot": placement["list_slot"],
        "list_min": int(placement["list_min"]),
        "list_max": int(placement["list_max"]),
        "meta_keys": list(placement["meta_keys"]),
        "asset_keys": list(placement["asset_keys"]),
        "motion_keys": list(placement["motion_keys"]),
        "notes": str(placement.get("notes") or ""),
    }


# Derived view over ENGINE_REGISTRY — kept for existing importers. Never edit
# this mapping; grow the engine's registry entry instead.
ENGINE_PLACEMENT_SPECS: dict[str, dict[str, Any]] = {
    engine_id: _derived_spec(engine_id) for engine_id in sorted(ENGINE_REGISTRY)
}


def assert_specs_cover_all_engines() -> None:
    """Validate registry well-formedness for placement.

    Coverage is structural now (specs derive from the registry), so this guards
    the declarations themselves: sane list bounds, and the D5 kicker ban at the
    declaration level — kicker may exist only in legacy_parameter_keys, never
    in any placement-facing bucket.
    """

    problems: list[str] = []
    for engine_id, spec in ENGINE_PLACEMENT_SPECS.items():
        placement_keys = (
            [str(slot).split(".", 1)[0] for slot in spec["fixed_line_slots"]]
            + ([spec["list_slot"]] if spec["list_slot"] else [])
            + list(spec["meta_keys"])
            + list(spec["asset_keys"])
            + list(spec["motion_keys"])
        )
        if "kicker" in placement_keys:
            problems.append(f"{engine_id}: kicker in placement interface (D5)")
        if spec["list_slot"] is None and spec["list_max"] != 0:
            problems.append(f"{engine_id}: list bounds without a list_slot")
        if spec["list_slot"] is not None and spec["list_max"] < max(1, spec["list_min"]):
            problems.append(f"{engine_id}: list_max below list_min")
        allowed = MODULE_PARAMETER_KEYS.get(engine_id) or set()
        unknown = sorted(set(placement_keys) - allowed)
        if unknown:
            problems.append(f"{engine_id}: placement keys not in engine parameters: {unknown}")
    if problems:
        raise RuntimeError("engine registry placement interfaces invalid: " + "; ".join(problems))


def get_engine_placement_spec(engine_id: str) -> dict[str, Any]:
    # Retired engines (e.g. speaker-side-panel → dependency-stack) resolve here so
    # Place / status never KeyError on persisted episode drafts.
    eid = canonicalize_engine_id(str(engine_id or "").strip())
    if eid not in ENGINE_REGISTRY:
        raise KeyError(f"No placement spec for engine {eid!r}")
    return _derived_spec(eid)


def list_fixed_and_list_slots(engine_id: str) -> tuple[list[str], str | None, int, int]:
    spec = get_engine_placement_spec(engine_id)
    fixed = list(spec.get("fixed_line_slots") or [])
    list_slot = spec.get("list_slot")
    list_min = int(spec.get("list_min") or 0)
    list_max = int(spec.get("list_max") or 0)
    return fixed, (str(list_slot) if list_slot else None), list_min, list_max


def slot_to_parameter_path(slot: str) -> str:
    """Map placement slot id → engine parameters path (for semanticItems)."""

    slot = str(slot or "").strip()
    if not slot:
        return "parameters"
    if "." in slot:
        # items.0 → parameters.items.0
        return f"parameters.{slot}"
    return f"parameters.{slot}"


def lines_to_engine_parameters(
    engine_id: str,
    lines: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
    assets: dict[str, Any] | None = None,
    motion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collapse placement lines/meta/assets/motion into engine parameters dict.

    Never emits kicker. Filters to MODULE_PARAMETER_KEYS for the engine.
    """

    eid = str(engine_id or "").strip()
    allowed = MODULE_PARAMETER_KEYS.get(eid) or set()
    params: dict[str, Any] = {}
    list_buckets: dict[str, list[Any]] = {}

    for row in lines or []:
        if not isinstance(row, dict):
            continue
        slot = str(row.get("slot") or "").strip()
        text = str(row.get("text") or "")
        if not slot:
            continue
        if "." in slot:
            head, _, index_s = slot.partition(".")
            try:
                index = int(index_s)
            except ValueError:
                continue
            bucket = list_buckets.setdefault(head, [])
            while len(bucket) <= index:
                bucket.append("")
            bucket[index] = text
        else:
            params[slot] = text

    for head, values in list_buckets.items():
        # problem-card-triptych uses cards.0 as fixed slots → list cards
        if head == "cards":
            params["cards"] = list(values)
        else:
            params[head] = list(values)

    for bag in (meta or {}, assets or {}, motion or {}):
        for key, value in bag.items():
            if key == "kicker":
                continue
            params[key] = value

    # Explicitly drop kicker if anything slipped through.
    params.pop("kicker", None)

    return {key: value for key, value in params.items() if key in allowed and key != "kicker"}


def placement_interface_summary(engine_id: str) -> dict[str, Any]:
    """UI-facing summary for one engine."""

    live_id = canonicalize_engine_id(str(engine_id or "").strip())
    spec = get_engine_placement_spec(live_id)
    fixed, list_slot, list_min, list_max = list_fixed_and_list_slots(live_id)
    return {
        "engineId": live_id,
        "fixedLineSlots": fixed,
        "listSlot": list_slot,
        "listMin": list_min,
        "listMax": list_max,
        "metaKeys": list(spec.get("meta_keys") or []),
        "assetKeys": list(spec.get("asset_keys") or []),
        "motionKeys": list(spec.get("motion_keys") or []),
        "notes": str(spec.get("notes") or ""),
        "kicker": False,
    }


def all_placement_interfaces() -> list[dict[str, Any]]:
    assert_specs_cover_all_engines()
    return [placement_interface_summary(eid) for eid in sorted(ENGINE_PLACEMENT_SPECS)]


# Validate import-time coverage of MODULE_IDS.
assert_specs_cover_all_engines()
