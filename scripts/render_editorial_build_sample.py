#!/usr/bin/env python3
"""Render a short editorial plan using REAL Visual Production modules.

Uses the same module markup / CSS / brand language as successful 7/14–7/22
videos (magenta kinetic stamps, left side panels, numbered example cards) —
not white-card placeholders.

Usage:
  python scripts/render_editorial_build_sample.py ^
    --project "%USERPROFILE%\\Videos\\MyPrivateProjects\\example-project" ^
    --seconds 42

Pass a private project root that already has a locked cut + visual source.
Do not commit real project paths or personal demo copy into the public tree.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.editorial_visual_plan import (  # noqa: E402
    build_visual_cues_from_beats,
    make_sample_visual_plan,
)
from app.core.file_utils import sha256_file  # noqa: E402
from app.core.process_utils import hidden_subprocess_flags  # noqa: E402
from app.core.visual_production import (  # noqa: E402
    build_hyperframes_composition,
    load_visual_plan,
    probe_visual_source,
    remux_locked_audio,
    save_visual_plan,
    validate_visual_plan,
)


def _load_current(root: Path) -> dict:
    creator = root / "creator-production" / "current.json"
    if creator.is_file():
        return json.loads(creator.read_text(encoding="utf-8-sig"))
    locked = root / "exports" / "locked-cut.mp4"
    transcript = root / "transcripts" / "final-transcript.json"
    return {
        "lockedCutPath": (
            locked.relative_to(root).as_posix()
            if locked.is_file()
            else "exports/locked-cut.mp4"
        ),
        "finalTranscriptPath": (
            transcript.relative_to(root).as_posix()
            if transcript.is_file()
            else "transcripts/final-transcript.json"
        ),
        "episodeId": root.name,
    }


def first_minute_tutorial_plan(*, episode_id: str, seconds: float) -> dict:
    """Editorial plan for the 7/23 Grok-for-PowerPoint open (spoken timings).

    Opening is full-screen talking (OBS 01 Full Camera). Layout IDs are measured
    facts from visual-production/layouts/scene-geometry.json — not guesses.
    """

    # Opening monologue: full-screen talking head until screen share begins later.
    open_layout = "full-screen-talking"

    # Diversified kit IDs on purpose — variety gate rejects the "same 3 shells on loop"
    # failure mode. Face-safe remaps may still rewrite modules, but rotate candidates.
    beats = [
        {
            "id": "beat-hook-jobs",
            "beatType": "hook",
            "graphicId": "kinetic-word-punctuation",
            "onScreenCopy": "SOUL-CRUSHING CORPORATE JOBS",
            "motionKind": "kinetic-hit",
            "startSec": 0.63,
            "endSec": 3.4,
            "layoutId": open_layout,
        },
        {
            "id": "beat-theme-ppt",
            "beatType": "context",
            "graphicId": "dependency-stack",
            "onScreenCopy": "WORKING IN POWERPOINT",
            "motionKind": "treatment-enter",
            "startSec": 3.5,
            "endSec": 7.8,
            "layoutId": open_layout,
        },
        {
            "id": "beat-love-job",
            "beatType": "proof",
            "graphicId": "tradeoff-meter",
            "onScreenCopy": "A JOB YOU LOVE",
            "motionKind": "treatment-enter",
            "startSec": 8.1,
            "endSec": 11.2,
            "layoutId": open_layout,
        },
        {
            "id": "beat-still-ppt",
            "beatType": "aftershock",
            "graphicId": "source-punch-zoom",
            "onScreenCopy": None,
            "motionKind": "punch-zoom",
            "startSec": 11.3,
            "endSec": 13.4,
            "layoutId": open_layout,
        },
        {
            "id": "beat-easier",
            "beatType": "punchline",
            "graphicId": "kinetic-word-punctuation",
            "onScreenCopy": "WAY EASIER",
            "motionKind": "treatment-enter",
            "startSec": 13.5,
            "endSec": 16.7,
            "layoutId": open_layout,
        },
        {
            "id": "beat-ten-ways",
            "beatType": "example",
            "graphicId": "numbered-example-card",
            "onScreenCopy": "01 — 10 WAYS WITH GROK",
            "motionKind": "treatment-enter",
            "startSec": 16.8,
            "endSec": 20.0,
            "layoutId": open_layout,
        },
        {
            "id": "beat-product",
            "beatType": "prompt",
            "graphicId": "windows-prompt-typing",
            "onScreenCopy": "Grok for PowerPoint add-in",
            "motionKind": "treatment-enter",
            "startSec": 20.0,
            "endSec": 24.4,
            "layoutId": open_layout,
        },
        {
            "id": "beat-lumberg",
            "beatType": "punchline",
            "graphicId": "punchline-reveal",
            "onScreenCopy": "PARKING SPOTS LIKE LUMBERG",
            "motionKind": "kinetic-hit",
            "startSec": 24.5,
            "endSec": 29.4,
            "layoutId": open_layout,
        },
        {
            "id": "beat-hook-end",
            "beatType": "hook",
            "graphicId": "dependency-stack",
            "onScreenCopy": "STICK AROUND TO THE END",
            "motionKind": "treatment-enter",
            "startSec": 29.5,
            "endSec": 34.4,
            "layoutId": open_layout,
        },
        {
            "id": "beat-claude",
            "beatType": "proof",
            "graphicId": "speaker-rise-callouts",
            "onScreenCopy": "NOT WITH CLAUDE",
            "motionKind": "treatment-enter",
            "startSec": 34.5,
            "endSec": 38.9,
            "layoutId": open_layout,
        },
        {
            "id": "beat-identity",
            "beatType": "context",
            "graphicId": "dependency-stack",
            "onScreenCopy": "SPEAKER · CREDENTIAL LINE",
            "motionKind": "treatment-enter",
            "startSec": 39.0,
            "endSec": min(seconds, 42.0),
            "layoutId": open_layout,
        },
    ]
    beats = [b for b in beats if b["startSec"] < seconds - 0.25]
    for beat in beats:
        beat["endSec"] = min(float(beat["endSec"]), seconds)
        if beat["endSec"] <= beat["startSec"]:
            beat["endSec"] = min(seconds, beat["startSec"] + 1.5)
    if beats and beats[-1]["endSec"] < seconds:
        if seconds - beats[-1]["endSec"] > 5.0:
            beats.append(
                {
                    "id": "beat-tail-motion",
                    "beatType": "aftershock",
                    "graphicId": "source-punch-zoom",
                    "onScreenCopy": None,
                    "motionKind": "reframe",
                    "startSec": beats[-1]["endSec"],
                    "endSec": seconds,
                }
            )
        else:
            beats[-1]["endSec"] = seconds

    return {
        "schemaVersion": 2,
        "episodeId": episode_id,
        "mode": "tutorial",
        "fps": {"numerator": 30, "denominator": 1},
        "totalDurationSec": float(seconds),
        "source": {
            "lockedCutPath": "exports/locked-cut.mp4",
            "transcriptPath": "transcripts/final-transcript.json",
        },
        "beats": beats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Editorial beats → Visual Production modules → HyperFrames sample."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=42.0)
    parser.add_argument(
        "--quality",
        default="draft",
        choices=["draft", "standard", "high"],
    )
    parser.add_argument("--plan", type=Path, help="Optional editorial beat plan JSON.")
    args = parser.parse_args()

    root = args.project.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Project not found: {root}")
    if not (root / ".vcg-private").is_file():
        raise SystemExit("Project is not a marked private VCG project (.vcg-private missing).")

    current = _load_current(root)
    locked_cut = (root / current["lockedCutPath"]).resolve()
    if not locked_cut.is_file():
        raise SystemExit(f"Locked cut missing: {locked_cut}")

    if args.plan:
        editorial = json.loads(args.plan.expanduser().resolve().read_text(encoding="utf-8-sig"))
    else:
        editorial = first_minute_tutorial_plan(
            episode_id=str(current.get("episodeId") or root.name),
            seconds=float(args.seconds),
        )
    editorial["totalDurationSec"] = float(args.seconds)

    print("Mapping editorial beats → Visual Production modules...")
    mapped = build_visual_cues_from_beats(editorial)
    if not mapped["ok"]:
        print(json.dumps(mapped, indent=2, ensure_ascii=False)[:4000])
        raise SystemExit("Editorial plan failed validation.")
    print(
        f"Mapped {mapped['summary']['mapped']}/{mapped['summary']['totalBeats']} beats "
        f"→ modules: {', '.join(mapped['summary']['moduleIds'])}"
    )
    for cue in mapped["cues"]:
        label = (cue.get("parameters") or {}).get("reviewLabel") or cue["moduleId"]
        print(
            f"  {cue['startSec']:5.1f}-{cue['endSec']:5.1f}s  "
            f"{cue['moduleId']:28}  {label}"
        )
    for skip in mapped["skipped"]:
        print(f"  SKIP  {skip.get('graphicId') or skip.get('treatmentId')}: {skip['reason']}")

    # Full locked-cut duration required for visual-plan validation; render is a range.
    meta = probe_visual_source(locked_cut)
    full_duration = float(meta["durationSec"])
    width = int(meta["width"])
    height = int(meta["height"])
    if width >= height:
        width, height = 1920, 1080
    fps = float(meta.get("fps") or 30)

    sample_dir = (
        root
        / "creator-production"
        / "sample-renders"
        / f"vp-modules-first-{int(args.seconds)}s"
    )
    if sample_dir.exists():
        shutil.rmtree(sample_dir)
    sample_dir.mkdir(parents=True)

    (sample_dir / "editorial-beats.json").write_text(
        json.dumps(editorial, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Write a temporary visual-plan under visual-production for the official builder.
    vp_dir = root / "visual-production"
    vp_dir.mkdir(parents=True, exist_ok=True)
    plan_path = vp_dir / "visual-plan.editorial-sample.json"
    visual_plan = make_sample_visual_plan(
        project_name=root.name,
        source_video_rel=Path(current["lockedCutPath"]).as_posix(),
        transcript_rel=Path(current.get("finalTranscriptPath") or "").as_posix(),
        duration_sec=full_duration,
        width=width,
        height=height,
        fps=fps,
        cues=mapped["cues"],
        video_sha256=sha256_file(locked_cut),
    )
    # Clamp cue ends to sample window only (not full duration) — cues are first N seconds.
    for cue in visual_plan["cues"]:
        cue["endSec"] = min(float(cue["endSec"]), float(args.seconds))
        for semantic in cue.get("semanticItems") or []:
            semantic["spokenStartSec"] = min(
                float(semantic["spokenStartSec"]), float(cue["endSec"]) - 0.05
            )
            semantic["fullyVisibleSec"] = min(
                float(semantic["fullyVisibleSec"]), float(cue["endSec"])
            )
            if semantic["fullyVisibleSec"] < semantic["spokenStartSec"]:
                semantic["fullyVisibleSec"] = float(cue["endSec"])

    plan_path.write_text(
        json.dumps(visual_plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Validate without save_visual_plan hash side effects on primary plan.
    validate_visual_plan(visual_plan, root)
    print(f"Visual plan: {plan_path}")

    workspace = sample_dir / "hyperframes"
    print(f"Building HyperFrames composition (0–{args.seconds:.0f}s) with VP modules...")
    runtime_root, render_duration = build_hyperframes_composition(
        plan_path,
        start_sec=0.0,
        end_sec=float(args.seconds),
        workspace_override=workspace,
        progress=lambda pct, msg: print(f"  [{pct:3d}%] {msg}"),
    )
    print(f"Runtime: {runtime_root} ({render_duration:.1f}s)")

    # Copy plan artifacts into sample dir for inspection.
    shutil.copy2(plan_path, sample_dir / "visual-plan.editorial-sample.json")

    output = sample_dir / f"vp-modules-first-{int(args.seconds)}s.mp4"
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is required.")
    # Call the JS CLI directly so paths with spaces (this repo) do not break .cmd shims.
    cli_js = REPO / "node_modules" / "hyperframes" / "dist" / "cli.js"
    if not cli_js.is_file():
        from app.core.creator_rendering import resolve_creator_renderer_assets

        assets = resolve_creator_renderer_assets(REPO)
        candidate = Path(assets["hyperframesCli"])
        cli_js = candidate if candidate.suffix == ".js" else cli_js
    if not cli_js.is_file():
        raise SystemExit(f"HyperFrames CLI not found at {cli_js}")

    video_only = sample_dir / f".tmp-video-only-{int(args.seconds)}s.mp4"
    print(f"Rendering ({args.quality})...")
    command = [
        node,
        str(cli_js),
        "render",
        str(runtime_root),
        "--output",
        str(video_only),
        "--quality",
        args.quality,
    ]

    env = __import__("os").environ.copy()
    from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe

    media_dirs = [str(find_ffmpeg().parent)]
    if find_ffprobe() is not None:
        media_dirs.append(str(find_ffprobe().parent))
    env["PATH"] = __import__("os").pathsep.join(media_dirs + [env.get("PATH", "")])

    rendered = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO),
        env=env,
        creationflags=hidden_subprocess_flags(),
    )
    if rendered.returncode != 0 or not video_only.is_file():
        print(rendered.stdout[-2500:] if rendered.stdout else "")
        print(rendered.stderr[-2500:] if rendered.stderr else "")
        raise SystemExit(f"HyperFrames render failed ({rendered.returncode})")

    print("Remuxing locked-cut audio...")
    remux_locked_audio(
        video_only,
        locked_cut,
        output,
        start_sec=0.0,
        duration_sec=float(args.seconds),
    )
    video_only.unlink(missing_ok=True)

    print("Done.")
    print(f"  output: {output}")
    print(f"  size:   {output.stat().st_size / (1024 * 1024):.1f} MB")
    print(f"  plan:   {sample_dir / 'editorial-beats.json'}")
    print(f"  vp:     {sample_dir / 'visual-plan.editorial-sample.json'}")
    print(f"  html:   {runtime_root / 'public' / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
