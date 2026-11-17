"""Isolated Parakeet inference. JSONL stdout, runtime diagnostics on stderr.

Decode bounded cores with two seconds of context on each side. The parent
reconciles overlapping results using words and source timing together.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import tempfile
import time
import wave
from parakeet_profiling import executed_providers


def emit(data):
    print(json.dumps(data, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--provider", choices=["cuda", "cpu"], required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    handles = []
    if os.name == "nt":
        for folder in (root / ".venv-parakeet/Lib/site-packages/nvidia").glob("*/bin"):
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            handles.append(os.add_dll_directory(str(folder)))
    import numpy as np
    import sherpa_onnx

    def load(provider):
        return sherpa_onnx.OfflineRecognizer.from_transducer(
            **{part: str(next(args.model.glob(f"{part}*.onnx"))) for part in ("encoder", "decoder", "joiner")},
            tokens=str(args.model / "tokens.txt"), num_threads=4, sample_rate=16000,
            feature_dim=80, model_type="nemo_transducer", decoding_method="greedy_search", provider=provider,
        )

    started = time.perf_counter()
    # Verify executed CUDA kernels, not merely the requested provider. Profiling
    # only the probe bounds diagnostic storage for multi-hour recordings.
    if args.provider == "cuda":
        with tempfile.TemporaryDirectory(prefix="parakeet-device-") as folder:
            config = Path(folder) / "provider.config"
            config.write_text(f"ProfilingFilePrefix={Path(folder).as_posix()}/profile\n")
            probe = load(f"cuda:{config}")
            stream = probe.create_stream()
            stream.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
            probe.decode_stream(stream)
            del stream, probe
            gc.collect()
            providers = executed_providers(Path(folder).glob("profile*.json"))
            if "CUDAExecutionProvider" not in providers:
                raise RuntimeError("Parakeet CUDA probe executed no verified CUDA kernels.")
    recognizer = load(args.provider)
    loaded = time.perf_counter()
    emit({"event": "device", "device": args.provider, "engine": "parakeet",
          "engine_version": sherpa_onnx.__version__, "load_seconds": loaded - started,
          "device_evidence": "executed CUDA kernels" if args.provider == "cuda" else "explicit CPU session"})
    with wave.open(str(args.audio), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError("Parakeet requires 16 kHz mono PCM16 WAV.")
        total = audio.getnframes() / 16000
        core_start = 0.0
        while core_start < total:
            core_end = min(total, core_start + 28)
            start = max(0.0, core_start - 2)
            end = min(total, core_end + 2)
            audio.setpos(round(start * 16000))
            samples = np.frombuffer(audio.readframes(round((end - start) * 16000)), dtype="<i2").astype(np.float32) / 32768
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            recognizer.decode_stream(stream)
            result = stream.result
            emit({"event": "chunk", "offset": start, "core_start": core_start, "core_end": core_end,
                  "duration": total, "tokens": list(result.tokens), "timestamps": list(result.timestamps),
                  "durations": list(result.durations)})
            core_start = core_end
    emit({"event": "complete", "decode_seconds": time.perf_counter() - loaded})


if __name__ == "__main__":
    main()
