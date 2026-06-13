from __future__ import annotations

from pathlib import Path

from app.core.settings import CaptionGroup, CaptionStyle


ALIGNMENTS = {
    "Top": 8,
    "Middle": 5,
    "Bottom": 2,
}


def seconds_to_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    if centiseconds == 100:
        whole_seconds += 1
        centiseconds = 0
        if whole_seconds == 60:
            minutes += 1
            whole_seconds = 0
        if minutes == 60:
            hours += 1
            minutes = 0
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def hex_to_ass_color(hex_color: str, alpha: str = "00") -> str:
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError("Colors must use #RRGGBB format.")
    rr = h[0:2]
    gg = h[2:4]
    bb = h[4:6]
    return f"&H{alpha}{bb}{gg}{rr}&"


def escape_ass_text(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\\n", " ").strip()


def _weight_flag(enabled: bool) -> str:
    return "1" if enabled else "0"


def _inline_word(text: str, color: str, bold: bool, size: int) -> str:
    return f"{{\\c{color}\\b{_weight_flag(bold)}\\fs{size}}}{escape_ass_text(text)}"


def _effect_prefix(style: CaptionStyle, glow: bool = False) -> str:
    if not glow:
        return ""
    color = hex_to_ass_color(style.glow_color, alpha="65")
    strength = max(1, style.glow_strength)
    return f"{{\\bord{strength}\\blur{strength * 1.8:.1f}\\c{color}\\3c{color}}}"


def _event_text(group: CaptionGroup, active_index: int, style: CaptionStyle, glow: bool = False) -> str:
    main_color = hex_to_ass_color(style.main_color)
    active_color = hex_to_ass_color(style.active_color)
    prefix = _effect_prefix(style, glow=glow)
    rendered = []
    for index, word in enumerate(group.words):
        if index == active_index:
            rendered.append(_inline_word(word.text, active_color, style.active_bold, style.active_font_size))
        else:
            rendered.append(_inline_word(word.text, main_color, style.bold, style.main_font_size))
    return prefix + " ".join(rendered)


def build_ass_document(
    groups: list[CaptionGroup],
    style: CaptionStyle,
    play_res_x: int,
    play_res_y: int,
) -> str:
    alignment = ALIGNMENTS.get(style.position, 2)
    primary = hex_to_ass_color(style.main_color)
    outline = hex_to_ass_color(style.outline_color)
    back = hex_to_ass_color(style.shadow_color, alpha="55")
    outline_width = style.outline_width if style.outline_enabled else 0
    shadow_depth = style.shadow_depth if style.shadow_enabled else 0
    bold = "-1" if style.bold else "0"

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{style.font_family},{style.main_font_size},{primary},&H000000FF,{outline},{back},{bold},0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},{alignment},50,50,{style.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for group in groups:
        for index, word in enumerate(group.words):
            next_start = group.words[index + 1].start if index + 1 < len(group.words) else group.end
            event_end = max(next_start, word.start + 0.08)
            event_end = min(event_end, group.end)
            if event_end <= word.start:
                event_end = word.end
            if style.glow_enabled and style.glow_strength > 0:
                lines.append(
                    "Dialogue: 0,"
                    f"{seconds_to_ass_time(word.start)},{seconds_to_ass_time(event_end)},"
                    f"Default,,0,0,0,,{_event_text(group, index, style, glow=True)}"
                )
            lines.append(
                "Dialogue: 1,"
                f"{seconds_to_ass_time(word.start)},{seconds_to_ass_time(event_end)},"
                f"Default,,0,0,0,,{_event_text(group, index, style)}"
            )

    return "\n".join(lines) + "\n"


def write_ass_file(path: Path, groups: list[CaptionGroup], style: CaptionStyle, play_res_x: int, play_res_y: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_ass_document(groups=groups, style=style, play_res_x=play_res_x, play_res_y=play_res_y),
        encoding="utf-8",
    )
    return path
