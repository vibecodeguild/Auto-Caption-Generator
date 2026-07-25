from __future__ import annotations

import os
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
