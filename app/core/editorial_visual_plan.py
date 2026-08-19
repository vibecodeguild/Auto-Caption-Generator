"""Map validated editorial beats onto production engine cues.

This is the design authority for daily finishing graphics:
- engines from app/core/visual_production.py (MODULE_IDS)
- brand accent #FF00CE magenta, teal kickers, Montserrat
- edge / left-panel placement so the speaker is not covered

Uses engines only. See architecture.md (engine / usage / placement).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.core.editorial_beats import validate_editorial_plan
from app.core.editorial_layout import (
    LAYOUT_IDS,
    placement_for_module,
    speaker_safety_payload,
)
from app.core.visual_production import (
    BRAND_ID,
    MODULE_IDS,
    MODULE_PARAMETER_KEYS,
    _module_semantic_texts,
    _unanchored_semantic_items,
)

VCG_MAGENTA = "#FF00CE"
VCG_TEAL = "#007C7D"

# Editorial graphicId → Visual Production moduleId + parameter mode.
# Only real VP modules (same IDs the successful projects already used).
TREATMENT_TO_MODULE: dict[str, dict[str, str]] = {
    # Punchlines / emphasis → magenta kinetic stamps (readable, face-clear edges)
    # Module ids only — seed-only aliases (compact-editorial-emphasis, compact-prompt-card) deleted.
    "punchline-reveal": {
        "moduleId": "punchline-reveal",
        "mode": "punchline",
    },
    "kinetic-word-punctuation": {
        "moduleId": "kinetic-word-punctuation",
        "mode": "kinetic",
    },
    # Lists / stacks → dependency stack (speaker docks right)
    "dependency-stack": {
        "moduleId": "dependency-stack",
        "mode": "dependency",
    },
    # Host intro: left docked head, right name + experience + Wai thank-you
    "intro-credentials": {
        "moduleId": "intro-credentials",
        "mode": "intro",
    },
    # Tutorial structure
    "numbered-example-card": {
        "moduleId": "numbered-example-card",
        "mode": "numbered-example",
    },
    "numbered-step-intro": {
        "moduleId": "numbered-step-intro",
        "mode": "numbered-step",
    },
    "windows-prompt-typing": {
        "moduleId": "windows-prompt-typing",
        "mode": "prompt",
    },
    "windows-prompt-overlay": {
        "moduleId": "windows-prompt-overlay",
        "mode": "prompt-overlay",
    },
    "numbered-phrase-reveal": {
        "moduleId": "numbered-phrase-reveal",
        "mode": "numbered-phrase",
    },
    # Lists
    # UI / proof / CTA
    "ui-callout": {"moduleId": "ui-callout", "mode": "callout"},
    "brand-cta-lockup": {"moduleId": "brand-cta-lockup", "mode": "cta"},
    # Source-led
    "source-punch-zoom": {
        "moduleId": "source-punch-zoom",
        "mode": "punch-zoom",
    },
    # Recovered VCG mascot reactions
    "robot-cheer": {"moduleId": "robot-cheer", "mode": "robot"},
    "robot-defiant": {"moduleId": "robot-defiant", "mode": "robot"},
    "robot-roast": {"moduleId": "robot-roast", "mode": "robot"},
    "robot-rocket-sign": {"moduleId": "robot-rocket-sign", "mode": "robot-rocket"},
}

GRAPHIC_TO_MODULE = TREATMENT_TO_MODULE


def resolve_module_binding(graphic_id: str) -> dict[str, str] | None:
    """Resolve plan usage/engine id → engine binding for cue parameters."""

    key = str(graphic_id or "").strip()
    if not key:
        return None
    if key in TREATMENT_TO_MODULE:
        binding = dict(TREATMENT_TO_MODULE[key])
        binding.setdefault("engineId", binding.get("moduleId", key))
        return binding
    # Any production engine id is valid (usage may equal engine id).
    if key in MODULE_IDS:
        return _binding_for_module(key, key)
    # Library usage with distinct engineId
    try:
        from app.core.graphics_library import resolve_engine_id

        engine_id = resolve_engine_id(key)
        if engine_id:
            return _binding_for_module(engine_id, key)
    except Exception:  # noqa: BLE001
        pass
    return None


def buildable_module_treatment_ids() -> frozenset[str]:
    return frozenset(MODULE_IDS)


def _parse_numbered(text: str) -> tuple[int, list[str]]:
    stripped = text.strip()
    match = re.match(
        r"^(?:0*(?P<num>\d{1,2}))\s*(?:[—–\-:.]|\s)\s*(?P<body>.+)$",
        stripped,
    )
    if match:
        body = match.group("body").strip()
        return int(match.group("num")), _title_lines(body)
    return 1, _title_lines(stripped)


def _title_lines(text: str, max_lines: int = 3) -> list[str]:
    words = text.upper().split()
    if not words:
        return ["EXAMPLE"]
    if len(words) <= 4:
        return [" ".join(words)]
    # Prefer two short lines over one long line.
    mid = max(2, len(words) // 2)
    lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    return lines[:max_lines]


def _kicker_for(beat: dict, mode: str) -> str:
    mapping = {
        "kinetic": "HIT",
        "side-panel": "SECTION",
        "numbered-example": "EXAMPLE",
        "numbered-step": "STEP",
        "numbered-phrase": "STEP",
        "prompt": "PROMPT",
        "list": "LIST",
        "side-list": "LIST",
        "result": "RESULT",
        "link": "LINK",
        "cta": "NEXT",
        "callout": "UI",
        "rank": "RANK",
    }
    beat_type = str(beat.get("beatType") or "")
    if beat_type == "punchline":
        return "PUNCHLINE"
    if beat_type == "cta":
        return "CTA"
    if beat_type == "proof":
        return "PROOF"
    return mapping.get(mode, "VCG")


def _kinetic_anchor(index: int) -> str:
    # Prefer high stamps; only dip to middle for variety (avoid face band).
    return ("top", "top", "middle")[index % 3]


def _filter_module_params(module_id: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed = MODULE_PARAMETER_KEYS.get(module_id) or set()
    return {key: value for key, value in params.items() if key in allowed}


def _module_parameters(beat: dict, binding: dict[str, str], *, index: int) -> dict[str, Any]:
    mode = binding["mode"]
    module_id = binding["moduleId"]
    copy = "" if beat.get("onScreenCopy") is None else str(beat["onScreenCopy"]).strip()
    accent = VCG_MAGENTA
    # Do not invent speakerSafety objects — schema requires measured fields.
    # Face-clear placement comes from module CSS (left panels, left kinetics).
    base: dict[str, Any] = {
        "reviewLabel": copy or beat["id"],
        "editorialPurpose": (
            f"Editorial beat {beat['id']} via graphic "
            f"{beat.get('graphicId') or beat.get('treatmentId')}."
        ),
        "recipeId": beat.get("graphicId") or beat.get("treatmentId"),
        "opacity": 1,
        "transitionIn": "editorial-snap",
        "transitionOut": "fade",
        "accentColor": accent,
    }

    if mode == "kinetic":
        base.update(
            {
                "phrase": copy.upper() if copy else "HIT",
                "anchor": _kinetic_anchor(index),
                "side": "left",
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "punchline":
        base.update(
            {
                "text": copy.upper() if copy else "PUNCHLINE",
                "kicker": _kicker_for(beat, mode),
            }
        )
        # Optional generated image on the beat → joke card (head left, art right).
        image_id = str(beat.get("imageAssetId") or beat.get("jokeImageAssetId") or "").strip()
        if image_id:
            base["imageAssetId"] = image_id
            base["transitionIn"] = "none"
            base["transitionOut"] = "none"
        return _filter_module_params(module_id, base)

    if mode == "side-panel":
        base.update(
            {
                "text": copy.upper() if copy else "SECTION",
                "kicker": _kicker_for(beat, mode),
                "side": "left",
                "frameStyle": "hairline",
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "numbered-example":
        number, lines = _parse_numbered(copy or "1 — EXAMPLE")
        base.update(
            {
                "kicker": "EXAMPLE",
                "exampleNumber": number,
                "totalExamples": 10,
                "titleLines": lines,
                "accentLineIndex": 0 if lines else -1,
                "tags": ["GROK", "POWERPOINT"],
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "numbered-step":
        number, lines = _parse_numbered(copy or "1 — STEP")
        base.update(
            {
                "stepNumber": number,
                "title": lines[0] if lines else "STEP",
                "action": lines[1] if len(lines) > 1 else "DO THIS",
                "side": "left",
                "showNumber": True,
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "prompt":
        base.update(
            {
                "appName": "Windows PowerShell",
                "prompt": copy or "prompt",
                "side": "left",
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "numbered-phrase":
        number, lines = _parse_numbered(copy or "1 — Phrase")
        base.update(
            {
                "numberLabel": str(number),
                "title": "",
                "text": " ".join(lines) if lines else (copy or "Phrase"),
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "callout":
        base.update(
            {
                "label": copy or "UI",
                "targetBounds": beat.get("uiRegion")
                or {"x": 0.12, "y": 0.18, "width": 0.36, "height": 0.16},
                "pointer": "below",
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "result":
        lines = [part.strip() for part in re.split(r"[·|\n]", copy) if part.strip()] or [
            copy or "RESULT"
        ]
        base.update(
            {
                "kicker": _kicker_for(beat, mode),
                "lines": lines[:3],
                "accentLineIndex": 0,
                "mark": "check",
                "side": "left",
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "rank":
        base.update(
            {
                "rank": copy.split()[0] if copy else "#1",
                "verdict": copy or "RANKED",
                "medal": "gold",
                "side": "left",
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "cta":
        base.update(
            {
                "logoText": "Community",
                "action": copy or "JOIN THE COMMUNITY",
                "destination": "your.community.url",
                "transitionIn": "none",
                "transitionOut": "none",
            }
        )
        return _filter_module_params(module_id, base)

    if mode == "punch-zoom":
        base.update(
            {
                "focusX": 0.62,
                "focusY": 0.42,
                "zoom": 1.12,
                "settleSec": 0.35,
            }
        )
        base.pop("accentColor", None)
        return _filter_module_params(module_id, base)

    if mode == "robot":
        # Bubble line is spoken-sync copy; cheer keeps the classic energy tagline.
        base.update({"text": copy or "YEAH!"})
        if module_id == "robot-cheer":
            base["tagline"] = "FOR THE WIN!"
        base["transitionIn"] = "none"
        base["transitionOut"] = "none"
        return _filter_module_params(module_id, base)

    if mode == "robot-rocket":
        base.update({"text": copy or "LINK IN DESCRIPTION"})
        base["transitionIn"] = "none"
        base["transitionOut"] = "none"
        return _filter_module_params(module_id, base)

    base.update({"text": copy, "kicker": _kicker_for(beat, mode)})
    return _filter_module_params(module_id, base)


def _attach_semantic_items(cue: dict) -> dict:
    """Ensure every visible module string has a reveal anchor (unanchored ok for sample)."""

    required = _module_semantic_texts(cue)
    if not required:
        cue["semanticItems"] = []
        return cue
    # Prefer unanchored fills generated by VP helper so validation passes.
    auto = _unanchored_semantic_items(cue)
    # Map by parameterPath if helper produced matching set; else build explicitly.
    by_path = {item["parameterPath"]: item for item in auto}
    items = []
    start = float(cue["startSec"])
    end = float(cue["endSec"])
    fully = min(end, start + 0.45)
    for index, (path, text, label) in enumerate(required):
        if path in by_path:
            items.append(by_path[path])
            continue
        items.append(
            {
                "id": f"{cue['id']}-sem-{index + 1}",
                "label": label,
                "text": text,
                "parameterPath": path,
                "phrase": text,
                "anchorType": "unanchored",
                "spokenStartSec": start,
                "fullyVisibleSec": fully,
            }
        )
    cue["semanticItems"] = items
    return cue


def _binding_for_module(module_id: str, fallback_treatment: str) -> dict[str, str]:
    """Best-effort parameter mode for a (possibly remapped) moduleId."""

    for treatment_id, binding in TREATMENT_TO_MODULE.items():
        if binding["moduleId"] == module_id:
            return binding
    # Direct module id used as treatment (kinetic, …).
    mode_by_module = {
        "kinetic-word-punctuation": "kinetic",
        "punchline-reveal": "punchline",
        "numbered-step-intro": "numbered-step",
        "numbered-phrase-reveal": "numbered-phrase",
        "windows-prompt-typing": "prompt",
        "windows-prompt-overlay": "prompt-overlay",
        "source-punch-zoom": "punch-zoom",
        "dependency-stack": "dependency",
        "intro-credentials": "intro",
        "numbered-example-card": "numbered-example",
        "robot-cheer": "robot",
        "robot-defiant": "robot",
        "robot-roast": "robot",
        "robot-rocket-sign": "robot-rocket",
    }
    return {
        "moduleId": module_id,
        "engineId": module_id,
        "mode": mode_by_module.get(module_id, "kinetic"),
        "graphicId": fallback_treatment,
    }


def beat_to_visual_cue(
    beat: dict,
    *,
    index: int = 0,
    default_layout_id: str | None = None,
    recent_module_ids: list[str] | None = None,
) -> dict | None:
    treatment_id = str(beat.get("graphicId") or beat.get("treatmentId") or "")
    binding = resolve_module_binding(treatment_id)
    if binding is None:
        return None
    module_id = binding["moduleId"]
    if module_id not in MODULE_IDS:
        return None

    layout_id = beat.get("layoutId") or default_layout_id
    if layout_id is not None and layout_id not in LAYOUT_IDS:
        raise ValueError(f"Beat {beat.get('id')} has unknown layoutId {layout_id!r}")

    params = _module_parameters(beat, binding, index=index)
    placement = None
    if layout_id:
        preferred_side = params.get("side") if isinstance(params.get("side"), str) else None
        preferred_anchor = params.get("anchor") if isinstance(params.get("anchor"), str) else None
        placement = placement_for_module(
            layout_id=str(layout_id),
            module_id=module_id,
            preferred_side=preferred_side,
            preferred_anchor=preferred_anchor,
            recent_module_ids=recent_module_ids,
        )
        # Layout may remap an unsafe module (e.g. side-panel on full-screen talking).
        if placement.module_id != module_id:
            remapped_binding = _binding_for_module(placement.module_id, treatment_id)
            params = _module_parameters(beat, remapped_binding, index=index)
            module_id = placement.module_id
        if "side" in MODULE_PARAMETER_KEYS.get(module_id, set()):
            params["side"] = placement.side
        if "anchor" in MODULE_PARAMETER_KEYS.get(module_id, set()):
            params["anchor"] = placement.anchor
        safety = speaker_safety_payload(
            placement,
            start_sec=float(beat["startSec"]),
            end_sec=float(beat["endSec"]),
        )
        if safety is not None and "speakerSafety" in MODULE_PARAMETER_KEYS.get(module_id, set()):
            params["speakerSafety"] = safety
        params = _filter_module_params(module_id, params)

    cue = {
        "id": f"cue-{beat['id']}",
        "kind": "module",
        "moduleId": module_id,
        "startSec": float(beat["startSec"]),
        "endSec": float(beat["endSec"]),
        "enabled": True,
        "parameters": params,
    }
    if beat.get("intentionalSeriesId"):
        cue["parameters"] = params  # already set
        # series is editorial metadata; keep in notes for now (not a cue schema field).
    if layout_id:
        cue["notes"] = (
            f"layoutId={layout_id}"
            + (
                f"; remapped from {placement.remapped_from}"
                if placement and placement.remapped_from
                else ""
            )
            + (f"; {placement.reason}" if placement else "")
        )
    return _attach_semantic_items(cue)


def build_visual_cues_from_beats(
    plan: dict,
    *,
    default_layout_id: str | None = None,
) -> dict[str, Any]:
    """Validate editorial plan, then emit VP module cues.

    When beats carry layoutId (or default_layout_id is set), placement uses the
    measured OBS eight-layout speaker geometry so chrome stays in free zones.
    """

    validation = validate_editorial_plan(plan)
    if not validation["ok"]:
        return {
            "ok": False,
            "stage": "validate",
            "validation": validation,
            "cues": [],
            "skipped": [],
            "errors": validation["errors"],
        }

    plan = validation.get("normalizedPlan") or plan

    from app.core.editorial_variety import validate_variety, variety_report

    cues: list[dict] = []
    skipped: list[dict] = []
    placements: list[dict] = []
    recent_modules: list[str] = []
    for index, beat in enumerate(plan.get("beats") or []):
        try:
            cue = beat_to_visual_cue(
                beat,
                index=index,
                default_layout_id=default_layout_id,
                recent_module_ids=recent_modules,
            )
        except ValueError as exc:
            skipped.append(
                {
                    "beatId": beat.get("id"),
                    "graphicId": beat.get("graphicId") or beat.get("treatmentId"),
                    "reason": str(exc),
                }
            )
            continue
        if cue is None:
            skipped.append(
                {
                    "beatId": beat.get("id"),
                    "graphicId": beat.get("graphicId") or beat.get("treatmentId"),
                    "reason": "No Visual Production module binding for this kit treatment.",
                }
            )
            continue
        cues.append(cue)
        recent_modules.append(str(cue["moduleId"]))
        layout_id = beat.get("layoutId") or default_layout_id
        if layout_id:
            placements.append(
                {
                    "beatId": beat.get("id"),
                    "layoutId": layout_id,
                    "moduleId": cue["moduleId"],
                    "side": (cue.get("parameters") or {}).get("side"),
                    "anchor": (cue.get("parameters") or {}).get("anchor"),
                    "notes": cue.get("notes"),
                }
            )

    # Variety gate on *realized* modules (after face-safe remaps).
    variety_items = [
        {
            "moduleId": cue["moduleId"],
            "intentionalSeriesId": next(
                (
                    b.get("intentionalSeriesId")
                    for b in (plan.get("beats") or [])
                    if f"cue-{b.get('id')}" == cue["id"]
                ),
                None,
            ),
        }
        for cue in cues
    ]
    variety_errors = validate_variety(variety_items, id_key="moduleId")
    report = variety_report(variety_items, id_key="moduleId")

    return {
        "ok": not variety_errors,
        "stage": "map",
        "validation": validation,
        "cues": cues,
        "skipped": skipped,
        "placements": placements,
        "variety": report,
        "errors": variety_errors,
        "summary": {
            "totalBeats": len(plan.get("beats") or []),
            "mapped": len(cues),
            "skipped": len(skipped),
            "moduleIds": sorted({cue["moduleId"] for cue in cues}),
            "layoutAware": bool(placements),
            "varietyOk": not variety_errors,
        },
    }


def merge_cues_into_visual_plan(
    visual_plan: dict,
    cues: list[dict],
    *,
    replace_existing: bool = True,
) -> dict:
    """Insert mapped cues into a Visual Production plan document."""

    plan = json_deepcopy(visual_plan)
    if replace_existing:
        plan["cues"] = list(cues)
    else:
        existing_ids = {str(item.get("id")) for item in plan.get("cues") or []}
        merged = list(plan.get("cues") or [])
        for cue in cues:
            if cue["id"] in existing_ids:
                merged = [cue if item.get("id") == cue["id"] else item for item in merged]
            else:
                merged.append(cue)
        plan["cues"] = merged
    plan.setdefault("composition", {})["brandId"] = BRAND_ID
    return plan


def json_deepcopy(value: Any) -> Any:
    import json

    return json.loads(json.dumps(value))


def make_sample_visual_plan(
    *,
    project_name: str,
    source_video_rel: str,
    transcript_rel: str,
    duration_sec: float,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    cues: list[dict],
    video_sha256: str | None = None,
) -> dict:
    """Build a minimal valid visual-plan.json shell with mapped cues."""

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    return {
        "schemaVersion": 2,
        "project": {
            "id": uuid.uuid4().hex,
            "name": project_name,
            "createdAt": now,
            "updatedAt": now,
        },
        "source": {
            "video": source_video_rel,
            "transcript": transcript_rel,
            "videoSha256": video_sha256 or ("0" * 64),
        },
        "composition": {
            "width": width,
            "height": height,
            "fps": fps,
            "durationSec": float(duration_sec),
            "brandId": BRAND_ID,
        },
        "assets": [],
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
