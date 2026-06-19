from __future__ import annotations

import json
import mimetypes
import subprocess
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from tkinter import Tk, filedialog

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app.core.audio_normalizer import (
    LoudnessHotspots,
    LoudnessMeasurement,
    analyze_audio,
    analyze_loudness_hotspots,
    create_audio_preview,
    normalize_video_audio,
    preset_options,
)
from app.core.pipeline import generate_captioned_video
from app.core.caption_grouping import group_words
from app.core.editor_pipeline import generate_editor_transcript
from app.core.edit_decisions import EditDecisionList
from app.core.editor_tokens import transcript_tokens
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.ffmpeg_runner import extract_audio
from app.core.project_store import editor_project_document, load_editor_project, save_editor_project
from app.core.settings import COMPUTE_OPTIONS, MODEL_OPTIONS, PRESETS, CaptionPreset, CaptionStyle, WordTimestamp, default_style, exports_dir, temp_dir
from app.core.splice_generation import DynamicSplice, SplicePlan, generate_splices
from app.core.splice_preview import source_splice_preview_segments
from app.core.style_library import delete_user_style, is_built_in_style, load_style_library, save_user_style
from app.core.transcriber import transcribe_audio
from app.core.transcript_model import TranscriptProject
from app.core.file_utils import validate_input_video
from app.core.video_cutter import frame_intervals_to_seconds, run_cut


class ApiState:
    project: TranscriptProject | None = None
    edits: EditDecisionList = EditDecisionList()
    project_path: Path | None = None
    transcript_video_path: Path | None = None
    caption_video_path: Path | None = None
    caption_preview_cache_key: tuple[str, str, str] | None = None
    caption_preview_words: list[WordTimestamp] | None = None
    audio_video_path: Path | None = None
    audio_analysis_key: tuple[str, str, float, float, float] | None = None
    audio_analysis: LoudnessMeasurement | None = None
    audio_hotspots: LoudnessHotspots | None = None
    audio_hotspots_source: Path | None = None
    audio_preview_id: str | None = None
    audio_preview_original: Path | None = None
    audio_preview_corrected: Path | None = None
    transcription_jobs: dict[str, TranscriptionJob]

    def __init__(self) -> None:
        self.project = None
        self.edits = EditDecisionList()
        self.project_path = None
        self.transcript_video_path = None
        self.caption_video_path = None
        self.caption_preview_cache_key = None
        self.caption_preview_words = None
        self.audio_video_path = None
        self.audio_analysis_key = None
        self.audio_analysis = None
        self.audio_hotspots = None
        self.audio_hotspots_source = None
        self.audio_preview_id = None
        self.audio_preview_original = None
        self.audio_preview_corrected = None
        self.transcription_jobs = {}


class TranscriptionJob:
    def __init__(self) -> None:
        self.status = "running"
        self.value = 0
        self.message = "Starting transcription..."
        self.result: dict | None = None
        self.error: str | None = None
        self.lock = threading.Lock()

    def update(self, value: int, message: str) -> None:
        with self.lock:
            self.value = value
            self.message = message

    def complete(self, result: dict) -> None:
        with self.lock:
            self.status = "complete"
            self.value = 100
            self.message = "Transcript ready."
            self.result = result

    def fail(self, error: str) -> None:
        with self.lock:
            self.status = "failed"
            self.error = error
            self.message = error

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "status": self.status,
                "value": self.value,
                "message": self.message,
                "result": self.result,
                "error": self.error,
            }


state = ApiState()
LOCAL_UI_ORIGINS = {"http://127.0.0.1:3000", "http://localhost:3000"}

app = FastAPI(
    title="VCG AutoCaption Local API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(LOCAL_UI_ORIGINS),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver"],
)


@app.middleware("http")
async def enforce_local_browser_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin is not None and origin not in LOCAL_UI_ORIGINS:
        return JSONResponse(
            status_code=403,
            content={"detail": "Requests are only accepted from the local VCG interface."},
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


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


class TranscribeProjectRequest(BaseModel):
    model_label: str
    compute_label: str


class CaptionStylePayload(BaseModel):
    font_family: str
    main_font_size: int
    active_font_size: int
    main_color: str
    active_color: str
    outline_color: str
    outline_width: int
    bold: bool
    active_bold: bool
    position: str
    margin_v: int
    outline_enabled: bool = True
    shadow_enabled: bool = False
    shadow_color: str = "#000000"
    shadow_depth: int = 5
    glow_enabled: bool = False
    glow_color: str = "#FF00CE"
    glow_strength: int = 5

    def to_style(self) -> CaptionStyle:
        return CaptionStyle(**self.model_dump())


class CaptionPresetPayload(BaseModel):
    name: str
    max_words: int
    max_duration: float
    max_chars: int

    def to_preset(self) -> CaptionPreset:
        return CaptionPreset(**self.model_dump())


class CaptionGenerateRequest(BaseModel):
    input_video_path: str | None = None
    output_folder: str | None = None
    style: CaptionStylePayload
    preset: CaptionPresetPayload
    model_label: str
    compute_label: str


class CaptionPreviewRequest(BaseModel):
    input_video_path: str | None = None
    preset: CaptionPresetPayload
    model_label: str
    compute_label: str


class CaptionStyleSaveRequest(BaseModel):
    name: str
    style: CaptionStylePayload


class AudioAnalyzeRequest(BaseModel):
    input_video_path: str | None = None
    preset_id: str = "gentle"
    target_i: float = -14.0
    target_lra: float = 7.0
    target_tp: float = -1.5


class AudioNormalizeRequest(AudioAnalyzeRequest):
    output_folder: str | None = None


class AudioPreviewRequest(AudioAnalyzeRequest):
    start_seconds: float = 0.0
    duration_seconds: float = 20.0


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


def _choose_project_save_file(project: TranscriptProject) -> Path | None:
    default_name = "editor-project.vcg.json"
    source_path = Path(project.source)
    if source_path.exists():
        default_name = f"{source_path.stem}.vcg.json"

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        filename = filedialog.asksaveasfilename(
            title="Save VCG project",
            initialfile=default_name,
            defaultextension=".vcg.json",
            filetypes=[("VCG project", "*.vcg.json"), ("JSON files", "*.json"), ("All files", "*.*")],
        )
    finally:
        root.destroy()
    return Path(filename).resolve() if filename else None


def _choose_video_file() -> Path | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        filename = filedialog.askopenfilename(
            title="Choose video",
            filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All files", "*.*")],
        )
    finally:
        root.destroy()
    return Path(filename).resolve() if filename else None


def _choose_output_folder() -> Path | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        folder = filedialog.askdirectory(title="Choose output folder")
    finally:
        root.destroy()
    return Path(folder).resolve() if folder else None


@app.get("/api/projects/current")
def current_project() -> dict:
    _require_project()
    return _project_response()


@app.post("/api/projects/choose-video")
def choose_transcript_video() -> dict:
    path = _choose_video_file()
    if path is None:
        raise HTTPException(status_code=400, detail="No video file selected.")
    state.transcript_video_path = path
    state.project = None
    state.edits = EditDecisionList()
    state.project_path = None
    return {"source": str(path)}


@app.post("/api/projects/transcribe")
def transcribe_project(payload: TranscribeProjectRequest) -> dict:
    if payload.model_label not in MODEL_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown Whisper model: {payload.model_label}")
    if payload.compute_label not in COMPUTE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown compute device: {payload.compute_label}")
    if state.transcript_video_path is None:
        raise HTTPException(status_code=400, detail="Choose a video before transcribing.")

    source = state.transcript_video_path.expanduser().resolve()
    validate_input_video(source)
    project = generate_editor_transcript(
        input_video_path=source,
        working_dir=temp_dir(),
        model_size=MODEL_OPTIONS[payload.model_label],
        compute_mode=payload.compute_label,
    )
    state.project = project
    state.edits = EditDecisionList()
    state.project_path = None
    state.caption_video_path = source
    return _project_response()


@app.post("/api/projects/transcribe/start")
def start_transcribe_project(payload: TranscribeProjectRequest) -> dict:
    if payload.model_label not in MODEL_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown Whisper model: {payload.model_label}")
    if payload.compute_label not in COMPUTE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown compute device: {payload.compute_label}")
    if state.transcript_video_path is None:
        raise HTTPException(status_code=400, detail="Choose a video before transcribing.")

    source = state.transcript_video_path.expanduser().resolve()
    validate_input_video(source)
    job_id = uuid.uuid4().hex
    job = TranscriptionJob()
    state.transcription_jobs[job_id] = job

    thread = threading.Thread(
        target=_run_transcription_job,
        args=(job, source, MODEL_OPTIONS[payload.model_label], payload.compute_label),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/projects/transcribe/jobs/{job_id}")
def transcribe_job_status(job_id: str) -> dict:
    job = state.transcription_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Transcription job not found.")
    return job.snapshot()


def _run_transcription_job(job: TranscriptionJob, source: Path, model_size: str, compute_mode: str) -> None:
    try:
        project = generate_editor_transcript(
            input_video_path=source,
            working_dir=temp_dir(),
            model_size=model_size,
            compute_mode=compute_mode,
            progress_callback=job.update,
        )
        state.project = project
        state.edits = EditDecisionList()
        state.project_path = None
        state.caption_video_path = source
        job.complete(_project_response())
    except Exception as exc:  # noqa: BLE001
        job.fail(str(exc))


@app.post("/api/projects/current/delete")
def delete_selection(payload: TokenSelectionRequest) -> dict:
    project = _require_project()
    word_ids, silence_ids = _partition_token_ids(project, payload.token_ids)
    if word_ids:
        start, end = _word_bounds(project, word_ids)
        state.edits.delete_word_selection(start, end)
    for silence_id in silence_ids:
        state.edits.delete_silence(f"delete_{silence_id}", silence_id)
    _save_current_project_if_loaded(project)
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
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/delete-dead-space")
def delete_dead_space() -> dict:
    project = _require_project()
    deleted = _deleted_silence_ids()
    for silence in project.silence_ranges:
        if silence.id not in deleted:
            state.edits.delete_silence(f"delete_{silence.id}", silence.id)
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/splices/adjust")
def adjust_splice(payload: AdjustSpliceRequest) -> dict:
    project = _require_project()
    state.edits.adjust_splice(
        payload.anchor_key,
        left_out_delta=payload.left_delta,
        right_in_delta=payload.right_delta,
    )
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/splices/review")
def review_splice(payload: ReviewSpliceRequest) -> dict:
    project = _require_project()
    state.edits.adjust_splice(payload.anchor_key, reviewed=payload.reviewed)
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/save")
def save_project() -> dict:
    project = _require_project()
    if state.project_path is None:
        path = _choose_project_save_file(project)
        if path is None:
            raise HTTPException(status_code=400, detail="No project file selected.")
        state.project_path = path
    save_editor_project(state.project_path, project, state.edits)
    return {"saved": str(state.project_path)}


@app.get("/api/projects/current/document")
def project_document() -> dict:
    project = _require_project()
    source = Path(project.source)
    filename = f"{source.stem if source.stem else 'editor-project'}.vcg.json"
    return {
        "filename": filename,
        "document": editor_project_document(project, state.edits),
    }


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


@app.get("/api/caption/options")
def caption_options() -> dict:
    styles = {name: asdict(style) for name, style in load_style_library().items()}
    project_source = state.project.source if state.project is not None else None
    caption_source = str(state.caption_video_path) if state.caption_video_path is not None else project_source
    return {
        "presets": {name: asdict(preset) for name, preset in PRESETS.items()},
        "models": MODEL_OPTIONS,
        "compute": COMPUTE_OPTIONS,
        "styles": styles,
        "built_in_styles": [name for name in styles if is_built_in_style(name)],
        "default_style": asdict(default_style()),
        "source": caption_source,
        "output_folder": str(exports_dir()),
    }


@app.post("/api/caption/choose-video")
def choose_caption_video() -> dict:
    path = _choose_video_file()
    if path is None:
        raise HTTPException(status_code=400, detail="No video file selected.")
    state.caption_video_path = path
    return {"source": str(path), "output_folder": str(exports_dir())}


@app.post("/api/caption/choose-output-folder")
def choose_caption_output_folder() -> dict:
    path = _choose_output_folder()
    if path is None:
        raise HTTPException(status_code=400, detail="No output folder selected.")
    return {"output_folder": str(path)}


@app.get("/api/audio/options")
def audio_options() -> dict:
    return {
        "presets": preset_options(),
        "source": str(state.audio_video_path) if state.audio_video_path else None,
        "output_folder": str(exports_dir()),
        "defaults": {
            "preset_id": "gentle",
            "target_i": -14.0,
            "target_lra": 7.0,
            "target_tp": -1.5,
        },
    }


@app.post("/api/audio/choose-video")
def choose_audio_video() -> dict:
    path = _choose_video_file()
    if path is None:
        raise HTTPException(status_code=400, detail="No video file selected.")
    state.audio_video_path = path
    state.audio_analysis_key = None
    state.audio_analysis = None
    state.audio_hotspots = None
    state.audio_hotspots_source = None
    _clear_audio_preview()
    return {"source": str(path), "output_folder": str(exports_dir())}


@app.post("/api/audio/choose-output-folder")
def choose_audio_output_folder() -> dict:
    path = _choose_output_folder()
    if path is None:
        raise HTTPException(status_code=400, detail="No output folder selected.")
    return {"output_folder": str(path)}


@app.post("/api/audio/analyze")
def analyze_video_audio(payload: AudioAnalyzeRequest) -> dict:
    source = _audio_source_path(payload.input_video_path)
    _validate_audio_targets(payload)
    try:
        measurement = analyze_audio(
            ffmpeg=find_ffmpeg(),
            input_video=source,
            preset_id=payload.preset_id,
            target_i=payload.target_i,
            target_lra=payload.target_lra,
            target_tp=payload.target_tp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    hotspot_error: str | None = None
    try:
        hotspots = analyze_loudness_hotspots(
            ffmpeg=find_ffmpeg(),
            input_video=source,
        )
    except RuntimeError as exc:
        hotspots = None
        hotspot_error = str(exc).split("\n\nFFmpeg details:", 1)[0]
    state.audio_video_path = source
    state.audio_analysis_key = _audio_analysis_key(source, payload)
    state.audio_analysis = measurement
    state.audio_hotspots = hotspots
    state.audio_hotspots_source = source if hotspots else None
    return {
        "source": str(source),
        "measurement": measurement.to_dict(),
        "target": {
            "integrated_lufs": payload.target_i,
            "loudness_range_lu": payload.target_lra,
            "true_peak_dbtp": payload.target_tp,
        },
        "hotspots": hotspots.to_dict() if hotspots else None,
        "hotspot_message": hotspot_error,
    }


@app.post("/api/audio/normalize")
def normalize_audio(payload: AudioNormalizeRequest) -> dict:
    source = _audio_source_path(payload.input_video_path)
    _validate_audio_targets(payload)
    key = _audio_analysis_key(source, payload)
    measurement = state.audio_analysis if state.audio_analysis_key == key else None
    if measurement is None:
        raise HTTPException(status_code=400, detail="Analyze this video with the selected preset before exporting.")
    output_root = Path(payload.output_folder).expanduser().resolve() if payload.output_folder else exports_dir()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{source.stem}_normalized.mp4"
    try:
        normalize_video_audio(
            ffmpeg=find_ffmpeg(),
            input_video=source,
            output_video=output_path,
            preset_id=payload.preset_id,
            measurement=measurement,
            target_i=payload.target_i,
            target_lra=payload.target_lra,
            target_tp=payload.target_tp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"output_path": str(output_path)}


@app.post("/api/audio/preview")
def generate_audio_preview(payload: AudioPreviewRequest) -> dict:
    source = _audio_source_path(payload.input_video_path)
    _validate_audio_targets(payload)
    if payload.start_seconds < 0:
        raise HTTPException(status_code=400, detail="Preview start time must be zero or greater.")
    if not 5.0 <= payload.duration_seconds <= 30.0:
        raise HTTPException(status_code=400, detail="Preview duration must be between 5 and 30 seconds.")

    key = _audio_analysis_key(source, payload)
    measurement = state.audio_analysis if state.audio_analysis_key == key else None
    if measurement is None:
        try:
            measurement = analyze_audio(
                ffmpeg=find_ffmpeg(),
                input_video=source,
                preset_id=payload.preset_id,
                target_i=payload.target_i,
                target_lra=payload.target_lra,
                target_tp=payload.target_tp,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state.audio_analysis_key = key
        state.audio_analysis = measurement
    hotspots = state.audio_hotspots if state.audio_hotspots_source == source else None
    hotspot_error: str | None = None
    if hotspots is None:
        try:
            hotspots = analyze_loudness_hotspots(
                ffmpeg=find_ffmpeg(),
                input_video=source,
            )
            state.audio_hotspots = hotspots
            state.audio_hotspots_source = source
        except RuntimeError as exc:
            hotspot_error = str(exc).split("\n\nFFmpeg details:", 1)[0]

    _clear_audio_preview()
    preview_id = uuid.uuid4().hex
    preview_root = temp_dir()
    original_path = preview_root / f"audio_preview_{preview_id}_original.mp4"
    corrected_path = preview_root / f"audio_preview_{preview_id}_corrected.mp4"
    try:
        create_audio_preview(
            ffmpeg=find_ffmpeg(),
            input_video=source,
            original_preview=original_path,
            corrected_preview=corrected_path,
            start_seconds=payload.start_seconds,
            duration_seconds=payload.duration_seconds,
            preset_id=payload.preset_id,
            measurement=measurement,
            target_i=payload.target_i,
            target_lra=payload.target_lra,
            target_tp=payload.target_tp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        message = str(exc).split("\n\nFFmpeg details:", 1)[0]
        raise HTTPException(status_code=500, detail=message) from exc
    state.audio_video_path = source
    state.audio_preview_id = preview_id
    state.audio_preview_original = original_path
    state.audio_preview_corrected = corrected_path
    return {
        "preview_id": preview_id,
        "start_seconds": payload.start_seconds,
        "duration_seconds": payload.duration_seconds,
        "measurement": measurement.to_dict(),
        "target": {
            "integrated_lufs": payload.target_i,
            "loudness_range_lu": payload.target_lra,
            "true_peak_dbtp": payload.target_tp,
        },
        "hotspots": hotspots.to_dict() if hotspots else None,
        "hotspot_message": hotspot_error,
    }


@app.post("/api/caption/styles")
def save_caption_style(payload: CaptionStyleSaveRequest) -> dict:
    try:
        save_user_style(payload.name, payload.style.to_style())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return caption_options()


@app.delete("/api/caption/styles/{name}")
def delete_caption_style(name: str) -> dict:
    if is_built_in_style(name):
        raise HTTPException(status_code=400, detail="Built-in styles cannot be deleted.")
    delete_user_style(name)
    return caption_options()


@app.post("/api/caption/generate")
def generate_caption_video(payload: CaptionGenerateRequest) -> dict:
    source_text = payload.input_video_path or (str(state.caption_video_path) if state.caption_video_path else None)
    if source_text is None and state.project is not None:
        source_text = state.project.source
    if source_text is None:
        raise HTTPException(status_code=400, detail="Choose a video before generating captions.")

    source = Path(source_text).expanduser().resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {source}")
    if payload.model_label not in MODEL_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown Whisper model: {payload.model_label}")
    if payload.compute_label not in COMPUTE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown compute device: {payload.compute_label}")

    output_root = Path(payload.output_folder).expanduser().resolve() if payload.output_folder else exports_dir()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{source.stem}_captioned.mp4"

    progress: list[dict[str, object]] = []

    def collect_progress(value: int, message: str) -> None:
        progress.append({"value": value, "message": message})

    output = generate_captioned_video(
        input_video_path=str(source),
        output_video_path=str(output_path),
        working_dir=str(temp_dir()),
        style=payload.style.to_style(),
        preset=payload.preset.to_preset(),
        model_size=MODEL_OPTIONS[payload.model_label],
        compute_mode=payload.compute_label,
        progress_callback=collect_progress,
    )
    state.caption_video_path = source
    return {"output_path": output, "progress": progress}


@app.post("/api/caption/preview")
def caption_preview(payload: CaptionPreviewRequest) -> dict:
    source = _caption_source_path(payload.input_video_path)
    if payload.model_label not in MODEL_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown Whisper model: {payload.model_label}")
    if payload.compute_label not in COMPUTE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown compute device: {payload.compute_label}")

    words, used_project_transcript = _caption_preview_words(
        source=source,
        model_size=MODEL_OPTIONS[payload.model_label],
        compute_label=payload.compute_label,
    )
    groups = group_words(
        words,
        max_words=payload.preset.max_words,
        max_duration=payload.preset.max_duration,
        max_chars=payload.preset.max_chars,
    )
    if not groups:
        raise HTTPException(status_code=400, detail="No speech was detected in this video.")
    state.caption_video_path = source
    return {
        "source": str(source),
        "word_count": len(words),
        "used_project_transcript": used_project_transcript,
        "words": [asdict(word) for word in words],
        "groups": [
            {
                "start": group.start,
                "end": group.end,
                "words": [asdict(word) for word in group.words],
            }
            for group in groups
        ],
    }


def _caption_source_path(input_video_path: str | None) -> Path:
    source_text = input_video_path or (str(state.caption_video_path) if state.caption_video_path else None)
    if source_text is None and state.project is not None:
        source_text = state.project.source
    if source_text is None:
        raise HTTPException(status_code=400, detail="Choose a video before preparing live captions.")

    source = Path(source_text).expanduser().resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {source}")
    return source


def _caption_preview_words(source: Path, model_size: str, compute_label: str) -> tuple[list[WordTimestamp], bool]:
    if state.project is not None and Path(state.project.source).expanduser().resolve() == source:
        return [
            WordTimestamp(text=word.text, start=word.start, end=word.end)
            for word in state.project.words
        ], True

    cache_key = (str(source), model_size, compute_label)
    if state.caption_preview_cache_key == cache_key and state.caption_preview_words is not None:
        return state.caption_preview_words, False

    validate_input_video(source)
    audio_path = extract_audio(source, temp_dir() / "caption_preview_audio.wav")
    words = transcribe_audio(audio_path, model_size=model_size, compute_mode=compute_label)
    state.caption_preview_cache_key = cache_key
    state.caption_preview_words = words
    return words, False


@app.get("/api/caption/source-video")
def caption_source_video(request: Request, range_header: str | None = Header(default=None, alias="Range")) -> Response:
    source_text = str(state.caption_video_path) if state.caption_video_path else None
    if source_text is None and state.project is not None:
        source_text = state.project.source
    if source_text is None:
        raise HTTPException(status_code=404, detail="No caption source video is loaded.")
    path = Path(source_text)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Source video not found: {path}")
    return _range_response(path, range_header)


@app.get("/api/audio/source-video")
def audio_source_video(request: Request, range_header: str | None = Header(default=None, alias="Range")) -> Response:
    if state.audio_video_path is None:
        raise HTTPException(status_code=404, detail="No audio normalizer source video is loaded.")
    if not state.audio_video_path.exists():
        raise HTTPException(status_code=404, detail=f"Source video not found: {state.audio_video_path}")
    return _range_response(state.audio_video_path, range_header)


@app.get("/api/audio/preview/{preview_id}/{mode}")
def audio_preview_media(preview_id: str, mode: str, range_header: str | None = Header(default=None, alias="Range")) -> Response:
    if preview_id != state.audio_preview_id:
        raise HTTPException(status_code=404, detail="Audio preview not found.")
    if mode == "original":
        path = state.audio_preview_original
    elif mode == "corrected":
        path = state.audio_preview_corrected
    else:
        raise HTTPException(status_code=400, detail="Preview mode must be original or corrected.")
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Audio preview file not found.")
    return _range_response(path, range_header)


@app.get("/api/projects/current/source-video")
def source_video(request: Request, range_header: str | None = Header(default=None, alias="Range")) -> Response:
    path = Path(state.project.source) if state.project is not None else state.transcript_video_path
    if path is None:
        raise HTTPException(status_code=404, detail="No transcript source video is loaded.")
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


def _audio_source_path(input_video_path: str | None) -> Path:
    source_text = input_video_path or (str(state.audio_video_path) if state.audio_video_path else None)
    if source_text is None:
        raise HTTPException(status_code=400, detail="Choose a video before analyzing its audio.")
    source = Path(source_text).expanduser().resolve()
    try:
        validate_input_video(source)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return source


def _audio_analysis_key(source: Path, payload: AudioAnalyzeRequest) -> tuple[str, str, float, float, float]:
    return (
        str(source),
        payload.preset_id,
        payload.target_i,
        payload.target_lra,
        payload.target_tp,
    )


def _validate_audio_targets(payload: AudioAnalyzeRequest) -> None:
    if not -24.0 <= payload.target_i <= -10.0:
        raise HTTPException(status_code=400, detail="Integrated loudness must be between -24 and -10 LUFS.")
    if not 1.0 <= payload.target_lra <= 20.0:
        raise HTTPException(status_code=400, detail="Loudness range must be between 1 and 20 LU.")
    if not -3.0 <= payload.target_tp <= -1.0:
        raise HTTPException(status_code=400, detail="True peak must be between -3 and -1 dBTP.")


def _clear_audio_preview() -> None:
    preview_root = temp_dir().resolve()
    for path in (state.audio_preview_original, state.audio_preview_corrected):
        if path is None:
            continue
        resolved = path.resolve()
        if resolved.parent == preview_root:
            try:
                resolved.unlink()
            except OSError:
                pass
    state.audio_preview_id = None
    state.audio_preview_original = None
    state.audio_preview_corrected = None


def _save_current_project_if_loaded(project: TranscriptProject) -> None:
    if state.project_path is not None:
        save_editor_project(state.project_path, project, state.edits)


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
