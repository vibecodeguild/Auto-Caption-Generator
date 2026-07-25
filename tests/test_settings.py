from app.core.settings import COMPUTE_OPTIONS, DEFAULT_COMPUTE_LABEL, DEFAULT_MODEL_LABEL, MODEL_OPTIONS


def test_default_whisper_model_uses_large_v3() -> None:
    assert DEFAULT_MODEL_LABEL == "Large v3 - best accuracy"
    assert MODEL_OPTIONS[DEFAULT_MODEL_LABEL] == "large-v3"


def test_default_compute_uses_nvidia_gpu() -> None:
    assert DEFAULT_COMPUTE_LABEL == "NVIDIA GPU"
    assert COMPUTE_OPTIONS[DEFAULT_COMPUTE_LABEL] == {"device": "cuda", "compute_type": "float16"}
