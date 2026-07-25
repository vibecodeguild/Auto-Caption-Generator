from __future__ import annotations

from app.core.splice_generation import DynamicSplice
from app.core.splice_preview import source_splice_preview_segments


def _splice() -> DynamicSplice:
    return DynamicSplice(
        id="splice_001",
        anchor_key="w1->w2",
        left_keep_range_id="keep_001",
        right_keep_range_id="keep_002",
        left_word_id="w1",
        right_word_id="w2",
        left_out_frame=29,
        right_in_frame=300,
        left_whisper_out_frame=29,
        left_suggested_out_frame=29,
        right_whisper_in_frame=300,
        right_suggested_in_frame=300,
        left_out_adjustment=0,
        right_in_adjustment=0,
        left_context="...one",
        right_context="two...",
        reviewed=False,
    )


def test_source_splice_preview_segments_play_before_then_after_cut() -> None:
    assert source_splice_preview_segments(_splice(), fps=30.0, seconds=4) == [
        (0.0, 1.0),
        (10.0, 12.0),
    ]
