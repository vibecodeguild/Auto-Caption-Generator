#!/usr/bin/env python3
"""Ensure private Graphics Library has candidate usages for each engine.

Private data only — never writes into the Git checkout.

This does **not** draw graphics or promote golden. It only creates shelf rows
so you can sample, rate, and promote.

Usage:
  python scripts/ensure_graphics_library_usages.py
  python scripts/ensure_graphics_library_usages.py --render
  python scripts/ensure_graphics_library_usages.py --render --force --quality draft
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.graphics_library import (  # noqa: E402
    configure_default_vcg_demo_beds_from_project,
    create_graphics_library,
    default_graphics_library_root,
    ensure_candidate_usages_from_engines,
    import_treatment_harvest,
    render_missing_samples,
    summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure Graphics Library candidate usages for each engine."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override graphics-library root (default: Creator Library path).",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Private project used for demo beds (default: 2026-07-23 VCG project if present).",
    )
    parser.add_argument("--render", action="store_true", help="Render missing samples.")
    parser.add_argument("--force", action="store_true", help="Re-render samples that already exist.")
    parser.add_argument(
        "--quality",
        default="draft",
        choices=["draft", "standard", "high"],
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Optional usage ids to render.",
    )
    args = parser.parse_args()

    root = (args.root or default_graphics_library_root()).expanduser().resolve()
    print(f"Graphics Library root: {root}")
    create_graphics_library(root)
    ensured = ensure_candidate_usages_from_engines(root)
    print(f"Engine usages: created={ensured['created']} total={ensured['total']}")
    harvested = import_treatment_harvest(root)
    print(
        f"Harvest import: imported={harvested['imported']} "
        f"skippedUnbuildable={harvested['skippedUnbuildable']}"
    )

    project = args.project
    if project is None:
        candidate = Path.home() / "Videos" / "VCG Projects" / "2026-07-23-15-33-08"
        if candidate.is_dir():
            project = candidate
    if project is not None:
        project = project.expanduser().resolve()
        beds = configure_default_vcg_demo_beds_from_project(project, root=root)
        print(f"Demo beds configured from {project}: {json.dumps(beds, indent=2)}")

    if args.render:
        report = render_missing_samples(
            root,
            force=args.force,
            quality=args.quality,
            only_ids=args.only,
        )
        print(json.dumps(report, indent=2))

    print(json.dumps(summary(root), indent=2, default=str)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
