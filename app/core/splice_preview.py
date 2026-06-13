from __future__ import annotations

from app.core.splice_generation import DynamicSplice


def source_splice_preview_segments(splice: DynamicSplice, *, fps: float, seconds: int) -> list[tuple[float, float]]:
    if fps <= 0:
        raise ValueError("FPS must be greater than zero.")
    if seconds <= 0:
        raise ValueError("Preview seconds must be greater than zero.")

    half_seconds = max(0.1, seconds / 2)
    out_end = max(0.0, (splice.left_out_frame + 1) / fps)
    out_start = max(0.0, out_end - half_seconds)
    in_start = max(0.0, splice.right_in_frame / fps)
    in_end = in_start + half_seconds
    return [(round(out_start, 6), round(out_end, 6)), (round(in_start, 6), round(in_end, 6))]
