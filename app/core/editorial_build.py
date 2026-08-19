"""Build validated editorial beat plans via production engines.

Pipeline:
  validated plan (usage ids from Graphics Library golden set)
    → usageId (plan field graphicId) → engineId
    → Visual Production engine cue (editorial_visual_plan) or source-led graph
    → namespaced review graph + optional HTML

Seed kit is not used. See docs/vcg-graphics-process/architecture.md.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.creator_adaptation import _validate_fixture_graph
from app.core.editorial_beats import beat_graphic_id, production_graphic_ids, validate_editorial_plan
from app.core.visual_production import MODULE_IDS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Brand tokens for review HTML.
DEFAULT_TOKENS: dict[str, str] = {
    "brand.colors.ink": "#1A1A2E",
    "brand.colors.structure": "#007C7D",
    "brand.colors.paper": "#FBFBFD",
    "brand.colors.accent": "#FF00CE",
}

# Default protected *face* region (normalized). Opaque chrome must not cover this.
DEFAULT_SPEAKER_REGION: dict[str, float] = {
    "x": 0.58,
    "y": 0.10,
    "width": 0.36,
    "height": 0.55,
}

SOURCE_LED_ENGINES = frozenset({"source-punch-zoom"})


@dataclass(frozen=True)
class EngineBinding:
    """Usage → engine resolution for production draw."""

    usage_id: str
    engine_id: str

    @property
    def graphic_id(self) -> str:
        return self.usage_id

    @property
    def treatment_id(self) -> str:
        """Legacy alias — plan field still named treatmentId / graphicId."""

        return self.usage_id

    @property
    def capability_id(self) -> str:
        return f"engine:{self.engine_id}"

    @property
    def parameter_mode(self) -> str:
        return "source-led" if self.engine_id in SOURCE_LED_ENGINES else "engine"


# Deprecated name: production engines are MODULE_IDS, not a seed table.
GRAPHIC_IMPLEMENTATION_BINDINGS: dict[str, EngineBinding] = {
    engine_id: EngineBinding(usage_id=engine_id, engine_id=engine_id) for engine_id in sorted(MODULE_IDS)
}
TREATMENT_BINDINGS = GRAPHIC_IMPLEMENTATION_BINDINGS
SeedBinding = EngineBinding  # legacy alias for imports


def resolve_binding(
    graphic_id: str,
    *,
    golden_root: Path | None = None,
) -> EngineBinding | None:
    """Resolve plan usage id → production engine."""

    usage_id = str(graphic_id or "").strip()
    if not usage_id:
        return None
    from app.core.graphics_library import resolve_engine_id

    engine_id = resolve_engine_id(usage_id, golden_root)
    if not engine_id:
        return None
    return EngineBinding(usage_id=usage_id, engine_id=engine_id)


def buildable_treatment_ids() -> frozenset[str]:
    """Engine ids that can draw (production inventory)."""

    return frozenset(MODULE_IDS)


def buildable_graphic_ids() -> frozenset[str]:
    return buildable_treatment_ids()


def _fps_ratio(fps: dict) -> float:
    return float(fps["numerator"]) / float(fps["denominator"])


def _sec_to_frame(sec: float, fps: dict) -> int:
    return max(0, int(round(float(sec) * _fps_ratio(fps))))


def _parse_numbered_copy(text: str) -> tuple[str, str]:
    """Split '01 — TITLE' or '1. TITLE' into number + remainder."""

    stripped = text.strip()
    match = re.match(
        r"^(?:0*(?P<num>\d{1,2}))\s*(?:[—–\-:.]|\s)\s*(?P<body>.+)$",
        stripped,
    )
    if match:
        return match.group("num"), match.group("body").strip()
    return "1", stripped


def beat_parameters(beat: dict, binding: EngineBinding) -> dict[str, Any]:
    """Build content params for review/tests from beat copy (engine path uses visual_plan)."""

    copy = beat.get("onScreenCopy")
    text = "" if copy is None else str(copy).strip()
    engine_id = binding.engine_id
    if engine_id in SOURCE_LED_ENGINES:
        return {"motionKind": beat.get("motionKind") or "reframe"}
    if "numbered" in engine_id or engine_id == "numbered-example-card":
        number, body = _parse_numbered_copy(text or "STEP")
        return {"number": number, "text": body.upper() if body else "STEP"}
    if "list" in engine_id:
        rows = beat.get("listRows") or []
        lines = [str(row.get("text") or "").strip() for row in rows]
        lines = [line for line in lines if line]
        return {"title": text or "", "lines": lines or [text or "POINT"]}
    if engine_id == "ui-callout":
        return {
            "label": text or "Callout",
            "region": beat.get("uiRegion")
            or {"x": 0.12, "y": 0.2, "width": 0.38, "height": 0.2},
        }
    if "prompt" in engine_id or engine_id in {"windows-prompt-typing", "windows-prompt-overlay"}:
        return {"text": text or "prompt"}
    return {"text": text or "Emphasis"}


def beat_timing_context(beat: dict, fps: dict) -> dict[str, Any]:
    start = _sec_to_frame(beat["startSec"], fps)
    end = max(start + 1, _sec_to_frame(beat["endSec"], fps))
    words = [
        {
            "id": f"{beat['id']}-w0",
            "text": str(beat.get("onScreenCopy") or beat["id"]),
            "startFrame": start,
            "endFrame": end - 1,
        }
    ]
    return {"words": words, "startFrame": start, "endFrameExclusive": end}


def list_reveal_frames(beat: dict, fps: dict) -> list[int]:
    frames: list[int] = []
    for row in beat.get("listRows") or []:
        frames.append(_sec_to_frame(row["startSec"], fps))
    return frames


def _engine_review_graph(beat: dict, binding: EngineBinding, fps: dict) -> dict[str, Any]:
    """Lightweight review graph from engine content (not a parallel draw stack)."""

    params = beat_parameters(beat, binding)
    text = (
        params.get("text")
        or params.get("label")
        or params.get("phrase")
        or params.get("title")
        or " ".join(str(item) for item in (params.get("lines") or [])[:3])
        or beat.get("onScreenCopy")
        or binding.engine_id
    )
    start = _sec_to_frame(beat["startSec"], fps)
    end = max(start + 1, _sec_to_frame(beat["endSec"], fps))
    duration = max(1, end - start)
    return {
        "elements": [
            {
                "id": "chrome",
                "kind": "text",
                "geometry": {"x": 0.06, "y": 0.28, "width": 0.44, "height": 0.32},
                "properties": {
                    "text": str(text),
                    "layer": 5,
                    "engineId": binding.engine_id,
                    "usageId": binding.usage_id,
                },
            }
        ],
        "events": [
            {
                "id": "enter",
                "operation": "fade",
                "targetElementId": "chrome",
                "atFrame": start,
                "durationFrames": min(8, duration),
                "parameters": {"from": {"opacity": 0}, "to": {"opacity": 1}},
            },
            {
                "id": "exit",
                "operation": "fade",
                "targetElementId": "chrome",
                "atFrame": max(start, end - 6),
                "durationFrames": min(6, duration),
                "parameters": {"to": {"opacity": 0}},
            },
        ],
    }


def build_source_led_graph(beat: dict, fps: dict) -> dict:
    """Synthetic source-primary motion: reframe or punch-zoom, never a long freeze."""

    timing = beat_timing_context(beat, fps)
    start = int(timing["startFrame"])
    end = int(timing["endFrameExclusive"])
    motion = str(beat.get("motionKind") or "reframe")
    # Full-frame speaker source; motion is scale/emphasis only (no layout drift).
    elements = [
        {
            "id": "speaker-source",
            "kind": "speaker-source",
            "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "properties": {"role": "source-primary"},
        }
    ]
    if motion == "punch-zoom":
        events = [
            {
                "id": "punch-in",
                "targetElementId": "speaker-source",
                "operation": "scale",
                "absoluteFrame": start,
                "durationFrames": min(10, max(4, end - start - 4)),
                "easing": "power2.out",
                "parameters": {
                    "from": {"scale": 1.0, "opacity": 1},
                    "to": {"scale": 1.08, "opacity": 1},
                    "resolvedGeometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                },
            },
            {
                "id": "punch-settle",
                "targetElementId": "speaker-source",
                "operation": "scale",
                "absoluteFrame": max(start + 8, end - 8),
                "durationFrames": 8,
                "easing": "power1.inOut",
                "parameters": {
                    "from": {"scale": 1.08},
                    "to": {"scale": 1.0},
                    "resolvedGeometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                },
            },
        ]
    else:
        # Light emphasize / reframe pulse so cadence is not a freeze.
        events = [
            {
                "id": "reframe-pulse",
                "targetElementId": "speaker-source",
                "operation": "emphasize",
                "absoluteFrame": start,
                "durationFrames": min(12, max(6, end - start - 2)),
                "easing": "power1.inOut",
                "parameters": {
                    "from": {"opacity": 1, "scale": 1.0},
                    "to": {"opacity": 1, "scale": 1.03},
                    "resolvedGeometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                },
            }
        ]
    graph = {"elements": elements, "events": events}
    _validate_fixture_graph(graph)
    return graph


def namespace_graph(graph: dict, beat_id: str) -> dict:
    """Prefix element/event IDs so multi-beat graphs merge cleanly."""

    prefix = re.sub(r"[^A-Za-z0-9._:-]+", "-", beat_id).strip("-") or "beat"
    id_map: dict[str, str] = {}
    elements = []
    for element in graph.get("elements") or []:
        old = str(element["id"])
        new = f"{prefix}__{old}"
        id_map[old] = new
        cloned = json.loads(json.dumps(element))
        cloned["id"] = new
        if cloned.get("parentId") in id_map:
            cloned["parentId"] = id_map[cloned["parentId"]]
        props = cloned.setdefault("properties", {})
        props["sourceBeatId"] = beat_id
        elements.append(cloned)
    events = []
    for index, event in enumerate(graph.get("events") or []):
        cloned = json.loads(json.dumps(event))
        old_target = str(cloned.get("targetElementId") or "")
        if old_target not in id_map:
            raise ValueError(
                f"Event target {old_target!r} missing after namespace for beat {beat_id}"
            )
        cloned["targetElementId"] = id_map[old_target]
        old_event_id = str(cloned.get("id") or f"event-{index}")
        cloned["id"] = f"{prefix}__{old_event_id}"
        cloned["sourceBeatId"] = beat_id
        events.append(cloned)
    return {"elements": elements, "events": events}


def _rects_overlap(a: dict[str, float], b: dict[str, float], *, pad: float = 0.0) -> bool:
    return not (
        a["x"] + a["width"] + pad <= b["x"]
        or b["x"] + b["width"] + pad <= a["x"]
        or a["y"] + a["height"] + pad <= b["y"]
        or b["y"] + b["height"] + pad <= a["y"]
    )


def geometry_safety_errors(
    graph: dict,
    *,
    speaker_region: dict[str, float] | None,
    beat_id: str,
    face_safe: bool = True,
) -> list[dict]:
    """Reject opaque panels that sit on the protected speaker region."""

    if not face_safe or speaker_region is None:
        return []
    errors: list[dict] = []
    for element in graph.get("elements") or []:
        kind = str(element.get("kind") or "")
        if kind in {"speaker-source", "shape"}:
            # Source and stroke callouts may touch speaker; opaque panels may not.
            continue
        role = str((element.get("properties") or {}).get("role") or "")
        if kind not in {"panel", "text"} and "panel" not in role:
            # Light text/emphasis may edge near speaker; flag only solid panels.
            if kind != "panel":
                continue
        if kind != "panel" and role not in {
            "numbered-step",
            "prompt-card",
            "bullet-list-panel",
            "stat-hit",
        }:
            continue
        geometry = element.get("geometry") or {}
        try:
            rect = {
                "x": float(geometry["x"]),
                "y": float(geometry["y"]),
                "width": float(geometry["width"]),
                "height": float(geometry["height"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if _rects_overlap(rect, speaker_region, pad=-0.01):
            errors.append(
                {
                    "code": "face-unsafe-geometry",
                    "beatId": beat_id,
                    "elementId": element.get("id"),
                    "message": (
                        f"Element {element.get('id')} intersects protected speaker region. "
                        "Switch graphic or layout; face-primary motion is a graphic choice, not a beat type."
                    ),
                }
            )
    return errors


def materialize_beat(
    beat: dict,
    fps: dict,
    *,
    speaker_region: dict[str, float] | None = None,
    production_ids: frozenset[str] | None = None,
    golden_root: Path | None = None,
) -> dict[str, Any]:
    """Build one beat via production engine (usage → engineId)."""

    usage_id = beat_graphic_id(beat)
    if production_ids is not None and usage_id and usage_id not in production_ids:
        return {
            "beatId": beat["id"],
            "graphicId": usage_id,
            "usageId": usage_id,
            "status": "not-buildable",
            "reason": (
                f"usage id {usage_id!r} is not in the Graphics Library golden set."
            ),
            "graph": None,
            "errors": [],
        }
    binding = resolve_binding(usage_id, golden_root=golden_root)
    if binding is None:
        return {
            "beatId": beat["id"],
            "graphicId": usage_id,
            "usageId": usage_id,
            "status": "not-buildable",
            "reason": (
                f"No engine for usage id {usage_id!r}. "
                "Usage must reference a real engineId in the Graphics Library."
            ),
            "graph": None,
            "errors": [],
        }

    cue: dict[str, Any] | None = None
    try:
        if binding.engine_id in SOURCE_LED_ENGINES:
            raw = build_source_led_graph(beat, fps)
        else:
            from app.core.editorial_visual_plan import beat_to_visual_cue

            # Resolve cue using engine id as graphicId for engine parameter mapping.
            cue_beat = {**beat, "graphicId": binding.engine_id}
            cue = beat_to_visual_cue(cue_beat, index=0)
            raw = _engine_review_graph(beat, binding, fps)
        graph = namespace_graph(raw, str(beat["id"]))
    except Exception as exc:  # noqa: BLE001 — surface as beat-level build error
        return {
            "beatId": beat["id"],
            "graphicId": usage_id,
            "usageId": usage_id,
            "engineId": binding.engine_id,
            "status": "failed",
            "reason": str(exc),
            "capabilityId": binding.capability_id,
            "graph": None,
            "errors": [{"code": "materialize-failed", "message": str(exc)}],
        }

    face_safe = bool(beat.get("faceSafe", True))
    geo_errors = geometry_safety_errors(
        graph,
        speaker_region=speaker_region,
        beat_id=str(beat["id"]),
        face_safe=face_safe,
    )
    if geo_errors:
        return {
            "beatId": beat["id"],
            "graphicId": usage_id,
            "usageId": usage_id,
            "engineId": binding.engine_id,
            "status": "failed",
            "reason": "Geometry safety failed.",
            "capabilityId": binding.capability_id,
            "graph": graph,
            "cue": cue,
            "errors": geo_errors,
        }

    return {
        "beatId": beat["id"],
        "graphicId": usage_id,
        "usageId": usage_id,
        "engineId": binding.engine_id,
        "status": "built",
        "capabilityId": binding.capability_id,
        "parameterMode": binding.parameter_mode,
        "startFrame": _sec_to_frame(beat["startSec"], fps),
        "endFrameExclusive": _sec_to_frame(beat["endSec"], fps),
        "graph": graph,
        "cue": cue,
        "errors": [],
    }


def build_editorial_composition(
    plan: dict,
    *,
    transcript_document: dict | None = None,
    speaker_region: dict[str, float] | None = None,
    require_all_buildable: bool = False,
) -> dict[str, Any]:
    """Validate then materialize every beat. Returns composition + report."""

    validation = validate_editorial_plan(plan, transcript_document=transcript_document)
    if not validation["ok"]:
        return {
            "ok": False,
            "stage": "validate",
            "validation": validation,
            "beats": [],
            "composition": None,
            "errorCount": validation["errorCount"],
            "errors": validation["errors"],
        }

    plan = validation.get("normalizedPlan") or plan
    fps = plan["fps"]
    region = speaker_region if speaker_region is not None else DEFAULT_SPEAKER_REGION
    production_ids, _production_snap = production_graphic_ids()
    beat_results = [
        materialize_beat(
            beat,
            fps,
            speaker_region=region,
            production_ids=production_ids,
        )
        for beat in plan["beats"]
    ]

    errors: list[dict] = []
    for result in beat_results:
        if result["status"] == "failed":
            errors.extend(
                {
                    **error,
                    "beatId": result["beatId"],
                    "graphicId": result.get("graphicId"),
                }
                for error in (result.get("errors") or [{"code": "failed", "message": result.get("reason")}])
            )
        elif result["status"] == "not-buildable" and require_all_buildable:
            errors.append(
                {
                    "code": "not-buildable",
                    "beatId": result["beatId"],
                    "graphicId": result.get("graphicId"),
                    "message": result.get("reason"),
                }
            )

    elements: list[dict] = []
    events: list[dict] = []
    # One base source layer for the full runtime (not duplicated per beat).
    elements.append(
        {
            "id": "locked-source",
            "kind": "speaker-source",
            "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "properties": {"role": "locked-cut", "layer": 0},
        }
    )
    for result in beat_results:
        graph = result.get("graph")
        if not graph:
            continue
        for element in graph["elements"]:
            # Drop per-beat full-frame speaker sources; keep treatment chrome only.
            if (
                element.get("kind") == "speaker-source"
                and float((element.get("geometry") or {}).get("width") or 0) >= 0.99
                and float((element.get("geometry") or {}).get("height") or 0) >= 0.99
            ):
                # Keep source-led motion events by rebinding to locked-source.
                continue
            elements.append(element)
        for event in graph["events"]:
            target = event.get("targetElementId") or ""
            # If target was a dropped full-frame speaker, retarget to locked-source.
            raw_target_suffix = target.split("__", 1)[-1]
            if raw_target_suffix == "speaker-source" and not any(
                item["id"] == target for item in elements
            ):
                cloned = json.loads(json.dumps(event))
                cloned["targetElementId"] = "locked-source"
                events.append(cloned)
            else:
                events.append(event)

    composition = {
        "schemaVersion": 1,
        "kind": "editorial-composition",
        "episodeId": plan.get("episodeId"),
        "mode": plan.get("mode"),
        "fps": fps,
        "totalDurationSec": plan["totalDurationSec"],
        "totalFrames": _sec_to_frame(plan["totalDurationSec"], fps),
        "source": plan.get("source"),
        "elements": elements,
        "events": events,
        "beats": [
            {
                "beatId": item["beatId"],
                "graphicId": item.get("graphicId"),
                "usageId": item.get("usageId"),
                "engineId": item.get("engineId"),
                "status": item["status"],
                "capabilityId": item.get("capabilityId"),
                "startFrame": item.get("startFrame"),
                "endFrameExclusive": item.get("endFrameExclusive"),
            }
            for item in beat_results
        ],
    }

    built = sum(1 for item in beat_results if item["status"] == "built")
    not_buildable = sum(1 for item in beat_results if item["status"] == "not-buildable")
    failed = sum(1 for item in beat_results if item["status"] == "failed")

    return {
        "ok": not errors and failed == 0,
        "stage": "build",
        "validation": validation,
        "summary": {
            "totalBeats": len(beat_results),
            "built": built,
            "notBuildable": not_buildable,
            "failed": failed,
            "buildableTreatmentIds": sorted(buildable_treatment_ids()),
        },
        "beats": beat_results,
        "composition": composition,
        "errorCount": len(errors),
        "errors": errors,
    }


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pct(value: float) -> str:
    return f"{float(value) * 100:.3f}%"


def composition_to_html(
    composition: dict,
    *,
    video_name: str = "locked-cut.mp4",
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Materialize a HyperFrames-style HTML review composition from graph geometry.

    Uses real seed geometries (normalized 0–1), VCG brand tokens, and GSAP
    enter/exit from event absolute frames — not throwaway white-card shells.
    """

    fps = composition["fps"]
    fps_ratio = _fps_ratio(fps)
    duration_sec = float(composition["totalDurationSec"])
    ink = DEFAULT_TOKENS["brand.colors.ink"]
    structure = DEFAULT_TOKENS["brand.colors.structure"]
    paper = DEFAULT_TOKENS["brand.colors.paper"]
    accent = DEFAULT_TOKENS["brand.colors.accent"]

    elements = composition.get("elements") or []
    events = composition.get("events") or []
    by_id = {str(item["id"]): item for item in elements}

    cards: list[str] = []
    for element in elements:
        eid = str(element["id"])
        kind = str(element.get("kind") or "")
        if kind == "speaker-source" or eid == "locked-source":
            continue
        geometry = element.get("geometry") or {}
        props = element.get("properties") or {}
        role = str(props.get("role") or kind)
        text = str(props.get("text") or "")
        fill = str(props.get("fill") or paper)
        color = str(props.get("color") or ink)
        accent_color = str(props.get("accentColor") or structure)
        mono = bool(props.get("mono"))
        left = _pct(float(geometry.get("x", 0)))
        top = _pct(float(geometry.get("y", 0)))
        w = _pct(float(geometry.get("width", 0.2)))
        h = _pct(float(geometry.get("height", 0.1)))
        font_size = max(18, int(float(geometry.get("height", 0.1)) * height * 0.42))
        font_family = (
            "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
            if mono
            else "Arial Black, Arial, sans-serif"
        )
        if kind == "panel":
            cards.append(
                f'<div class="el panel" id="{_escape_html(eid)}" data-role="{_escape_html(role)}" '
                f'style="left:{left};top:{top};width:{w};height:{h};'
                f'background:{fill};border-left:8px solid {accent_color};"></div>'
            )
        elif kind == "shape":
            cards.append(
                f'<div class="el shape" id="{_escape_html(eid)}" data-role="{_escape_html(role)}" '
                f'style="left:{left};top:{top};width:{w};height:{h};'
                f'border:3px solid {accent_color};"></div>'
            )
        else:
            # text and other labels
            cards.append(
                f'<div class="el text" id="{_escape_html(eid)}" data-role="{_escape_html(role)}" '
                f'style="left:{left};top:{top};width:{w};height:{h};color:{color};'
                f'font-size:{font_size}px;font-family:{font_family};">'
                f"{_escape_html(text)}</div>"
            )

    # Event payload for GSAP: only events targeting visible chrome.
    # Seed builds often animate only the panel; companion text must still appear.
    timeline_events: list[dict] = []
    targeted_ids: set[str] = set()
    beat_enter: dict[str, dict] = {}
    beat_exit: dict[str, dict] = {}

    def _append_event(event: dict, target_id: str) -> None:
        timeline_events.append(
            {
                "id": event.get("id"),
                "targetId": target_id,
                "operation": event.get("operation"),
                "start": float(event.get("absoluteFrame", 0)) / fps_ratio,
                "duration": max(
                    0.05, float(event.get("durationFrames", 8)) / fps_ratio
                ),
                "easing": event.get("easing") or "power2.out",
                "from": (event.get("parameters") or {}).get("from") or {},
                "to": (event.get("parameters") or {}).get("to") or {},
                "text": (event.get("parameters") or {}).get("text"),
            }
        )

    for event in events:
        target = str(event.get("targetElementId") or "")
        op = str(event.get("operation") or "")
        if target == "locked-source":
            _append_event(event, "source")
            continue
        if target not in by_id:
            continue
        if by_id[target].get("kind") == "speaker-source":
            continue
        targeted_ids.add(target)
        _append_event(event, target)
        beat_id = str(
            event.get("sourceBeatId")
            or (by_id[target].get("properties") or {}).get("sourceBeatId")
            or ""
        )
        if beat_id and op in {"enter", "reveal", "show", "emphasize"}:
            prev = beat_enter.get(beat_id)
            if prev is None or int(event.get("absoluteFrame", 0)) < int(
                prev.get("absoluteFrame", 0)
            ):
                beat_enter[beat_id] = event
        if beat_id and op in {"exit", "hide"}:
            prev = beat_exit.get(beat_id)
            if prev is None or int(event.get("absoluteFrame", 0)) > int(
                prev.get("absoluteFrame", 0)
            ):
                beat_exit[beat_id] = event

    # Ride panel enter/exit for untargeted text/shape chrome in the same beat.
    for element in elements:
        eid = str(element["id"])
        kind = str(element.get("kind") or "")
        if kind == "speaker-source" or eid == "locked-source" or eid in targeted_ids:
            continue
        beat_id = str((element.get("properties") or {}).get("sourceBeatId") or "")
        if not beat_id:
            continue
        enter = beat_enter.get(beat_id)
        if enter:
            companion = json.loads(json.dumps(enter))
            companion["id"] = f"{eid}__companion-enter"
            companion["targetElementId"] = eid
            companion["operation"] = "enter"
            companion["parameters"] = {
                "from": {"opacity": 0},
                "to": {"opacity": 1},
            }
            _append_event(companion, eid)
        exit_event = beat_exit.get(beat_id)
        if exit_event:
            companion = json.loads(json.dumps(exit_event))
            companion["id"] = f"{eid}__companion-exit"
            companion["targetElementId"] = eid
            companion["operation"] = "exit"
            companion["parameters"] = {"to": {"opacity": 0}}
            _append_event(companion, eid)

    event_json = json.dumps(timeline_events, ensure_ascii=False)
    cards_html = "\n    ".join(cards)
    beat_badges = []
    for item in composition.get("beats") or []:
        if item.get("status") != "built":
            continue
        beat_badges.append(
            f'{item.get("graphicId")}@{item.get("startFrame")}-{item.get("endFrameExclusive")}'
        )
    badge_note = " · ".join(beat_badges[:6])
    if len(beat_badges) > 6:
        badge_note += f" · +{len(beat_badges) - 6} more"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width={width}, height={height}" />
  <title>VCG editorial composition</title>
  <style>
    html, body {{
      margin: 0;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      background: #0b0b12;
    }}
    #root {{
      position: relative;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
    }}
    #source {{
      position: absolute;
      inset: 0;
      width: {width}px;
      height: {height}px;
      object-fit: cover;
      background: #000;
      z-index: 1;
    }}
    .el {{
      position: absolute;
      z-index: 5;
      box-sizing: border-box;
      opacity: 0;
      pointer-events: none;
    }}
    .panel {{
      border-radius: 18px;
      box-shadow: 0 18px 50px rgba(26,26,46,.22);
    }}
    .text {{
      display: flex;
      align-items: center;
      font-weight: 800;
      letter-spacing: -0.03em;
      line-height: 1.08;
      text-transform: uppercase;
      z-index: 6;
    }}
    .shape {{
      border-radius: 10px;
      background: transparent;
      z-index: 4;
    }}
    .badge {{
      position: absolute;
      left: 24px;
      top: 20px;
      z-index: 20;
      max-width: 70%;
      background: {structure};
      color: #fff;
      font: 700 13px/1.3 Arial, sans-serif;
      letter-spacing: .08em;
      text-transform: uppercase;
      padding: 10px 14px;
      border-radius: 999px;
      opacity: 0.92;
    }}
  </style>
</head>
<body>
  <div
    id="root"
    class="clip"
    data-composition-id="editorial-composition"
    data-start="0"
    data-duration="{duration_sec:.3f}"
    data-fps="{fps_ratio:.6f}"
    data-width="{width}"
    data-height="{height}"
    data-track="0"
  >
    <div class="badge">KIT BUILD · {width}x{height} · {_escape_html(badge_note or "no beats")}</div>
    <video
      id="source"
      class="clip"
      data-start="0"
      data-duration="{duration_sec:.3f}"
      data-track="1"
      src="{_escape_html(video_name)}"
      muted
      playsinline
    ></video>
    {cards_html}
  </div>
  <script src="./vendor/gsap.min.js"></script>
  <script>
    window.__timelines = window.__timelines || {{}};
    const events = {event_json};
    const tl = gsap.timeline({{ paused: true }});
    for (const event of events) {{
      const el = document.getElementById(event.targetId);
      if (!el) continue;
      const op = event.operation || "enter";
      const from = Object.assign({{ opacity: 0 }}, event.from || {{}});
      const to = Object.assign({{ opacity: 1 }}, event.to || {{}});
      // Map normalized y deltas used by seeds onto pixel-ish transforms when present.
      if (typeof from.y === "number" && from.y <= 1) {{
        from.y = (from.y - (to.y || from.y)) * {height};
      }}
      if (typeof to.y === "number" && to.y <= 1 && typeof event.from?.y === "number") {{
        to.y = 0;
      }}
      if (typeof from.x === "number" && from.x <= 1) {{
        from.x = (from.x - (to.x || from.x)) * {width};
      }}
      if (typeof to.x === "number" && to.x <= 1 && typeof event.from?.x === "number") {{
        to.x = 0;
      }}
      if (op === "exit" || op === "hide") {{
        tl.to(el, {{
          opacity: 0,
          duration: event.duration,
          ease: event.easing || "power1.in",
          ...(event.to || {{}}),
        }}, event.start);
      }} else if (op === "type-reveal" && event.text) {{
        el.textContent = "";
        tl.set(el, {{ opacity: 1 }}, event.start);
        const full = String(event.text);
        tl.to(el, {{
          duration: event.duration,
          ease: "none",
          onUpdate: function() {{
            const n = Math.floor(full.length * this.progress());
            el.textContent = full.slice(0, n);
          }},
        }}, event.start);
      }} else if (op === "scale" || op === "emphasize" || op === "move") {{
        tl.fromTo(el, from, {{
          ...to,
          duration: event.duration,
          ease: event.easing || "power2.out",
        }}, event.start);
      }} else {{
        tl.fromTo(el, from, {{
          ...to,
          duration: event.duration,
          ease: event.easing || "power2.out",
        }}, event.start);
      }}
    }}
    window.__timelines["editorial-composition"] = tl;
  </script>
</body>
</html>
"""


def write_composition_artifacts(
    result: dict,
    out_dir: Path,
    *,
    write_html: bool = True,
    video_name: str = "locked-cut.mp4",
    width: int = 1920,
    height: int = 1080,
) -> dict[str, str]:
    """Write composition.json (+ optional index.html) under out_dir."""

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    report_path = out_dir / "build-report.json"
    report = {
        "ok": result["ok"],
        "stage": result["stage"],
        "summary": result.get("summary"),
        "errorCount": result.get("errorCount"),
        "errors": result.get("errors"),
        "beats": [
            {
                key: item.get(key)
                for key in (
                    "beatId",
                    "graphicId",
                    "usageId",
                    "engineId",
                    "status",
                    "capabilityId",
                    "reason",
                    "startFrame",
                    "endFrameExclusive",
                    "errors",
                )
            }
            for item in (result.get("beats") or [])
        ],
        "validation": result.get("validation"),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["report"] = str(report_path)

    composition = result.get("composition")
    if composition:
        comp_path = out_dir / "composition.json"
        comp_path.write_text(
            json.dumps(composition, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        paths["composition"] = str(comp_path)
        if write_html:
            html_path = out_dir / "index.html"
            html_path.write_text(
                composition_to_html(
                    composition,
                    video_name=video_name,
                    width=width,
                    height=height,
                ),
                encoding="utf-8",
            )
            paths["html"] = str(html_path)
    return paths
