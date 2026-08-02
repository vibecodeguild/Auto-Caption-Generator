#!/usr/bin/env python3
"""CLI for VCG editorial beat plans (Phase 1 validate + Phase 2 build).

Usage:
  python scripts/editorial_beats.py validate --plan path/to/beats.json
  python scripts/editorial_beats.py validate --plan beats.json --transcript final-transcript.json
  python scripts/editorial_beats.py kit
  python scripts/editorial_beats.py map
  python scripts/editorial_beats.py example > beats.example.json
  python scripts/editorial_beats.py build --plan beats.json --out ./build-out
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.editorial_beats import (  # noqa: E402
    MAX_MOTION_GAP_SEC,
    load_plan,
    load_transcript,
    production_graphic_ids,
    validate_editorial_plan,
)
from app.core.editorial_build import (  # noqa: E402
    TREATMENT_BINDINGS,
    build_editorial_composition,
    write_composition_artifacts,
)
from app.core.editorial_layout import layout_table_markdown  # noqa: E402
from app.core.graphics_library import get_production_graphics  # noqa: E402


def _cmd_kit(_: argparse.Namespace) -> int:
    production = get_production_graphics(policy="golden-only")
    print(
        json.dumps(
            {
                "maxMotionGapSec": MAX_MOTION_GAP_SEC,
                "targetMotionGapSec": 2.0,
                "authority": "graphics-library-golden-usages",
                "policy": production.get("policy"),
                "empty": production.get("empty"),
                "message": production.get("message"),
                "graphics": production.get("ids"),
            },
            indent=2,
        )
    )
    return 0


def _cmd_example(_: argparse.Namespace) -> int:
    example = {
        "schemaVersion": 2,
        "episodeId": "example-episode",
        "mode": "tutorial",
        "fps": {"numerator": 30, "denominator": 1},
        "totalDurationSec": 30.0,
        "source": {
            "lockedCutPath": "exports/locked-cut.mp4",
            "transcriptPath": "transcripts/final-transcript.json",
        },
        "beats": [
            {
                "id": "beat-hook",
                "beatType": "hook",
                "graphicId": "punchline-reveal",
                "onScreenCopy": "SOUL-CRUSHING CORPORATE JOBS",
                "motionKind": "treatment-enter",
                "startSec": 1.1,
                "endSec": 4.4,
                "wordSpan": None,
            },
            {
                "id": "beat-theme",
                "beatType": "context",
                "graphicId": "speaker-side-panel",
                "onScreenCopy": "WORKING IN POWERPOINT",
                "motionKind": "treatment-enter",
                "startSec": 4.5,
                "endSec": 9.0,
                "wordSpan": None,
            },
            {
                "id": "beat-promise",
                "beatType": "example",
                "graphicId": "numbered-example-card",
                "onScreenCopy": "10 WAYS WITH GROK",
                "motionKind": "treatment-enter",
                "startSec": 9.0,
                "endSec": 14.0,
                "wordSpan": None,
            },
            {
                "id": "beat-reframe",
                "beatType": "aftershock",
                "graphicId": "source-punch-zoom",
                "onScreenCopy": None,
                "motionKind": "punch-zoom",
                "startSec": 14.0,
                "endSec": 16.5,
                "wordSpan": None,
            },
            {
                "id": "beat-list",
                "beatType": "list",
                "graphicId": "problem-card-triptych",
                "onScreenCopy": "WHAT YOU WILL GET",
                "motionKind": "internal-reveal",
                "startSec": 16.5,
                "endSec": 28.0,
                "listRows": [
                    {
                        "id": "row-1",
                        "text": "FASTER DECKS",
                        "startSec": 17.0,
                        "wordSpan": None,
                    },
                    {
                        "id": "row-2",
                        "text": "CLEANER SLIDES",
                        "startSec": 21.0,
                        "wordSpan": None,
                    },
                    {
                        "id": "row-3",
                        "text": "LESS BUSYWORK",
                        "startSec": 25.0,
                        "wordSpan": None,
                    },
                ],
            },
            {
                "id": "beat-close",
                "beatType": "cta",
                "graphicId": "brand-cta-lockup",
                "onScreenCopy": "INSTALL THE ADD-IN",
                "motionKind": "treatment-enter",
                "startSec": 28.0,
                "endSec": 30.0,
                "wordSpan": None,
            },
        ],
    }
    print(json.dumps(example, indent=2, ensure_ascii=False))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan.expanduser().resolve())
    transcript = None
    if args.transcript:
        transcript = load_transcript(args.transcript.expanduser().resolve())
    result = validate_editorial_plan(plan, transcript_document=transcript)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


def _cmd_map(_: argparse.Namespace) -> int:
    production_ids, production_snap = production_graphic_ids()
    rows = [
        {
            "graphicId": binding.treatment_id,
            "engineId": binding.engine_id,
            "capabilityId": binding.capability_id,
            "parameterMode": binding.parameter_mode,
            "inProductionSet": binding.treatment_id in production_ids,
        }
        for binding in sorted(TREATMENT_BINDINGS.values(), key=lambda item: item.treatment_id)
    ]
    print(
        json.dumps(
            {
                "authority": "graphics-library-golden-usages",
                "productionCount": len(production_ids),
                "productionEmpty": production_snap.get("empty"),
                "implementationBindingCount": len(rows),
                "bindings": rows,
                "productionOnlyUnbound": sorted(
                    production_ids - {row["graphicId"] for row in rows}
                ),
            },
            indent=2,
        )
    )
    return 0


def _cmd_layouts(_: argparse.Namespace) -> int:
    """Print the eight measured OBS layouts (usable area authority)."""

    print(layout_table_markdown())
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan.expanduser().resolve())
    transcript = None
    if args.transcript:
        transcript = load_transcript(args.transcript.expanduser().resolve())
    result = build_editorial_composition(
        plan,
        transcript_document=transcript,
        require_all_buildable=bool(args.require_all),
    )
    out = args.out.expanduser().resolve() if args.out else None
    paths = {}
    if out is not None:
        paths = write_composition_artifacts(
            result,
            out,
            write_html=not args.no_html,
            video_name=args.video_name,
            width=args.width,
            height=args.height,
        )
    payload = {
        "ok": result["ok"],
        "stage": result["stage"],
        "summary": result.get("summary"),
        "errorCount": result.get("errorCount"),
        "errors": result.get("errors"),
        "beats": [
            {
                "beatId": item["beatId"],
                "graphicId": item["graphicId"],
                "status": item["status"],
                "engineId": item.get("engineId"),
                "reason": item.get("reason"),
            }
            for item in (result.get("beats") or [])
        ],
        "artifacts": paths,
    }
    if result.get("stage") == "validate":
        payload["validation"] = result.get("validation")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not result["ok"]:
        return 1
    # Partial builds (some not-buildable) still exit 0 unless --require-all.
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="VCG editorial beat plans (validate + kit build)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a beat plan JSON file.")
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument(
        "--transcript",
        type=Path,
        help="Optional final-transcript.json for wordSpan checks.",
    )
    validate.set_defaults(func=_cmd_validate)

    kit = sub.add_parser("kit", help="Print the daily treatment kit.")
    kit.set_defaults(func=_cmd_kit)

    mapping = sub.add_parser("map", help="Print graphicId → engine bindings.")
    mapping.set_defaults(func=_cmd_map)

    layouts = sub.add_parser(
        "layouts",
        help="Print the eight measured OBS layouts and speaker bounds.",
    )
    layouts.set_defaults(func=_cmd_layouts)

    example = sub.add_parser("example", help="Print a valid example plan.")
    example.set_defaults(func=_cmd_example)

    build = sub.add_parser(
        "build",
        help="Validate then materialize engine composition graphs.",
    )
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument(
        "--transcript",
        type=Path,
        help="Optional final-transcript.json for wordSpan checks.",
    )
    build.add_argument(
        "--out",
        type=Path,
        help="Write composition.json, build-report.json, and index.html here.",
    )
    build.add_argument(
        "--require-all",
        action="store_true",
        help="Fail if any kit treatment lacks a Phase-2 seed binding.",
    )
    build.add_argument("--no-html", action="store_true", help="Skip index.html.")
    build.add_argument(
        "--video-name",
        default="locked-cut.mp4",
        help="Video filename referenced by index.html (default locked-cut.mp4).",
    )
    build.add_argument("--width", type=int, default=1920)
    build.add_argument("--height", type=int, default=1080)
    build.set_defaults(func=_cmd_build)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
