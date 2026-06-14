from __future__ import annotations

import json
import mimetypes
import subprocess
from dataclasses import asdict
from pathlib import Path
from tkinter import Tk, filedialog

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app.core.edit_decisions import EditDecisionList
from app.core.editor_tokens import transcript_tokens
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.project_store import load_editor_project, save_editor_project
from app.core.settings import exports_dir
from app.core.splice_generation import DynamicSplice, SplicePlan, generate_splices
from app.core.splice_preview import source_splice_preview_segments
from app.core.transcript_model import TranscriptProject
from app.core.video_cutter import frame_intervals_to_seconds, run_cut


class ApiState:
    project: TranscriptProject | None = None
    edits: EditDecisionList = EditDecisionList()
    project_path: Path | None = None


state = ApiState()
app = FastAPI(title="VCG AutoCaption Local API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OpenProjectRequest(BaseModel):
    path: str


class TokenSelectionRequest(BaseModel):
    token_ids: list[str]


class AdjustSpliceRequest(BaseModel):
    anchor_key: str
    left_delta: int = 0
    right_delta: int = 0


class ReviewSpliceRequest(BaseModel):
    anchor_key: str
    reviewed: bool


class ExportCutRequest(BaseModel):
    output_path: str | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/projects/open")
def open_project(payload: OpenProjectRequest) -> dict:
    path = Path(payload.path).expanduser().resolve()
    return _open_project_path(path)


@app.post("/api/projects/open-dialog")
def open_project_dialog() -> dict:
    path = _choose_project_file()
    if path is None:
        raise HTTPException(status_code=400, detail="No project file selected.")
    return _open_project_path(path)


def _open_project_path(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project file not found: {path}")
    project, edits = load_editor_project(path)
    state.project = project
    state.edits = edits
    state.project_path = path
    return _project_response()


def _choose_project_file() -> Path | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        filename = filedialog.askopenfilename(
            title="Open VCG project",
            filetypes=[("VCG project", "*.vcg.json"), ("JSON files", "*.json"), ("All files", "*.*")],
        )
    finally:
        root.destroy()
    return Path(filename).resolve() if filename else None


@app.get("/api/projects/current")
def current_project() -> dict:
    _require_project()
    return _project_response()


@app.post("/api/projects/current/delete")
def delete_selection(payload: TokenSelectionRequest) -> dict:
    project = _require_project()
    word_ids, silence_ids = _partition_token_ids(project, payload.token_ids)
    if word_ids:
        start, end = _word_bounds(project, word_ids)
        state.edits.delete_word_selection(start, end)
    for silence_id in silence_ids:
        state.edits.delete_silence(f"delete_{silence_id}", silence_id)
    return _project_response()


@app.post("/api/projects/current/restore")
def restore_selection(payload: TokenSelectionRequest) -> dict:
    project = _require_project()
    word_ids, silence_ids = _partition_token_ids(project, payload.token_ids)
    if word_ids:
        start, end = _word_bounds(project, word_ids)
        state.edits.restore_word_selection(start, end)
    for silence_id in silence_ids:
        state.edits.restore_silence(silence_id)
    return _project_response()


@app.post("/api/projects/current/splices/adjust")
def adjust_splice(payload: AdjustSpliceRequest) -> dict:
    _require_project()
    state.edits.adjust_splice(
        payload.anchor_key,
        left_out_delta=payload.left_delta,
        right_in_delta=payload.right_delta,
    )
    return _project_response()


@app.post("/api/projects/current/splices/review")
def review_splice(payload: ReviewSpliceRequest) -> dict:
    _require_project()
    state.edits.adjust_splice(payload.anchor_key, reviewed=payload.reviewed)
    return _project_response()


@app.post("/api/projects/current/save")
def save_project() -> dict:
    project = _require_project()
    if state.project_path is None:
        raise HTTPException(status_code=400, detail="No project path is loaded.")
    save_editor_project(state.project_path, project, state.edits)
    return {"saved": str(state.project_path)}


@app.post("/api/projects/current/export")
def export_cut(payload: ExportCutRequest) -> dict:
    project = _require_project()
    source = Path(project.source)
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {source}")
    plan = generate_splices(project, state.edits)
    intervals = plan.export_intervals()
    if not intervals:
        raise HTTPException(status_code=400, detail="No kept intervals to export.")
    output_path = Path(payload.output_path).expanduser().resolve() if payload.output_path else exports_dir() / f"{source.stem}_cut.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_cut(
        ffmpeg=find_ffmpeg(),
        input_video=source,
        output_video=output_path,
        intervals=frame_intervals_to_seconds(intervals, project.fps),
    )
    return {"output_path": str(output_path)}


@app.get("/api/projects/current/source-video")
def source_video(request: Request, range_header: str | None = Header(default=None, alias="Range")) -> Response:
    project = _require_project()
    path = Path(project.source)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Source video not found: {path}")
    return _range_response(path, range_header)


@app.get("/api/projects/current/frame")
def frame_image(frame: int) -> Response:
    project = _require_project()
    path = Path(project.source)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Source video not found: {path}")
    if frame < 0:
        raise HTTPException(status_code=400, detail="Frame must be zero or greater.")
    timestamp = frame / project.fps
    try:
        completed = subprocess.run(
            [
                str(find_ffmpeg()),
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.6f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:-1",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip() or "Could not extract frame."
        raise HTTPException(status_code=500, detail=detail) from exc
    if not completed.stdout:
        raise HTTPException(status_code=404, detail=f"No image produced for frame {frame}.")
    return Response(
        content=completed.stdout,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


def _require_project() -> TranscriptProject:
    if state.project is None:
        raise HTTPException(status_code=404, detail="No project is loaded.")
    return state.project


def _project_response() -> dict:
    project = _require_project()
    plan = generate_splices(project, state.edits)
    return {
        "project_path": str(state.project_path) if state.project_path else None,
        "project": _project_dict(project),
        "tokens": [asdict(token) for token in transcript_tokens(project)],
        "deleted_word_ids": sorted(_deleted_word_ids(project)),
        "deleted_silence_ids": sorted(_deleted_silence_ids()),
        "splices": [_splice_dict(splice, project.fps) for splice in plan.splices],
        "kept_ranges": [asdict(item) for item in plan.kept_ranges],
    }


def _project_dict(project: TranscriptProject) -> dict:
    return {
        "source": project.source,
        "fps": project.fps,
        "words": [asdict(word) for word in project.words],
        "silence_ranges": [asdict(silence) for silence in project.silence_ranges],
    }


def _splice_dict(splice: DynamicSplice, fps: float) -> dict:
    data = asdict(splice)
    data["preview_segments_2s"] = source_splice_preview_segments(splice, fps=fps, seconds=2)
    data["preview_segments_4s"] = source_splice_preview_segments(splice, fps=fps, seconds=4)
    data["preview_segments_6s"] = source_splice_preview_segments(splice, fps=fps, seconds=6)
    return data


def _partition_token_ids(project: TranscriptProject, token_ids: list[str]) -> tuple[list[str], list[str]]:
    word_ids = {word.id for word in project.words}
    silence_ids = {silence.id for silence in project.silence_ranges}
    selected_words = [token_id for token_id in token_ids if token_id in word_ids]
    selected_silences = [token_id for token_id in token_ids if token_id in silence_ids]
    return selected_words, selected_silences


def _word_bounds(project: TranscriptProject, word_ids: list[str]) -> tuple[str, str]:
    indexes = sorted(project.word_index(word_id) for word_id in word_ids)
    return project.words[indexes[0]].id, project.words[indexes[-1]].id


def _deleted_word_ids(project: TranscriptProject) -> set[str]:
    deleted: set[str] = set()
    for deleted_range in state.edits.deleted_word_ranges:
        start = project.word_index(deleted_range.start_word_id)
        end = project.word_index(deleted_range.end_word_id)
        if end < start:
            start, end = end, start
        deleted.update(word.id for word in project.words[start : end + 1])
    return deleted


def _deleted_silence_ids() -> set[str]:
    return {item.silence_id for item in state.edits.deleted_silence_ranges}


def _range_response(path: Path, range_header: str | None) -> Response:
    file_size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not range_header:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    start, end = _parse_range(range_header, file_size)
    length = end - start + 1

    def iterator():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return Response(
        content=b"".join(iterator()),
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        },
    )


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    try:
        units, value = range_header.split("=", 1)
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Invalid range header.") from exc
    if units.strip().lower() != "bytes":
        raise HTTPException(status_code=416, detail="Only byte ranges are supported.")
    start_text, _, end_text = value.partition("-")
    start = int(start_text) if start_text else 0
    end = int(end_text) if end_text else file_size - 1
    end = min(end, file_size - 1)
    if start < 0 or end < start or start >= file_size:
        raise HTTPException(status_code=416, detail="Requested range is not satisfiable.")
    return start, end
