"""Read-only inference probe; writes diagnostic evidence only to app/temp."""
import argparse
import gc
import json
import os
from pathlib import Path
import time
import wave
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--provider", default="cuda", choices=["cuda", "cpu"])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from app.core.parakeet_profiling import executed_providers
    handles = []
    for environment in (".venv", ".venv-parakeet"):
        for folder in (root / environment / "Lib/site-packages/nvidia").glob("*/bin"):
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            handles.append(os.add_dll_directory(str(folder)))
    import numpy as np
    import sherpa_onnx
    evidence = root / "app/temp/parakeet-probe"
    evidence.mkdir(parents=True, exist_ok=True)
    config = evidence / "provider.config"
    prefix = f"profile-{args.provider}-{time.time_ns()}"
    config.write_text(f"ProfilingFilePrefix={evidence.as_posix()}/{prefix}\n")
    started = time.perf_counter()
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        **{part: str(next(args.model.glob(f"{part}*.onnx"))) for part in ("encoder", "decoder", "joiner")},
        tokens=str(args.model / "tokens.txt"), num_threads=4, sample_rate=16000,
        feature_dim=80, model_type="nemo_transducer", decoding_method="greedy_search",
        provider=f"{args.provider}:{config}")
    loaded = time.perf_counter()
    with wave.open(str(args.audio), "rb") as audio:
        rate = audio.getframerate()
        samples = np.frombuffer(audio.readframes(min(audio.getnframes(), rate * 30)), dtype="<i2").astype(np.float32) / 32768
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    recognizer.decode_stream(stream)
    result = stream.result
    output = {"text": result.text, "tokens": list(result.tokens), "timestamps": list(result.timestamps),
              "durations": list(result.durations), "loadSeconds": loaded - started,
              "decodeSeconds": time.perf_counter() - loaded, "version": sherpa_onnx.__version__}
    del stream, recognizer
    gc.collect()
    providers = executed_providers(evidence.glob(f"{prefix}*.json"))
    output["profileProviders"] = sorted(providers)
    (evidence / f"{args.provider}-result.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=True))
    if args.provider == "cuda" and "CUDAExecutionProvider" not in providers:
        raise RuntimeError("CUDA was requested but profiling found no executed CUDA kernels.")


if __name__ == "__main__":
    main()
