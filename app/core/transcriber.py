from __future__ import annotations

import os
from pathlib import Path

from app.core.settings import COMPUTE_OPTIONS, WordTimestamp, resource_root, runtime_root


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
    for segment in segments:
        if segment.words is None:
            continue
        for word in segment.words:
            text = word.word.strip()
            if not text or word.start is None or word.end is None or word.end <= word.start:
                continue
            words.append(WordTimestamp(text=text, start=float(word.start), end=float(word.end)))

    if not words:
        raise RuntimeError("No speech was detected in this video.")

    return words
