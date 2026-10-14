from pathlib import Path

from app.core.settings import (
    COMPUTE_OPTIONS,
    DEFAULT_COMPUTE_LABEL,
    DEFAULT_MODEL_LABEL,
    MODEL_OPTIONS,
    read_dotenv_key,
    upsert_dotenv_local,
)


def test_default_whisper_model_uses_large_v3() -> None:
    assert DEFAULT_MODEL_LABEL == "Large v3 - best accuracy"
    assert MODEL_OPTIONS[DEFAULT_MODEL_LABEL] == "large-v3"


def test_default_compute_uses_nvidia_gpu() -> None:
    assert DEFAULT_COMPUTE_LABEL == "NVIDIA GPU"
    assert COMPUTE_OPTIONS[DEFAULT_COMPUTE_LABEL] == {"device": "cuda", "compute_type": "float16"}


def test_dotenv_local_overrides_env_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.settings.project_root", lambda: tmp_path)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    (tmp_path / ".env").write_text("PEXELS_API_KEY=from-env\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text('PEXELS_API_KEY="from-local"\n', encoding="utf-8")
    value, source = read_dotenv_key("PEXELS_API_KEY")
    assert value == "from-local"
    assert source == "env-local"


def test_process_env_wins_over_dotenv_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.settings.project_root", lambda: tmp_path)
    monkeypatch.setenv("PEXELS_API_KEY", "from-process")
    (tmp_path / ".env.local").write_text("PEXELS_API_KEY=from-local\n", encoding="utf-8")
    value, source = read_dotenv_key("PEXELS_API_KEY")
    assert value == "from-process"
    assert source == "environment"


def test_upsert_dotenv_local_preserves_other_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.settings.project_root", lambda: tmp_path)
    (tmp_path / ".env.local").write_text("OTHER=keep\nPEXELS_API_KEY=old\n", encoding="utf-8")
    path = upsert_dotenv_local("PEXELS_API_KEY", "new-key-value")
    text = path.read_text(encoding="utf-8")
    assert "OTHER=keep" in text
    assert "PEXELS_API_KEY=new-key-value" in text
    assert "PEXELS_API_KEY=old" not in text
