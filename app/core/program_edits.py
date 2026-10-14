"""Stage 4 insert clips — program edit list on the locked-cut clock.

See docs/vcg-graphics-process/inserts.md.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.masterbeater import (
    extract_words,
    load_masterbeater_output,
    load_masterbeater_reviewed,
    load_transcript_document,
    sort_beats_by_timeline,
    transcript_fps,
)
from app.core.placement import (
    FinalRenderCanceled,
    PLACEMENT_VIDEO_EXTENSIONS,
    a_roll_output_path_for_project,
    placement_status_for_video_project,
    render_placement_final_for_video_project,
)
from app.core.video_project import preferred_stage_source, video_project_root

SCHEMA_VERSION = 1
EDITS_REL = "visual-production/program-edits.json"
TRANSCRIPT_REL = "transcripts/program-transcript.json"
INSERT_ID_RE = re.compile(r"^ins_[a-zA-Z0-9]{6,16}$")


def edits_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / EDITS_REL


def program_transcript_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / TRANSCRIPT_REL


def program_delivery_path_for_project(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / "exports" / "final-video.mp4"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _working_beats(project_root: Path) -> list[dict[str, Any]]:
    reviewed = load_masterbeater_reviewed(project_root)
    original = load_masterbeater_output(project_root)
    working = reviewed if reviewed is not None else original
    if working is None:
        return []
    return sort_beats_by_timeline(
        [b for b in (working.get("beats") or []) if isinstance(b, dict) and b.get("id")]
    )


def _beat_span(beat: dict[str, Any]) -> tuple[int, int] | None:
    start_raw = beat.get("startFrame")
    end = beat.get("endFrameExclusive")
    if end is None and beat.get("endFrame") is not None:
        try:
            end = int(beat["endFrame"]) + 1
        except (TypeError, ValueError):
            end = None
    try:
        start_i = int(start_raw)
        end_i = int(end)
    except (TypeError, ValueError):
        return None
    if end_i <= start_i:
        return None
    return max(0, start_i), end_i


def beat_spans(project_root: Path) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for beat in _working_beats(project_root):
        span = _beat_span(beat)
        if span is not None:
            spans.append(span)
    spans.sort(key=lambda item: (item[0], item[1]))
    return spans


def cut_end_frame_exclusive(duration_sec: float, fps: float) -> int:
    if fps <= 0 or duration_sec <= 0:
        return 1
    return max(1, int(round(float(duration_sec) * float(fps))))


def is_legal_t_frame(t_frame: int, spans: list[tuple[int, int]], cut_end: int) -> bool:
    if t_frame < 0 or t_frame > cut_end:
        return False
    for start, end_ex in spans:
        if start < t_frame < end_ex:
            return False
    return True


def legal_slots(spans: list[tuple[int, int]], cut_end: int) -> list[dict[str, int]]:
    slots: list[dict[str, int]] = []
    cursor = 0
    for start, end_ex in spans:
        if cursor <= start:
            slots.append({"startFrame": cursor, "endFrameExclusive": start})
        cursor = max(cursor, end_ex)
    if cursor <= cut_end:
        slots.append({"startFrame": cursor, "endFrameExclusive": cut_end})
    return slots


def empty_edits() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": _now(),
        "inserts": [],
    }


def load_program_edits(project_root: Path) -> dict[str, Any]:
    path = edits_path_for_project(project_root)
    if not path.is_file():
        return empty_edits()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return empty_edits()
    inserts = data.get("inserts")
    if not isinstance(inserts, list):
        inserts = []
    return {
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": str(data.get("updatedAt") or ""),
        "inserts": [row for row in inserts if isinstance(row, dict)],
    }


def _new_insert_id(existing: set[str]) -> str:
    for _ in range(16):
        candidate = f"ins_{uuid.uuid4().hex[:8]}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("Could not allocate an insert id.")


def insert_clip_path(project_root: Path, asset_id: str) -> Path:
    from app.core.placement import _find_placement_media

    found = _find_placement_media(project_root, asset_id, PLACEMENT_VIDEO_EXTENSIONS)
    if found is None or not found.is_file():
        raise FileNotFoundError(f"No frozen clip named {asset_id!r}.")
    return found.resolve()


def _clip_duration_sec(project_root: Path, asset_id: str) -> float:
    from app.core.visual_production import probe_visual_source

    path = insert_clip_path(project_root, asset_id)
    try:
        duration = float(probe_visual_source(path)["durationSec"])
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read duration for clip {asset_id!r}.") from exc
    if duration <= 0:
        raise ValueError(f"Could not read duration for clip {asset_id!r}.")
    return duration


def normalize_insert(
    row: dict[str, Any],
    *,
    project_root: Path,
    spans: list[tuple[int, int]],
    cut_end: int,
    existing_ids: set[str],
    probe_clip: bool = True,
) -> dict[str, Any]:
    insert_id = str(row.get("id") or "").strip()
    if insert_id and insert_id not in existing_ids and INSERT_ID_RE.fullmatch(insert_id):
        pass
    else:
        insert_id = _new_insert_id(existing_ids)
    try:
        t_frame = int(row.get("tFrame"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Insert tFrame must be an integer locked-cut frame.") from exc
    if not is_legal_t_frame(t_frame, spans, cut_end):
        raise ValueError(
            f"Insert T frame {t_frame} is inside a beat. v1 only allows gaps and beat boundaries."
        )
    asset_id = str(row.get("videoAssetId") or "").strip()
    if not asset_id:
        raise ValueError("Insert needs a frozen clip (videoAssetId).")
    try:
        clip_start = max(0.0, float(row.get("clipStartSec") or 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("clipStartSec must be a number.") from exc
    requested_used: float | None
    try:
        raw_used = row.get("durationSec")
        requested_used = float(raw_used) if raw_used is not None and str(raw_used) != "" else None
    except (TypeError, ValueError) as exc:
        raise ValueError("durationSec must be a number.") from exc
    clip_file_sec: float | None = None
    if probe_clip:
        clip_file_sec = _clip_duration_sec(project_root, asset_id)
        if clip_start >= clip_file_sec:
            raise ValueError("clipStartSec is past the end of the clip.")
    display = str(row.get("displayName") or "").strip()
    if not display:
        display = asset_id
    out: dict[str, Any] = {
        "id": insert_id,
        "tFrame": t_frame,
        "videoAssetId": asset_id,
        "clipStartSec": clip_start,
        "muted": bool(row.get("muted")),
        "displayName": display,
    }
    if clip_file_sec is not None:
        max_used = max(0.001, clip_file_sec - clip_start)
        used = max_used if requested_used is None else min(max(requested_used, 0.001), max_used)
        out["durationSec"] = used
        out["clipDurationSec"] = clip_file_sec
    elif requested_used is not None:
        out["durationSec"] = max(0.001, requested_used)
    return out


def save_program_edits(
    project_root: Path,
    inserts: list[dict[str, Any]],
    *,
    spans: list[tuple[int, int]],
    cut_end: int,
    probe_clip: bool = True,
) -> dict[str, Any]:
    existing: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in inserts:
        item = normalize_insert(
            row,
            project_root=project_root,
            spans=spans,
            cut_end=cut_end,
            existing_ids=existing,
            probe_clip=probe_clip,
        )
        existing.add(str(item["id"]))
        normalized.append(item)
    normalized.sort(key=lambda item: (int(item["tFrame"]), str(item["id"])))
    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": _now(),
        "inserts": normalized,
    }
    path = edits_path_for_project(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def _probe_cut(manifest_path: Path, manifest: dict) -> tuple[Path, dict[str, Any], float]:
    from app.core.visual_production import probe_visual_source

    source = preferred_stage_source(manifest_path, manifest)
    if not source.is_file():
        raise FileNotFoundError("No locked cut / stage source for insert placement.")
    probed = probe_visual_source(source)
    fps = float(probed.get("fps") or 30.0)
    return source, probed, fps


def _cut_end_for_project(manifest_path: Path, manifest: dict) -> tuple[int, float, float]:
    _source, probed, fps = _probe_cut(manifest_path, manifest)
    duration = float(probed.get("durationSec") or 0.0)
    return cut_end_frame_exclusive(duration, fps), fps, duration


def build_program_timeline(
    inserts: list[dict[str, Any]],
    *,
    cut_end: int,
    fps: float,
) -> list[dict[str, Any]]:
    if fps <= 0:
        raise ValueError("FPS must be greater than zero.")
    ordered = sorted(
        [row for row in inserts if isinstance(row, dict)],
        key=lambda item: (int(item.get("tFrame") or 0), str(item.get("id") or "")),
    )
    pieces: list[dict[str, Any]] = []
    cursor = 0
    program = 0

    def _aroll(start: int, end: int) -> None:
        nonlocal program
        if end <= start:
            return
        duration_frames = end - start
        pieces.append(
            {
                "kind": "aroll",
                "cutStartFrame": start,
                "cutEndFrameExclusive": end,
                "programStartFrame": program,
                "programEndFrameExclusive": program + duration_frames,
                "startSec": start / fps,
                "durationSec": duration_frames / fps,
            }
        )
        program += duration_frames

    for row in ordered:
        t_frame = int(row["tFrame"])
        _aroll(cursor, t_frame)
        duration_sec = float(row.get("durationSec") or 0.0)
        duration_frames = max(1, int(round(duration_sec * fps)))
        pieces.append(
            {
                "kind": "insert",
                "insertId": row.get("id"),
                "videoAssetId": row.get("videoAssetId"),
                "displayName": row.get("displayName"),
                "tFrame": t_frame,
                "clipStartSec": float(row.get("clipStartSec") or 0.0),
                "muted": bool(row.get("muted")),
                "programStartFrame": program,
                "programEndFrameExclusive": program + duration_frames,
                "startSec": float(row.get("clipStartSec") or 0.0),
                "durationSec": duration_frames / fps,
            }
        )
        program += duration_frames
        cursor = max(cursor, t_frame)
    _aroll(cursor, cut_end)
    return pieces


def program_duration_frames(pieces: list[dict[str, Any]]) -> int:
    if not pieces:
        return 0
    return int(pieces[-1]["programEndFrameExclusive"])


def insert_wait_before_frame(inserts: list[dict[str, Any]], source_frame: int, fps: float) -> int:
    wait = 0
    for row in inserts:
        t_frame = int(row.get("tFrame") or 0)
        if t_frame <= source_frame:
            duration_sec = float(row.get("durationSec") or 0.0)
            wait += max(1, int(round(duration_sec * fps)))
    return wait


def shift_aroll_word(
    word: dict[str, Any],
    *,
    inserts: list[dict[str, Any]],
    fps: float,
) -> dict[str, Any]:
    try:
        start_frame = int(word.get("start_frame", word.get("startFrame")))
        end_frame = int(word.get("end_frame", word.get("endFrame")))
    except (TypeError, ValueError):
        start_frame = 0
        end_frame = 0
    wait = insert_wait_before_frame(inserts, start_frame, fps)
    out = dict(word)
    out["sourceStartFrame"] = start_frame
    out["sourceEndFrame"] = end_frame
    out["start_frame"] = start_frame + wait
    out["end_frame"] = end_frame + wait
    out["start"] = (start_frame + wait) / fps
    out["end"] = (end_frame + wait) / fps
    out["clock"] = "program"
    return out


def _transcribe_insert_words(
    clip_path: Path,
    *,
    work_dir: Path,
    model_size: str,
    compute_mode: str,
) -> list[Any]:
    from app.core.ffmpeg_runner import extract_audio
    from app.core.transcriber import transcribe_audio

    audio_path = work_dir / f"{clip_path.stem}-insert.wav"
    extract_audio(clip_path, audio_path)
    try:
        return transcribe_audio(audio_path, model_size=model_size, compute_mode=compute_mode)
    except RuntimeError as exc:
        if "No speech" in str(exc):
            return []
        raise


def build_program_transcript(
    manifest_path: Path,
    manifest: dict,
    *,
    pieces: list[dict[str, Any]],
    inserts: list[dict[str, Any]],
    fps: float,
    transcribe_clip: Callable[..., list[Any]] | None = None,
    model_size: str | None = None,
    compute_mode: str | None = None,
) -> dict[str, Any]:
    from app.core.masterbeater import final_transcript_path
    from app.core.settings import DEFAULT_COMPUTE_LABEL, DEFAULT_MODEL_LABEL, MODEL_OPTIONS
    from app.core.visual_production import probe_has_audio_stream

    root = video_project_root(manifest_path)
    transcript_path = final_transcript_path(manifest_path, manifest)
    document = load_transcript_document(transcript_path)
    aroll_words = extract_words(document)
    if fps <= 0:
        fps = transcript_fps(document)

    generation = (document.get("project") or document).get("generation") or {}
    model_label = str(generation.get("modelLabel") or DEFAULT_MODEL_LABEL)
    model_size = model_size or MODEL_OPTIONS.get(model_label, MODEL_OPTIONS[DEFAULT_MODEL_LABEL])
    compute_mode = compute_mode or str(generation.get("computeLabel") or DEFAULT_COMPUTE_LABEL)

    words: list[dict[str, Any]] = []
    for word in aroll_words:
        words.append(shift_aroll_word(word, inserts=inserts, fps=fps))

    insert_by_id = {str(row.get("id")): row for row in inserts}
    work = root / "working" / "program-edits"
    transcribe_clip = transcribe_clip or (
        lambda clip_path: _transcribe_insert_words(
            clip_path, work_dir=work, model_size=model_size, compute_mode=compute_mode
        )
    )

    for piece in pieces:
        if piece.get("kind") != "insert":
            continue
        insert_id = str(piece.get("insertId") or "")
        row = insert_by_id.get(insert_id) or {}
        display = str(row.get("displayName") or insert_id)
        program_start = int(piece["programStartFrame"])
        program_end = int(piece["programEndFrameExclusive"])
        marker = {
            "id": f"ins:{insert_id}:marker",
            "text": display,
            "raw": f"[{display}]",
            "kind": "insert-marker",
            "insertId": insert_id,
            "start_frame": program_start,
            "end_frame": program_start,
            "start": program_start / fps,
            "end": program_start / fps,
            "clock": "program",
        }
        words.append(marker)
        if row.get("muted"):
            continue
        asset_id = str(row.get("videoAssetId") or "")
        try:
            clip_path = insert_clip_path(root, asset_id)
        except (FileNotFoundError, ValueError):
            continue
        try:
            has_audio = probe_has_audio_stream(clip_path)
        except RuntimeError:
            has_audio = False
        if not has_audio:
            continue
        work.mkdir(parents=True, exist_ok=True)
        clip_words = transcribe_clip(clip_path)
        clip_start = float(row.get("clipStartSec") or 0.0)
        duration_sec = float(piece.get("durationSec") or 0.0)
        program_start_sec = program_start / fps
        for index, stamped in enumerate(clip_words, start=1):
            local_start = float(stamped.start) - clip_start
            local_end = float(stamped.end) - clip_start
            if local_end <= 0 or local_start >= duration_sec:
                continue
            local_start = max(0.0, local_start)
            local_end = min(duration_sec, local_end)
            if local_end <= local_start:
                continue
            start_sec = program_start_sec + local_start
            end_sec = program_start_sec + local_end
            words.append(
                {
                    "id": f"ins:{insert_id}:w:{index:06d}",
                    "text": stamped.text.strip(),
                    "raw": stamped.text,
                    "kind": "insert-word",
                    "insertId": insert_id,
                    "start": start_sec,
                    "end": end_sec,
                    "start_frame": int(round(start_sec * fps)),
                    "end_frame": int(round(end_sec * fps)),
                    "clock": "program",
                }
            )

    words.sort(key=lambda item: (int(item.get("start_frame") or 0), str(item.get("id") or "")))
    duration_frames = program_duration_frames(pieces)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "clock": "program",
        "fps": fps,
        "durationSec": duration_frames / fps if fps else 0.0,
        "durationFrames": duration_frames,
        "updatedAt": _now(),
        "words": words,
        "inserts": [
            {
                "id": row.get("id"),
                "displayName": row.get("displayName"),
                "tFrame": row.get("tFrame"),
                "muted": bool(row.get("muted")),
            }
            for row in inserts
        ],
    }


def build_program_concat_filter(
    pieces: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    fps: float,
    sample_rate: int = 48000,
) -> str:
    if not pieces:
        raise ValueError("Program list is empty.")
    video_pad = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},setsar=1,format=yuv420p"
    )
    filters: list[str] = []
    concat_refs: list[str] = []
    for index, piece in enumerate(pieces):
        input_index = int(piece["inputIndex"])
        start = float(piece["startSec"])
        duration = float(piece["durationSec"])
        end = start + duration
        filters.append(
            f"[{input_index}:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
            f"{video_pad}[v{index}]"
        )
        muted = bool(piece.get("muted")) or not piece.get("hasAudio")
        if muted:
            filters.append(
                f"anullsrc=channel_layout=stereo:sample_rate={sample_rate},"
                f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo[a{index}]"
            )
        else:
            filters.append(
                f"[{input_index}:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo[a{index}]"
            )
        concat_refs.extend([f"[v{index}]", f"[a{index}]"])
    filters.append(f"{''.join(concat_refs)}concat=n={len(pieces)}:v=1:a=1[outv][outa]")
    return ";".join(filters)


def build_program_concat_command(
    *,
    ffmpeg: Path,
    output: Path,
    input_paths: list[Path],
    filter_complex: str,
) -> list[str]:
    command: list[str] = [str(ffmpeg), "-y"]
    for path in input_paths:
        command.extend(["-i", str(path)])
    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return command


def _piece_inputs(
    pieces: list[dict[str, Any]],
    *,
    a_roll: Path,
    project_root: Path,
) -> tuple[list[Path], list[dict[str, Any]]]:
    from app.core.visual_production import probe_has_audio_stream

    inputs: list[Path] = [a_roll]
    aroll_has_audio = True
    try:
        aroll_has_audio = probe_has_audio_stream(a_roll)
    except RuntimeError:
        aroll_has_audio = True
    prepared: list[dict[str, Any]] = []
    insert_index: dict[str, int] = {}
    for piece in pieces:
        row = dict(piece)
        if piece.get("kind") == "aroll":
            row["inputIndex"] = 0
            row["hasAudio"] = aroll_has_audio
            row["muted"] = False
        else:
            asset_id = str(piece.get("videoAssetId") or "")
            if asset_id not in insert_index:
                clip = insert_clip_path(project_root, asset_id)
                insert_index[asset_id] = len(inputs)
                inputs.append(clip)
            row["inputIndex"] = insert_index[asset_id]
            clip_path = inputs[row["inputIndex"]]
            try:
                row["hasAudio"] = probe_has_audio_stream(clip_path)
            except RuntimeError:
                row["hasAudio"] = False
        prepared.append(row)
    return inputs, prepared


def assemble_program_media(
    *,
    a_roll: Path,
    pieces: list[dict[str, Any]],
    project_root: Path,
    output: Path,
    width: int,
    height: int,
    fps: float,
    progress: Callable[[int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process: Callable[[subprocess.Popen[str] | None], None] | None = None,
) -> Path:
    from app.core.ffmpeg_locator import find_ffmpeg
    from app.core.process_utils import hidden_subprocess_flags, terminate_process_tree
    from app.core.visual_production import publish_verified_render

    progress = progress or (lambda _v, _m: None)
    cancel_check = cancel_check or (lambda: False)
    on_process = on_process or (lambda _p: None)

    if cancel_check():
        raise FinalRenderCanceled("Final render canceled.")
    work = Path(project_root).expanduser().resolve() / "working" / "program-edits"
    work.mkdir(parents=True, exist_ok=True)
    staged = work / f".program-{uuid.uuid4().hex[:8]}.mp4"

    insert_count = sum(1 for piece in pieces if piece.get("kind") == "insert")
    if insert_count == 0:
        progress(88, "No inserts — publishing A-roll master as the program...")
        shutil.copy2(a_roll, staged)
        published = publish_verified_render(staged, output)
        return published

    inputs, prepared = _piece_inputs(pieces, a_roll=a_roll, project_root=project_root)
    filter_complex = build_program_concat_filter(
        prepared, width=width, height=height, fps=fps
    )
    command = build_program_concat_command(
        ffmpeg=find_ffmpeg(),
        output=staged,
        input_paths=inputs,
        filter_complex=filter_complex,
    )
    progress(70, "Assembling program (A-roll slices + insert clips)...")
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=hidden_subprocess_flags(),
        )
        on_process(process)
        captured: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            if cancel_check():
                terminate_process_tree(process)
                raise FinalRenderCanceled("Final render canceled.")
            captured.append(line)
        code = process.wait()
        on_process(None)
        process = None
        if cancel_check():
            raise FinalRenderCanceled("Final render canceled.")
        if code != 0 or not staged.is_file() or staged.stat().st_size == 0:
            raise RuntimeError("Program concat failed. " + ("".join(captured)[-1800:]))
        published = publish_verified_render(staged, output)
        return published
    except FinalRenderCanceled:
        if process is not None:
            terminate_process_tree(process)
            on_process(None)
        raise
    finally:
        if process is not None:
            on_process(None)
        staged.unlink(missing_ok=True)


def program_status_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    library_root: Path | None = None,
) -> dict[str, Any]:
    del library_root
    root = video_project_root(manifest_path)
    placement = placement_status_for_video_project(manifest_path, manifest)
    locked_ready = bool(placement.get("finalRenderReady"))
    try:
        cut_end, fps, duration = _cut_end_for_project(manifest_path, manifest)
    except (FileNotFoundError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
        cut_end, fps, duration = 1, 30.0, 0.0
    spans = beat_spans(root)
    edits = load_program_edits(root)
    inserts: list[dict[str, Any]] = []
    for row in edits.get("inserts") or []:
        try:
            inserts.append(
                normalize_insert(
                    row,
                    project_root=root,
                    spans=spans,
                    cut_end=cut_end,
                    existing_ids={str(item.get("id") or "") for item in inserts},
                    probe_clip=True,
                )
            )
        except (FileNotFoundError, ValueError):
            inserts.append(dict(row))
    pieces = build_program_timeline(inserts, cut_end=cut_end, fps=fps)
    a_roll = a_roll_output_path_for_project(root)
    delivery = program_delivery_path_for_project(root)
    return {
        "ok": True,
        "ready": locked_ready,
        "editsPath": str(edits_path_for_project(root)),
        "editsExist": edits_path_for_project(root).is_file(),
        "insertCount": len(inserts),
        "inserts": inserts,
        "legalSlots": legal_slots(spans, cut_end),
        "pieces": pieces,
        "cutEndFrameExclusive": cut_end,
        "cutDurationSec": duration,
        "fps": fps,
        "programDurationFrames": program_duration_frames(pieces),
        "programDurationSec": program_duration_frames(pieces) / fps if fps else 0.0,
        "aRollExists": a_roll.is_file() and a_roll.stat().st_size > 0,
        "aRollPath": str(a_roll),
        "deliveryExists": delivery.is_file() and delivery.stat().st_size > 0,
        "deliveryPath": str(delivery),
        "transcriptPath": str(program_transcript_path_for_project(root)),
        "transcriptExists": program_transcript_path_for_project(root).is_file(),
    }


def save_program_edits_for_video_project(
    manifest_path: Path,
    manifest: dict,
    payload: dict[str, Any],
) -> dict[str, Any]:
    root = video_project_root(manifest_path)
    cut_end, fps, _duration = _cut_end_for_project(manifest_path, manifest)
    spans = beat_spans(root)
    raw_inserts = payload.get("inserts")
    if not isinstance(raw_inserts, list):
        raise ValueError("inserts must be a list.")
    save_program_edits(root, raw_inserts, spans=spans, cut_end=cut_end, probe_clip=True)
    return program_status_for_video_project(manifest_path, manifest)


def render_program_final_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    quality: str = "standard",
    force: bool = False,
    progress: Callable[[int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process: Callable[[subprocess.Popen[str] | None], None] | None = None,
    transcribe_clip: Callable[..., list[Any]] | None = None,
) -> dict[str, Any]:
    """Ensure A-roll master, concat the program list, write program transcript, publish."""

    from app.core.visual_production import probe_visual_source

    progress = progress or (lambda _v, _m: None)
    cancel_check = cancel_check or (lambda: False)
    on_process = on_process or (lambda _p: None)

    root = video_project_root(manifest_path)
    placement = placement_status_for_video_project(manifest_path, manifest)
    if not placement.get("finalRenderReady"):
        raise ValueError("Lock every assigned placement before Stage 4 Final.")

    progress(2, "Encoding A-roll master (locked graphics on the locked cut)...")
    aroll_result = render_placement_final_for_video_project(
        manifest_path,
        manifest,
        quality=quality,
        force=force,
        progress=lambda value, message: progress(min(65, max(2, int(value * 0.65))), message),
        cancel_check=cancel_check,
        on_process=on_process,
    )
    a_roll = Path(str(aroll_result["outputPath"]))
    if not a_roll.is_file():
        raise RuntimeError("A-roll master was not written.")

    cut_end, fps, _cut_duration = _cut_end_for_project(manifest_path, manifest)
    spans = beat_spans(root)
    edits = load_program_edits(root)
    inserts = save_program_edits(
        root,
        [row for row in (edits.get("inserts") or []) if isinstance(row, dict)],
        spans=spans,
        cut_end=cut_end,
        probe_clip=True,
    )["inserts"]
    pieces = build_program_timeline(inserts, cut_end=cut_end, fps=fps)
    probed = probe_visual_source(a_roll)
    width = int(probed.get("width") or 1920)
    height = int(probed.get("height") or 1080)
    delivery = program_delivery_path_for_project(root)
    progress(68, "Building program list...")
    published = assemble_program_media(
        a_roll=a_roll,
        pieces=pieces,
        project_root=root,
        output=delivery,
        width=width,
        height=height,
        fps=float(probed.get("fps") or fps),
        progress=progress,
        cancel_check=cancel_check,
        on_process=on_process,
    )
    progress(92, "Writing program transcript...")
    transcript = build_program_transcript(
        manifest_path,
        manifest,
        pieces=pieces,
        inserts=inserts,
        fps=fps,
        transcribe_clip=transcribe_clip,
    )
    t_path = program_transcript_path_for_project(root)
    t_path.parent.mkdir(parents=True, exist_ok=True)
    t_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    progress(100, "Program Final ready.")
    return {
        "ok": True,
        "outputPath": str(published),
        "aRollPath": str(a_roll),
        "aRollReused": bool(aroll_result.get("reused")),
        "insertCount": len(inserts),
        "programDurationSec": transcript["durationSec"],
        "transcriptPath": str(t_path),
        "quality": quality,
    }
