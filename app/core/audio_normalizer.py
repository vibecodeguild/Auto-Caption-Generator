from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.process_utils import hidden_subprocess_flags


@dataclass(frozen=True)
class AudioPreset:
    id: str
    name: str
    description: str
    leveling_filter: str | None


@dataclass(frozen=True)
class LoudnessMeasurement:
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class LoudnessHotspot:
    start_seconds: float
    focus_seconds: float
    loudness_lufs: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class LoudnessHotspots:
    loudest: LoudnessHotspot
    quietest_speech: LoudnessHotspot

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {
            "loudest": self.loudest.to_dict(),
            "quietest_speech": self.quietest_speech.to_dict(),
        }


AUDIO_PRESETS: dict[str, AudioPreset] = {
    "normalize": AudioPreset(
        id="normalize",
        name="Normalize Only",
        description="Set a consistent final loudness while preserving the natural difference between quiet and loud speech.",
        leveling_filter=None,
    ),
    "gentle": AudioPreset(
        id="gentle",
        name="Gentle Voice Leveling",
        description="Smooth noticeable volume changes with a conservative gain limit, then normalize for YouTube.",
        leveling_filter="dynaudnorm=f=500:g=31:p=0.90:m=4",
    ),
    "strong": AudioPreset(
        id="strong",
        name="Strong Voice Leveling",
        description="More aggressively raise quiet speech. Best for uneven recordings with low background noise.",
        leveling_filter="dynaudnorm=f=400:g=21:p=0.90:m=8",
    ),
}


def analyze_audio(
    *,
    ffmpeg: Path,
    input_video: Path,
    preset_id: str,
    target_i: float = -14.0,
    target_lra: float = 7.0,
    target_tp: float = -1.5,
) -> LoudnessMeasurement:
    preset = _preset(preset_id)
    loudnorm = _loudnorm_first_pass(target_i=target_i, target_lra=target_lra, target_tp=target_tp)
    audio_filter = ",".join(filter(None, [preset.leveling_filter, loudnorm]))
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-i",
        str(input_video),
        "-map",
        "0:a:0",
        "-af",
        audio_filter,
        "-f",
        "null",
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
        details = (result.stderr or result.stdout or "").strip()
        if "matches no streams" in details or "does not contain any stream" in details:
            raise RuntimeError("This video does not contain an audio track.")
        raise RuntimeError(f"FFmpeg could not analyze this video's audio.\n\nFFmpeg details:\n{details[-1200:]}")
    return parse_loudnorm_measurement(result.stderr)


def analyze_loudness_hotspots(
    *,
    ffmpeg: Path,
    input_video: Path,
    preview_duration: float = 20.0,
    focus_duration: float = 3.0,
) -> LoudnessHotspots:
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-i",
        str(input_video),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file=-",
        "-f",
        "null",
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
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"FFmpeg could not scan this video's loudness changes.\n\nFFmpeg details:\n{details[-1200:]}")
    samples = parse_momentary_loudness(result.stdout)
    speech_ranges = detect_speech_ranges(input_video)
    if not speech_ranges:
        raise RuntimeError("No speech was detected, so loudest and quietest speech previews are unavailable.")
    return find_loudness_hotspots(
        samples,
        preview_duration=preview_duration,
        focus_duration=focus_duration,
        speech_ranges=speech_ranges,
    )


def normalize_video_audio(
    *,
    ffmpeg: Path,
    input_video: Path,
    output_video: Path,
    preset_id: str,
    measurement: LoudnessMeasurement,
    target_i: float = -14.0,
    target_lra: float = 7.0,
    target_tp: float = -1.5,
) -> Path:
    preset = _preset(preset_id)
    output_video.parent.mkdir(parents=True, exist_ok=True)
    loudnorm = _loudnorm_second_pass(
        measurement=measurement,
        target_i=target_i,
        target_lra=target_lra,
        target_tp=target_tp,
    )
    audio_filter = ",".join(filter(None, [preset.leveling_filter, loudnorm]))
    command = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-i",
        str(input_video),
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0",
        "-map_metadata",
        "0",
        "-c:v",
        "copy",
        "-af",
        audio_filter,
        "-ar",
        "48000",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-movflags",
        "+faststart",
        str(output_video),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "FFmpeg could not create the normalized video. Check that the output file is not open and the output folder is writable."
            f"\n\nFFmpeg details:\n{details[-1200:]}"
        )
    return output_video


def create_audio_preview(
    *,
    ffmpeg: Path,
    input_video: Path,
    original_preview: Path,
    corrected_preview: Path,
    start_seconds: float,
    duration_seconds: float,
    preset_id: str,
    measurement: LoudnessMeasurement,
    target_i: float = -14.0,
    target_lra: float = 7.0,
    target_tp: float = -1.5,
) -> tuple[Path, Path]:
    preset = _preset(preset_id)
    original_preview.parent.mkdir(parents=True, exist_ok=True)
    corrected_preview.parent.mkdir(parents=True, exist_ok=True)
    clip_prefix = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        str(input_video),
        "-t",
        f"{duration_seconds:.3f}",
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0",
    ]
    video_options = [
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
    ]
    audio_options = ["-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    _run_ffmpeg(
        clip_prefix + video_options + audio_options + [str(original_preview)],
        "FFmpeg could not create the original preview clip.",
    )

    loudnorm = _loudnorm_second_pass(
        measurement=measurement,
        target_i=target_i,
        target_lra=target_lra,
        target_tp=target_tp,
    )
    audio_filter = ",".join(filter(None, [preset.leveling_filter, loudnorm]))
    _run_ffmpeg(
        clip_prefix + video_options + ["-af", audio_filter] + audio_options + [str(corrected_preview)],
        "FFmpeg could not create the corrected preview clip.",
    )
    return original_preview, corrected_preview


def parse_loudnorm_measurement(stderr: str) -> LoudnessMeasurement:
    matches = re.findall(r"\{\s*\"input_i\".*?\}", stderr, flags=re.DOTALL)
    if not matches:
        raise RuntimeError("FFmpeg finished without returning loudness measurements.")
    try:
        data = json.loads(matches[-1])
        measurement = LoudnessMeasurement(
            input_i=float(data["input_i"]),
            input_tp=float(data["input_tp"]),
            input_lra=float(data["input_lra"]),
            input_thresh=float(data["input_thresh"]),
            target_offset=float(data["target_offset"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("FFmpeg returned invalid loudness measurements.") from exc
    if not all(math.isfinite(value) for value in asdict(measurement).values()):
        raise RuntimeError("The audio is silent or too quiet to measure reliably.")
    return measurement


def parse_momentary_loudness(output: str) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    current_time: float | None = None
    for line in output.splitlines():
        time_match = re.search(r"pts_time:([0-9.]+)", line)
        if time_match:
            current_time = float(time_match.group(1))
            continue
        loudness_match = re.search(r"lavfi\.r128\.M=(-?[0-9.]+)", line)
        if loudness_match and current_time is not None:
            loudness = float(loudness_match.group(1))
            if math.isfinite(loudness):
                samples.append((current_time, loudness))
            current_time = None
    if not samples:
        raise RuntimeError("FFmpeg did not return a usable loudness timeline.")
    return samples


def find_loudness_hotspots(
    samples: list[tuple[float, float]],
    *,
    preview_duration: float = 20.0,
    focus_duration: float = 3.0,
    speech_ranges: list[tuple[float, float]] | None = None,
) -> LoudnessHotspots:
    speech_mask = _speech_mask(samples, speech_ranges)
    audible = [
        loudness
        for (_, loudness), is_speech in zip(samples, speech_mask)
        if is_speech and loudness > -100.0
    ]
    if not audible:
        raise RuntimeError("The audio is silent or too quiet to identify preview sections.")
    sorted_audible = sorted(audible)
    high_reference = sorted_audible[max(0, math.ceil(len(sorted_audible) * 0.9) - 1)]
    speech_gate = max(-70.0, high_reference - 50.0)
    step = _sample_step(samples)
    window_size = max(1, round(focus_duration / step))
    candidates: list[tuple[float, float]] = []

    for start_index in range(0, len(samples), max(1, round(0.5 / step))):
        window = samples[start_index : start_index + window_size]
        if not window:
            continue
        window_mask = speech_mask[start_index : start_index + window_size]
        active = [
            (time, loudness)
            for (time, loudness), is_speech in zip(window, window_mask)
            if is_speech and loudness >= speech_gate
        ]
        required_active = max(1, math.ceil(len(window) * (0.3 if speech_ranges else 0.5)))
        if len(active) < required_active:
            continue
        loudness = _energy_average([value for _, value in active])
        focus_time = sum(time for time, _ in active) / len(active)
        candidates.append((focus_time, loudness))

    if not candidates:
        active = [
            (time, loudness)
            for (time, loudness), is_speech in zip(samples, speech_mask)
            if is_speech and loudness >= speech_gate
        ]
        if not active:
            raise RuntimeError("No speech-like audio was found for recommended previews.")
        candidates = active

    loudest_focus, loudest_lufs = max(candidates, key=lambda item: item[1])
    quietest_focus, quietest_lufs = min(candidates, key=lambda item: item[1])
    duration = samples[-1][0] + step
    return LoudnessHotspots(
        loudest=_hotspot(loudest_focus, loudest_lufs, duration, preview_duration),
        quietest_speech=_hotspot(quietest_focus, quietest_lufs, duration, preview_duration),
    )


def detect_speech_ranges(input_video: Path) -> list[tuple[float, float]]:
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError as exc:
        raise RuntimeError("Speech detection is unavailable because faster-whisper is not installed.") from exc

    audio = decode_audio(str(input_video), sampling_rate=16000)
    timestamps = get_speech_timestamps(
        audio,
        VadOptions(
            threshold=0.45,
            min_speech_duration_ms=250,
            min_silence_duration_ms=400,
            speech_pad_ms=250,
        ),
        sampling_rate=16000,
    )
    return [
        (item["start"] / 16000.0, item["end"] / 16000.0)
        for item in timestamps
        if item["end"] > item["start"]
    ]


def preset_options() -> list[dict[str, str]]:
    return [
        {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
        }
        for preset in AUDIO_PRESETS.values()
    ]


def _preset(preset_id: str) -> AudioPreset:
    try:
        return AUDIO_PRESETS[preset_id]
    except KeyError as exc:
        raise ValueError(f"Unknown audio preset: {preset_id}") from exc


def _loudnorm_first_pass(*, target_i: float, target_lra: float, target_tp: float) -> str:
    return f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:print_format=json"


def _loudnorm_second_pass(
    *,
    measurement: LoudnessMeasurement,
    target_i: float,
    target_lra: float,
    target_tp: float,
) -> str:
    return (
        f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}"
        f":measured_I={measurement.input_i}:measured_LRA={measurement.input_lra}"
        f":measured_TP={measurement.input_tp}:measured_thresh={measurement.input_thresh}"
        f":offset={measurement.target_offset}:linear=true:print_format=summary"
    )


def _run_ffmpeg(command: list[str], friendly_error: str) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_subprocess_flags(),
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{friendly_error}\n\nFFmpeg details:\n{details[-1200:]}")


def _sample_step(samples: list[tuple[float, float]]) -> float:
    if len(samples) < 2:
        return 0.1
    deltas = [
        later[0] - earlier[0]
        for earlier, later in zip(samples, samples[1:])
        if later[0] > earlier[0]
    ]
    return sorted(deltas)[len(deltas) // 2] if deltas else 0.1


def _speech_mask(
    samples: list[tuple[float, float]],
    speech_ranges: list[tuple[float, float]] | None,
) -> list[bool]:
    if not speech_ranges:
        return [True] * len(samples)
    mask: list[bool] = []
    range_index = 0
    for time, _ in samples:
        while range_index < len(speech_ranges) and time > speech_ranges[range_index][1]:
            range_index += 1
        mask.append(
            range_index < len(speech_ranges)
            and speech_ranges[range_index][0] <= time <= speech_ranges[range_index][1]
        )
    return mask


def _energy_average(values: list[float]) -> float:
    power = sum(10 ** (value / 10.0) for value in values) / len(values)
    return 10.0 * math.log10(power)


def _hotspot(focus_seconds: float, loudness_lufs: float, duration: float, preview_duration: float) -> LoudnessHotspot:
    latest_start = max(0.0, duration - preview_duration)
    start = max(0.0, min(focus_seconds - preview_duration / 2.0, latest_start))
    return LoudnessHotspot(
        start_seconds=round(start, 3),
        focus_seconds=round(focus_seconds, 3),
        loudness_lufs=round(loudness_lufs, 2),
    )
