"""Editorial beat plans for daily VCG production.

Closed beat types: docs/vcg-graphics-process/beat-universe.md (schemaVersion 2).
Process home: docs/vcg-graphics-process/README.md
Graphic membership: Graphics Library production set (usages with status golden).

Plan field is graphicId (Golden Record entry id). treatmentId is a deprecated read alias.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.core.editorial_variety import validate_variety


SCHEMA_VERSION = 2
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "visual-production"
    / "schemas"
    / "editorial-beats.v1.schema.json"
)

# Approved closed universe — keep in lockstep with schema + docs/vcg-graphics-process/beat-universe.md
BEAT_TYPES: frozenset[str] = frozenset(
    {
        "hook",
        "setup",
        "punchline",
        "aftershock",
        "callback",
        "proof",
        "context",
        "cta",
        "example",
        "prompt",
        "list",
        "structure",
        "ui",
    }
)

# Superseded v1 labels (rejected by schema). Kept for diagnostics/docs only.
SUPERSEDED_BEAT_TYPES: frozenset[str] = frozenset(
    {
        "source-led-motion",
        "section-label",
        "example-card",
        "prompt-card",
        "list-reveal",
        "ui-callout",
    }
)

# Hard maximum stillness (seconds). Target energy is nearer ~2s when content allows.
MAX_MOTION_GAP_SEC = 5.0

# LEGACY inventory snapshot only — NOT production selection authority.
# Do not use for kit membership. Prefer production_graphic_ids() / GR.
# Retained so old docs/scripts can list historically known ids during cleanup.
DAILY_TREATMENT_KIT: frozenset[str] = frozenset(
    {
        "source-punch-zoom",
        "punchline-reveal",
        "kinetic-word-punctuation",
        "numbered-example-card",
        "numbered-step-intro",
        "numbered-phrase-reveal",
        "windows-prompt-typing",
        "windows-prompt-overlay",
        "ui-callout",
        "dependency-stack",
        "intro-credentials",
        "progress-scale",
        "tradeoff-meter",
        "brand-cta-lockup",
        "speaker-rise-callouts",
        "problem-card-triptych",
        "robot-cheer",
        "robot-defiant",
        "robot-roast",
        "robot-rocket-sign",
    }
)


def production_graphic_ids(root: Path | None = None) -> tuple[frozenset[str], dict[str, Any]]:
    """Return (ids, production-set snapshot) from the Golden Record.

    Empty ids means cook must not invent graphics — promote in Graphics Library.
    """

    from app.core.graphics_library import get_production_graphics

    snap = get_production_graphics(root, policy="golden-only")
    return frozenset(str(item) for item in snap.get("ids") or []), snap


def beat_graphic_id(beat: dict) -> str:
    """Canonical graphic id on a beat (graphicId, with deprecated treatmentId fallback)."""

    return str(beat.get("graphicId") or beat.get("treatmentId") or "").strip()

FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "then",
        "this",
        "to",
        "too",
        "up",
        "we",
        "with",
        "you",
        "your",
    }
)

# Motion kinds that may omit on-screen copy (face/UI carries the line).
# This is motion presentation — not a beat type. Never use a "source-led" beatType.
COPY_OPTIONAL_MOTION: frozenset[str] = frozenset(
    {
        "reframe",
        "punch-zoom",
        "ui-highlight",
        "supporting-cutin",
        "treatment-exit",
    }
)

# Back-compat alias for any external imports.
SOURCE_PRIMARY_MOTION = COPY_OPTIONAL_MOTION


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def normalize_plan(plan: dict) -> dict:
    """Return a shallow-copied plan with deprecated aliases filled in.

    - treatmentId → graphicId when graphicId is missing
    Does not invent beat types or rewrite copy.
    """

    out = dict(plan)
    beats_out: list[dict] = []
    for beat in plan.get("beats") or []:
        item = dict(beat)
        if not str(item.get("graphicId") or "").strip():
            legacy = str(item.get("treatmentId") or "").strip()
            if legacy:
                item["graphicId"] = legacy
        beats_out.append(item)
    out["beats"] = beats_out
    return out


def validate_schema(plan: dict) -> list[dict]:
    errors = sorted(
        Draft202012Validator(load_schema()).iter_errors(plan),
        key=lambda error: list(error.path),
    )
    return [
        {
            "code": "schema",
            "path": "/" + "/".join(str(part) for part in error.path),
            "message": error.message,
        }
        for error in errors
    ]


def _normalize_token(token: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", token.lower())


def copy_is_function_word_only(text: str | None) -> bool:
    if text is None:
        return False
    tokens = [_normalize_token(part) for part in text.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return True
    return all(token in FUNCTION_WORDS for token in tokens)


def copy_lacks_substance(text: str | None) -> bool:
    """Reject empty or function-only copy when copy is required."""

    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    if copy_is_function_word_only(stripped):
        return True
    # Single short token that isn't a number/name-like signal.
    tokens = [t for t in re.split(r"\s+", stripped) if t]
    if len(tokens) == 1 and len(_normalize_token(tokens[0])) <= 3:
        if not re.fullmatch(r"\d+[\w%]*", tokens[0]):
            return True
    return False


def _beat_requires_copy(beat: dict) -> bool:
    """Copy is required unless motionKind is an intentional no-card motion.

    Beat type is always a real universe type (hook, punchline, …). Omitting
    copy is a presentation choice via motionKind — never a fake beat type.
    """

    if beat.get("motionKind") in COPY_OPTIONAL_MOTION and beat.get("onScreenCopy") is None:
        return False
    return True


def _motion_events(plan: dict) -> list[float]:
    """Collect times (seconds) at which a meaningful visual change begins."""

    events: list[float] = []
    for beat in plan.get("beats") or []:
        start = float(beat["startSec"])
        events.append(start)
        for row in beat.get("listRows") or []:
            events.append(float(row["startSec"]))
    return sorted(set(events))


def validate_structure(
    plan: dict,
    *,
    production_ids: frozenset[str] | None = None,
    production_snap: dict[str, Any] | None = None,
) -> list[dict]:
    errors: list[dict] = []
    if plan.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(
            {
                "code": "schema-version",
                "path": "/schemaVersion",
                "message": f"schemaVersion must be {SCHEMA_VERSION}.",
            }
        )
        return errors

    if production_ids is None:
        production_ids, production_snap = production_graphic_ids()
    production_snap = production_snap or {}

    if not production_ids:
        errors.append(
            {
                "code": "empty-production-set",
                "path": "/",
                "message": production_snap.get("message")
                or (
                    "No production graphics available. Promote graphics to golden in "
                    "Graphics Library before planning beats."
                ),
            }
        )

    beats = plan.get("beats") or []
    ids: set[str] = set()
    total = float(plan["totalDurationSec"])

    for index, beat in enumerate(beats):
        path = f"/beats/{index}"
        beat_id = str(beat.get("id") or "")
        if beat_id in ids:
            errors.append(
                {
                    "code": "duplicate-beat-id",
                    "path": f"{path}/id",
                    "message": f"Duplicate beat id: {beat_id}",
                }
            )
        ids.add(beat_id)

        start = float(beat["startSec"])
        end = float(beat["endSec"])
        if end <= start:
            errors.append(
                {
                    "code": "beat-time-order",
                    "path": f"{path}/endSec",
                    "message": "endSec must be greater than startSec.",
                }
            )
        if start >= total:
            errors.append(
                {
                    "code": "beat-outside-runtime",
                    "path": f"{path}/startSec",
                    "message": "startSec is outside totalDurationSec.",
                }
            )
        if end > total + 1e-6:
            errors.append(
                {
                    "code": "beat-outside-runtime",
                    "path": f"{path}/endSec",
                    "message": "endSec exceeds totalDurationSec.",
                }
            )

        graphic_id = beat_graphic_id(beat)
        if graphic_id and graphic_id not in production_ids:
            errors.append(
                {
                    "code": "unknown-graphic",
                    "path": f"{path}/graphicId",
                    "message": (
                        f"usage id {graphic_id!r} is not in the Graphics Library golden set. "
                        "Promote the usage, or pick a golden usage."
                    ),
                }
            )

        if _beat_requires_copy(beat) and copy_lacks_substance(beat.get("onScreenCopy")):
            errors.append(
                {
                    "code": "weak-copy",
                    "path": f"{path}/onScreenCopy",
                    "message": (
                        "onScreenCopy must be editorial (joke, promise, step, command, "
                        "number, name). Function words and empty labels are invalid."
                    ),
                }
            )

        if beat.get("beatType") == "list":
            rows = beat.get("listRows") or []
            if len(rows) < 2:
                errors.append(
                    {
                        "code": "list-rows",
                        "path": f"{path}/listRows",
                        "message": "list beats need at least two listRows.",
                    }
                )
            for row_index, row in enumerate(rows):
                if copy_lacks_substance(row.get("text")):
                    errors.append(
                        {
                            "code": "weak-copy",
                            "path": f"{path}/listRows/{row_index}/text",
                            "message": "list row text is too weak / function-word-only.",
                        }
                    )
                row_start = float(row["startSec"])
                if row_start < start - 1e-6 or row_start >= end:
                    errors.append(
                        {
                            "code": "list-row-time",
                            "path": f"{path}/listRows/{row_index}/startSec",
                            "message": "list row startSec must fall inside the beat range.",
                        }
                    )

    # Ordered by start for cadence.
    ordered = sorted(beats, key=lambda item: float(item["startSec"]))
    for left, right in zip(ordered, ordered[1:]):
        if float(right["startSec"]) + 1e-9 < float(left["startSec"]):
            continue
        # Overlaps are allowed only if intentional multi-layer; warn as error for v1 simplicity? allow.
        pass

    events = _motion_events(plan)
    if not events:
        errors.append(
            {
                "code": "no-motion-events",
                "path": "/beats",
                "message": "Plan has no motion events.",
            }
        )
        return errors

    # Cadence from 0 through totalDurationSec using event starts + list rows.
    checkpoints = [0.0, *events, total]
    for left, right in zip(checkpoints, checkpoints[1:]):
        gap = right - left
        if gap > MAX_MOTION_GAP_SEC + 1e-6:
            errors.append(
                {
                    "code": "motion-gap",
                    "path": "/beats",
                    "absoluteStartSec": left,
                    "absoluteEndSec": right,
                    "maximumGapSec": MAX_MOTION_GAP_SEC,
                    "message": (
                        f"No meaningful visual change between {left:.2f}s and {right:.2f}s "
                        f"(gap {gap:.2f}s > {MAX_MOTION_GAP_SEC:.0f}s max). "
                        "Long static holds are forbidden; add real motion or a real beat."
                    ),
                }
            )

    # Leading gap before first event.
    if events[0] > MAX_MOTION_GAP_SEC + 1e-6:
        errors.append(
            {
                "code": "motion-gap",
                "path": "/beats/0/startSec",
                "absoluteStartSec": 0.0,
                "absoluteEndSec": events[0],
                "maximumGapSec": MAX_MOTION_GAP_SEC,
                "message": (
                    f"First motion is at {events[0]:.2f}s; must begin within "
                    f"{MAX_MOTION_GAP_SEC:.0f}s of timeline start."
                ),
            }
        )

    # Variety: app-owned gate (not HyperFrames skill defaults).
    errors.extend(validate_variety(beats, id_key="graphicId"))

    return errors


def _transcript_words(document: dict) -> dict[str, dict]:
    project = document.get("project") or document
    words = project.get("words") or []
    return {str(word.get("id")): word for word in words if word.get("id")}


def validate_transcript_bindings(plan: dict, transcript_document: dict) -> list[dict]:
    errors: list[dict] = []
    words = _transcript_words(transcript_document)
    if not words:
        errors.append(
            {
                "code": "transcript-empty",
                "path": "/source",
                "message": "Transcript has no words to bind against.",
            }
        )
        return errors

    for index, beat in enumerate(plan.get("beats") or []):
        span = beat.get("wordSpan")
        if not span:
            # Allowed in Phase 1 if times are present; Phase 2 may require spans.
            continue
        for field in ("startWordId", "endWordId"):
            word_id = str(span.get(field) or "")
            if word_id not in words:
                errors.append(
                    {
                        "code": "unknown-word-id",
                        "path": f"/beats/{index}/wordSpan/{field}",
                        "message": f"Word id {word_id!r} is not in the locked transcript.",
                    }
                )
        start_id = str(span.get("startWordId") or "")
        end_id = str(span.get("endWordId") or "")
        if start_id in words and end_id in words:
            start_frame = int(
                words[start_id].get("start_frame", words[start_id].get("startFrame", -1))
            )
            end_frame = int(
                words[end_id].get("end_frame", words[end_id].get("endFrame", -1))
            )
            if end_frame < start_frame:
                errors.append(
                    {
                        "code": "word-span-order",
                        "path": f"/beats/{index}/wordSpan",
                        "message": "endWordId is before startWordId in the transcript.",
                    }
                )
        for row_index, row in enumerate(beat.get("listRows") or []):
            row_span = row.get("wordSpan")
            if not row_span:
                continue
            for field in ("startWordId", "endWordId"):
                word_id = str(row_span.get(field) or "")
                if word_id not in words:
                    errors.append(
                        {
                            "code": "unknown-word-id",
                            "path": f"/beats/{index}/listRows/{row_index}/wordSpan/{field}",
                            "message": f"Word id {word_id!r} is not in the locked transcript.",
                        }
                    )
    return errors


def validate_editorial_plan(
    plan: dict,
    *,
    transcript_document: dict | None = None,
    golden_root: Path | None = None,
) -> dict[str, Any]:
    """Validate a plan. Returns {ok, errors}.

    Graphic membership is the Graphics Library golden usage set.
    """

    plan = normalize_plan(plan)
    production_ids, production_snap = production_graphic_ids(golden_root)
    errors = validate_schema(plan)
    if not errors:
        errors.extend(
            validate_structure(
                plan,
                production_ids=production_ids,
                production_snap=production_snap,
            )
        )
    if transcript_document is not None and not any(
        item["code"] == "schema" for item in errors
    ):
        errors.extend(validate_transcript_bindings(plan, transcript_document))
    return {
        "ok": not errors,
        "errorCount": len(errors),
        "errors": errors,
        "maxMotionGapSec": MAX_MOTION_GAP_SEC,
        "kitSize": len(production_ids),
        "productionSet": {
            "count": production_snap.get("count", len(production_ids)),
            "empty": bool(production_snap.get("empty", not production_ids)),
            "emptyReason": production_snap.get("emptyReason"),
            "policy": production_snap.get("policy", "golden-only"),
            "ids": sorted(production_ids),
        },
        "normalizedPlan": plan,
    }


def load_plan(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_transcript(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))
