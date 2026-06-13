from __future__ import annotations

from pathlib import Path

from app.core.action_logger import ActionLogger
from app.core.ffmpeg_runner import extract_audio
from app.core.media_probe import probe_video_fps
from app.core.transcriber import transcribe_audio, words_to_transcript_project
from app.core.transcript_model import TranscriptProject


def generate_editor_transcript(
    *,
    input_video_path: Path,
    working_dir: Path,
    model_size: str,
    compute_mode: str,
    logger: ActionLogger | None = None,
    progress_callback=None,
) -> TranscriptProject:
    _log(logger, f"Starting transcript generation for {input_video_path}")
    _progress(progress_callback, 5, "Reading video timing...")
    fps = probe_video_fps(input_video_path)
    _log(logger, f"Detected FPS: {fps}")

    _progress(progress_callback, 15, "Extracting audio...")
    audio_path = extract_audio(input_video_path, working_dir / "editor_audio.wav")
    _log(logger, f"Extracted audio to {audio_path}")

    _progress(progress_callback, -1, "Transcribing words... first run may download the selected Whisper model.")
    _log(logger, f"Starting faster-whisper model={model_size} compute={compute_mode}")
    words = transcribe_audio(
        audio_path,
        model_size=model_size,
        compute_mode=compute_mode,
        progress_callback=lambda count, seconds_done, total: _transcription_progress(
            progress_callback,
            logger,
            count,
            seconds_done,
            total,
        ),
    )
    _log(logger, f"Transcribed {len(words)} words")

    _progress(progress_callback, 90, "Building transcript editor project...")
    project = words_to_transcript_project(str(input_video_path), words, fps=fps)
    _progress(progress_callback, 100, "Transcript ready.")
    return project


def _progress(callback, value: int, message: str) -> None:
    if callback:
        callback(value, message)


def _transcription_progress(callback, logger: ActionLogger | None, count: int, seconds_done: float, total: float) -> None:
    if total > 0:
        percent = max(35, min(89, int(35 + (seconds_done / total) * 54)))
        message = f"Transcribing... {count} words, {seconds_done:.1f}s / {total:.1f}s processed"
    else:
        percent = -1
        message = f"Transcribing... {count} words, {seconds_done:.1f}s processed"
    _progress(callback, percent, message)
    if count and count % 100 == 0:
        _log(logger, message)


def _log(logger: ActionLogger | None, message: str) -> None:
    if logger:
        logger.info(message)
