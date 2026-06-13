from __future__ import annotations

import json
from dataclasses import MISSING, asdict, fields
from pathlib import Path

from app.core.settings import CaptionStyle, user_data_root


BUILT_IN_STYLES: dict[str, CaptionStyle] = {
    "Magenta Pop": CaptionStyle(
        font_family="Montserrat",
        main_font_size=72,
        active_font_size=78,
        main_color="#FFFFFF",
        active_color="#FF00CE",
        outline_color="#05050A",
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
    ),
    "Teal Clean": CaptionStyle(
        font_family="Open Sans",
        main_font_size=66,
        active_font_size=72,
        main_color="#FFFFFF",
        active_color="#00B8BA",
        outline_color="#071314",
        outline_width=4,
        bold=True,
        active_bold=True,
        position="Bottom",
        margin_v=200,
        outline_enabled=True,
        shadow_enabled=True,
        shadow_color="#000000",
        shadow_depth=5,
        glow_enabled=False,
        glow_color="#007C7D",
        glow_strength=5,
    ),
    "Classic Red": CaptionStyle(
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
        glow_color="#FF0000",
        glow_strength=5,
    ),
}


STYLE_DEFAULTS = {
    field.name: field.default
    for field in fields(CaptionStyle)
    if field.default is not MISSING
}
STYLE_FIELDS = {field.name for field in fields(CaptionStyle)}


def style_library_path() -> Path:
    return user_data_root() / "style_library.json"


def load_style_library(path: Path | None = None) -> dict[str, CaptionStyle]:
    library = dict(BUILT_IN_STYLES)
    source = path or style_library_path()
    if not source.exists():
        return library

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return library

    if not isinstance(payload, dict):
        return library

    for name, raw_style in payload.items():
        if not isinstance(name, str) or not isinstance(raw_style, dict):
            continue
        normalized = {key: raw_style[key] for key in STYLE_FIELDS if key in raw_style}
        for key, value in STYLE_DEFAULTS.items():
            normalized.setdefault(key, value)
        if set(normalized) != STYLE_FIELDS:
            continue
        try:
            library[name] = CaptionStyle(**normalized)
        except TypeError:
            continue

    return library


def save_user_style(name: str, style: CaptionStyle, path: Path | None = None) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Style name cannot be blank.")

    source = path or style_library_path()
    source.parent.mkdir(parents=True, exist_ok=True)
    existing = load_user_styles(source)
    existing[clean_name] = asdict(style)
    source.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def delete_user_style(name: str, path: Path | None = None) -> bool:
    source = path or style_library_path()
    existing = load_user_styles(source)
    if name not in existing:
        return False
    del existing[name]
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return True


def is_built_in_style(name: str) -> bool:
    return name in BUILT_IN_STYLES


def load_user_styles(path: Path | None = None) -> dict[str, dict[str, object]]:
    source = path or style_library_path()
    if not source.exists():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {name: value for name, value in payload.items() if isinstance(name, str) and isinstance(value, dict)}
