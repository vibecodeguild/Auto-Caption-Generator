from __future__ import annotations

from pathlib import Path

from app.core.ass_builder import write_ass_file
from app.core.caption_grouping import group_words
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.ffmpeg_runner import burn_subtitles, extract_audio
from app.core.file_utils import ensure_output_path, validate_input_video
from app.core.media_probe import ass_play_resolution_for_video
from app.core.settings import CaptionPreset, CaptionStyle, fonts_dir
from app.core.transcriber import transcribe_audio


def _progress(callback, value: int, message: str) -> None:
    if callback:
        callback(value, message)


def generate_captioned_video(
    input_video_path: str,
    output_video_path: str,
    working_dir: str,
    style: CaptionStyle,
    preset: CaptionPreset,
    model_size: str,
    compute_mode: str,
    progress_callback=None,
) -> str:
    input_path = Path(input_video_path)
    output_path = Path(output_video_path)
    work_path = Path(working_dir)

    _progress(progress_callback, 5, "Validating input...")
    validate_input_video(input_path)
    ensure_output_path(output_path)
    find_ffmpeg()

    play_res_x, play_res_y, default_margin = ass_play_resolution_for_video(input_path)
    if style.margin_v <= 0:
        style = CaptionStyle(
            font_family=style.font_family,
            main_font_size=style.main_font_size,
            active_font_size=style.active_font_size,
            main_color=style.main_color,
            active_color=style.active_color,
            outline_color=style.outline_color,
            outline_width=style.outline_width,
            bold=style.bold,
            active_bold=style.active_bold,
            position=style.position,
            margin_v=default_margin,
            outline_enabled=style.outline_enabled,
            shadow_enabled=style.shadow_enabled,
            shadow_color=style.shadow_color,
            shadow_depth=style.shadow_depth,
            glow_enabled=style.glow_enabled,
            glow_color=style.glow_color,
            glow_strength=style.glow_strength,
        )

    _progress(progress_callback, 15, "Extracting audio...")
    audio_path = extract_audio(input_path, work_path / "audio.wav")

    _progress(progress_callback, 35, "Transcribing audio...")
    words = transcribe_audio(audio_path, model_size=model_size, compute_mode=compute_mode)

    _progress(progress_callback, 65, "Creating styled captions...")
    groups = group_words(
        words,
        max_words=preset.max_words,
        max_duration=preset.max_duration,
        max_chars=preset.max_chars,
    )
    if not groups:
        raise RuntimeError("No speech was detected in this video.")
    ass_path = write_ass_file(
        work_path / "captions.ass",
        groups=groups,
        style=style,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
    )

    _progress(progress_callback, 80, "Rendering video...")
    burn_subtitles(input_path, ass_path, output_path, fonts_dir())

    _progress(progress_callback, 100, "Done.")
    return str(output_path)
