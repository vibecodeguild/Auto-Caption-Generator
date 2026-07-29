from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.core.settings import SUPPORTED_VIDEO_EXTENSIONS


BOUNDS_KEYS = ("x", "y", "width", "height")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "asset"


def normalized_bounds(value: object) -> dict[str, float] | None:
    """Parse normalized frame bounds, or None when the value is unusable.

    Callers that must fail loudly wrap this; callers that collect issues use it directly. Two
    copies of this parse previously disagreed about what counted as valid.
    """
    if not isinstance(value, dict):
        return None
    try:
        bounds = {key: float(value[key]) for key in BOUNDS_KEYS}
    except (KeyError, TypeError, ValueError):
        return None
    if (
        bounds["x"] < 0
        or bounds["y"] < 0
        or bounds["width"] <= 0
        or bounds["height"] <= 0
        or bounds["x"] + bounds["width"] > 1
        or bounds["y"] + bounds["height"] > 1
    ):
        return None
    return bounds


def bounds_intersect(left: dict[str, float], right: dict[str, float]) -> bool:
    return not (
        left["x"] + left["width"] <= right["x"]
        or right["x"] + right["width"] <= left["x"]
        or left["y"] + left["height"] <= right["y"]
        or right["y"] + right["height"] <= left["y"]
    )


def validate_input_video(path: Path) -> None:
    if not path.exists():
        raise RuntimeError("Please choose a video file first.")
    if path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        raise RuntimeError("Please choose a supported video file: MP4, MOV, MKV, AVI, or WEBM.")


def ensure_output_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    probe = path.parent / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("The output folder is not writable.") from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
