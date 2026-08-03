"""Scenelayer — deterministic layout scoring + human override artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.editorial_layout import LAYOUT_IDS
from app.core.scenelayer import (
    OUTPUT_FILENAME,
    REVIEWED_FILENAME,
    SOURCE_HUMAN,
    classify_layout_from_rgb,
    load_scenelayer_ledger,
    load_scenelayer_original,
    load_scenelayer_reviewed,
    save_scenelayer_override_for_video_project,
    score_layouts_for_frame,
    write_scenelayer_original,
    write_scenelayer_reviewed,
)
from app.core.masterbeater import (
    normalize_masterbeater_result,
    write_masterbeater_output,
)


def _solid_rgb(width: int, height: int, r: int, g: int, b: int) -> bytes:
    pixel = bytes((r, g, b))
    return pixel * (width * height)


def _paint_rect(
    buf: bytearray,
    width: int,
    height: int,
    bounds: dict[str, float],
    r: int,
    g: int,
    b: int,
) -> None:
    x0 = max(0, int(bounds["x"] * width))
    y0 = max(0, int(bounds["y"] * height))
    x1 = min(width, int((bounds["x"] + bounds["width"]) * width))
    y1 = min(height, int((bounds["y"] + bounds["height"]) * height))
    for y in range(y0, y1):
        for x in range(x0, x1):
            # Checkerboard inside speaker to create edges.
            if (x + y) % 2 == 0:
                rr, gg, bb = r, g, b
            else:
                rr, gg, bb = min(255, r + 80), min(255, g + 80), min(255, b + 80)
            i = (y * width + x) * 3
            buf[i] = rr
            buf[i + 1] = gg
            buf[i + 2] = bb


def test_classify_prefers_talking_left_when_left_panel_detailed() -> None:
    w, h = 80, 45
    # Flat right half + busy left half + hard vertical seam at mid (OBS big-face left).
    buf = bytearray(_solid_rgb(w, h, 20, 20, 25))
    _paint_rect(
        buf,
        w,
        h,
        {"x": 0.0, "y": 0.02, "width": 0.50, "height": 0.96},
        200,
        40,
        40,
    )
    # Emphasize mid seam (lighter strip on left of seam, dark right).
    for y in range(h):
        for x in range(w // 2 - 1, w // 2 + 1):
            i = (y * w + x) * 3
            if x < w // 2:
                buf[i] = buf[i + 1] = buf[i + 2] = 220
            else:
                buf[i] = buf[i + 1] = buf[i + 2] = 15
    layout = classify_layout_from_rgb(bytes(buf), w, h)
    assert layout == "talking-left"
    scores = score_layouts_for_frame(bytes(buf), w, h)
    assert scores["talking-left"] > scores["full-screen-talking"]
    assert scores["talking-left"] > scores["talking-right"]


def test_classify_full_screen_without_mid_seam() -> None:
    w, h = 80, 45
    # Continuous busy frame (camera) — no hard L/R composite seam.
    buf = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            v = (x * 3 + y * 5) % 180 + 40
            i = (y * w + x) * 3
            buf[i] = min(255, v + 20)
            buf[i + 1] = min(255, v)
            buf[i + 2] = min(255, v // 2)
    layout = classify_layout_from_rgb(bytes(buf), w, h)
    assert layout == "full-screen-talking"
    scores = score_layouts_for_frame(bytes(buf), w, h)
    assert scores["full-screen-talking"] > scores["talking-left"]


def test_classify_bottom_left_pip_over_top() -> None:
    w, h = 80, 45
    buf = bytearray(_solid_rgb(w, h, 40, 40, 45))
    # Busy stage
    for y in range(h):
        for x in range(w):
            if (x + y) % 4 == 0:
                i = (y * w + x) * 3
                buf[i] = buf[i + 1] = buf[i + 2] = 90
    # Strong bottom-left PIP window with hard borders
    bl = {"x": 0.0, "y": 0.68, "width": 0.16, "height": 0.32}
    _paint_rect(buf, w, h, bl, 220, 60, 60)
    # Dark frame border around PIP
    x0, y0 = 0, int(0.68 * h)
    x1, y1 = int(0.16 * w), h
    for y in range(y0, y1):
        for x in (x0, max(x0, x1 - 1)):
            i = (y * w + x) * 3
            buf[i] = buf[i + 1] = buf[i + 2] = 0
    for x in range(x0, x1):
        for y in (y0, max(y0, y1 - 1)):
            i = (y * w + x) * 3
            buf[i] = buf[i + 1] = buf[i + 2] = 0
    layout = classify_layout_from_rgb(bytes(buf), w, h)
    scores = score_layouts_for_frame(bytes(buf), w, h)
    assert scores["talking-bottom-left"] >= scores["talking-top-left"]
    assert scores["talking-bottom-left"] >= scores["talking-top-right"]
    assert layout in {
        "talking-bottom-left",
        "talking-bottom-right",
        "talking-top-left",
        "talking-top-right",
    }
    # Prefer correct corner when PIP family wins
    if max(scores[p] for p in (
        "talking-bottom-left",
        "talking-bottom-right",
        "talking-top-left",
        "talking-top-right",
    )) == max(scores.values()):
        assert layout == "talking-bottom-left"


def test_classify_computer_screen_even_detail() -> None:
    w, h = 80, 45
    # High-frequency pattern across whole frame, no PIP chrome / mid seam.
    buf = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            v = (x * 17 + y * 31) % 255
            i = (y * w + x) * 3
            buf[i] = buf[i + 1] = buf[i + 2] = v
    layout = classify_layout_from_rgb(bytes(buf), w, h)
    assert layout in LAYOUT_IDS


def test_scenelayer_override_preserves_original(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".vcg-private").write_text("private\n", encoding="utf-8")
    transcript = project / "final-transcript.json"
    document = {
        "project": {
            "fps": 30,
            "words": [
                {
                    "id": "w1",
                    "text": "Hi",
                    "start": 0.0,
                    "end": 0.3,
                    "start_frame": 0,
                    "end_frame": 9,
                },
                {
                    "id": "w2",
                    "text": "there",
                    "start": 0.3,
                    "end": 0.6,
                    "start_frame": 9,
                    "end_frame": 18,
                },
            ],
        }
    }
    transcript.write_text(json.dumps(document), encoding="utf-8")
    manifest_path = project / "manifest.json"
    manifest = {
        "paths": {
            "finalTranscript": "final-transcript.json",
            "lockedCut": "locked.mp4",
            "sourceVideo": "source.mp4",
        }
    }
    mb = normalize_masterbeater_result(
        {
            "mode": "tutorial",
            "beats": [
                {
                    "id": "b1",
                    "beatType": "hook",
                    "startWordId": "w1",
                    "endWordId": "w2",
                    "rationale": "Open",
                }
            ],
        },
        project_root=project,
        transcript_path=transcript,
        document=document,
    )
    write_masterbeater_output(project, mb)

    original = {
        "agent": "scenelayer",
        "schemaVersion": 1,
        "beats": [
            {"beatId": "b1", "layoutId": "talking-left", "source": "algorithm"},
        ],
    }
    write_scenelayer_original(project, original)
    write_scenelayer_reviewed(
        project,
        {**original, "agent": "scenelayer-reviewed", "role": "reviewed"},
    )
    before = json.loads((project / OUTPUT_FILENAME).read_text(encoding="utf-8"))

    saved = save_scenelayer_override_for_video_project(
        manifest_path,
        manifest,
        {"beatId": "b1", "layoutId": "talking-right", "detail": "fix"},
    )
    assert saved["ok"] is True
    reviewed = load_scenelayer_reviewed(project)
    assert reviewed is not None
    assert reviewed["beats"][0]["layoutId"] == "talking-right"
    assert reviewed["beats"][0]["source"] == SOURCE_HUMAN
    after = json.loads((project / OUTPUT_FILENAME).read_text(encoding="utf-8"))
    assert after == before
    assert load_scenelayer_original(project)["beats"][0]["layoutId"] == "talking-left"
    assert (project / REVIEWED_FILENAME).is_file()
    ledger = load_scenelayer_ledger(project)
    assert ledger["entryCount"] == 1
    assert ledger["entries"][0]["toLayoutId"] == "talking-right"
