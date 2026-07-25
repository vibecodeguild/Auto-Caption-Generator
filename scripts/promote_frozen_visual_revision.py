from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.visual_production import (
    calculate_visual_plan_hash,
    load_visual_plan,
    probe_visual_source,
    resolve_project_path,
    run_hyperframes_production_checks,
    save_visual_plan,
    semantic_layout_inspection_times,
    sha256_directory,
    sha256_file,
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "revision"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Revision artifact must be inside the private project: {path}") from exc


def _scene_label(scene: dict, index: int) -> str:
    copy = scene.get("copy") if isinstance(scene.get("copy"), dict) else {}
    label = str(copy.get("kicker") or scene.get("id") or f"Scene {index}").strip()
    return f"{index:02d} · {label}"


def _root_composition_id(entry_path: Path) -> str:
    source = entry_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'data-composition-id=["\']([^"\']+)["\']', source)
    if not match:
        raise ValueError("The HyperFrames entry file does not declare a root data-composition-id.")
    return match.group(1)


def _semantic_items(scene: dict, ledger_scene: dict, fps: float, start: float, end: float) -> list[dict]:
    results: list[dict] = []
    for index, reveal in enumerate(ledger_scene.get("reveals") or []):
        phrase = str(reveal.get("phrase") or "").strip()
        spoken_start = float(reveal.get("absoluteSec"))
        settled_frame = int(reveal.get("settledFrame"))
        fully_visible = min(end, max(spoken_start, settled_frame / fps))
        if spoken_start < start - 0.01 or spoken_start > end + 0.01:
            raise ValueError(f"Reveal {index} in {scene.get('id')} falls outside its scene.")
        results.append({
            "id": f"reveal-{index + 1:02d}",
            "label": str(reveal.get("label") or f"Reveal {index + 1}"),
            "text": str(reveal.get("label") or phrase or f"Reveal {index + 1}"),
            "parameterPath": f"scene.reveals.{index}",
            "phrase": phrase,
            "anchorType": "scene-relative" if phrase.casefold() == "scene-relative" else "spoken",
            "spokenStartSec": round(spoken_start, 4),
            "fullyVisibleSec": round(fully_visible, 4),
        })
    return results


def promote(
    project_root: Path,
    master: Path,
    storyboard_path: Path,
    *,
    revision_id: str,
    revision_name: str,
    superseded_id: str,
    revision_number: int = 5,
    timing_ledger_path: Path | None = None,
    hyperframes_source: Path | None = None,
    skip_production_checks: bool = False,
) -> dict:
    """Register an approved custom HyperFrames delivery as the canonical plan revision."""
    root = project_root.resolve()
    if not (root / ".vcg-private").is_file():
        raise ValueError("The target is not a marked private VCG project.")
    manifest_path = root / "project.vcg-project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = manifest.get("paths") or {}
    plan_path = resolve_project_path(root, str(paths.get("visualPlan") or ""))
    final_path = resolve_project_path(root, str(paths.get("finalVideo") or ""))
    plan = load_visual_plan(plan_path)
    if any(str(review.get("note") or "").strip() for review in plan.get("reviews", [])):
        raise ValueError("The active plan has review notes. Resolve or archive them before promoting another revision.")

    source_master = master.resolve()
    if not source_master.is_file():
        raise FileNotFoundError(source_master)
    storyboard_path = storyboard_path.resolve()
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    scenes = sorted(storyboard.get("scenes") or [], key=lambda scene: float(scene.get("startSec") or 0))
    if not scenes:
        raise ValueError("The storyboard does not contain scene intervals.")

    project_directory = (hyperframes_source or (storyboard_path.parent / "public")).resolve()
    entry_path = project_directory / "index.html"
    if not entry_path.is_file():
        raise FileNotFoundError(f"HyperFrames entry file is missing: {entry_path}")
    ledger_path = (timing_ledger_path or (storyboard_path.parent / "timing-ledger.json")).resolve()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    fps = float(ledger.get("fps") or plan["composition"]["fps"])
    ledger_scenes = {str(item.get("sceneId")): item for item in ledger.get("scenes") or []}
    if len(ledger_scenes) != len(scenes):
        raise ValueError("The timing ledger and storyboard scene counts do not match.")

    composition = plan["composition"]
    metadata = probe_visual_source(source_master)
    if metadata["width"] != int(composition["width"]) or metadata["height"] != int(composition["height"]):
        raise ValueError("The master dimensions do not match the visual plan.")
    if abs(float(metadata["fps"]) - float(composition["fps"])) > 0.01:
        raise ValueError("The master frame rate does not match the visual plan.")
    if abs(float(metadata["durationSec"]) - float(composition["durationSec"])) > 0.1:
        raise ValueError("The master duration does not match the visual plan.")

    duration = float(composition["durationSec"])
    scene_intervals: list[tuple[dict, float, float]] = []
    for index, scene in enumerate(scenes):
        start = float(scene.get("startSec") or 0)
        end = min(float(scene.get("renderEndSec") or scene.get("endSec") or 0), duration)
        if start < 0 or end <= start or end > duration + 0.01:
            raise ValueError(f"Scene {scene.get('id') or index + 1} has invalid timing.")
        scene_intervals.append((scene, start, end))
    if scene_intervals[0][1] > 0.01 or duration - scene_intervals[-1][2] > 0.05:
        raise ValueError("The storyboard does not cover the complete visual runtime.")

    master_hash = sha256_file(source_master)

    composition_id = f"hyperframes-{_slug(revision_id)}"
    composition_record = {
        "id": composition_id,
        "name": revision_name,
        "runtime": "hyperframes",
        "projectPath": _relative(project_directory, root),
        "entryFile": entry_path.name,
        "rootCompositionId": _root_composition_id(entry_path),
        "storyboardPath": _relative(storyboard_path, root),
        "timingLedgerPath": _relative(ledger_path, root),
        "sourceHash": sha256_directory(project_directory),
    }
    cues: list[dict] = []
    for index, (scene, start, end) in enumerate(scene_intervals, 1):
        scene_id = str(scene.get("id") or f"scene-{index:02d}")
        ledger_scene = ledger_scenes.get(scene_id)
        if ledger_scene is None:
            raise ValueError(f"The timing ledger is missing {scene_id}.")
        cues.append({
            "id": f"composition-{_slug(revision_id)}-{_slug(scene_id)}",
            "kind": "composition",
            "compositionId": composition_id,
            "sceneId": scene_id,
            "startSec": start,
            "endSec": end,
            "enabled": True,
            "parameters": {
                "reviewLabel": _scene_label(scene, index),
                "editorialPurpose": str(scene.get("purpose") or ""),
                "recipeId": str(scene.get("recipe") or scene.get("layoutFamily") or "custom-hyperframes"),
            },
            "semanticItems": _semantic_items(scene, ledger_scene, fps, start, end),
            "notes": str(scene.get("purpose") or ""),
        })

    plan["schemaVersion"] = 2
    plan["assets"] = [
        asset for asset in plan.get("assets", [])
        if not isinstance(asset.get("origin"), dict) or asset["origin"].get("kind") != "frozen-visual-revision"
    ]
    plan["customCompositions"] = [composition_record]
    plan["cues"] = cues
    plan["reviews"] = []
    plan_hash = calculate_visual_plan_hash(plan, root)
    now = datetime.now(timezone.utc).isoformat()
    revision = {
        "number": revision_number,
        "id": revision_id,
        "name": revision_name,
        "status": "delivered",
        "runtime": "hyperframes",
        "compositionId": composition_id,
        "hyperframesSource": composition_record["projectPath"],
        "entryFile": composition_record["entryFile"],
        "reviewRender": _relative(source_master, root),
        "finalRender": _relative(final_path, root),
        "planHash": plan_hash,
        "reviewHash": master_hash,
        "finalHash": master_hash,
        "createdAt": now,
        "updatedAt": now,
    }
    representative_ids = [str(value) for value in storyboard.get("representativeApprovalSet") or []]
    representative_scene = representative_ids[0] if representative_ids else cues[0]["sceneId"]
    representative_cue = next(cue for cue in cues if cue["sceneId"] == representative_scene)
    inspection_commands = ["legacy-approved-render"] if skip_production_checks else run_hyperframes_production_checks(
        project_directory,
        inspection_times=semantic_layout_inspection_times({"cues": cues}),
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = plan_path.with_name(f"visual-plan.superseded-{_slug(superseded_id)}-{timestamp}.json")
    shutil.copy2(plan_path, backup_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if source_master != final_path.resolve():
        temporary = final_path.with_suffix(f"{final_path.suffix}.promoting")
        shutil.copy2(source_master, temporary)
        if sha256_file(temporary) != master_hash:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("The promoted master failed its byte-for-byte verification.")
        temporary.replace(final_path)
    plan["revisions"] = {"activeRevision": revision_number, "items": [revision]}
    plan["productionGates"] = {
        "representativeApproval": {
            "planHash": plan_hash,
            "cueId": representative_cue["id"],
            "startSec": representative_cue["startSec"],
            "endSec": representative_cue["endSec"],
            "approvedAt": now,
            "approvedSceneIds": representative_ids or [representative_scene],
        },
        "fullReviewApproval": {"planHash": plan_hash, "revisionNumber": revision_number, "approvedAt": now},
        "layoutInspection": {"planHash": plan_hash, "status": "passed", "commands": inspection_commands, "checkedAt": now},
        "deliveryReopen": None,
    }
    saved = save_visual_plan(plan_path, plan)
    return {
        "planPath": str(plan_path),
        "supersededPlan": str(backup_path),
        "finalVideo": str(final_path),
        "revisionId": revision_id,
        "revisionName": revision_name,
        "revisionNumber": revision_number,
        "compositionId": composition_id,
        "sceneCount": len(cues),
        "semanticItemCount": sum(len(cue["semanticItems"]) for cue in cues),
        "masterSha256": master_hash,
        "planHash": plan_hash,
        "productionChecks": inspection_commands,
        "planUpdatedAt": saved["project"]["updatedAt"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Register an approved custom HyperFrames delivery as a canonical Visual Production revision.")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("master", type=Path)
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--revision-name", required=True)
    parser.add_argument("--superseded-id", required=True)
    parser.add_argument("--revision-number", type=int, default=5)
    parser.add_argument("--timing-ledger", type=Path)
    parser.add_argument("--hyperframes-source", type=Path)
    parser.add_argument("--skip-production-checks", action="store_true", help="Migration tests only; do not use for production promotion.")
    args = parser.parse_args()
    print(json.dumps(promote(
        args.project_root,
        args.master,
        args.storyboard,
        revision_id=args.revision_id,
        revision_name=args.revision_name,
        superseded_id=args.superseded_id,
        revision_number=args.revision_number,
        timing_ledger_path=args.timing_ledger,
        hyperframes_source=args.hyperframes_source,
        skip_production_checks=args.skip_production_checks,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
