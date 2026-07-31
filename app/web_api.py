from __future__ import annotations

import copy
import json
import mimetypes
import subprocess
import threading
import time
import urllib.error
import uuid
import wave
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core.audio_normalizer import (
    LoudnessHotspots,
    LoudnessMeasurement,
    analyze_audio,
    analyze_loudness_hotspots,
    create_audio_preview,
    normalize_video_audio,
    preset_options,
)
from app.core.audio_boundary import (
    MAX_EXTENSION_SECONDS,
    analyze_pause_candidates,
    suggest_word_end_boundaries,
)
from app.core.pipeline import generate_captioned_video
from app.core.caption_grouping import group_words
from app.core.editor_pipeline import generate_editor_transcript
from app.core.edit_decisions import EditDecisionList
from app.core.editor_tokens import transcript_tokens
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.ffmpeg_runner import extract_audio
from app.core.project_store import editor_project_document, load_editor_project, save_editor_project
from app.core.repetition_detection import detect_repeated_word_ids
from app.core.settings import COMPUTE_OPTIONS, MODEL_OPTIONS, PRESETS, CaptionPreset, CaptionStyle, WordTimestamp, default_style, exports_dir, project_root, temp_dir
from app.core.splice_generation import DynamicSplice, InvalidCutPlanError, SplicePlan, generate_splices
from app.core.splice_preview import source_splice_preview_segments
from app.core.style_library import delete_user_style, is_built_in_style, load_style_library, save_user_style
from app.core.story_assets import (
    build_review_prompt,
    build_nonmedia_suggestion,
    create_recipe_suggestion,
    credits_text,
    creator_asset_path,
    default_creator_library,
    decide_suggestion,
    freeze_creator_asset,
    import_creator_asset,
    load_creator_library,
    load_visual_catalog,
    load_visual_suggestions,
    pexels_settings,
    prepare_suggestion_approval_evidence,
    recipe_preview_path,
    suggestion_approval_frame_path,
    treatment_motion_preview_path,
    save_pexels_key,
    search_creator_library,
    search_pexels_videos,
    select_pexels_candidate,
    update_creator_asset,
    update_suggestion,
    update_treatment_metadata,
)
from app.core.transcriber import transcribe_audio
from app.core.transcript_history import build_edit_analysis, build_generation_metadata, with_initial_repeat_suggestions
from app.core.transcript_remap import remap_transcript
from app.core.transcript_model import TranscriptProject
from app.core.creator_production import transcript_word_timing_hash
from app.core.creator_production import (
    accept_review_note,
    create_approval_record,
    next_artifact_version,
    save_review_note,
    utc_now,
    write_versioned_artifact,
)
from app.core.creator_project import (
    promote_creator_artifact,
    transition_creator_project,
    upgrade_creator_workflow_package,
    verify_live_workflow_package_matches_lock,
)
from app.core.file_utils import sha256_file, validate_input_video
from app.core.video_cutter import frame_intervals_to_seconds, run_cut
from app.core.visual_production import (
    active_visual_master,
    active_visual_revision,
    active_visual_runtime,
    approve_full_review,
    approve_representative_scene,
    build_hyperframes_composition,
    create_visual_plan_in_video_project,
    create_visual_project,
    find_visual_root,
    import_visual_asset,
    load_visual_plan,
    render_visual_plan,
    resolve_project_path,
    save_visual_plan,
    scene_frame_preview,
    verify_delivered_revision_reopened,
    visual_production_gate_report,
    visual_plan_response,
)
from app.core.creator_project import (
    available_channel_profiles,
    ensure_capture_layout_catalog,
    initialize_creator_project,
    resolve_hyperframes_animation_source,
    verify_creator_project,
)
from app.core.creator_jobs import CreatorJobStore
from app.core.creator_evidence import save_source_evidence, source_evidence_draft
from app.core.creator_render_jobs import CreatorRenderJobStore
from app.core.creator_rendering import resolve_creator_renderer_assets
from app.core.creator_studio import create_studio_handoff, persist_studio_edits
from app.core.creator_production import read_frozen_bytes
from app.core.video_project import (
    DEFAULT_PROJECT_PATHS,
    VIDEO_PROJECT_SUFFIX,
    add_source_clips,
    artifact_current,
    build_visual_plan_prompt,
    create_video_project_from_sources,
    load_video_project,
    mark_artifact_current,
    preferred_stage_source,
    remove_source_clip,
    reorder_source_clips,
    resolve_video_project_path,
    save_video_project,
    video_project_response,
    video_project_root,
)
from app.core.windows_dialog import (
    choose_output_folder as _windows_choose_output_folder,
    choose_project_file as _windows_choose_project_file,
    choose_project_save_file as _windows_choose_project_save_file,
    choose_video_file as _windows_choose_video_file,
    choose_video_files as _windows_choose_video_files,
    choose_visual_asset_file as _windows_choose_visual_asset_file,
    choose_visual_plan_file as _windows_choose_visual_plan_file,
)


class ApiState:
    video_project_path: Path | None = None
    video_project: dict | None = None
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
    rendered_cut_preview_id: str | None = None
    rendered_cut_preview_path: Path | None = None
    transcription_jobs: dict[str, TranscriptionJob]
    visual_plan_path: Path | None = None
    visual_plan: dict | None = None
    visual_render_jobs: dict[str, VisualRenderJob]
    visual_render_start_lock: threading.Lock
    creator_job_stores: dict[str, CreatorJobStore]
    creator_job_lock: threading.Lock
    creator_render_job_threads: dict[str, threading.Thread]
    creator_render_job_stores: dict[str, CreatorRenderJobStore]

    def __init__(self) -> None:
        self.video_project_path = None
        self.video_project = None
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
        self.rendered_cut_preview_id = None
        self.rendered_cut_preview_path = None
        self.transcription_jobs = {}
        self.visual_plan_path = None
        self.visual_plan = None
        self.visual_render_jobs = {}
        self.visual_render_start_lock = threading.Lock()
        self.creator_job_stores = {}
        self.creator_job_lock = threading.Lock()
        self.creator_render_job_threads = {}
        self.creator_render_job_stores = {}


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


class VisualRenderJob:
    def __init__(self, job_id: str, plan_path: Path, purpose: str) -> None:
        self.job_id = job_id
        self.plan_path = plan_path.resolve()
        self.purpose = purpose
        self.status = "running"
        self.value = 0
        self.stage = "queued"
        self.message = "Final export queued..." if purpose == "final" else "Visual render queued..."
        self.output_path: str | None = None
        self.error: str | None = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.started_at
        self.started_monotonic = time.monotonic()
        self.lock = threading.Lock()
        self._persist()

    @property
    def state_path(self) -> Path:
        return self.plan_path.parent / "render-job.json"

    def _stage_for(self, value: int, message: str) -> str:
        lowered = message.lower()
        if value >= 100:
            return "complete"
        if "verif" in lowered:
            return "verifying"
        if "audio" in lowered:
            return "audio"
        if "render" in lowered and value >= 40:
            return "rendering"
        if "lint" in lowered or "layout" in lowered or "gate" in lowered:
            return "validating"
        return "preparing"

    def _snapshot_unlocked(self) -> dict:
        elapsed = max(0.0, time.monotonic() - self.started_monotonic)
        eta = None
        if self.status == "running" and 0 < self.value < 100:
            eta = max(0.0, elapsed * (100 - self.value) / self.value)
        return {
            "job_id": self.job_id,
            "plan_path": str(self.plan_path),
            "purpose": self.purpose,
            "status": self.status,
            "stage": self.stage,
            "value": self.value,
            "message": self.message,
            "output_path": self.output_path,
            "error": self.error,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": round(eta, 1) if eta is not None else None,
        }

    def _persist(self) -> None:
        try:
            snapshot = self._snapshot_unlocked()
            temporary = self.state_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            # The in-memory job remains authoritative while the API is running.
            pass

    def update(self, value: int, message: str) -> None:
        with self.lock:
            bounded_value = max(0, min(100, value))
            if bounded_value == self.value and message == self.message:
                return
            self.value = bounded_value
            self.message = message
            self.stage = self._stage_for(self.value, message)
            self.updated_at = datetime.now(timezone.utc).isoformat()
            self._persist()

    def complete(self, output_path: Path) -> None:
        with self.lock:
            self.status = "complete"
            self.value = 100
            self.stage = "complete"
            self.message = "Final video verified and ready." if self.purpose == "final" else "Visual render complete."
            self.output_path = str(output_path)
            self.updated_at = datetime.now(timezone.utc).isoformat()
            self._persist()

    def fail(self, error: str) -> None:
        with self.lock:
            self.status = "failed"
            self.stage = "failed"
            self.error = error
            self.message = error
            self.updated_at = datetime.now(timezone.utc).isoformat()
            self._persist()

    def snapshot(self, job_id: str) -> dict:
        with self.lock:
            return self._snapshot_unlocked()


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


class ManualCutRequest(BaseModel):
    out_frame: int
    in_frame: int


class AdjustManualCutRequest(BaseModel):
    cut_id: str
    out_delta: int = 0
    in_delta: int = 0


class FinalOutFrameRequest(BaseModel):
    frame: int | None


class EditorSettingsRequest(BaseModel):
    dead_space_min_seconds: float


class ExportCutRequest(BaseModel):
    output_path: str | None = None
    normalize_audio: bool = False
    normalization_preset_id: str = "gentle"
    target_i: float = -14.0
    target_lra: float = 7.0
    target_tp: float = -1.5


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

    @field_validator("main_color", "active_color", "outline_color", "shadow_color", "glow_color")
    @classmethod
    def normalize_hex_color(cls, value: str) -> str:
        clean = value.strip()
        if clean.startswith("#"):
            clean = clean[1:]
        if len(clean) == 3 and all(character in "0123456789abcdefABCDEF" for character in clean):
            clean = "".join(character * 2 for character in clean)
        if len(clean) != 6 or any(character not in "0123456789abcdefABCDEF" for character in clean):
            raise ValueError("Colors must use #RRGGBB format.")
        return f"#{clean.upper()}"

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


class VisualPlanSaveRequest(BaseModel):
    plan: dict


class VisualRenderRequest(BaseModel):
    start_sec: float | None = None
    end_sec: float | None = None
    quality: str = "standard"
    purpose: str | None = None


class VisualRepresentativeApprovalRequest(BaseModel):
    cue_id: str


class VisualReopenVerificationRequest(BaseModel):
    revision_number: int
    plan_hash: str


class CreatorProductionJobRequest(BaseModel):
    task_kind: str
    requested_resource_ids: list[str] = Field(default_factory=list)
    input_artifact_keys: list[str] = Field(default_factory=list)
    task_parameters: dict = Field(default_factory=dict)


class CreatorProductionClaimRequest(BaseModel):
    task_id: str
    visible_skill_ids: list[str] = Field(default_factory=list)


class CreatorProductionCompleteRequest(BaseModel):
    task_id: str
    output: dict | None = None
    technical_capability_ids: list[str] = Field(default_factory=list)


class CreatorProductionInitializeRequest(BaseModel):
    channel_profile_id: str
    legacy_transcript_attestation: dict | None = None


class CreatorProductionWorkflowUpgradeRequest(BaseModel):
    actor: str
    reason: str


class CreatorSourceEvidenceRequest(BaseModel):
    ledger: dict


class CreatorReviewNoteRequest(BaseModel):
    id: str
    sequence_id: str
    element_id: str | None = None
    word_id: str | None = None
    absolute_frame: int
    note: str


class CreatorStudioHandoffRequest(BaseModel):
    sequence_id: str
    element_id: str | None = None
    absolute_frame: int


class CreatorStudioEditRequest(BaseModel):
    handoff: dict
    edits: list[dict]


class SourceClipOrderRequest(BaseModel):
    clip_ids: list[str]


class CreatorAssetUpdateRequest(BaseModel):
    updates: dict


class CreatorAssetUseRequest(BaseModel):
    start_sec: float
    end_sec: float
    suggestion_id: str | None = None


class SuggestionUpdateRequest(BaseModel):
    updates: dict


class SuggestionDecisionRequest(BaseModel):
    action: str
    notes: str = ""


class TreatmentUpdateRequest(BaseModel):
    updates: dict


class RecipeSuggestionRequest(BaseModel):
    recipe_id: str
    start_sec: float
    end_sec: float


class ReviewPromptRequest(BaseModel):
    review_ids: list[str] | None = None


class PexelsKeyRequest(BaseModel):
    api_key: str


class StockSelectRequest(BaseModel):
    candidate: dict


def _active_video_project() -> tuple[Path, dict] | None:
    if state.video_project_path is None or state.video_project is None:
        return None
    return state.video_project_path, state.video_project


def _video_project_stage_path(key: str) -> Path | None:
    active = _active_video_project()
    if active is None:
        return None
    active[1].setdefault("paths", {}).setdefault(key, DEFAULT_PROJECT_PATHS[key])
    return resolve_video_project_path(active[0], active[1], key)


def _video_project_output_folder() -> Path:
    path = _video_project_stage_path("finalVideo")
    return path.parent if path is not None else exports_dir()


def _active_sequence_fps() -> float | None:
    active = _active_video_project()
    if active is None:
        return None
    clips = sorted(active[1].get("sourceSequence", []), key=lambda clip: int(clip.get("order", 0)))
    if not clips:
        return None
    value = str((clips[0].get("metadata") or {}).get("frameRate") or "")
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return round(float(numerator) / float(denominator), 3)
        return round(float(value), 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _activate_video_project(manifest_path: Path, manifest: dict) -> dict:
    state.video_project_path = manifest_path.resolve()
    state.video_project = manifest
    source = resolve_video_project_path(manifest_path, manifest, "sourceVideo")
    state.transcript_video_path = source
    state.caption_video_path = preferred_stage_source(manifest_path, manifest)
    state.audio_video_path = preferred_stage_source(manifest_path, manifest)
    editor_path = resolve_video_project_path(manifest_path, manifest, "editorProject")
    editor_response = None
    if editor_path.is_file():
        project, edits = load_editor_project(editor_path)
        state.project = project
        state.edits = edits
        state.project_path = editor_path
        editor_response = _project_response()
    else:
        state.project = None
        state.edits = EditDecisionList()
        state.project_path = editor_path
    visual_path = resolve_video_project_path(manifest_path, manifest, "visualPlan")
    if visual_path.is_file():
        state.visual_plan_path = visual_path
        state.visual_plan = load_visual_plan(visual_path)
    else:
        state.visual_plan_path = None
        state.visual_plan = None
    return {"videoProject": video_project_response(manifest_path, manifest), "editorProject": editor_response}


def _activate_rebuilt_sequence(manifest_path: Path, manifest: dict) -> dict:
    state.video_project_path = manifest_path
    state.video_project = manifest
    source = resolve_video_project_path(manifest_path, manifest, "sourceVideo")
    state.transcript_video_path = source
    state.caption_video_path = source
    state.audio_video_path = source
    state.project = None
    state.edits = EditDecisionList()
    state.project_path = resolve_video_project_path(manifest_path, manifest, "editorProject")
    state.visual_plan_path = None
    state.visual_plan = None
    return {"videoProject": video_project_response(manifest_path, manifest), "editorProject": None}


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
    if path.name.endswith(VIDEO_PROJECT_SUFFIX):
        raise HTTPException(status_code=400, detail="Use Open Video Project for a .vcg-project.json parent project.")
    return _open_project_path(path)


@app.get("/api/video-project/current")
def current_video_project() -> dict:
    active = _active_video_project()
    if active is None:
        raise HTTPException(status_code=404, detail="No private video project is open.")
    return video_project_response(active[0], active[1])


@app.post("/api/video-project/create-dialog")
def create_video_project_dialog() -> dict:
    sources = _choose_video_files()
    if not sources:
        raise HTTPException(status_code=400, detail="No source clips selected.")
    try:
        manifest_path, manifest = create_video_project_from_sources(sources)
        return _activate_video_project(manifest_path, manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not create the private video project: {exc}") from exc


@app.post("/api/video-project/open-dialog")
def open_video_project_dialog() -> dict:
    path = _choose_project_file()
    if path is None:
        raise HTTPException(status_code=400, detail="No project selected.")
    if not path.name.endswith(VIDEO_PROJECT_SUFFIX):
        raise HTTPException(status_code=400, detail="Choose a .vcg-project.json parent project. Legacy transcript projects still open from Transcript Project.")
    try:
        return _activate_video_project(path, load_video_project(path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not open the private video project: {exc}") from exc


@app.get("/api/video-project/visual-prompt")
def video_project_visual_prompt() -> dict:
    active = _active_video_project()
    if active is None:
        raise HTTPException(status_code=404, detail="Create or open a private video project first.")
    return {"prompt": build_visual_plan_prompt(active[0], active[1])}


@app.post("/api/video-project/clips/add-dialog")
def add_video_project_clips() -> dict:
    active = _active_video_project()
    if active is None:
        raise HTTPException(status_code=404, detail="No private video project is open.")
    sources = _choose_video_files()
    if not sources:
        raise HTTPException(status_code=400, detail="No source clips selected.")
    try:
        manifest = add_source_clips(active[0], active[1], sources)
        return _activate_rebuilt_sequence(active[0], manifest)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not add source clips: {exc}") from exc


@app.post("/api/video-project/clips/reorder")
def reorder_video_project_clips(payload: SourceClipOrderRequest) -> dict:
    active = _active_video_project()
    if active is None:
        raise HTTPException(status_code=404, detail="No private video project is open.")
    try:
        manifest = reorder_source_clips(active[0], active[1], payload.clip_ids)
        return _activate_rebuilt_sequence(active[0], manifest)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not reorder source clips: {exc}") from exc


@app.delete("/api/video-project/clips/{clip_id}")
def delete_video_project_clip(clip_id: str) -> dict:
    active = _active_video_project()
    if active is None:
        raise HTTPException(status_code=404, detail="No private video project is open.")
    try:
        manifest = remove_source_clip(active[0], active[1], clip_id)
        return _activate_rebuilt_sequence(active[0], manifest)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not remove source clip: {exc}") from exc


def _open_project_path(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project file not found: {path}")
    project, edits = load_editor_project(path)
    state.project = project
    state.edits = edits
    state.project_path = path
    state.video_project_path = None
    state.video_project = None
    return _project_response()


def _choose_project_file() -> Path | None:
    try:
        return _windows_choose_project_file()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Windows project picker error ({type(exc).__name__}): {exc}",
        ) from exc


def _choose_project_save_file(project: TranscriptProject) -> Path | None:
    default_name = "editor-project.vcg.json"
    source_path = Path(project.source)
    if source_path.exists():
        default_name = f"{source_path.stem}.vcg.json"

    try:
        return _windows_choose_project_save_file(default_name)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Windows project save picker error ({type(exc).__name__}): {exc}",
        ) from exc


def _choose_video_file() -> Path | None:
    try:
        return _windows_choose_video_file()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Windows video picker error ({type(exc).__name__}): {exc}",
        ) from exc


def _choose_video_files() -> list[Path]:
    try:
        return _windows_choose_video_files()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Windows multi-video picker error ({type(exc).__name__}): {exc}",
        ) from exc


def _choose_output_folder() -> Path | None:
    try:
        return _windows_choose_output_folder()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Windows folder picker error ({type(exc).__name__}): {exc}",
        ) from exc


def _choose_visual_plan_file() -> Path | None:
    try:
        return _windows_choose_visual_plan_file()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=500, detail=f"Windows visual-plan picker error ({type(exc).__name__}): {exc}") from exc


def _choose_visual_asset_file() -> Path | None:
    try:
        return _windows_choose_visual_asset_file()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=500, detail=f"Windows visual-asset picker error ({type(exc).__name__}): {exc}") from exc


@app.get("/api/projects/current")
def current_project() -> dict:
    _require_project()
    return _project_response()


@app.post("/api/projects/choose-video")
def choose_transcript_video() -> dict:
    sources = _choose_video_files()
    if not sources:
        raise HTTPException(status_code=400, detail="No source clips selected.")
    try:
        manifest_path, manifest = create_video_project_from_sources(sources)
        response = _activate_video_project(manifest_path, manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not create the private video project: {exc}") from exc
    return {"source": str(state.transcript_video_path), **response}


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
        fps_override=_active_sequence_fps(),
    )
    project = _annotate_generated_project(project, source, payload.model_label, payload.compute_label)
    _store_generated_project(project, source)
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
        args=(job, source, payload.model_label, payload.compute_label),
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


def _run_transcription_job(job: TranscriptionJob, source: Path, model_label: str, compute_mode: str) -> None:
    try:
        model_size = MODEL_OPTIONS[model_label]
        project = generate_editor_transcript(
            input_video_path=source,
            working_dir=temp_dir(),
            model_size=model_size,
            compute_mode=compute_mode,
            fps_override=_active_sequence_fps(),
            progress_callback=job.update,
        )
        job.update(96, "Recording transcript provenance...")
        project = _annotate_generated_project(project, source, model_label, compute_mode)
        _store_generated_project(project, source)
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
        duration = _silence_duration_seconds(silence, project.fps)
        if (
            silence.audio_analyzed
            and silence.id not in deleted
            and duration >= state.edits.settings.dead_space_min_seconds
        ):
            state.edits.delete_silence(f"delete_{silence.id}", silence.id)
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/settings")
def update_editor_settings(payload: EditorSettingsRequest) -> dict:
    project = _require_project()
    if not 0.35 <= payload.dead_space_min_seconds <= 10.0:
        raise HTTPException(status_code=400, detail="Dead-space threshold must be between 0.35 and 10 seconds.")

    state.edits.settings.dead_space_min_seconds = payload.dead_space_min_seconds
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/analyze-pauses")
def analyze_current_pauses() -> dict:
    project = _require_project()
    source = Path(project.source).expanduser().resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {source}")
    try:
        audio_path = extract_audio(source, temp_dir() / "editor_boundary_audio.wav")
        state.project, summary = analyze_pause_candidates(
            project,
            audio_path,
            state.edits.settings.dead_space_min_seconds,
        )
    except (OSError, RuntimeError, ValueError, wave.Error) as exc:
        raise HTTPException(status_code=400, detail=f"Pause analysis failed: {exc}") from exc

    for silence in state.project.silence_ranges:
        if (
            silence.audio_analyzed
            and _silence_duration_seconds(silence, state.project.fps)
            < state.edits.settings.dead_space_min_seconds
        ):
            state.edits.restore_silence(silence.id)
    _save_current_project_if_loaded(state.project)
    return _project_response(pause_analysis_summary=summary)


@app.post("/api/projects/current/analyze-boundaries")
def analyze_current_boundaries() -> dict:
    project = _require_project()
    plan = generate_splices(project, state.edits)
    targets = [splice for splice in plan.splices if not splice.reviewed and splice.left_word_id]
    if not targets:
        return _project_response(
            fine_tune_summary={"cuts_checked": 0, "cuts_adjusted": 0, "cuts_unchanged": 0}
        )

    source = Path(project.source).expanduser().resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {source}")
    try:
        audio_path = extract_audio(source, temp_dir() / "editor_boundary_audio.wav")
        suggestions = suggest_word_end_boundaries(
            project,
            audio_path,
            {splice.left_word_id for splice in targets},
        )
    except (OSError, RuntimeError, ValueError, wave.Error) as exc:
        raise HTTPException(status_code=400, detail=f"Audio boundary analysis failed: {exc}") from exc

    previous_edits = copy.deepcopy(state.edits)
    adjusted = 0
    for splice in targets:
        suggestion = suggestions.get(splice.left_word_id)
        measured_suggestion = _measured_pause_out_frame(project, splice.left_word_id, splice.right_word_id)
        if measured_suggestion is not None:
            suggestion = measured_suggestion
        state.edits.set_assisted_out_frame(splice.anchor_key, suggestion)
        if suggestion is not None and suggestion != splice.left_whisper_out_frame:
            adjusted += 1
    try:
        generate_splices(project, state.edits)
    except InvalidCutPlanError as exc:
        state.edits = previous_edits
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _save_current_project_if_loaded(project)
    checked = len(targets)
    return _project_response(
        fine_tune_summary={
            "cuts_checked": checked,
            "cuts_adjusted": adjusted,
            "cuts_unchanged": checked - adjusted,
        }
    )


@app.post("/api/projects/current/splices/adjust")
def adjust_splice(payload: AdjustSpliceRequest) -> dict:
    project = _require_project()
    previous_edits = copy.deepcopy(state.edits)
    state.edits.adjust_splice(
        payload.anchor_key,
        left_out_delta=payload.left_delta,
        right_in_delta=payload.right_delta,
    )
    try:
        generate_splices(project, state.edits)
    except InvalidCutPlanError as exc:
        state.edits = previous_edits
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/splices/review")
def review_splice(payload: ReviewSpliceRequest) -> dict:
    project = _require_project()
    if payload.anchor_key.startswith("MANUAL:"):
        try:
            state.edits.review_manual_cut(payload.anchor_key.removeprefix("MANUAL:"), payload.reviewed)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    else:
        state.edits.adjust_splice(payload.anchor_key, reviewed=payload.reviewed)
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/manual-cuts")
def add_manual_cut(payload: ManualCutRequest) -> dict:
    project = _require_project()
    previous_edits = copy.deepcopy(state.edits)
    state.edits.add_manual_cut(f"manual_{uuid.uuid4().hex[:10]}", payload.out_frame, payload.in_frame)
    try:
        generate_splices(project, state.edits)
    except InvalidCutPlanError as exc:
        state.edits = previous_edits
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/manual-cuts/adjust")
def adjust_manual_cut(payload: AdjustManualCutRequest) -> dict:
    project = _require_project()
    previous_edits = copy.deepcopy(state.edits)
    try:
        state.edits.adjust_manual_cut(payload.cut_id, out_delta=payload.out_delta, in_delta=payload.in_delta)
        generate_splices(project, state.edits)
    except KeyError as exc:
        state.edits = previous_edits
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidCutPlanError as exc:
        state.edits = previous_edits
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _save_current_project_if_loaded(project)
    return _project_response()


@app.delete("/api/projects/current/manual-cuts/{cut_id}")
def remove_manual_cut(cut_id: str) -> dict:
    project = _require_project()
    try:
        state.edits.remove_manual_cut(cut_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/final-out-frame")
def set_final_out_frame(payload: FinalOutFrameRequest) -> dict:
    project = _require_project()
    previous_edits = copy.deepcopy(state.edits)
    state.edits.set_final_out_frame(payload.frame)
    try:
        generate_splices(project, state.edits)
    except InvalidCutPlanError as exc:
        state.edits = previous_edits
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _save_current_project_if_loaded(project)
    return _project_response()


@app.post("/api/projects/current/render-preview")
def render_cut_preview() -> dict:
    project = _require_project()
    source = Path(project.source).expanduser().resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {source}")
    try:
        plan = generate_splices(project, state.edits)
    except InvalidCutPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    frame_intervals = plan.export_intervals()
    if not frame_intervals:
        raise HTTPException(status_code=400, detail="No kept intervals to preview.")
    intervals = frame_intervals_to_seconds(frame_intervals, project.fps)

    preview_id = uuid.uuid4().hex
    cut_preview_root = _video_project_stage_path("cutPreviews") or temp_dir()
    output_path = cut_preview_root / f"rendered-cut-{preview_id}.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_cut(
            ffmpeg=find_ffmpeg(),
            input_video=source,
            output_video=output_path,
            intervals=intervals,
            crf=28,
            preset="ultrafast",
        )
    except (RuntimeError, ValueError) as exc:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Rendered cut preview failed: {exc}") from exc

    _clear_rendered_cut_preview()
    state.rendered_cut_preview_id = preview_id
    state.rendered_cut_preview_path = output_path
    return {
        "preview_id": preview_id,
        "duration_seconds": round(sum(end - start for start, end in intervals), 3),
        "splices": _rendered_preview_splices(plan, project),
        "segments": _rendered_preview_segments(plan, project),
    }


@app.post("/api/projects/current/save")
def save_project() -> dict:
    project = _require_project()
    if state.project_path is None:
        path = _choose_project_save_file(project)
        if path is None:
            raise HTTPException(status_code=400, detail="No project file selected.")
        state.project_path = path
    save_editor_project(state.project_path, project, state.edits)
    _touch_video_project()
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
    try:
        plan = generate_splices(project, state.edits)
    except InvalidCutPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    intervals = plan.export_intervals()
    if not intervals:
        raise HTTPException(status_code=400, detail="No kept intervals to export.")
    if payload.normalize_audio:
        _validate_audio_targets(payload)
        valid_preset_ids = {preset["id"] for preset in preset_options()}
        if payload.normalization_preset_id not in valid_preset_ids:
            raise HTTPException(status_code=400, detail=f"Unknown audio preset: {payload.normalization_preset_id}")
    project_locked_cut = _video_project_stage_path("lockedCut")
    requested_output = Path(payload.output_path).expanduser().resolve() if payload.output_path else None
    final_cut_path = requested_output or project_locked_cut or (exports_dir() / f"{source.stem}_cut.mp4")
    output_path = final_cut_path
    if payload.normalize_audio and project_locked_cut is not None and requested_output is None:
        output_path = video_project_root(state.video_project_path) / "working" / "cut-unmastered.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_cut(
        ffmpeg=find_ffmpeg(),
        input_video=source,
        output_video=output_path,
        intervals=frame_intervals_to_seconds(intervals, project.fps),
    )
    if not payload.normalize_audio:
        state.caption_video_path = output_path
        state.audio_video_path = output_path
        _record_audio_delivery(
            normalized=False,
            output_path=output_path,
            preset_id=None,
            target_i=None,
            measurement=None,
        )
        _save_final_transcript(project, plan, output_path)
        return {
            "output_path": str(output_path),
            "cut_output_path": str(output_path),
            "normalized": False,
        }

    normalized_output_path = final_cut_path if output_path != final_cut_path else output_path.with_name(f"{output_path.stem}_normalized{output_path.suffix}")
    try:
        measurement = analyze_audio(
            ffmpeg=find_ffmpeg(),
            input_video=output_path,
            preset_id=payload.normalization_preset_id,
            target_i=payload.target_i,
            target_lra=payload.target_lra,
            target_tp=payload.target_tp,
        )
        normalize_video_audio(
            ffmpeg=find_ffmpeg(),
            input_video=output_path,
            output_video=normalized_output_path,
            preset_id=payload.normalization_preset_id,
            measurement=measurement,
            target_i=payload.target_i,
            target_lra=payload.target_lra,
            target_tp=payload.target_tp,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"The cut was exported successfully to {output_path}, but audio normalization failed: {exc}",
        ) from exc
    state.caption_video_path = normalized_output_path
    state.audio_video_path = normalized_output_path
    _record_audio_delivery(
        normalized=True,
        output_path=normalized_output_path,
        preset_id=payload.normalization_preset_id,
        target_i=payload.target_i,
        measurement=measurement,
    )
    _save_final_transcript(project, plan, normalized_output_path)
    return {
        "output_path": str(normalized_output_path),
        "cut_output_path": str(output_path),
        "normalized": True,
    }


def _require_visual_plan() -> tuple[Path, dict]:
    if state.visual_plan_path is None or state.visual_plan is None:
        raise HTTPException(status_code=404, detail="No private visual-production project is open.")
    return state.visual_plan_path, state.visual_plan


def _creator_production_root() -> Path:
    plan_path, _plan = _require_visual_plan()
    return find_visual_root(plan_path)


def _creator_job_store() -> CreatorJobStore:
    root = _creator_production_root().resolve()
    key = str(root)
    with state.creator_job_lock:
        store = state.creator_job_stores.get(key)
        if store is None:
            store = CreatorJobStore(root)
            state.creator_job_stores[key] = store
        return store


def _creator_render_job_store() -> CreatorRenderJobStore:
    root = _creator_production_root().resolve()
    key = str(root)
    with state.creator_job_lock:
        store = state.creator_render_job_stores.get(key)
        if store is None:
            store = CreatorRenderJobStore(root, project_root())
            state.creator_render_job_stores[key] = store
        return store


def _run_creator_render_job(store: CreatorRenderJobStore, job_id: str) -> None:
    try:
        store.run(job_id)
    finally:
        with state.creator_job_lock:
            state.creator_render_job_threads.pop(job_id, None)


@app.get("/api/creator-production/channel-profiles")
def creator_production_channel_profiles() -> dict:
    plan_path, _plan = _require_visual_plan()
    profiles = available_channel_profiles(find_visual_root(plan_path))
    return {
        "profiles": [
            {
                key: profile[key]
                for key in ("id", "version", "referenceGrammarRef", "fileName")
            }
            for profile in profiles
        ]
    }


@app.post("/api/creator-production/initialize")
def initialize_creator_production(
    payload: CreatorProductionInitializeRequest | None = None,
) -> dict:
    plan_path, plan = _require_visual_plan()
    root = find_visual_root(plan_path)
    source = plan.get("source") if isinstance(plan.get("source"), dict) else {}
    try:
        locked_cut = resolve_project_path(root, str(source.get("video") or ""))
        final_transcript = resolve_project_path(root, str(source.get("transcript") or ""))
        renderer_assets = resolve_creator_renderer_assets(project_root())
        hyperframes_package = json.loads(
            (renderer_assets["hyperframesPackage"] / "package.json").read_text(encoding="utf-8")
        )
        hyperframes_version = str(hyperframes_package["version"])
        animation_source = resolve_hyperframes_animation_source(
            private_root=root,
            hyperframes_version=hyperframes_version,
        )
        current = initialize_creator_project(
            root,
            episode_id=str((plan.get("project") or {}).get("id") or ""),
            locked_cut=locked_cut,
            final_transcript=final_transcript,
            hyperframes_skill_root=animation_source,
            hyperframes_cli_path=renderer_assets["hyperframesCli"],
            hyperframes_version=hyperframes_version,
            channel_profile_id=payload.channel_profile_id if payload else "",
            preserve_capability_source_cache=True,
            legacy_transcript_attestation=(
                payload.legacy_transcript_attestation if payload else None
            ),
        )
        return {
            "initialized": True,
            "workflowId": current["workflowId"],
            "episodeId": current["episodeId"],
            "state": current["state"],
            "currentHash": current["currentHash"],
            "workflowBundleHash": current["workflowBundle"]["bundleHash"],
            "capabilityBundleHash": current["capabilityBundle"]["bundleHash"],
        }
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Creator Production initialization failed: {exc}",
        ) from exc


@app.get("/api/creator-production/current")
def current_creator_production() -> dict:
    root = _creator_production_root()
    current_path = root / "creator-production" / "current.json"
    if not current_path.is_file():
        return {
            "initialized": False,
            "reason": "Creator Production has not been initialized for this private project.",
            "recoveryAction": "Initialize Creator Production.",
        }
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        verify_creator_project(root, current)
        workflow_upgrade_required = False
        workflow_upgrade_reason = None
        try:
            verify_live_workflow_package_matches_lock(root, current)
        except RuntimeError as exc:
            workflow_upgrade_required = True
            workflow_upgrade_reason = str(exc)
        catalog_ref = current["artifacts"]["capabilityCatalog"]
        catalog = json.loads((root / catalog_ref["path"]).read_text(encoding="utf-8"))
        review_stale = False
        if current["artifacts"].get("reviewState") and current["artifacts"].get("buildLock"):
            review_state = json.loads(
                (root / current["artifacts"]["reviewState"]["path"]).read_text(encoding="utf-8")
            )
            active_build = json.loads(
                (root / current["artifacts"]["buildLock"]["path"]).read_text(encoding="utf-8")
            )
            review_stale = review_state["buildHash"] != active_build["buildHash"]
        return {
            "initialized": True,
            "workflowId": current["workflowId"],
            "episodeId": current["episodeId"],
            "state": current["state"],
            "currentHash": current["currentHash"],
            "capabilitySummary": catalog["inventorySummary"],
            "reviewStale": review_stale,
            "workflowUpgradeRequired": workflow_upgrade_required,
            "workflowUpgradeReason": workflow_upgrade_reason,
            "artifactAvailability": {
                key: key in current["artifacts"]
                for key in (
                    "analysisLedger",
                    "semanticManifest",
                    "sourceEvidence",
                    "episodeManifest",
                    "compiledEpisode",
                    "buildLock",
                    "browserPreflight",
                    "reviewState",
                    "finalRenderReceipt",
                )
            },
            "authority": {
                "productionOwnsRouting": True,
                "nativeWorkflowDiscoveryPerformed": False,
                "lockedTranscriptIsTimingAuthority": True,
                "durationTargetsEnabled": False,
            },
        }
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator Production verification failed: {exc}") from exc


@app.post("/api/creator-production/workflow-upgrade")
def upgrade_creator_production_workflow(
    payload: CreatorProductionWorkflowUpgradeRequest,
) -> dict:
    try:
        upgrade_creator_workflow_package(
            _creator_production_root(),
            actor=payload.actor,
            reason=payload.reason,
        )
        return current_creator_production()
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Creator Production workflow upgrade failed: {exc}",
        ) from exc


@app.get("/api/creator-production/capabilities")
def creator_production_capabilities() -> dict:
    root = _creator_production_root()
    current_path = root / "creator-production" / "current.json"
    if not current_path.is_file():
        raise HTTPException(
            status_code=409,
            detail="Capability inventory unavailable until Creator Production is initialized.",
        )
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        verify_creator_project(root, current)
        catalog_ref = current["artifacts"]["capabilityCatalog"]
        catalog_bytes = read_frozen_bytes(root, catalog_ref["object"])
        catalog = json.loads(catalog_bytes.decode("utf-8"))
        return catalog
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Capability inventory unavailable: {exc}") from exc


@app.get("/api/creator-production/pipeline")
def creator_production_pipeline() -> dict:
    try:
        root = _creator_production_root()
        current = json.loads(
            (root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        verify_creator_project(root, current)
        catalog_ref = current["artifacts"]["capabilityCatalog"]
        catalog = json.loads((root / catalog_ref["path"]).read_text(encoding="utf-8"))
        semantic_ref = current["artifacts"].get("semanticManifest")
        if not semantic_ref:
            return {"sequences": [], "adaptationDebt": [], "sourceEvidenceStatus": "not-ready"}
        semantic = json.loads((root / semantic_ref["path"]).read_text(encoding="utf-8"))
        capabilities = {item["id"]: item for item in catalog["capabilities"]}
        decision_ref = current["artifacts"].get("sequenceDecisionIndex")
        decisions = {}
        if decision_ref:
            decision_index = json.loads((root / decision_ref["path"]).read_text(encoding="utf-8"))
            decisions = {item["sequenceId"]: item for item in decision_index["items"]}
        source_resources = {}
        for resource in catalog["sourceResources"]:
            source_resources.setdefault(
                (resource["relativePath"], resource["sha256"]), []
            ).append(resource["id"])
        sequences = []
        debt = []
        for sequence in semantic["sequences"]:
            candidates = []
            for capability_id in sequence["candidateCapabilityIds"]:
                capability = capabilities[capability_id]
                admissions = [
                    item
                    for item in capability.get("projectAdmissions", [])
                    if item.get("episodeId") == current["episodeId"]
                    and item.get("sequenceId") == sequence["id"]
                ]
                candidate = {
                    "capabilityId": capability_id,
                    "sourceResourceIds": source_resources.get(
                        (
                            capability["source"]["relativePath"],
                            capability["source"]["sha256"],
                        ),
                        [],
                    ),
                    "implementationMaturity": capability["implementationMaturity"],
                    "technicalAdmission": capability["technicalAdmission"],
                    "projectAdmissions": admissions,
                }
                candidates.append(candidate)
            item = {
                "id": sequence["id"],
                "chapterId": sequence["chapterId"],
                "absoluteStartFrame": sequence["absoluteStartFrame"],
                "absoluteEndFrameExclusive": sequence["absoluteEndFrameExclusive"],
                "editorialJob": sequence["editorialJob"],
                "semanticForm": sequence["semanticForm"],
                "presentationRole": sequence["presentationRole"],
                "candidates": candidates,
                "decision": decisions.get(sequence["id"]),
            }
            sequences.append(item)
            decision = decisions.get(sequence["id"])
            if (
                sequence["presentationRole"] != "source-led"
                and (not decision or decision["disposition"] != "selected")
            ):
                debt.append(item)
        return {
            "fps": semantic["fps"],
            "sequences": sequences,
            "adaptationDebt": debt,
            "sourceEvidenceStatus": (
                "complete"
                if current["artifacts"].get("sourceEvidence")
                else (
                    "layout-classification-blocked"
                    if current["artifacts"].get("sourceLayoutClassification")
                    else "agent-classification-required"
                )
            ),
        }
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Production pipeline unavailable: {exc}") from exc


@app.get("/api/creator-production/jobs")
def list_creator_production_jobs() -> dict:
    try:
        store = _creator_job_store()
        recovered = store.recover_interrupted()
        return {"jobs": store.list(), "recoveredJobIds": recovered}
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator Production jobs unavailable: {exc}") from exc


@app.post("/api/creator-production/jobs")
def create_creator_production_job(payload: CreatorProductionJobRequest) -> dict:
    try:
        root = _creator_production_root()
        if payload.task_kind == "classify-layouts":
            ensure_capture_layout_catalog(root)
        current = json.loads(
            (root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        verify_creator_project(root, current)
        unknown = sorted(set(payload.input_artifact_keys) - set(current["artifacts"]))
        if unknown:
            raise ValueError(f"Unknown current artifact keys: {', '.join(unknown)}")
        input_refs = [current["artifacts"][key] for key in payload.input_artifact_keys]
        return _creator_job_store().create(
            task_kind=payload.task_kind,
            requested_resource_ids=payload.requested_resource_ids,
            input_artifact_refs=input_refs,
            task_parameters=payload.task_parameters,
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator Production job rejected: {exc}") from exc


@app.get("/api/creator-production/jobs/{job_id}")
def get_creator_production_job(job_id: str) -> dict:
    try:
        return _creator_job_store().load(job_id)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=f"Creator Production job unavailable: {exc}") from exc


@app.post("/api/creator-production/jobs/{job_id}/start")
def start_creator_production_job(job_id: str) -> dict:
    """Reject the retired nested Codex execution path."""
    raise HTTPException(
        status_code=410,
        detail=(
            "Nested Creator Production execution is retired. Use the prepared "
            "handoff from a normal user-visible Codex task."
        ),
    )


@app.get("/api/creator-production/jobs/{job_id}/handoff")
def get_creator_production_handoff(job_id: str) -> dict:
    try:
        return _creator_job_store().handoff(job_id)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Creator Production handoff unavailable: {exc}",
        ) from exc


@app.post("/api/creator-production/jobs/{job_id}/claim")
def claim_creator_production_job(
    job_id: str,
    payload: CreatorProductionClaimRequest,
) -> dict:
    try:
        return _creator_job_store().claim(
            job_id,
            task_id=payload.task_id,
            visible_skill_ids=payload.visible_skill_ids,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Creator Production handoff could not be claimed: {exc}",
        ) from exc


@app.post("/api/creator-production/jobs/{job_id}/complete")
def complete_creator_production_job(
    job_id: str,
    payload: CreatorProductionCompleteRequest,
) -> dict:
    try:
        return _creator_job_store().complete(
            job_id,
            task_id=payload.task_id,
            output=payload.output,
            technical_capability_ids=payload.technical_capability_ids,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Creator Production handoff could not complete: {exc}",
        ) from exc


@app.post("/api/creator-production/jobs/{job_id}/cancel")
def cancel_creator_production_job(job_id: str) -> dict:
    try:
        return _creator_job_store().cancel(job_id)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator Production job could not be canceled: {exc}") from exc


@app.get("/api/creator-production/source-evidence")
def get_creator_source_evidence() -> dict:
    try:
        root = _creator_production_root()
        current = json.loads(
            (root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        verify_creator_project(root, current)
        reference = current["artifacts"].get("sourceEvidence")
        if reference:
            return {
                "status": "complete",
                "ledger": json.loads((root / reference["path"]).read_text(encoding="utf-8")),
                "artifactRef": reference,
            }
        if not current["artifacts"].get("captureLayoutCatalog"):
            return {"status": "agent-classification-required"}
        return {"status": "agent-classification-required", "draft": source_evidence_draft(root)}
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Source evidence unavailable: {exc}") from exc


@app.post("/api/creator-production/source-evidence")
def update_creator_source_evidence(payload: CreatorSourceEvidenceRequest) -> dict:
    try:
        reference = save_source_evidence(_creator_production_root(), payload.ledger)
        return {"status": "complete", "artifactRef": reference}
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Source evidence rejected: {exc}") from exc


@app.get("/api/creator-production/render-jobs")
def list_creator_render_jobs() -> dict:
    try:
        store = _creator_render_job_store()
        recovered = store.recover_interrupted()
        return {"jobs": store.list(), "recoveredJobIds": recovered}
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator render jobs unavailable: {exc}") from exc


@app.post("/api/creator-production/render-jobs")
def create_creator_render_job() -> dict:
    try:
        return _creator_render_job_store().create()
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator review render rejected: {exc}") from exc


@app.post("/api/creator-production/render-jobs/{job_id}/start")
def start_creator_render_job(job_id: str) -> dict:
    try:
        store = _creator_render_job_store()
        job = store.load(job_id)
        if job["status"] != "queued":
            raise ValueError(f"Render job cannot start from {job['status']}.")
        with state.creator_job_lock:
            thread = threading.Thread(
                target=_run_creator_render_job,
                args=(store, job_id),
                daemon=True,
                name=f"creator-render-{job_id[:8]}",
            )
            state.creator_render_job_threads[job_id] = thread
            thread.start()
        return store.load(job_id)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator review render could not start: {exc}") from exc


@app.post("/api/creator-production/render-jobs/{job_id}/cancel")
def cancel_creator_render_job(job_id: str) -> dict:
    try:
        return _creator_render_job_store().cancel(job_id)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator review render could not be canceled: {exc}") from exc


@app.get("/api/creator-production/review-video")
def creator_production_review_video(
    range_header: str | None = Header(default=None, alias="Range"),
) -> Response:
    try:
        root = _creator_production_root()
        current = json.loads(
            (root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        verify_creator_project(root, current)
        reference = current["artifacts"].get("reviewRenderReceipt")
        if not reference:
            raise ValueError("No final-quality review render is available.")
        receipt = json.loads((root / reference["path"]).read_text(encoding="utf-8"))
        path = (root / receipt["outputRelativePath"]).resolve()
        return _range_response(path, range_header)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=f"Review video unavailable: {exc}") from exc


def _load_creator_review() -> tuple[Path, dict, dict, dict]:
    root = _creator_production_root()
    current = json.loads(
        (root / "creator-production" / "current.json").read_text(encoding="utf-8")
    )
    verify_creator_project(root, current)
    review_ref = current["artifacts"].get("reviewState")
    build_ref = current["artifacts"].get("buildLock")
    if not review_ref or not build_ref:
        raise ValueError("Final-quality review is not ready.")
    review = json.loads((root / review_ref["path"]).read_text(encoding="utf-8"))
    build = json.loads((root / build_ref["path"]).read_text(encoding="utf-8"))
    return root, current, review, build


def _persist_creator_review(root: Path, current: dict, review: dict) -> dict:
    reference = write_versioned_artifact(
        root,
        artifact_kind="review-states",
        artifact_id=current["episodeId"],
        version=next_artifact_version(
            root, "review-states", current["episodeId"]
        ),
        value=review,
        schema_name="review-state",
    )
    promote_creator_artifact(root, artifact_key="reviewState", artifact_reference=reference)
    return {"review": review, "artifactRef": reference}


@app.get("/api/creator-production/review")
def get_creator_production_review() -> dict:
    try:
        root, current, review, build = _load_creator_review()
        manifest = json.loads(
            (root / current["artifacts"]["episodeManifest"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        preflight_ref = current["artifacts"].get("structuralPreflight")
        preflight = (
            json.loads((root / preflight_ref["path"]).read_text(encoding="utf-8"))
            if preflight_ref
            else None
        )
        return {
            "review": review,
            "build": build,
            "manifest": manifest,
            "preflight": preflight,
        }
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Creator review unavailable: {exc}") from exc


@app.post("/api/creator-production/review/notes")
def save_creator_production_review_note(payload: CreatorReviewNoteRequest) -> dict:
    try:
        root, current, review, build = _load_creator_review()
        sequence_ids = {item["sequenceId"] for item in build["sequences"]}
        if payload.sequence_id not in sequence_ids:
            raise ValueError("Review note targets an unknown sequence.")
        note = {
            "id": payload.id,
            "buildHash": build["buildHash"],
            "sequenceId": payload.sequence_id,
            "elementId": payload.element_id,
            "wordId": payload.word_id,
            "absoluteFrame": payload.absolute_frame,
            "note": payload.note,
            "status": "changes-requested",
            "saveStatus": "saving",
            "savedAt": utc_now(),
        }
        result = _persist_creator_review(root, current, save_review_note(review, note))
        if current["state"] == "REVIEW_READY":
            transition_creator_project(
                root,
                target_state="REVISION_REQUESTED",
                gate_receipt_refs=[result["artifactRef"]["sha256"]],
                actor="creator",
            )
        return result
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Review note was not saved: {exc}") from exc


@app.post("/api/creator-production/review/notes/{note_id}/accept")
def accept_creator_production_review_note(note_id: str) -> dict:
    try:
        root, current, review, _build = _load_creator_review()
        return _persist_creator_review(
            root,
            current,
            accept_review_note(review, note_id, actor_role="creator"),
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Review note could not be accepted: {exc}") from exc


@app.post("/api/creator-production/review/approve")
def approve_creator_production_review() -> dict:
    try:
        root, current, review, build = _load_creator_review()
        approved = create_approval_record(review, build, actor_role="creator")
        result = _persist_creator_review(root, current, approved)
        review_render = current["artifacts"]["reviewRenderReceipt"]
        promote_creator_artifact(
            root,
            artifact_key="finalRenderReceipt",
            artifact_reference=review_render,
        )
        result["delivery"] = {
            "reusedExactReviewBytes": True,
            "renderReceiptRef": review_render,
        }
        latest = json.loads(
            (root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        if latest["state"] == "REVIEW_READY":
            latest = transition_creator_project(
                root,
                target_state="APPROVED",
                gate_receipt_refs=[result["artifactRef"]["sha256"]],
                actor="creator",
            )
            latest = transition_creator_project(
                root,
                target_state="RENDERING",
                gate_receipt_refs=[review_render["sha256"]],
                actor="production",
            )
            transition_creator_project(
                root,
                target_state="DELIVERED",
                gate_receipt_refs=[review_render["sha256"]],
                actor="production",
            )
        return result
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Complete revision could not be approved: {exc}") from exc


@app.post("/api/creator-production/studio/handoff")
def create_creator_studio_handoff(payload: CreatorStudioHandoffRequest) -> dict:
    try:
        root, _current, review, build = _load_creator_review()
        if review["buildHash"] != build["buildHash"]:
            raise ValueError("Studio handoff is blocked because the review build is stale.")
        current = json.loads(
            (root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (root / current["artifacts"]["episodeManifest"]["path"]).read_text(encoding="utf-8")
        )
        sequence = next(
            (
                item
                for item in manifest["sequences"]
                if item["id"] == payload.sequence_id
            ),
            None,
        )
        if sequence is None:
            raise ValueError("Studio sequence does not exist.")
        chapter_lock = next(
            item for item in build["chapters"]
            if item["chapterId"] == sequence["chapterId"]
        )
        studio_project = (
            root
            / "creator-production"
            / "compositions"
            / sequence["chapterId"]
            / chapter_lock["chapterInputHash"]
        ).resolve()
        entry = studio_project / "public" / "index.html"
        if not entry.is_file():
            raise ValueError(
                "The exact compiled Studio composition is unavailable; render preflight first."
            )
        hyperframes_cli = (
            project_root()
            / "node_modules"
            / "hyperframes"
            / "dist"
            / "cli.js"
        ).resolve()
        return create_studio_handoff(
            manifest=manifest,
            build_lock=build,
            sequence_id=payload.sequence_id,
            element_id=payload.element_id,
            absolute_frame=payload.absolute_frame,
            studio_context={
                "projectPath": str(studio_project),
                "compositionPath": str(entry),
                "previewCommand": (
                    f'node "{hyperframes_cli}" preview '
                    f'"{studio_project}"'
                ),
                "selectionQueryCommand": (
                    f'node "{hyperframes_cli}" preview '
                    f'"{studio_project}" --selection --json'
                ),
            },
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Studio handoff rejected: {exc}") from exc


@app.post("/api/creator-production/studio/edits")
def apply_creator_studio_edits(payload: CreatorStudioEditRequest) -> dict:
    try:
        return persist_studio_edits(
            _creator_production_root(),
            handoff=payload.handoff,
            edits=payload.edits,
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Studio edits rejected: {exc}") from exc


@app.get("/api/visual/current")
def current_visual_project() -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        plan = load_visual_plan(plan_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not reload the private visual plan: {exc}") from exc
    state.visual_plan = plan
    return visual_plan_response(plan_path, plan)


@app.get("/api/visual/catalog")
def visual_catalog() -> dict:
    try:
        return load_visual_catalog()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not load the visual treatment catalog: {exc}") from exc


@app.get("/api/visual/catalog/recipes/{recipe_id}/preview")
def visual_recipe_preview(recipe_id: str) -> FileResponse:
    try:
        path = recipe_preview_path(recipe_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="No private production preview is available for this recipe yet.")
    return FileResponse(path)


@app.get("/api/visual/catalog/treatments/{treatment_id}/preview")
def visual_treatment_preview(treatment_id: str) -> FileResponse:
    try:
        path = recipe_preview_path(treatment_id, require_recipe=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="No private production preview is available for this treatment yet.")
    return FileResponse(path)


@app.get("/api/visual/catalog/treatments/{treatment_id}/motion-preview")
def visual_treatment_motion_preview(treatment_id: str) -> FileResponse:
    try:
        path = treatment_motion_preview_path(treatment_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="No private motion preview is available for this treatment yet.")
    return FileResponse(path, media_type="video/mp4")


@app.patch("/api/visual/catalog/treatments/{treatment_id}")
def patch_visual_treatment(treatment_id: str, payload: TreatmentUpdateRequest) -> dict:
    try:
        treatment, _library = update_treatment_metadata(treatment_id, payload.updates)
        return treatment
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/visual/source-frame")
def visual_source_frame(time_sec: float) -> FileResponse:
    plan_path, _plan = _require_visual_plan()
    try:
        return FileResponse(scene_frame_preview(plan_path, time_sec), media_type="image/jpeg")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/visual/review-prompt")
def visual_review_prompt(payload: ReviewPromptRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        prompt, plan, count = build_review_prompt(plan_path, set(payload.review_ids) if payload.review_ids is not None else None)
        state.visual_plan = plan
        response = visual_plan_response(plan_path, plan)
        response.update({"prompt": prompt, "noteCount": count})
        return response
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not prepare review notes: {exc}") from exc


@app.get("/api/creator-library")
def creator_library(query: str = "") -> dict:
    return {"root": str(default_creator_library()), "assets": search_creator_library(query)}


@app.post("/api/creator-library/import-dialog")
def import_creator_library_asset() -> dict:
    source = _choose_visual_asset_file()
    if source is None:
        raise HTTPException(status_code=400, detail="No AI footage or image selected.")
    try:
        asset, library, duplicate = import_creator_asset(source)
        return {"asset": asset, "duplicate": duplicate, "assets": library["assets"]}
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not import Creator Library asset: {exc}") from exc


@app.get("/api/creator-library/{asset_id}/media")
def creator_library_media(asset_id: str, range: str | None = Header(default=None)) -> Response:
    try:
        return _range_response(creator_asset_path(asset_id), range)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/creator-library/{asset_id}")
def patch_creator_library_asset(asset_id: str, payload: CreatorAssetUpdateRequest) -> dict:
    try:
        asset, library = update_creator_asset(asset_id, payload.updates)
        return {"asset": asset, "assets": library["assets"]}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/creator-library/{asset_id}/use")
def use_creator_library_asset(asset_id: str, payload: CreatorAssetUseRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        _cue, plan = freeze_creator_asset(
            plan_path,
            asset_id,
            start_sec=payload.start_sec,
            end_sec=payload.end_sec,
            suggestion_id=payload.suggestion_id,
        )
        state.visual_plan = plan
        return visual_plan_response(plan_path, plan)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not add Creator Library asset: {exc}") from exc


@app.get("/api/visual/suggestions")
def visual_suggestions() -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        return load_visual_suggestions(plan_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not load visual suggestions: {exc}") from exc


@app.patch("/api/visual/suggestions/{suggestion_id}")
def patch_visual_suggestion(suggestion_id: str, payload: SuggestionUpdateRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        return update_suggestion(plan_path, suggestion_id, payload.updates)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/visual/suggestions/{suggestion_id}/decision")
def decide_visual_suggestion(suggestion_id: str, payload: SuggestionDecisionRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        suggestion, suggestions, plan = decide_suggestion(
            plan_path,
            suggestion_id,
            action=payload.action,
            notes=payload.notes,
        )
        state.visual_plan = plan
        response = visual_plan_response(plan_path, plan)
        response.update({"suggestion": suggestion, "suggestions": suggestions["suggestions"], "coverage": suggestions.get("coverage")})
        return response
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/visual/suggestions/{suggestion_id}/approval-evidence/prepare")
def prepare_visual_suggestion_approval_evidence(suggestion_id: str) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        suggestion, suggestions = prepare_suggestion_approval_evidence(plan_path, suggestion_id)
        return {"suggestion": suggestion, "suggestions": suggestions["suggestions"], "coverage": suggestions.get("coverage")}
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/visual/suggestions/{suggestion_id}/approval-frame")
def visual_suggestion_approval_frame(suggestion_id: str) -> FileResponse:
    plan_path, _plan = _require_visual_plan()
    try:
        return FileResponse(suggestion_approval_frame_path(plan_path, suggestion_id), media_type="image/png")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/visual/suggestions/recipe")
def add_recipe_suggestion(payload: RecipeSuggestionRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        return create_recipe_suggestion(
            plan_path,
            payload.recipe_id,
            start_sec=payload.start_sec,
            end_sec=payload.end_sec,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/visual/suggestions/{suggestion_id}/build")
def build_visual_suggestion(suggestion_id: str) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        _cue, plan = build_nonmedia_suggestion(plan_path, suggestion_id)
        state.visual_plan = plan
        return visual_plan_response(plan_path, plan)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/visual/pexels/settings")
def pexels_configuration() -> dict:
    settings = pexels_settings()
    return {"configured": bool(settings["apiKey"]), "source": settings["source"]}


@app.post("/api/visual/pexels/settings")
def save_pexels_configuration(payload: PexelsKeyRequest) -> dict:
    try:
        save_pexels_key(payload.api_key)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"configured": True, "source": "local-settings"}


@app.post("/api/visual/suggestions/{suggestion_id}/pexels/search")
def search_suggestion_stock(suggestion_id: str) -> dict:
    plan_path, _plan = _require_visual_plan()
    suggestions = load_visual_suggestions(plan_path)
    suggestion = next((item for item in suggestions["suggestions"] if item.get("id") == suggestion_id), None)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Visual suggestion not found.")
    try:
        candidates = search_pexels_videos(suggestion.get("stockBrief") or {}, limit=5)
        update_suggestion(plan_path, suggestion_id, {"status": "prepared", "candidates": candidates})
        return {"suggestionId": suggestion_id, "candidates": candidates}
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        raise HTTPException(status_code=400, detail=f"Pexels search failed: {exc}") from exc


@app.post("/api/visual/suggestions/{suggestion_id}/pexels/select")
def select_suggestion_stock(suggestion_id: str, payload: StockSelectRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    suggestions = load_visual_suggestions(plan_path)
    suggestion = next((item for item in suggestions["suggestions"] if item.get("id") == suggestion_id), None)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Visual suggestion not found.")
    try:
        _cue, plan = select_pexels_candidate(plan_path, suggestion_id, payload.candidate, start_sec=float(suggestion["startSec"]), end_sec=float(suggestion["endSec"]))
        state.visual_plan = plan
        response = visual_plan_response(plan_path, plan)
        response["credits"] = credits_text(plan_path)
        return response
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not use Pexels footage: {exc}") from exc


@app.get("/api/visual/credits")
def visual_credits() -> dict:
    plan_path, _plan = _require_visual_plan()
    return {"credits": credits_text(plan_path)}


@app.post("/api/visual/create-dialog")
def create_visual_project_dialog() -> dict:
    active = _active_video_project()
    if active is not None:
        return ensure_visual_project()
    source = _choose_video_file()
    if source is None:
        raise HTTPException(status_code=400, detail="No locked video selected.")
    transcript = editor_project_document(state.project, state.edits) if state.project is not None else None
    try:
        plan_path, plan = create_visual_project(source, transcript_document=transcript)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not create the private visual project: {exc}") from exc
    state.visual_plan_path = plan_path
    state.visual_plan = plan
    return visual_plan_response(plan_path, plan)


@app.post("/api/visual/open-dialog")
def open_visual_project_dialog() -> dict:
    path = _choose_visual_plan_file()
    if path is None:
        raise HTTPException(status_code=400, detail="No visual plan selected.")
    try:
        plan = load_visual_plan(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not open the visual plan: {exc}") from exc
    state.visual_plan_path = path.resolve()
    state.visual_plan = plan
    return visual_plan_response(state.visual_plan_path, plan)


@app.post("/api/visual/ensure")
def ensure_visual_project() -> dict:
    active = _active_video_project()
    if active is None:
        raise HTTPException(status_code=400, detail="Create or open a parent video project first.")
    manifest_path, manifest = active
    plan_path = resolve_video_project_path(manifest_path, manifest, "visualPlan")
    if plan_path.is_file():
        plan = load_visual_plan(plan_path)
    else:
        locked_cut = resolve_video_project_path(manifest_path, manifest, "lockedCut")
        if not artifact_current(manifest, "lockedCutRevision"):
            raise HTTPException(status_code=400, detail="Export the current source sequence as a locked cut before starting Visual Production.")
        final_transcript = resolve_video_project_path(manifest_path, manifest, "finalTranscript")
        transcript = final_transcript if final_transcript.is_file() else resolve_video_project_path(manifest_path, manifest, "editorProject")
        try:
            plan_path, plan = create_visual_plan_in_video_project(
                video_project_root(manifest_path),
                source_video=locked_cut,
                transcript_path=transcript,
                plan_path=plan_path,
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Could not initialize Visual Production: {exc}") from exc
        # The plan is authored against this sequence revision. A later re-cut bumps the revision
        # and this artifact stops being current, alongside the source hash recorded in the plan.
        mark_artifact_current(manifest, "visualPlanRevision")
        save_video_project(manifest_path, manifest)
    state.visual_plan_path = plan_path
    state.visual_plan = plan
    return visual_plan_response(plan_path, plan)


@app.post("/api/visual/save")
def save_current_visual_plan(payload: VisualPlanSaveRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        plan = save_visual_plan(plan_path, payload.plan)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not save the visual plan: {exc}") from exc
    state.visual_plan = plan
    return visual_plan_response(plan_path, plan)


@app.post("/api/visual/assets/import-dialog")
def import_visual_asset_dialog() -> dict:
    plan_path, _plan = _require_visual_plan()
    source = _choose_visual_asset_file()
    if source is None:
        raise HTTPException(status_code=400, detail="No animation or image selected.")
    try:
        asset, plan = import_visual_asset(plan_path, source)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not import the visual asset: {exc}") from exc
    state.visual_plan = plan
    response = visual_plan_response(plan_path, plan)
    response["importedAsset"] = asset
    return response


@app.get("/api/visual/source")
def visual_source_video(request: Request, range: str | None = Header(default=None)) -> Response:
    plan_path, plan = _require_visual_plan()
    root = find_visual_root(plan_path)
    path = resolve_project_path(root, plan["source"]["video"])
    return _range_response(path, range)


@app.get("/api/visual/final")
def visual_final_video(request: Request, range: str | None = Header(default=None)) -> Response:
    plan_path, plan = _require_visual_plan()
    path, _revision = active_visual_master(plan_path, plan)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No persisted Visual Production master is available.")
    return _range_response(path, range)


def _hyperframes_distribution_file(name: str) -> Path:
    path = Path(__file__).resolve().parents[1] / "node_modules" / "hyperframes" / "dist" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"HyperFrames runtime file is missing: {name}")
    return path


@app.get("/api/visual/runtime/player.js")
def visual_runtime_player() -> FileResponse:
    return FileResponse(_hyperframes_distribution_file("hyperframes-player.global.js"), media_type="application/javascript")


@app.get("/api/visual/runtime/core.js")
def visual_runtime_core() -> FileResponse:
    return FileResponse(_hyperframes_distribution_file("hyperframe.runtime.iife.js"), media_type="application/javascript")


@app.get("/api/visual/runtime/composition/{relative_path:path}")
def visual_runtime_composition_file(relative_path: str) -> Response:
    plan_path, plan = _require_visual_plan()
    runtime_root, runtime_entry, _composition = active_visual_runtime(plan_path, plan)
    if runtime_root is None or runtime_entry is None:
        try:
            runtime_root, _duration = build_hyperframes_composition(plan_path)
            runtime_entry = runtime_root / "index.html"
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=400, detail=f"Could not prepare the HyperFrames preview: {exc}") from exc
    requested = relative_path or runtime_entry.name
    target = (runtime_root / requested).resolve()
    try:
        target.relative_to(runtime_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="HyperFrames preview path escapes the registered composition.") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="HyperFrames preview file not found.")
    if target.suffix.lower() == ".html" and target.resolve() == runtime_entry.resolve():
        document = target.read_text(encoding="utf-8")
        runtime_script = '<script src="/api/visual/runtime/core.js" data-vcg-runtime="hyperframes"></script>'
        document = document.replace("</body>", f"{runtime_script}</body>") if "</body>" in document else f"{document}{runtime_script}"
        return HTMLResponse(document, headers={"Cache-Control": "no-store"})
    return FileResponse(target)


@app.post("/api/visual/gates/representative")
def approve_visual_representative(payload: VisualRepresentativeApprovalRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        plan = approve_representative_scene(plan_path, payload.cue_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not approve the representative scene: {exc}") from exc
    state.visual_plan = plan
    return visual_plan_response(plan_path, plan)


@app.post("/api/visual/gates/full-review")
def approve_visual_full_review() -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        plan = approve_full_review(plan_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not approve the full review: {exc}") from exc
    state.visual_plan = plan
    return visual_plan_response(plan_path, plan)


@app.post("/api/visual/gates/reopen")
def verify_visual_delivery_reopened(payload: VisualReopenVerificationRequest) -> dict:
    plan_path, _plan = _require_visual_plan()
    try:
        plan = verify_delivered_revision_reopened(plan_path, payload.revision_number, payload.plan_hash)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not verify the reopened delivery: {exc}") from exc
    state.visual_plan = plan
    return visual_plan_response(plan_path, plan)


@app.get("/api/visual/assets/{asset_id}")
def visual_asset(asset_id: str, request: Request, range: str | None = Header(default=None)) -> Response:
    plan_path, plan = _require_visual_plan()
    asset = next((item for item in plan.get("assets", []) if item.get("id") == asset_id), None)
    if asset is None:
        raise HTTPException(status_code=404, detail="Visual asset not found.")
    root = find_visual_root(plan_path)
    path = resolve_project_path(root, asset["path"])
    return _range_response(path, range)


@app.post("/api/visual/render")
def start_visual_render(payload: VisualRenderRequest) -> dict:
    """Reject retired visual render execution."""
    raise HTTPException(
        status_code=410,
        detail=(
            "Legacy Visual Production rendering is retired. Existing projects and "
            "persisted outputs remain available for read-only recovery; use Creator "
            "Production for new render work."
        ),
    )


def _run_visual_render_job(job: VisualRenderJob, plan_path: Path, output: Path, payload: VisualRenderRequest, purpose: str) -> None:
    try:
        rendered = render_visual_plan(
            plan_path,
            output,
            start_sec=payload.start_sec,
            end_sec=payload.end_sec,
            quality=payload.quality,
            purpose=purpose,
            progress=job.update,
        )
        job.complete(rendered)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        job.fail(str(exc))


@app.get("/api/visual/render/jobs/{job_id}")
def visual_render_job(job_id: str) -> dict:
    job = state.visual_render_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Visual render job not found.")
    return job.snapshot(job_id)


@app.get("/api/visual/render/active")
def active_visual_render_job() -> dict:
    plan_path, _plan = _require_visual_plan()
    active = next(
        (
            job for job in reversed(list(state.visual_render_jobs.values()))
            if job.plan_path == plan_path.resolve() and job.status == "running"
        ),
        None,
    )
    if active is not None:
        return {"job": active.snapshot(active.job_id)}

    state_path = plan_path.parent / "render-job.json"
    if not state_path.is_file():
        return {"job": None}
    try:
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"job": None}
    if persisted.get("status") == "running":
        persisted.update({
            "status": "failed",
            "stage": "failed",
            "error": "The application restarted before this export completed. Start Export final again.",
            "message": "The application restarted before this export completed. Start Export final again.",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            state_path.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
        except OSError:
            pass
    return {"job": persisted}


@app.get("/api/visual/render/jobs/{job_id}/video")
def visual_render_video(job_id: str, range: str | None = Header(default=None)) -> Response:
    job = state.visual_render_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Visual render job not found.")
    snapshot = job.snapshot(job_id)
    if snapshot["status"] != "complete" or not snapshot["output_path"]:
        raise HTTPException(status_code=409, detail="Visual render is not complete.")
    return _range_response(Path(snapshot["output_path"]), range)


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
        "output_folder": str(_video_project_output_folder()),
    }


@app.post("/api/caption/choose-video")
def choose_caption_video() -> dict:
    path = _choose_video_file()
    if path is None:
        raise HTTPException(status_code=400, detail="No video file selected.")
    state.caption_video_path = path
    return {"source": str(path), "output_folder": str(_video_project_output_folder())}


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
        "output_folder": str(_video_project_output_folder()),
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
    return {"source": str(path), "output_folder": str(_video_project_output_folder())}


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
    output_root = Path(payload.output_folder).expanduser().resolve() if payload.output_folder else _video_project_output_folder()
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
    preview_root = _video_project_stage_path("audioPreviews") or temp_dir()
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

    output_root = Path(payload.output_folder).expanduser().resolve() if payload.output_folder else _video_project_output_folder()
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


@app.get("/api/projects/current/render-preview/{preview_id}")
def rendered_cut_preview(
    preview_id: str,
    request: Request,
    range_header: str | None = Header(default=None, alias="Range"),
) -> Response:
    if preview_id != state.rendered_cut_preview_id:
        raise HTTPException(status_code=404, detail="Rendered cut preview not found.")
    path = state.rendered_cut_preview_path
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Rendered cut preview file not found.")
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


def _clear_rendered_cut_preview() -> None:
    path = state.rendered_cut_preview_path
    if path is not None:
        try:
            resolved = path.resolve()
            if resolved.parent == temp_dir().resolve():
                resolved.unlink(missing_ok=True)
        except OSError:
            pass
    state.rendered_cut_preview_id = None
    state.rendered_cut_preview_path = None


def _rendered_preview_splices(plan: SplicePlan, project: TranscriptProject) -> list[dict]:
    range_end_times: dict[str, float] = {}
    section_text: dict[str, str] = {}
    elapsed = 0.0
    for kept_range in plan.kept_ranges:
        elapsed += (kept_range.adjusted_end_frame - kept_range.adjusted_start_frame + 1) / project.fps
        range_end_times[kept_range.id] = elapsed
        start_index = project.word_index(kept_range.start_word_id)
        end_index = project.word_index(kept_range.end_word_id)
        section_text[kept_range.id] = " ".join(word.text for word in project.words[start_index : end_index + 1])
    return [
        {
            "id": splice.id,
            "anchor_key": splice.anchor_key,
            "preview_time_seconds": round(range_end_times.get(splice.left_keep_range_id, 0.0), 6),
            "left_out_frame": splice.left_out_frame,
            "right_in_frame": splice.right_in_frame,
            "left_section": section_text.get(splice.left_keep_range_id, "Start of source"),
            "right_section": section_text.get(splice.right_keep_range_id, ""),
        }
        for splice in plan.splices
    ]


def _rendered_preview_segments(plan: SplicePlan, project: TranscriptProject) -> list[dict]:
    elapsed_frames = 0
    segments: list[dict] = []
    for kept_range in plan.kept_ranges:
        frame_count = kept_range.adjusted_end_frame - kept_range.adjusted_start_frame + 1
        segments.append(
            {
                "source_start_frame": kept_range.adjusted_start_frame,
                "source_end_frame": kept_range.adjusted_end_frame,
                "preview_start_seconds": round(elapsed_frames / project.fps, 6),
                "preview_end_seconds": round((elapsed_frames + frame_count) / project.fps, 6),
            }
        )
        elapsed_frames += frame_count
    return segments


def _save_current_project_if_loaded(project: TranscriptProject) -> None:
    if state.project_path is not None:
        save_editor_project(state.project_path, project, state.edits)
        _touch_video_project()


def _touch_video_project() -> None:
    active = _active_video_project()
    if active is None:
        return
    state.video_project = save_video_project(active[0], active[1])


def _annotate_generated_project(
    project: TranscriptProject,
    source: Path,
    model_label: str,
    compute_label: str,
) -> TranscriptProject:
    sequence_revision = (
        int(state.video_project.get("sequenceRevision") or 0)
        if state.video_project is not None
        else None
    )
    generation = build_generation_metadata(
        source,
        model_label=model_label,
        model_id=MODEL_OPTIONS[model_label],
        compute_label=compute_label,
        compute=COMPUTE_OPTIONS[compute_label],
        sequence_revision=sequence_revision,
    )
    annotated = replace(project, generation=generation)
    repeats = detect_repeated_word_ids(annotated.words)
    return replace(annotated, generation=with_initial_repeat_suggestions(annotated, repeats))


def _store_generated_project(project: TranscriptProject, source: Path) -> None:
    state.project = project
    state.edits = EditDecisionList()
    if state.project_path is not None:
        save_editor_project(state.project_path, project, state.edits)
        if state.video_project is not None:
            mark_artifact_current(state.video_project, "transcriptRevision")
            _save_original_transcript(project)
        _touch_video_project()
    state.caption_video_path = source


def _save_original_transcript(project: TranscriptProject) -> None:
    if state.video_project is None:
        return
    destination = _video_project_stage_path("originalTranscript")
    if destination is None:
        return
    if destination.exists() and not artifact_current(state.video_project, "originalTranscriptRevision"):
        revision = int(state.video_project.get("sequenceRevision") or 0)
        state.video_project["paths"]["originalTranscript"] = f"transcripts/original-generated-r{revision}.vcg.json"
        destination = _video_project_stage_path("originalTranscript")
    if destination is not None and not destination.exists():
        save_editor_project(destination, project, EditDecisionList())
    mark_artifact_current(state.video_project, "originalTranscriptRevision")


def _save_final_transcript(project: TranscriptProject, plan: SplicePlan, locked_cut: Path) -> None:
    destination = _video_project_stage_path("finalTranscript")
    if destination is None:
        return
    reviewed_destination = _video_project_stage_path("finalReviewedProject")
    analysis_destination = _video_project_stage_path("editAnalysis")
    if reviewed_destination is not None:
        save_editor_project(reviewed_destination, project, state.edits)
    if analysis_destination is not None:
        analysis_destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = analysis_destination.with_suffix(f"{analysis_destination.suffix}.tmp")
        temporary.write_text(
            json.dumps(build_edit_analysis(project, state.edits, plan), indent=2),
            encoding="utf-8",
        )
        temporary.replace(analysis_destination)
    remapped = replace(remap_transcript(project, plan.kept_ranges), source=str(locked_cut.resolve()))
    timing_hash = transcript_word_timing_hash(editor_project_document(remapped, EditDecisionList()))
    remapped = replace(
        remapped,
        generation={
            **remapped.generation,
            "lockedTranscript": {
                "schemaVersion": 1,
                "timingAuthority": "final-locked-transcript",
                "lockedCutSha256": sha256_file(locked_cut),
                "wordTimingSha256": timing_hash,
                "timingMutationAllowed": False,
            },
        },
    )
    save_editor_project(destination, remapped, EditDecisionList())
    if state.video_project is not None:
        # Only stamp the locked cut as current when the cut that was written is the one the
        # manifest points at. Stamping unconditionally marked a stale path as fresh.
        manifest_locked = _video_project_stage_path("lockedCut")
        if manifest_locked is not None and manifest_locked.resolve() == locked_cut.resolve():
            mark_artifact_current(state.video_project, "lockedCutRevision")
        mark_artifact_current(state.video_project, "finalReviewedProjectRevision")
        mark_artifact_current(state.video_project, "finalTranscriptRevision")
        mark_artifact_current(state.video_project, "editAnalysisRevision")
    _touch_video_project()


def _record_audio_delivery(
    *,
    normalized: bool,
    output_path: Path,
    preset_id: str | None,
    target_i: float | None,
    measurement: LoudnessMeasurement | None,
) -> None:
    if state.video_project is None:
        return
    state.video_project.setdefault("artifacts", {})["audioDelivery"] = {
        "normalizationApplied": normalized,
        "presetId": preset_id,
        "targetIntegratedLufs": target_i,
        "measuredIntegratedLufs": measurement.input_i if measurement is not None else None,
        "measurementPoint": "pre-normalization-source" if measurement is not None else "not-measured",
        "outputPath": str(output_path.resolve()),
        "recordedAt": datetime.now(timezone.utc).isoformat(),
    }


def _project_response(
    *,
    fine_tune_summary: dict[str, int] | None = None,
    pause_analysis_summary: dict[str, int] | None = None,
) -> dict:
    project = _require_project()
    plan = generate_splices(project, state.edits)
    deleted_word_ids = _deleted_word_ids(project)
    deleted_silence_ids = _deleted_silence_ids()
    dead_space_candidate_count = sum(
        1
        for silence in project.silence_ranges
        if silence.id not in deleted_silence_ids
        and silence.audio_analyzed
        and _silence_duration_seconds(silence, project.fps) >= state.edits.settings.dead_space_min_seconds
    )
    pause_analysis_pending_count = sum(
        1
        for silence in project.silence_ranges
        if not silence.audio_analyzed
        and (silence.end_frame - silence.start_frame + 1) / project.fps
        >= state.edits.settings.dead_space_min_seconds
    )
    final_range = plan.kept_ranges[-1] if plan.kept_ranges else None
    final_cut = None
    if final_range is not None:
        final_word_index = project.word_index(final_range.end_word_id)
        maximum_out_frame = (
            project.words[final_word_index + 1].start_frame - 1
            if final_word_index + 1 < len(project.words)
            else None
        )
        final_cut = {
            "out_frame": final_range.adjusted_end_frame,
            "suggested_out_frame": final_range.suggested_end_frame,
            "adjustment": final_range.adjusted_end_frame - final_range.suggested_end_frame,
            "minimum_out_frame": final_range.adjusted_start_frame,
            "maximum_out_frame": maximum_out_frame,
            "custom": state.edits.final_out_frame is not None,
        }
    return {
        "project_path": str(state.project_path) if state.project_path else None,
        "video_project": video_project_response(state.video_project_path, state.video_project) if _active_video_project() else None,
        "project": _project_dict(project),
        "tokens": [
            asdict(token)
            for token in transcript_tokens(project, state.edits.settings.dead_space_min_seconds)
        ],
        "deleted_word_ids": sorted(deleted_word_ids),
        "repeated_word_ids": sorted(detect_repeated_word_ids(project.words, deleted_word_ids)),
        "deleted_silence_ids": sorted(deleted_silence_ids),
        "settings": asdict(state.edits.settings),
        "dead_space_candidate_count": dead_space_candidate_count,
        "pause_analysis_pending_count": pause_analysis_pending_count,
        "fine_tune_summary": fine_tune_summary,
        "pause_analysis_summary": pause_analysis_summary,
        "splices": [_splice_dict(splice, project.fps) for splice in plan.splices],
        "kept_ranges": [asdict(item) for item in plan.kept_ranges],
        "final_cut": final_cut,
    }


def _project_dict(project: TranscriptProject) -> dict:
    return {
        "source": project.source,
        "fps": project.fps,
        "words": [asdict(word) for word in project.words],
        "silence_ranges": [asdict(silence) for silence in project.silence_ranges],
        "generation": project.generation,
    }


def _measured_pause_out_frame(project: TranscriptProject, left_word_id: str, right_word_id: str) -> int | None:
    left_word = project.word_by_id(left_word_id)
    right_word = project.word_by_id(right_word_id)
    maximum_out_frame = min(
        right_word.start_frame - 1,
        round((left_word.end + MAX_EXTENSION_SECONDS) * project.fps),
    )
    for silence in project.silence_ranges:
        if (
            silence.audio_analyzed
            and silence.start_frame == left_word.end_frame + 1
            and silence.end_frame == right_word.start_frame - 1
            and silence.measured_start_frame is not None
            and left_word.end_frame < silence.measured_start_frame <= maximum_out_frame
        ):
            return silence.measured_start_frame
    return None


def _silence_duration_seconds(silence, fps: float) -> float:
    if silence.measured_start_frame is not None and silence.measured_end_frame is not None:
        return max(0, silence.measured_end_frame - silence.measured_start_frame + 1) / fps
    return max(0, silence.end_frame - silence.start_frame + 1) / fps


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

    return StreamingResponse(
        iterator(),
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        },
    )


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    def unsatisfiable(detail: str) -> HTTPException:
        return HTTPException(
            status_code=416,
            detail=detail,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    if file_size <= 0:
        raise unsatisfiable("Requested range is not satisfiable.")
    try:
        units, value = range_header.split("=", 1)
    except ValueError as exc:
        raise unsatisfiable("Invalid range header.") from exc
    if units.strip().lower() != "bytes":
        raise unsatisfiable("Only byte ranges are supported.")
    if "," in value:
        raise unsatisfiable("Multiple byte ranges are not supported.")

    start_text, separator, end_text = value.strip().partition("-")
    if not separator or (not start_text and not end_text):
        raise unsatisfiable("Invalid range header.")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise unsatisfiable("Requested range is not satisfiable.")
            start = max(0, file_size - suffix_length)
            end = file_size - 1
    except ValueError as exc:
        raise unsatisfiable("Invalid range header.") from exc

    end = min(end, file_size - 1)
    if start < 0 or end < start or start >= file_size:
        raise unsatisfiable("Requested range is not satisfiable.")
    return start, end
