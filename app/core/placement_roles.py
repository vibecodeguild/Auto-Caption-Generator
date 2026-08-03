"""Placement content roles — all production engines, no kickers.

Authority: docs/vcg-graphics-process/placement.md

Placement UI edits **lines** (text + revealFrame + slot) plus small meta/assets/motion
bags. Adapters map slots → engine ``parameters.*`` at draft/draw time.

Kicker / eyebrow is retired from the product content model.
"""

from __future__ import annotations

from typing import Any

from app.core.visual_production import MODULE_IDS, MODULE_PARAMETER_KEYS

# --- Line unit ----------------------------------------------------------------

# Absolute frame on the locked cut when this line is revealed.
LINE_KEYS = frozenset({"text", "revealFrame", "slot"})


def empty_line(slot: str, *, text: str = "", reveal_frame: int = 0) -> dict[str, Any]:
    return {
        "text": str(text or ""),
        "revealFrame": int(reveal_frame),
        "slot": str(slot),
    }


# --- Engine specs -------------------------------------------------------------

# fixed_line_slots: ordered slots always present (may be empty text).
# list_slot: optional repeating slot prefix; UI allows add/remove (items.0, items.1, …).
# list_min / list_max: bounds for list_slot (None = no list).
# meta_keys / asset_keys / motion_keys: non-line bags (engine param names).

ENGINE_PLACEMENT_SPECS: dict[str, dict[str, Any]] = {
    "punchline-reveal": {
        "fixed_line_slots": ["text"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": ["imageAssetId"],  # required — joke card is the only mode
        "motion_keys": ["accentColor"],
        "notes": "Joke card only (image + caption, head docks left). Not a text-only kinetic.",
    },
    "kinetic-word-punctuation": {
        "fixed_line_slots": ["phrase"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": ["side", "anchor", "accentColor"],
        "notes": "Single kinetic phrase.",
    },
    "robot-cheer": {
        "fixed_line_slots": ["text", "tagline"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": [],
        "notes": "Bubble + optional energy tagline (not a kicker eyebrow).",
    },
    "robot-defiant": {
        "fixed_line_slots": ["text"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": [],
        "notes": "",
    },
    "robot-roast": {
        "fixed_line_slots": ["text"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": [],
        "notes": "",
    },
    "robot-rocket-sign": {
        "fixed_line_slots": ["text"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": [],
        "notes": "Placard line on rocket CTA.",
    },
    "speaker-side-panel": {
        "fixed_line_slots": ["text"],
        "list_slot": "items",
        "list_min": 0,
        "list_max": 12,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": ["side", "frameStyle", "panelWidth", "accentColor", "videoBounds"],
        "notes": "Title + bullet items; each item is lines slot items.i.",
    },
    "dependency-stack": {
        "fixed_line_slots": ["text"],
        "list_slot": "nodes",
        "list_min": 0,
        "list_max": 6,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": [],
        "notes": "Title + stack nodes.",
    },
    "numbered-example-card": {
        "fixed_line_slots": [],
        "list_slot": "titleLines",
        "list_min": 1,
        "list_max": 8,
        "meta_keys": ["exampleNumber", "totalExamples", "accentLineIndex"],
        "asset_keys": [],
        "motion_keys": ["accentColor", "tags"],
        "notes": "No kicker. Body is title lines only.",
    },
    "speaker-rise-callouts": {
        "fixed_line_slots": ["thesis"],
        "list_slot": "callouts",
        "list_min": 0,
        "list_max": 8,
        "meta_keys": ["accentCalloutIndex"],
        "asset_keys": [],
        "motion_keys": [],
        "notes": "Thesis + rising callout lines.",
    },
    "problem-card-triptych": {
        "fixed_line_slots": ["cards.0", "cards.1", "cards.2"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": [],
        "notes": "Exactly three card strings (v1).",
    },
    "progress-scale": {
        "fixed_line_slots": ["text", "startLabel", "targetLabel"],
        "list_slot": "milestones",
        "list_min": 0,
        "list_max": 8,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": ["accentColor"],
        "notes": "No kicker. Title + end labels + milestone lines.",
    },
    "numbered-step-intro": {
        "fixed_line_slots": ["title", "action"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": ["stepNumber", "showNumber"],
        "asset_keys": [],
        "motion_keys": ["side"],
        "notes": "",
    },
    "ui-callout": {
        "fixed_line_slots": ["label", "detail"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": ["targetBounds", "pointer", "accentColor"],
        "notes": "",
    },
    "windows-prompt-typing": {
        "fixed_line_slots": ["prompt"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": ["appName"],
        "asset_keys": [],
        "motion_keys": ["side"],
        "notes": "Prompt is one timed line (typing channel).",
    },
    "brand-cta-lockup": {
        "fixed_line_slots": ["logoText", "action", "destination"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": ["logoAssetId"],
        "motion_keys": [],
        "notes": "",
    },
    "tradeoff-meter": {
        "fixed_line_slots": ["leftLabel", "rightLabel", "verdict"],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": ["value"],
        "asset_keys": [],
        "motion_keys": ["side"],
        "notes": "No kicker. Meter value is meta 0–1.",
    },
    "source-punch-zoom": {
        "fixed_line_slots": [],
        "list_slot": None,
        "list_min": 0,
        "list_max": 0,
        "meta_keys": [],
        "asset_keys": [],
        "motion_keys": ["focusX", "focusY", "zoom", "settleSec", "motion"],
        "notes": "Motion-only engine; no copy lines.",
    },
}


def assert_specs_cover_all_engines() -> None:
    missing = sorted(MODULE_IDS - set(ENGINE_PLACEMENT_SPECS))
    extra = sorted(set(ENGINE_PLACEMENT_SPECS) - MODULE_IDS)
    if missing or extra:
        raise RuntimeError(
            f"placement specs out of sync with MODULE_IDS. missing={missing} extra={extra}"
        )


def get_engine_placement_spec(engine_id: str) -> dict[str, Any]:
    eid = str(engine_id or "").strip()
    if eid not in ENGINE_PLACEMENT_SPECS:
        raise KeyError(f"No placement spec for engine {eid!r}")
    return dict(ENGINE_PLACEMENT_SPECS[eid])


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

    spec = get_engine_placement_spec(engine_id)
    fixed, list_slot, list_min, list_max = list_fixed_and_list_slots(engine_id)
    return {
        "engineId": engine_id,
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
