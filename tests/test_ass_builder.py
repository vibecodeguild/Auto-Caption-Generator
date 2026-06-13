from app.core.ass_builder import (
    build_ass_document,
    escape_ass_text,
    hex_to_ass_color,
    seconds_to_ass_time,
)
from app.core.settings import CaptionGroup, CaptionStyle, WordTimestamp


def style():
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
    )


def test_seconds_to_ass_time_uses_centiseconds():
    assert seconds_to_ass_time(0) == "0:00:00.00"
    assert seconds_to_ass_time(65.432) == "0:01:05.43"
    assert seconds_to_ass_time(1.999) == "0:00:02.00"


def test_hex_to_ass_color_converts_rgb_to_ass_bgr():
    assert hex_to_ass_color("#FF0000") == "&H000000FF&"
    assert hex_to_ass_color("#00FF00") == "&H0000FF00&"
    assert hex_to_ass_color("#0000FF") == "&H00FF0000&"


def test_escape_ass_text_removes_override_braces_and_newlines():
    assert escape_ass_text(" hello {bad}\\nworld } ") == "hello bad world"


def test_build_ass_document_contains_active_word_dialogues():
    group = CaptionGroup(
        words=[
            WordTimestamp(text="I", start=0.10, end=0.25),
            WordTimestamp(text="built", start=0.25, end=0.55),
            WordTimestamp(text="this", start=0.55, end=0.75),
            WordTimestamp(text="tool", start=0.75, end=1.10),
        ]
    )

    ass = build_ass_document(
        groups=[group],
        style=style(),
        play_res_x=1080,
        play_res_y=1920,
    )

    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert ass.count("Dialogue:") == 4
    assert "{\\c&H000000FF&\\b1\\fs78}this" in ass
    assert "0:00:00.10,0:00:00.25" in ass


def test_build_ass_document_can_disable_outline_and_enable_shadow():
    custom = CaptionStyle(
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
        outline_enabled=False,
        shadow_enabled=True,
        shadow_color="#000000",
        shadow_depth=4,
    )

    ass = build_ass_document([], custom, play_res_x=1080, play_res_y=1920)

    assert ",1,0,4,2,50,50,220,1" in ass


def test_build_ass_document_adds_glow_layer_when_enabled():
    group = CaptionGroup(words=[WordTimestamp(text="Glow", start=0.0, end=0.5)])
    custom = CaptionStyle(
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
        glow_enabled=True,
        glow_color="#FF00CE",
        glow_strength=6,
    )

    ass = build_ass_document([group], custom, play_res_x=1080, play_res_y=1920)

    assert ass.count("Dialogue:") == 2
    assert "\\blur10.8" in ass
