from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
MODEL_OPTIONS = {
    "Tiny - fastest": "tiny.en",
    "Base - balanced": "base.en",
    "Small - better accuracy": "small.en",
    "Medium - high accuracy": "medium.en",
    "Large v3 - best accuracy": "large-v3",
}
DEFAULT_MODEL_LABEL = "Large v3 - best accuracy"
COMPUTE_OPTIONS = {
    "CPU": {"device": "cpu", "compute_type": "int8"},
    "NVIDIA GPU": {"device": "cuda", "compute_type": "float16"},
}
DEFAULT_COMPUTE_LABEL = "NVIDIA GPU"


@dataclass(frozen=True)
class CaptionPreset:
    name: str
    max_words: int
    max_duration: float
    max_chars: int


@dataclass(frozen=True)
class CaptionStyle:
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


@dataclass(frozen=True)
class WordTimestamp:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class CaptionGroup:
    words: list[WordTimestamp]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


PRESETS = {
    "TikTok": CaptionPreset("TikTok", max_words=3, max_duration=1.6, max_chars=24),
    "Creator": CaptionPreset("Creator", max_words=4, max_duration=2.2, max_chars=32),
    "YouTube": CaptionPreset("YouTube", max_words=6, max_duration=3.0, max_chars=48),
    "Podcast": CaptionPreset("Podcast", max_words=8, max_duration=4.0, max_chars=64),
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def project_root() -> Path:
    return resource_root()


def env_file_paths() -> tuple[Path, Path]:
    """Repo-root dotenv files. ``.env.local`` overrides ``.env`` (Next.js convention)."""

    root = project_root()
    return root / ".env", root / ".env.local"


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def read_dotenv_key(name: str) -> tuple[str, str]:
    """Return ``(value, source)`` for one key. Empty value means missing.

    Precedence: process env, ``.env.local``, ``.env``.
    """

    existing = os.environ.get(name)
    if existing is not None and str(existing).strip():
        return str(existing).strip(), "environment"
    env_path, local_path = env_file_paths()
    local = _parse_dotenv(local_path)
    if str(local.get(name) or "").strip():
        return str(local[name]).strip(), "env-local"
    dotenv = _parse_dotenv(env_path)
    if str(dotenv.get(name) or "").strip():
        return str(dotenv[name]).strip(), "env"
    return "", "missing"


def upsert_dotenv_local(name: str, value: str) -> Path:
    """Create or update ``KEY=value`` in repo-root ``.env.local`` without clobbering other keys."""

    key = str(name or "").strip()
    if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise ValueError("Invalid environment variable name.")
    raw = str(value)
    env_path, local_path = env_file_paths()
    del env_path
    lines: list[str] = []
    if local_path.is_file():
        lines = local_path.read_text(encoding="utf-8").splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        compare = stripped[7:].strip() if stripped.lower().startswith("export ") else stripped
        if compare and not compare.startswith("#") and "=" in compare:
            existing_key = compare.split("=", 1)[0].strip()
            if existing_key == key:
                out.append(f"{key}={raw}")
                found = True
                continue
        out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={raw}")
    local_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = raw
    return local_path


def runtime_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return resource_root()


def user_data_root() -> Path:
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "VCG AutoCaption"
        return Path.home() / "AppData" / "Local" / "VCG AutoCaption"
    return resource_root() / "app"


def temp_dir() -> Path:
    return user_data_root() / "temp"


def exports_dir() -> Path:
    return user_data_root() / "exports"


def fonts_dir() -> Path:
    return resource_root() / "app" / "assets" / "fonts"


def default_style() -> CaptionStyle:
    return CaptionStyle(
        font_family="Montserrat",
        main_font_size=72,
        active_font_size=78,
        main_color="#FFFFFF",
        active_color="#FF0000",
        outline_color="#000000",
        outline_width=5,
        bold=True,
        active_bold=True,
        position="Bottom",
        margin_v=220,
        outline_enabled=True,
        shadow_enabled=False,
        shadow_color="#000000",
        shadow_depth=5,
        glow_enabled=False,
        glow_color="#FF00CE",
        glow_strength=5,
    )
