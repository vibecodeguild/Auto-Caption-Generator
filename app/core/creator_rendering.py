from __future__ import annotations

import json
import html
import os
import shutil
import subprocess
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    artifact_id_storage_segment,
    atomic_write_json,
    canonical_hash,
    content_addressed_object_path,
    locked_audio_stream_hash,
    require_private_root,
    utc_now,
    validate_artifact,
)
from app.core.ffmpeg_locator import find_ffmpeg, find_ffprobe
from app.core.file_utils import is_within, sha256_file
from app.core.process_utils import hidden_subprocess_flags


SUPPORTED_GRAPH_OPERATIONS = frozenset(
    {
        "set",
        "reveal",
        "enter",
        "show",
        "type-reveal",
        "move",
        "scale",
        "rotate",
        "emphasize",
        "hide",
        "exit",
    }
)


def _frame_exact_duration_text(
    frame_count: int,
    *,
    fps_numerator: int,
    fps_denominator: int,
) -> str:
    """Serialize a half-open frame duration without rounding past its end frame."""

    if frame_count < 1:
        raise ValueError("Chapter frame count must be positive.")
    if fps_numerator < 1 or fps_denominator < 1:
        raise ValueError("Frame-rate components must be positive.")
    duration = (
        Decimal(frame_count) * Decimal(fps_denominator) / Decimal(fps_numerator)
    )
    return format(
        duration.quantize(Decimal("0.000000001"), rounding=ROUND_FLOOR),
        ".9f",
    )


def resolve_creator_renderer_assets(repository_root: Path) -> dict:
    """Resolve and hash-check the complete local renderer executable set."""

    repository = repository_root.resolve()
    manifest_path = repository / "app" / "private-renderer-assets" / "renderer-assets.v1.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            "Creator Production renderer assets are not preserved locally. "
            "Restore app/private-renderer-assets before rendering."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1:
        raise RuntimeError("Creator Production renderer asset manifest version is unsupported.")
    tree_entries = manifest.get("trees") or {}
    resolved_trees = {}
    for tree_id in ("hyperframesPackage", "browserBundle"):
        entry = tree_entries.get(tree_id)
        if not isinstance(entry, dict):
            raise RuntimeError(f"Renderer asset manifest is missing tree {tree_id}.")
        path = (repository / str(entry.get("path") or "")).resolve()
        if not is_within(path, repository) or not path.is_dir():
            raise RuntimeError(f"Preserved renderer tree is unavailable: {tree_id}.")
        files = sorted(
            (item for item in path.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(path).as_posix(),
        )
        identity = canonical_hash(
            [
                {
                    "path": item.relative_to(path).as_posix(),
                    "bytes": item.stat().st_size,
                    "sha256": sha256_file(item),
                }
                for item in files
            ]
        )
        if len(files) != entry.get("fileCount") or identity != entry.get("sha256"):
            raise RuntimeError(f"Preserved renderer tree identity changed: {tree_id}.")
        resolved_trees[tree_id] = path
    package_path = resolved_trees["hyperframesPackage"] / "package.json"
    if not package_path.is_file():
        raise RuntimeError("The pinned local HyperFrames package is unavailable.")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("version") != manifest.get("hyperframesVersion"):
        raise RuntimeError("Renderer assets belong to a different HyperFrames version.")
    resolved = {}
    for asset_id in ("browser", "hyperframesCli", "gsap", "ffmpeg", "ffprobe"):
        entry = (manifest.get("assets") or {}).get(asset_id)
        if not isinstance(entry, dict):
            raise RuntimeError(f"Renderer asset manifest is missing {asset_id}.")
        path = (repository / str(entry.get("path") or "")).resolve()
        if not is_within(path, repository) or not path.is_file():
            raise RuntimeError(f"Preserved renderer asset is unavailable: {asset_id}.")
        if sha256_file(path) != entry.get("sha256"):
            raise RuntimeError(f"Preserved renderer asset identity changed: {asset_id}.")
        resolved[asset_id] = path
    return {
        "manifestPath": manifest_path,
        "manifest": manifest,
        "hyperframesPackage": resolved_trees["hyperframesPackage"],
        "browserBundle": resolved_trees["browserBundle"],
        "browser": resolved["browser"],
        "hyperframesCli": resolved["hyperframesCli"],
        "gsap": resolved["gsap"],
        "ffmpeg": resolved["ffmpeg"],
        "ffprobe": resolved["ffprobe"],
    }


def creator_renderer_environment(repository_root: Path) -> dict[str, str]:
    assets = resolve_creator_renderer_assets(repository_root)
    environment = os.environ.copy()
    tool_directories = list(
        dict.fromkeys(
            [
                str(assets["ffmpeg"].parent),
                str(assets["ffprobe"].parent),
            ]
        )
    )
    environment["PATH"] = os.pathsep.join(
        [*tool_directories, environment.get("PATH", "")]
    )
    browser = str(assets["browser"])
    environment["HYPERFRAMES_BROWSER_PATH"] = browser
    environment["PRODUCER_HEADLESS_SHELL_PATH"] = browser
    return environment


def _css_rect(geometry: dict) -> str:
    return (
        f"left:{geometry['x'] * 100:.6f}%;top:{geometry['y'] * 100:.6f}%;"
        f"width:{geometry['width'] * 100:.6f}%;height:{geometry['height'] * 100:.6f}%;"
    )


def _js(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _element_markup(
    element: dict,
    staged_assets: dict[str, str],
    *,
    dom_id: str,
) -> str:
    properties = element["properties"]
    element_id = html.escape(dom_id, quote=True)
    style = (
        _css_rect(element["geometry"])
        + f"z-index:{element['zIndex']};"
        + _element_style(properties.get("style"))
    )
    kind = element["kind"]
    classes = f"graph-element kind-{html.escape(kind, quote=True)}"
    if properties.get("role") in {"speaker-source", "locked-source"}:
        return ""
    asset_id = properties.get("assetId")
    if asset_id:
        source = staged_assets.get(str(asset_id))
        if not source:
            raise ValueError(f"Composition element references an unstaged asset: {asset_id}")
        return (
            f'<img id="{element_id}" class="{classes}" style="{style}" '
            f'src="{html.escape(source, quote=True)}" />'
        )
    content = properties.get("text", properties.get("content", ""))
    if not isinstance(content, (str, int, float)):
        raise ValueError(f"Composition element {element['id']} has non-renderable content.")
    return (
        f'<div id="{element_id}" class="{classes}" style="{style}">'
        f"{html.escape(str(content))}</div>"
    )


_ELEMENT_STYLE_PROPERTIES = {
    "alignItems": "align-items",
    "background": "background",
    "backgroundColor": "background-color",
    "border": "border",
    "borderRadius": "border-radius",
    "boxShadow": "box-shadow",
    "color": "color",
    "display": "display",
    "fontFamily": "font-family",
    "fontSize": "font-size",
    "fontStyle": "font-style",
    "fontWeight": "font-weight",
    "justifyContent": "justify-content",
    "letterSpacing": "letter-spacing",
    "lineHeight": "line-height",
    "opacity": "opacity",
    "overflow": "overflow",
    "padding": "padding",
    "textAlign": "text-align",
    "textTransform": "text-transform",
    "transformOrigin": "transform-origin",
    "whiteSpace": "white-space",
}


def _element_style(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, dict):
        raise ValueError("Composition element style must be an object.")
    declarations = []
    for key, raw in sorted(value.items()):
        css_name = _ELEMENT_STYLE_PROPERTIES.get(str(key))
        if css_name is None:
            raise ValueError(f"Composition element style property is not admitted: {key}")
        css_value = str(raw)
        if any(character in css_value for character in ";{}<>") or "url(" in css_value.lower():
            raise ValueError(f"Composition element style value is unsafe: {key}")
        declarations.append(f"{css_name}:{html.escape(css_value, quote=True)};")
    return "".join(declarations)


def _event_timeline_line(
    event: dict,
    *,
    chapter_start: int,
    fps: float,
    target_dom_id: str | None = None,
) -> str:
    operation = event["operation"]
    if operation not in SUPPORTED_GRAPH_OPERATIONS:
        raise ValueError(f"Renderer has no admitted graph operation: {operation}")
    target = f'[id="{target_dom_id or event["targetElementId"]}"]'
    at = (event["absoluteFrame"] - chapter_start) / fps
    duration = event["durationFrames"] / fps
    easing = event.get("easing") or "none"
    parameters = {
        key: value
        for key, value in (event.get("parameters") or {}).items()
        if key != "resolvedGeometry"
    }
    if operation == "set":
        return f"tl.set({_js(target)},{_js(parameters)},{at:.9f});"
    if operation in {"reveal", "enter", "show", "type-reveal"}:
        before = parameters.get("from", {"opacity": 0})
        after = parameters.get("to", {"opacity": 1})
        after = {**after, "duration": duration, "ease": easing}
        return f"tl.fromTo({_js(target)},{_js(before)},{_js(after)},{at:.9f});"
    if operation in {"hide", "exit"}:
        after = parameters.get("to", {"opacity": 0})
        after = {**after, "duration": duration, "ease": easing}
        return f"tl.to({_js(target)},{_js(after)},{at:.9f});"
    after = parameters.get("to", parameters)
    after = {**after, "duration": duration, "ease": easing}
    return f"tl.to({_js(target)},{_js(after)},{at:.9f});"


def build_chapter_compositions(
    private_root: Path,
    *,
    manifest: dict,
    compiled: dict,
    build_lock: dict,
    locked_cut: Path,
    repository_root: Path,
) -> dict[str, Path]:
    """Lower an explicit compiled graph into standalone, seek-safe chapter HTML."""

    root = require_private_root(private_root)
    validate_artifact("build-lock", build_lock)
    locked_cut = locked_cut.resolve()
    if not is_within(locked_cut, root) or not locked_cut.is_file():
        raise ValueError("Locked cut is unavailable inside private project storage.")
    if compiled["manifestHash"] != build_lock["manifestHash"]:
        raise ValueError("Compiled episode and build lock do not share a manifest.")
    fps_numerator = int(manifest["fps"]["numerator"])
    fps_denominator = int(manifest["fps"]["denominator"])
    fps = fps_numerator / fps_denominator
    width = int(manifest.get("canvas", {}).get("width", 1920))
    height = int(manifest.get("canvas", {}).get("height", 1080))
    compiled_by_id = {item["sequenceId"]: item for item in compiled["sequences"]}
    sequence_by_id = {item["id"]: item for item in manifest["sequences"]}
    gsap_source = resolve_creator_renderer_assets(repository_root)["gsap"]
    outputs: dict[str, Path] = {}
    for chapter in manifest["chapters"]:
        chapter_id = chapter["id"]
        chapter_lock = next(item for item in build_lock["chapters"] if item["chapterId"] == chapter_id)
        workspace = (
            root
            / "creator-production"
            / "compositions"
            / artifact_id_storage_segment(chapter_id)
            / chapter_lock["chapterInputHash"]
        )
        public = workspace / "public"
        public.mkdir(parents=True, exist_ok=True)
        (public / "vendor").mkdir(exist_ok=True)
        (public / "assets").mkdir(exist_ok=True)
        shutil.copyfile(gsap_source, public / "vendor" / "gsap.min.js")
        chapter_start = chapter["absoluteStartFrame"]
        chapter_end = chapter["absoluteEndFrameExclusive"]
        frame_count = chapter_end - chapter_start
        staged_source = public / "source.mp4"
        source_cache_key = canonical_hash(
            {
                "lockedCutSha256": build_lock["lockedCutSha256"],
                "absoluteStartFrame": chapter_start,
                "absoluteEndFrameExclusive": chapter_end,
                "fps": manifest["fps"],
                "canvas": {"width": width, "height": height},
                "producerAdapterHash": build_lock["runtime"]["producerAdapterHash"],
                "preprocess": {
                    "selector": "decoded-frame-half-open-v1",
                    "videoCodec": "libx264",
                    "crf": 16,
                    "preset": "medium",
                    "pixelFormat": "yuv420p",
                    "audio": "none",
                },
            }
        )
        cached_source = (
            root
            / "creator-production"
            / "source-cache"
            / source_cache_key[:2]
            / source_cache_key
            / "source.mp4"
        )
        if cached_source.is_file():
            if probe_video_identity(cached_source)["frameCount"] != frame_count:
                raise RuntimeError(f"Cached source frame count changed: {chapter_id}")
        else:
            cached_source.parent.mkdir(parents=True, exist_ok=True)
            ffmpeg = find_ffmpeg()
            pending_source = cached_source.with_suffix(".pending.mp4")
            command = [
                str(ffmpeg),
                "-y",
                "-i",
                str(locked_cut),
                "-vf",
                f"select='between(n\\,{chapter_start}\\,{chapter_end - 1})',setpts=N/FRAME_RATE/TB",
                "-frames:v",
                str(frame_count),
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "16",
                "-preset",
                "medium",
                "-pix_fmt",
                "yuv420p",
                str(pending_source),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                creationflags=hidden_subprocess_flags(),
            )
            if result.returncode != 0:
                raise RuntimeError(f"Could not stage exact chapter frames: {result.stderr[-1200:]}")
            if probe_video_identity(pending_source)["frameCount"] != frame_count:
                raise RuntimeError(f"Staged chapter frame count is not exact: {chapter_id}")
            pending_source.replace(cached_source)
            atomic_write_json(
                cached_source.with_name("source-identity.json"),
                {
                    "schemaVersion": ARTIFACT_SCHEMA_VERSION,
                    "sourceCacheKey": source_cache_key,
                    "lockedCutSha256": build_lock["lockedCutSha256"],
                    "absoluteStartFrame": chapter_start,
                    "absoluteEndFrameExclusive": chapter_end,
                    "outputSha256": sha256_file(cached_source),
                    "createdAt": utc_now(),
                },
            )
        if staged_source.is_file():
            if sha256_file(staged_source) != sha256_file(cached_source):
                raise RuntimeError(f"Immutable staged source changed: {chapter_id}")
        else:
            shutil.copyfile(cached_source, staged_source)

        markup = []
        timeline = []
        initially_hidden: set[str] = set()
        for sequence in manifest["sequences"]:
            if sequence["chapterId"] != chapter_id:
                continue
            compiled_sequence = compiled_by_id[sequence["id"]]
            graph = compiled_sequence["compiledGraph"]
            staged_assets: dict[str, str] = {}
            for asset in sequence["resolvedAssetRefs"]:
                asset_id = str(asset.get("id") or "")
                relative_path = asset.get("path")
                sha = asset.get("sha256")
                if not asset_id or not relative_path or not sha:
                    raise ValueError(f"Sequence {sequence['id']} has an incomplete asset reference.")
                source = content_addressed_object_path(root, sha)
                if not source.is_file() or sha256_file(source) != sha:
                    raise ValueError(f"Frozen sequence asset bytes are unavailable: {asset_id}")
                suffix = Path(relative_path).suffix.lower()
                destination = public / "assets" / f"{sha}{suffix}"
                if not destination.exists():
                    shutil.copyfile(source, destination)
                staged_assets[asset_id] = f"assets/{destination.name}"
            reveal_targets = {
                event["targetElementId"]
                for event in graph["events"]
                if event["operation"] in {"reveal", "enter", "show", "type-reveal"}
            }
            sequence_dom_id = f"sequence--{sequence['id']}"
            sequence_start = (sequence["absoluteStartFrame"] - chapter_start) / fps
            sequence_end = (sequence["absoluteEndFrameExclusive"] - chapter_start) / fps
            timeline.append(
                f"tl.set({_js(f'[id={json.dumps(sequence_dom_id)}]')},"
                f"{{autoAlpha:1,pointerEvents:'auto'}},{sequence_start:.9f});"
            )
            if sequence["absoluteEndFrameExclusive"] < chapter_end:
                timeline.append(
                    f"tl.set({_js(f'[id={json.dumps(sequence_dom_id)}]')},"
                    f"{{autoAlpha:0,pointerEvents:'none'}},{sequence_end:.9f});"
                )
            sequence_markup = []
            speaker_source_ids = {
                element["id"]
                for element in graph["elements"]
                if element["properties"].get("role") == "speaker-source"
            }
            initially_hidden.update(
                f"{sequence['id']}--{target}" for target in reveal_targets
            )
            for element in graph["elements"]:
                if element["properties"].get("role") == "speaker-source":
                    geometry = element["geometry"]
                    source_style = {
                        "left": f"{geometry['x'] * 100:.6f}%",
                        "top": f"{geometry['y'] * 100:.6f}%",
                        "width": f"{geometry['width'] * 100:.6f}%",
                        "height": f"{geometry['height'] * 100:.6f}%",
                        "objectFit": str(element["properties"].get("fit", "cover")),
                    }
                    timeline.append(
                        f"tl.set('#main-video',{_js(source_style)},{sequence_start:.9f});"
                    )
                rendered = _element_markup(
                    element,
                    staged_assets,
                    dom_id=f"{sequence['id']}--{element['id']}",
                )
                if rendered:
                    sequence_markup.append(rendered)
            markup.append(
                f'<section id="{html.escape(sequence_dom_id, quote=True)}" '
                f'class="sequence-layer">{"".join(sequence_markup)}</section>'
            )
            for event in graph["events"]:
                timeline.append(
                    _event_timeline_line(
                        event,
                        chapter_start=chapter_start,
                        fps=fps,
                        target_dom_id=(
                            "main-video"
                            if event["targetElementId"] in speaker_source_ids
                            else f"{sequence['id']}--{event['targetElementId']}"
                        ),
                    )
                )
        hidden_css = "".join(
            f'[id="{html.escape(element_id, quote=True)}"]{{opacity:0;}}'
            for element_id in sorted(initially_hidden)
        )
        duration_text = _frame_exact_duration_text(
            frame_count,
            fps_numerator=fps_numerator,
            fps_denominator=fps_denominator,
        )
        document = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body,#root{{margin:0;width:100%;height:100%;overflow:hidden;background:#000}}
#root{{position:relative;font-family:var(--font-body,Arial,sans-serif)}}
#main-video{{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover}}
.sequence-layer{{position:absolute;inset:0;opacity:0;visibility:hidden;pointer-events:none}}
.graph-element{{position:absolute;box-sizing:border-box;overflow:hidden}}
{hidden_css}
</style></head><body><div id="root" data-composition-id="{html.escape(chapter_id)}"
data-start="0" data-width="{width}" data-height="{height}" data-duration="{duration_text}"
data-fps="{fps:.9f}"><video id="main-video" class="clip" src="source.mp4" muted playsinline
data-start="0" data-duration="{duration_text}" data-track-index="0"></video>
{''.join(markup)}<script src="vendor/gsap.min.js"></script><script>
(function(){{window.__timelines=window.__timelines||{{}};const tl=gsap.timeline({{paused:true}});
{''.join(timeline)}
window.__timelines[{_js(chapter_id)}]=tl;}})();
</script></div></body></html>"""
        entry = public / "index.html"
        entry.write_text(document, encoding="utf-8")
        outputs[chapter_id] = entry
    return outputs


def chapter_cache_key(
    chapter_lock: dict,
    *,
    render_profile: dict,
    hyperframes_cli_hash: str,
    producer_adapter_hash: str,
) -> str:
    return canonical_hash(
        {
            "chapterInputHash": chapter_lock["chapterInputHash"],
            "renderProfile": render_profile,
            "hyperframesCliHash": hyperframes_cli_hash,
            "producerAdapterHash": producer_adapter_hash,
        }
    )


def augment_build_lock_with_browser_receipts(
    build_lock: dict,
    *,
    manifest: dict,
    receipt_ids_by_chapter: dict[str, list[str]],
) -> dict:
    already_present = True
    for sequence_lock in build_lock["sequences"]:
        required = set(receipt_ids_by_chapter.get(sequence_lock["chapterId"], []))
        if not required.issubset(set(sequence_lock["validationResultIds"])):
            already_present = False
            break
    if already_present:
        return json.loads(json.dumps(build_lock))
    updated = json.loads(json.dumps(build_lock))
    for sequence_lock in updated["sequences"]:
        receipt_ids = receipt_ids_by_chapter.get(sequence_lock["chapterId"], [])
        sequence_lock["validationResultIds"] = sorted(
            set([*sequence_lock["validationResultIds"], *receipt_ids])
        )
        sequence_lock["sequenceBuildHash"] = canonical_hash(
            {
                key: value
                for key, value in sequence_lock.items()
                if key != "sequenceBuildHash"
            }
        )
    for chapter_lock in updated["chapters"]:
        chapter = next(
            item for item in manifest["chapters"] if item["id"] == chapter_lock["chapterId"]
        )
        owned = [
            item
            for item in updated["sequences"]
            if item["chapterId"] == chapter_lock["chapterId"]
        ]
        owned_ids = {item["sequenceId"] for item in owned}
        dependencies = {
            "chapter": chapter,
            "sequenceBuildHashes": [item["sequenceBuildHash"] for item in owned],
            "transitionBoundaries": [
                boundary
                for boundary in manifest["transitionBoundaries"]
                if boundary["fromSequenceId"] in owned_ids
                or boundary["toSequenceId"] in owned_ids
            ],
        }
        chapter_lock["chapterInputHash"] = canonical_hash(dependencies)
    updated["createdAt"] = utc_now()
    updated["buildHash"] = canonical_hash(
        {key: value for key, value in updated.items() if key != "buildHash"}
    )
    validate_artifact("build-lock", updated)
    return updated


def plan_chapter_renders(
    private_root: Path,
    *,
    build_lock: dict,
    composition_paths: dict[str, Path],
    render_profile: dict,
) -> list[dict]:
    root = require_private_root(private_root)
    validate_artifact("build-lock", build_lock)
    jobs = []
    for chapter in build_lock["chapters"]:
        chapter_id = chapter["chapterId"]
        composition = composition_paths.get(chapter_id)
        if composition is None:
            raise ValueError(f"Chapter has no standalone composition: {chapter_id}")
        composition = composition.resolve()
        if not is_within(composition, root) or not composition.is_file():
            raise ValueError(f"Chapter composition is unavailable inside private storage: {chapter_id}")
        key = chapter_cache_key(
            chapter,
            render_profile=render_profile,
            hyperframes_cli_hash=build_lock["runtime"]["hyperframesCliHash"],
            producer_adapter_hash=build_lock["runtime"]["producerAdapterHash"],
        )
        output = (
            root
            / "creator-production"
            / "render-cache"
            / "chapters"
            / key[:2]
            / key
            / "chapter.mp4"
        )
        receipt_path = output.with_name("receipt.json")
        cached = False
        if output.is_file() and receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            cached = (
                receipt.get("cacheKey") == key
                and receipt.get("chapterInputHash") == chapter["chapterInputHash"]
                and receipt.get("outputSha256") == sha256_file(output)
                and receipt.get("status") == "verified"
            )
        jobs.append(
            {
                "chapterId": chapter_id,
                "chapterInputHash": chapter["chapterInputHash"],
                "absoluteStartFrame": chapter["absoluteStartFrame"],
                "absoluteEndFrameExclusive": chapter["absoluteEndFrameExclusive"],
                "expectedFrameCount": (
                    chapter["absoluteEndFrameExclusive"] - chapter["absoluteStartFrame"]
                ),
                "compositionPath": composition,
                "cacheKey": key,
                "outputPath": output,
                "receiptPath": receipt_path,
                "cacheStatus": "verified-hit" if cached else "miss",
            }
        )
    return jobs


def hyperframes_chapter_render_command(
    *,
    node_executable: Path,
    hyperframes_cli: Path,
    project_directory: Path,
    composition_path: Path,
    output_path: Path,
    fps: str,
    quality: str,
    workers: str = "auto",
) -> list[str]:
    if quality not in {"draft", "standard", "high"}:
        raise ValueError("Unknown HyperFrames render quality.")
    relative_composition = composition_path.resolve().relative_to(project_directory.resolve())
    return [
        str(node_executable),
        str(hyperframes_cli),
        "render",
        str(project_directory),
        "--composition",
        relative_composition.as_posix(),
        "--output",
        str(output_path),
        "--fps",
        fps,
        "--quality",
        quality,
        "--workers",
        workers,
        "--strict",
    ]


def probe_video_identity(path: Path) -> dict:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise RuntimeError("FFprobe is required for Creator Production render verification.")
    command = [
        str(ffprobe),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_read_frames",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not inspect rendered video: {(result.stderr or result.stdout)[-1200:]}")
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if len(streams) != 1:
        raise RuntimeError("Rendered chapter must contain exactly one video stream.")
    stream = streams[0]
    try:
        frame_count = int(stream["nb_read_frames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Rendered chapter has no exact decoded-frame count.") from exc
    return {
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "pixelFormat": stream.get("pix_fmt"),
        "rFrameRate": stream.get("r_frame_rate"),
        "averageFrameRate": stream.get("avg_frame_rate"),
        "frameCount": frame_count,
    }


def probe_audio_identity(path: Path) -> dict:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise RuntimeError("FFprobe is required for locked-audio verification.")
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,time_base,duration,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not inspect locked audio: {(result.stderr or result.stdout)[-1200:]}"
        )
    streams = (json.loads(result.stdout).get("streams") or [])
    if len(streams) != 1:
        raise RuntimeError("Media must contain exactly one primary locked-audio stream.")
    stream = streams[0]
    return {
        "codec": stream.get("codec_name"),
        "sampleRate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "timeBase": stream.get("time_base"),
        "duration": stream.get("duration"),
        "packetOrFrameCount": stream.get("nb_frames"),
    }


def record_verified_chapter_render(
    private_root: Path,
    *,
    job: dict,
    render_profile: dict,
    command: list[str],
) -> dict:
    root = require_private_root(private_root)
    output = Path(job["outputPath"]).resolve()
    if not is_within(output, root) or not output.is_file():
        raise RuntimeError("Chapter renderer did not produce its private cache output.")
    identity = probe_video_identity(output)
    if identity["frameCount"] != job["expectedFrameCount"]:
        raise RuntimeError(
            f"Chapter frame count mismatch for {job['chapterId']}: "
            f"expected {job['expectedFrameCount']}, found {identity['frameCount']}."
        )
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "chapterId": job["chapterId"],
        "chapterInputHash": job["chapterInputHash"],
        "cacheKey": job["cacheKey"],
        "status": "verified",
        "outputSha256": sha256_file(output),
        "outputRelativePath": output.relative_to(root).as_posix(),
        "renderProfile": render_profile,
        "videoIdentity": identity,
        "commandContract": {
            "usesStandaloneComposition": "--composition" in command,
            "strict": "--strict" in command,
            "nativeWorkflowSkillFlagPresent": "--skill" in command,
        },
        "verifiedAt": utc_now(),
    }
    if receipt["commandContract"]["nativeWorkflowSkillFlagPresent"]:
        raise RuntimeError("Production chapter renders may not inject a native workflow skill.")
    receipt["receiptHash"] = canonical_hash(receipt)
    atomic_write_json(Path(job["receiptPath"]), receipt)
    return receipt


def assert_chapter_stream_compatibility(receipts: list[dict]) -> dict:
    if not receipts:
        raise ValueError("At least one verified chapter is required for assembly.")
    identities = [receipt["videoIdentity"] for receipt in receipts]
    fields = ("codec", "width", "height", "pixelFormat", "rFrameRate")
    baseline = {field: identities[0][field] for field in fields}
    for receipt, identity in zip(receipts[1:], identities[1:]):
        mismatches = {
            field: (baseline[field], identity[field])
            for field in fields
            if identity[field] != baseline[field]
        }
        if mismatches:
            raise RuntimeError(
                f"Chapter stream is incompatible with lossless assembly: "
                f"{receipt['chapterId']} {mismatches}"
            )
    return baseline


def _decoded_frame_hashes(path: Path, frame_numbers: list[int]) -> dict[int, str]:
    requested = sorted(set(frame_numbers))
    if not requested:
        return {}
    expression = "+".join(f"eq(n\\,{frame})" for frame in requested)
    command = [
        str(find_ffmpeg()),
        "-v",
        "error",
        "-i",
        str(path),
        "-vf",
        f"select='{expression}'",
        "-map",
        "0:v:0",
        "-an",
        "-vsync",
        "0",
        "-f",
        "framemd5",
        "-",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not hash decoded seam frames: {(result.stderr or result.stdout)[-1200:]}"
        )
    digests = [
        line.rsplit(",", 1)[-1].strip()
        for line in result.stdout.splitlines()
        if line and not line.startswith("#") and "," in line
    ]
    if len(digests) != len(requested):
        raise RuntimeError(
            f"Decoded seam sample count changed: expected {len(requested)}, found {len(digests)}."
        )
    return dict(zip(requested, digests))


def verify_lossless_seams(
    *,
    assembled: Path,
    chapter_paths: list[Path],
    receipts: list[dict],
) -> dict:
    boundaries = []
    assembled_offset = 0
    for index, (chapter_path, receipt) in enumerate(zip(chapter_paths, receipts)):
        frame_count = int(receipt["videoIdentity"]["frameCount"])
        if index > 0:
            previous_receipt = receipts[index - 1]
            previous_path = chapter_paths[index - 1]
            previous_count = int(previous_receipt["videoIdentity"]["frameCount"])
            previous_frames = list(range(max(0, previous_count - 2), previous_count))
            next_frames = list(range(0, min(2, frame_count)))
            assembled_frames = [
                *range(assembled_offset - len(previous_frames), assembled_offset),
                *range(assembled_offset, assembled_offset + len(next_frames)),
            ]
            expected = [
                *_decoded_frame_hashes(previous_path, previous_frames).values(),
                *_decoded_frame_hashes(chapter_path, next_frames).values(),
            ]
            actual = list(_decoded_frame_hashes(assembled, assembled_frames).values())
            if actual != expected:
                raise RuntimeError(
                    f"Assembled seam changed decoded frames between "
                    f"{previous_receipt['chapterId']} and {receipt['chapterId']}."
                )
            boundaries.append(
                {
                    "fromChapterId": previous_receipt["chapterId"],
                    "toChapterId": receipt["chapterId"],
                    "absoluteBoundaryFrame": assembled_offset,
                    "sampledAssembledFrames": assembled_frames,
                    "decodedFrameHashes": actual,
                    "passed": True,
                }
            )
        assembled_offset += frame_count
    return {
        "algorithm": "decoded-frame-md5-two-before-two-after-v1",
        "boundaries": boundaries,
        "passed": True,
    }


def assemble_verified_chapters(
    private_root: Path,
    *,
    receipts: list[dict],
    locked_audio_source: Path,
    destination: Path,
    expected_total_frames: int,
    expected_locked_audio_sha256: str,
    provenance: dict,
) -> dict:
    root = require_private_root(private_root)
    assert_chapter_stream_compatibility(receipts)
    chapter_paths = []
    for receipt in receipts:
        if receipt.get("status") != "verified":
            raise RuntimeError(f"Chapter is not verified: {receipt.get('chapterId')}")
        path = (root / receipt["outputRelativePath"]).resolve()
        if not is_within(path, root) or not path.is_file() or sha256_file(path) != receipt["outputSha256"]:
            raise RuntimeError(f"Verified chapter bytes are missing or changed: {receipt['chapterId']}")
        chapter_paths.append(path)
    locked_audio_source = locked_audio_source.resolve()
    destination = destination.resolve()
    if not is_within(locked_audio_source, root) or not is_within(destination, root):
        raise ValueError("Assembly sources and destination must stay inside private storage.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if locked_audio_stream_hash(locked_audio_source) != expected_locked_audio_sha256:
        raise RuntimeError("Locked audio identity changed before final assembly.")
    concat_path = destination.with_suffix(".chapters.txt")
    concat_path.write_text(
        "".join(
            f"file '{path.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
            for path in chapter_paths
        ),
        encoding="utf-8",
    )
    silent_video = destination.with_suffix(".silent.mp4")
    ffmpeg = find_ffmpeg()
    commands = [
        [
            str(ffmpeg),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-an",
            str(silent_video),
        ],
        [
            str(ffmpeg),
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(locked_audio_source),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(destination),
        ],
    ]
    for command in commands:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            creationflags=hidden_subprocess_flags(),
        )
        if result.returncode != 0:
            raise RuntimeError(f"Chapter assembly failed: {(result.stderr or result.stdout)[-1200:]}")
    identity = probe_video_identity(destination)
    if identity["frameCount"] != expected_total_frames:
        raise RuntimeError(
            f"Assembled frame count mismatch: expected {expected_total_frames}, "
            f"found {identity['frameCount']}."
        )
    delivered_audio_hash = locked_audio_stream_hash(destination)
    if delivered_audio_hash != expected_locked_audio_sha256:
        raise RuntimeError(
            "Final assembly changed or truncated the locked audio packet stream."
        )
    source_audio_identity = probe_audio_identity(locked_audio_source)
    delivered_audio_identity = probe_audio_identity(destination)
    for field in ("codec", "sampleRate", "channels", "timeBase"):
        if delivered_audio_identity[field] != source_audio_identity[field]:
            raise RuntimeError(f"Final assembly changed locked-audio {field}.")
    seam_validation = verify_lossless_seams(
        assembled=destination,
        chapter_paths=chapter_paths,
        receipts=receipts,
    )
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "status": "assembled",
        **provenance,
        "chapterReceiptHashes": [receipt["receiptHash"] for receipt in receipts],
        "lockedAudioSourceSha256": expected_locked_audio_sha256,
        "outputSha256": sha256_file(destination),
        "outputRelativePath": destination.relative_to(root).as_posix(),
        "videoIdentity": identity,
        "audioIdentity": {
            "source": source_audio_identity,
            "delivered": delivered_audio_identity,
            "packetStreamSha256": delivered_audio_hash,
            "passed": True,
        },
        "seamValidation": seam_validation,
        "expectedTotalFrames": expected_total_frames,
        "assembledAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    validate_artifact("render-receipt", receipt)
    return receipt
