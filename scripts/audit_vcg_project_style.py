"""Audit visual-production style across historical VCG projects."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def module_of(cue: dict) -> str:
    params = cue.get("parameters") or {}
    return str(
        cue.get("moduleId")
        or params.get("moduleId")
        or cue.get("recipeId")
        or params.get("recipeId")
        or cue.get("kind")
        or "?"
    )


def textish(cue: dict) -> dict:
    params = cue.get("parameters") or {}
    keys = (
        "text",
        "title",
        "headline",
        "label",
        "lines",
        "copy",
        "setupText",
        "punchlineText",
        "items",
        "rows",
        "body",
        "subtitle",
    )
    out = {}
    for key in keys:
        value = params.get(key)
        if value:
            out[key] = value
    return out


def audit(root: Path) -> None:
    """Audit one private visual project root (must be passed explicitly; no hard-coded home paths)."""
    root = root.expanduser().resolve()
    name = root.name
    plan = json.loads((root / "visual-production" / "visual-plan.json").read_text(encoding="utf-8"))
    sug_path = root / "visual-production" / "visual-suggestions.json"
    sug = (
        json.loads(sug_path.read_text(encoding="utf-8"))
        if sug_path.is_file()
        else None
    )
    cues = plan.get("cues") or []
    duration = (plan.get("composition") or {}).get("durationSec")
    print("=" * 72)
    print(name, "durationSec=", duration, "cues=", len(cues))
    print("MODULE MIX:")
    for module, count in Counter(module_of(c) for c in cues).most_common():
        print(f"  {count:3d}  {module}")

    # Custom composition / geometry clues
    custom = plan.get("customCompositions") or []
    print("customCompositions:", len(custom) if isinstance(custom, list) else type(custom))
    if isinstance(custom, list):
        for item in custom[:8]:
            if isinstance(item, dict):
                print(
                    "  custom:",
                    item.get("id") or item.get("name") or item.get("path"),
                    list(item.keys())[:12],
                )

    print("FIRST 18 CUES:")
    for cue in cues[:18]:
        start = cue.get("startSec")
        end = cue.get("endSec")
        print(
            f"  {start!s:>8}-{end!s:<8}  {module_of(cue)[:42]:42}  {textish(cue)}"
        )

    # Joke-ish suggestions / purposes
    if not sug:
        print("No suggestions file.")
        return
    items = sug.get("suggestions") or []
    print(f"SUGGESTIONS ({len(items)}): categories")
    print(" ", Counter(str(item.get("category")) for item in items).most_common())
    print("PURPOSES / TREATMENTS (first 25):")
    for item in items[:25]:
        decision = item.get("decision") or {}
        purpose = (
            item.get("editorialPurpose")
            or item.get("purpose")
            or (item.get("scenePacket") or {}).get("editorialPurpose")
            or ""
        )
        treatment = (
            decision.get("selectedTreatmentId")
            or item.get("moduleId")
            or item.get("recipeId")
            or (decision.get("treatment") if isinstance(decision.get("treatment"), str) else None)
        )
        status = item.get("status") or decision.get("status")
        print(
            f"  {item.get('id')}: [{item.get('category')}/{status}] treat={treatment} :: {purpose[:110]}"
        )

    # Scan for joke/comedy keywords in purposes
    joke_hits = []
    for item in items:
        blob = json.dumps(item, ensure_ascii=False).lower()
        if any(token in blob for token in ("joke", "comedy", "punch", "roast", "funny", "callback", "humor")):
            purpose = (
                item.get("editorialPurpose")
                or item.get("purpose")
                or ""
            )
            joke_hits.append((item.get("id"), item.get("category"), item.get("moduleId") or item.get("recipeId"), purpose[:120]))
    print(f"JOKE/COMEDY HITS: {len(joke_hits)}")
    for hit in joke_hits[:15]:
        print(" ", hit)


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Audit module mix / purposes for private visual-production projects."
    )
    parser.add_argument(
        "projects",
        nargs="*",
        type=Path,
        help="One or more private project roots (each containing visual-production/visual-plan.json).",
    )
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="Also scan VCG_AUDIT_PROJECTS (os.pathsep-separated absolute roots).",
    )
    args = parser.parse_args()
    roots: list[Path] = list(args.projects)
    if args.from_env:
        raw = os.environ.get("VCG_AUDIT_PROJECTS") or ""
        roots.extend(Path(part.strip()) for part in raw.split(os.pathsep) if part.strip())
    if not roots:
        raise SystemExit(
            "Pass one or more private project roots, or set VCG_AUDIT_PROJECTS. "
            "No home-directory paths are hard-coded in this script."
        )
    for root in roots:
        audit(root)


if __name__ == "__main__":
    main()
