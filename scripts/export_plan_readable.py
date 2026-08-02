"""Export a human-readable markdown view of the current Creator Production plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    print("PROJECT STATE:", current.get("state"))
    print()
    print("=== PLAN ARTIFACTS (on disk) ===")
    for key in [
        "editorialPlanDecisions",
        "semanticManifest",
        "semanticPlanMaterialization",
        "sequenceDecisionIndex",
        "analysisLedger",
    ]:
        ref = (current.get("artifacts") or {}).get(key)
        if not ref:
            print(f"{key}: MISSING")
            continue
        path = root / ref["path"]
        print(f"{key}:")
        print(f"  {path}")
        print(f"  exists={path.is_file()} size={path.stat().st_size if path.is_file() else 0}")

    semantic = json.loads(
        (root / current["artifacts"]["semanticManifest"]["path"]).read_text(encoding="utf-8")
    )
    lines: list[str] = []
    lines.append("# Creator Production Plan (first Grok plan)")
    lines.append("")
    lines.append(f"- Episode: `{current.get('episodeId')}`")
    lines.append(f"- State: `{current.get('state')}`")
    lines.append(f"- Sequences: **{len(semantic.get('sequences', []))}**")
    lines.append(f"- Chapters: **{len(semantic.get('chapters', []))}**")
    lines.append(f"- Total frames: {semantic.get('totalFrames')} @ {semantic.get('fps')}")
    lines.append("")
    lines.append("## Important")
    lines.append("")
    lines.append(
        "This is the **planning document**, not a finished visual design. "
        "The white-card sample render was a throwaway preview shell and is **not** "
        "this plan rendered through VCG modules/fonts."
    )
    lines.append("")
    lines.append("## Chapters")
    lines.append("")
    for chapter in semantic.get("chapters", []):
        lines.append(
            f"- **{chapter.get('id')}** — {chapter.get('title')} "
            f"({chapter.get('absoluteStartFrame')}–{chapter.get('absoluteEndFrameExclusive')})"
        )
    lines.append("")
    lines.append("## Sequences / beats")
    lines.append("")
    for sequence in semantic.get("sequences", []):
        start = int(sequence.get("absoluteStartFrame") or 0)
        end = int(sequence.get("absoluteEndFrameExclusive") or 0)
        beats = (sequence.get("editorialDirective") or {}).get("spokenBeats") or []
        changes = (sequence.get("editorialDirective") or {}).get("meaningfulChanges") or []
        lines.append(f"### {sequence.get('id')}  ({start/30:.1f}s – {end/30:.1f}s)")
        lines.append(f"- Editorial job: {sequence.get('editorialJob')}")
        lines.append(
            f"- Form: {sequence.get('semanticForm')} · role: {sequence.get('presentationRole')} · "
            f"strategy: {(sequence.get('editorialDirective') or {}).get('sourceStrategy')}"
        )
        lines.append(
            f"- Purpose: {(sequence.get('editorialDirective') or {}).get('visualPurpose')}"
        )
        lines.append(
            f"- Spoken beats: **{len(beats)}** · meaningful changes: **{len(changes)}**"
        )
        candidates = sequence.get("candidateCapabilityIds") or []
        if candidates:
            shown = ", ".join(str(item) for item in candidates[:10])
            if len(candidates) > 10:
                shown += "..."
            lines.append(f"- Candidate capabilities: {shown}")
        lines.append("")
        lines.append("| t | on-screen label | spoken phrase |")
        lines.append("| --- | --- | --- |")
        for beat in beats:
            reveal = beat.get("revealFrame")
            stamp = f"{reveal/30:.1f}s" if isinstance(reveal, int) else "?"
            label = str(beat.get("onScreenText") or "—").replace("|", "/")
            phrase = str(beat.get("spokenPhrase") or "—").replace("|", "/")
            lines.append(f"| {stamp} | {label} | {phrase} |")
        lines.append("")

    out = root / "creator-production" / "PLAN-READABLE.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print()
    print("=== READABLE SUMMARY ===")
    print(out)
    print()
    print("First sequence labels (raw plan, often weak single words):")
    first = semantic["sequences"][0]
    for beat in ((first.get("editorialDirective") or {}).get("spokenBeats") or [])[:15]:
        print(
            f"  {int(beat.get('revealFrame') or 0)/30:5.1f}s  "
            f"label={beat.get('onScreenText')!r:16}  "
            f"phrase={beat.get('spokenPhrase')!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
