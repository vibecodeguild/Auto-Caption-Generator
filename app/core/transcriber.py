from __future__ import annotations

import os
from pathlib import Path

from app.core.settings import COMPUTE_OPTIONS, WordTimestamp, resource_root, runtime_root
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord


CUDA_DLL_DIRS = [
    Path("nvidia") / "cublas" / "bin",
    Path("nvidia") / "cuda_runtime" / "bin",
    Path("nvidia") / "cuda_nvrtc" / "bin",
    Path("nvidia") / "cudnn" / "bin",
    Path("cublas") / "bin",
    Path("cuda_runtime") / "bin",
    Path("cuda_nvrtc") / "bin",
    Path("cudnn") / "bin",
    Path("gpu-runtime") / "nvidia" / "cublas" / "bin",
    Path("gpu-runtime") / "nvidia" / "cuda_runtime" / "bin",
    Path("gpu-runtime") / "nvidia" / "cuda_nvrtc" / "bin",
    Path("gpu-runtime") / "nvidia" / "cudnn" / "bin",
    Path("ctranslate2"),
]


def configure_cuda_dll_paths() -> None:
    if os.name != "nt":
        return

    roots = [resource_root(), runtime_root()]
    try:
        import nvidia

        roots.extend(Path(path) for path in nvidia.__path__)
        roots.extend(Path(path).parent for path in nvidia.__path__)
    except Exception:
        pass

    seen: set[Path] = set()
    for root in roots:
        for relative in CUDA_DLL_DIRS:
            dll_dir = (root / relative).resolve()
            if dll_dir in seen or not dll_dir.exists():
                continue
            seen.add(dll_dir)
            os.environ["PATH"] = f"{dll_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            os.add_dll_directory(str(dll_dir))


def missing_cuda_runtime_dlls() -> list[str]:
    if os.name != "nt":
        return []

    required = [
        "cublas64_12.dll",
        "cublasLt64_12.dll",
        "cudart64_12.dll",
        "cudnn64_9.dll",
    ]
    roots = [resource_root(), runtime_root()]
    try:
        import nvidia

        roots.extend(Path(path) for path in nvidia.__path__)
        roots.extend(Path(path).parent for path in nvidia.__path__)
    except Exception:
        pass

    found = set()
    for root in roots:
        for relative in CUDA_DLL_DIRS:
            dll_dir = (root / relative).resolve()
            if not dll_dir.exists():
                continue
            for dll_name in required:
                if (dll_dir / dll_name).exists():
                    found.add(dll_name)
    return [dll_name for dll_name in required if dll_name not in found]


def transcribe_audio(
    audio_path: Path,
    model_size: str,
    compute_mode: str,
    progress_callback=None,
) -> list[WordTimestamp]:
    if compute_mode == "NVIDIA GPU":
        configure_cuda_dll_paths()
        missing = missing_cuda_runtime_dlls()
        if missing:
            raise RuntimeError(
                "NVIDIA GPU mode needs CUDA runtime DLLs that Windows cannot find.\n\n"
                f"Missing: {', '.join(missing)}\n\n"
                "Install the optional GPU runtime packages from requirements-gpu.txt, or install CUDA 12 runtime/cuBLAS/cuDNN and make those DLLs available to Windows."
            )

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed. Run pip install -r requirements.txt first.") from exc

    compute = COMPUTE_OPTIONS.get(compute_mode, COMPUTE_OPTIONS["CPU"])

    try:
        model = WhisperModel(
            model_size_or_path=model_size,
            device=compute["device"],
            compute_type=compute["compute_type"],
        )
        segments, _info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=True,
        )
    except Exception as exc:
        if compute["device"] == "cuda":
            details = str(exc).strip()
            suffix = f"\n\nDetails: {details}" if details else ""
            raise RuntimeError(
                "GPU transcription failed. The app could not start faster-whisper on CUDA. Confirm your NVIDIA driver supports CUDA 12 and that the required CUDA/cuDNN DLLs are installed."
                f"{suffix}"
            ) from exc
        raise RuntimeError("The audio transcription failed. Try a smaller Whisper model or a shorter video.") from exc

    words: list[WordTimestamp] = []
    total_duration = float(getattr(_info, "duration", 0.0) or 0.0)
    for segment in segments:
        if segment.words is None:
            continue
        for word in segment.words:
            text = word.word.strip()
            if not text or word.start is None or word.end is None or word.end <= word.start:
                continue
            words.append(WordTimestamp(text=text, start=float(word.start), end=float(word.end)))
        if progress_callback:
            seconds_done = float(segment.end or 0.0)
            progress_callback(len(words), seconds_done, total_duration)

    if not words:
        raise RuntimeError("No speech was detected in this video.")

    return words


def words_to_transcript_project(source: str, words: list[WordTimestamp], fps: float) -> TranscriptProject:
    transcript_words: list[TranscriptWord] = []
    silence_ranges: list[SilenceRange] = []
    sentence_id = 1
    previous_word: TranscriptWord | None = None

    for index, word in enumerate(words, start=1):
        start_frame = round(word.start * fps)
        end_frame = round(word.end * fps)
        if previous_word is not None:
            gap_start = previous_word.end_frame + 1
            gap_end = start_frame - 1
            if gap_end >= gap_start and (gap_end - gap_start + 1) / fps >= 0.35:
                silence_ranges.append(
                    SilenceRange(
                        id=f"s{len(silence_ranges) + 1:06d}",
                        start=round(gap_start / fps, 3),
                        end=round((gap_end + 1) / fps, 3),
                        start_frame=gap_start,
                        end_frame=gap_end,
                    )
                )
        if previous_word is not None and previous_word.text.endswith((".", "?", "!")):
            sentence_id += 1

        raw = word.text if word.text.startswith(" ") else f" {word.text}"
        transcript_word = TranscriptWord(
            id=f"w{index:06d}",
            raw=raw,
            text=word.text.strip(),
            start=word.start,
            end=word.end,
            start_frame=start_frame,
            end_frame=end_frame,
            sentence_id=sentence_id,
        )
        transcript_words.append(transcript_word)
        previous_word = transcript_word

    return TranscriptProject(
        source=source,
        fps=fps,
        words=transcript_words,
        silence_ranges=silence_ranges,
    )
