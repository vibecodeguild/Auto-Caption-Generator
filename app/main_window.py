from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.ffmpeg_locator import find_ffmpeg
from app.core.settings import COMPUTE_OPTIONS, MODEL_OPTIONS, PRESETS, CaptionPreset, CaptionStyle, exports_dir, temp_dir
from app.core.style_library import delete_user_style, is_built_in_style, load_style_library, save_user_style
from app.worker import CaptionWorker, JobSettings


MAGENTA = "#FF00CE"
TEAL = "#007C7D"
SURFACE = "#101119"
PANEL = "#171923"
PANEL_ALT = "#20232F"
BORDER = "#303443"
TEXT = "#F7F7FB"
MUTED = "#A7AABD"


class ColorButton(QPushButton):
    color_changed = Signal()

    def __init__(self, color: str):
        super().__init__(color)
        self._color = color
        self.clicked.connect(self.choose_color)
        self._refresh()

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color.upper()
        self._refresh()
        self.color_changed.emit()

    def choose_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "Choose color")
        if chosen.isValid():
            self.set_color(chosen.name().upper())

    def _refresh(self) -> None:
        text_color = "#0B0C12" if self._color.upper() in {"#FFFFFF", "#FFF0FB", "#F0FAFA"} else "#FFFFFF"
        self.setText(self._color)
        self.setStyleSheet(
            "QPushButton {"
            f"background: {self._color};"
            f"color: {text_color};"
            "border: 1px solid rgba(255,255,255,0.20);"
            "}"
        )


class NumericInput(QWidget):
    valueChanged = Signal()

    def __init__(self, minimum: float, maximum: float, value: float, step: float = 1, decimals: int = 0):
        super().__init__()
        self._decimals = decimals
        self._step = step
        self._spin = QDoubleSpinBox() if decimals else QSpinBox()
        self._spin.setRange(minimum, maximum)
        self._spin.setSingleStep(step)
        if decimals:
            self._spin.setDecimals(decimals)
        self._spin.setValue(value)
        self._spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin.valueChanged.connect(self._emit_value_changed)

        decrement = QPushButton("-")
        decrement.setObjectName("StepButton")
        decrement.clicked.connect(lambda: self.setValue(self.value() - self._step))
        increment = QPushButton("+")
        increment.setObjectName("StepButton")
        increment.clicked.connect(lambda: self.setValue(self.value() + self._step))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._spin, 1)
        layout.addWidget(decrement)
        layout.addWidget(increment)

    def value(self):
        return self._spin.value()

    def setValue(self, value: float) -> None:  # noqa: N802
        self._spin.setValue(value)

    def setRange(self, minimum: float, maximum: float) -> None:  # noqa: N802
        self._spin.setRange(minimum, maximum)

    def setSingleStep(self, step: float) -> None:  # noqa: N802
        self._step = step
        self._spin.setSingleStep(step)

    def setDecimals(self, decimals: int) -> None:  # noqa: N802
        self._decimals = decimals
        if isinstance(self._spin, QDoubleSpinBox):
            self._spin.setDecimals(decimals)

    def _emit_value_changed(self) -> None:
        if not self.signalsBlocked():
            self.valueChanged.emit()


class ToggleSwitch(QCheckBox):
    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("ToggleSwitch")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(150, 26)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track = QRectF(0, 3, 42, 22)
        track_color = QColor(TEAL if self.isChecked() else "#2A2E3B")
        border_color = QColor(TEAL if self.isChecked() else BORDER)
        knob_color = QColor("#FFFFFF" if self.isChecked() else "#A7AABD")

        painter.setPen(border_color)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 11, 11)

        knob_x = 22 if self.isChecked() else 3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        painter.drawEllipse(QRectF(knob_x, 6, 16, 16))

        painter.setPen(QColor(TEXT))
        painter.setFont(self.font())
        painter.drawText(QRectF(50, 0, self.width() - 50, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.end()


class PreviewPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._frame = QPixmap()
        self._style: CaptionStyle | None = None
        self._sample_text = "Build fast. Skip the syntax."
        self.setMinimumSize(500, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, path: Path | None) -> None:
        if path and path.exists():
            self._frame = QPixmap(str(path))
        else:
            self._frame = QPixmap()
        self.update()

    def set_caption_style(self, style: CaptionStyle) -> None:
        self._style = style
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#08090E"))

        viewport = self._content_rect()
        painter.setPen(QColor(BORDER))
        painter.setBrush(QColor("#0D0F16"))
        painter.drawRoundedRect(viewport, 12, 12)

        if self._frame.isNull():
            self._draw_placeholder(painter, viewport)
        else:
            scaled = self._frame.scaled(
                viewport.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = viewport.x() + (viewport.width() - scaled.width()) / 2
            y = viewport.y() + (viewport.height() - scaled.height()) / 2
            painter.drawPixmap(int(x), int(y), scaled)

        self._draw_caption(painter, viewport)
        painter.end()

    def _content_rect(self) -> QRectF:
        margin = 22
        available_width = max(240, self.width() - margin * 2)
        available_height = max(180, self.height() - margin * 2)
        if self._frame.isNull() or self._frame.height() <= 0:
            aspect = 16 / 9
        else:
            aspect = self._frame.width() / self._frame.height()
        width = available_width
        height = width / aspect
        if height > available_height:
            height = available_height
            width = height * aspect
        x = (self.width() - width) / 2
        y = (self.height() - height) / 2
        return QRectF(x, y, width, height)

    def _draw_placeholder(self, painter: QPainter, viewport: QRectF) -> None:
        painter.setPen(QColor(MUTED))
        font = QFont("Open Sans", 14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(viewport, Qt.AlignmentFlag.AlignCenter, "Choose a video to preview the first frame")

    def _draw_caption(self, painter: QPainter, viewport: QRectF) -> None:
        if self._style is None:
            return

        style = self._style
        words = self._sample_text.split()
        active_index = 1

        base_width = self._frame.width() if not self._frame.isNull() else 1080
        base_height = self._frame.height() if not self._frame.isNull() else 1920
        scale = min(viewport.width() / base_width, viewport.height() / base_height)
        font_size = max(16, int(style.main_font_size * scale))
        active_size = max(17, int(style.active_font_size * scale))
        margin = max(14, int(style.margin_v * scale))

        if style.position == "Top":
            y = viewport.top() + margin
        elif style.position == "Middle":
            y = viewport.center().y() - active_size
        else:
            y = viewport.bottom() - margin - active_size * 1.4

        main_font = QFont(style.font_family, font_size)
        main_font.setBold(style.bold)
        active_font = QFont(style.font_family, active_size)
        active_font.setBold(style.active_bold)

        max_text_width = viewport.width() * 0.92
        lines = self._caption_lines(painter, words, active_index, main_font, active_font, max_text_width)
        while max(self._caption_line_width(painter, line_words, line_active, main_font, active_font) for line_words, line_active in lines) > max_text_width and font_size > 10:
            font_size -= 1
            active_size = max(11, active_size - 1)
            main_font.setPointSize(font_size)
            active_font.setPointSize(active_size)
            lines = self._caption_lines(painter, words, active_index, main_font, active_font, max_text_width)

        painter.setFont(active_font)
        metrics = painter.fontMetrics()
        line_height = metrics.height() * 0.92
        total_height = line_height * len(lines)
        if style.position == "Top":
            first_baseline = viewport.top() + margin + metrics.ascent()
        elif style.position == "Middle":
            first_baseline = viewport.center().y() - total_height / 2 + metrics.ascent()
        else:
            first_baseline = viewport.bottom() - margin - metrics.descent() - line_height * (len(lines) - 1)

        painter.save()
        painter.setClipRect(viewport)
        for index, (line_words, line_active) in enumerate(lines):
            self._draw_caption_line(
                painter,
                line_words,
                line_active,
                main_font,
                active_font,
                viewport.center().x(),
                first_baseline + line_height * index,
                style,
            )
        painter.restore()

    def _caption_lines(
        self,
        painter: QPainter,
        words: list[str],
        active_index: int,
        main_font: QFont,
        active_font: QFont,
        max_width: float,
    ) -> list[tuple[list[str], int]]:
        if self._caption_line_width(painter, words, active_index, main_font, active_font) <= max_width:
            return [(words, active_index)]

        lines: list[tuple[list[str], int]] = []
        current_words: list[str] = []
        current_indices: list[int] = []
        for index, word in enumerate(words):
            candidate_words = [*current_words, word]
            candidate_indices = [*current_indices, index]
            candidate_active = candidate_indices.index(active_index) if active_index in candidate_indices else -1
            if current_words and self._caption_line_width(painter, candidate_words, candidate_active, main_font, active_font) > max_width:
                current_active = current_indices.index(active_index) if active_index in current_indices else -1
                lines.append((current_words, current_active))
                current_words = [word]
                current_indices = [index]
            else:
                current_words = candidate_words
                current_indices = candidate_indices
        if current_words:
            current_active = current_indices.index(active_index) if active_index in current_indices else -1
            lines.append((current_words, current_active))
        return lines

    def _caption_line_width(self, painter: QPainter, words: list[str], active_index: int, main_font: QFont, active_font: QFont) -> int:
        total_width = 0
        space_width = 0
        for index, word in enumerate(words):
            painter.setFont(active_font if index == active_index else main_font)
            metrics = painter.fontMetrics()
            total_width += metrics.horizontalAdvance(word)
            space_width = max(space_width, metrics.horizontalAdvance(" "))
        return total_width + space_width * (len(words) - 1)

    def _draw_caption_line(
        self,
        painter: QPainter,
        words: list[str],
        active_index: int,
        main_font: QFont,
        active_font: QFont,
        center_x: float,
        baseline_y: float,
        style: CaptionStyle,
    ) -> None:
        pieces: list[tuple[str, QFont, QColor, float]] = []
        total_width = 0
        space_width = 0
        for index, word in enumerate(words):
            font = active_font if index == active_index else main_font
            color = QColor(style.active_color if index == active_index else style.main_color)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(word)
            pieces.append((word, font, color, width))
            total_width += width
            space_width = max(space_width, metrics.horizontalAdvance(" "))
        total_width += space_width * (len(words) - 1)

        x = center_x - total_width / 2
        for word, font, color, width in pieces:
            self._draw_outlined_text(
                painter,
                word,
                font,
                color,
                QColor(style.outline_color),
                style.outline_width if style.outline_enabled else 0,
                x,
                baseline_y,
                style,
            )
            x += width + space_width

    def _draw_outlined_text(
        self,
        painter: QPainter,
        text: str,
        font: QFont,
        fill: QColor,
        outline: QColor,
        outline_width: int,
        x: float,
        baseline_y: float,
        style: CaptionStyle,
    ) -> None:
        painter.setFont(font)
        path = QPainterPath()
        path.addText(x, baseline_y, font, text)

        painter.save()
        if style.shadow_enabled and style.shadow_depth > 0:
            shadow = QPainterPath()
            shadow.addText(x + style.shadow_depth, baseline_y + style.shadow_depth, font, text)
            painter.fillPath(shadow, QColor(style.shadow_color))
        if style.glow_enabled and style.glow_strength > 0:
            glow = QPainterPath()
            glow.addText(x, baseline_y, font, text)
            glow_color = QColor(style.glow_color)
            glow_color.setAlpha(125)
            painter.setPen(glow_color)
            painter.strokePath(glow, painter.pen())
            for radius in range(1, style.glow_strength + 1):
                for dx, dy in ((-radius, 0), (radius, 0), (0, -radius), (0, radius)):
                    shifted = QPainterPath()
                    shifted.addText(x + dx, baseline_y + dy, font, text)
                    painter.fillPath(shifted, glow_color)
        if outline_width > 0:
            stroke = max(1, int(outline_width * 0.8))
            for dx, dy in ((-stroke, 0), (stroke, 0), (0, -stroke), (0, stroke)):
                shifted = QPainterPath()
                shifted.addText(x + dx, baseline_y + dy, font, text)
                painter.fillPath(shifted, outline)
        painter.fillPath(path, fill)
        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VCG AutoCaption")
        self.setMinimumSize(1280, 720)
        self.input_video_path: Path | None = None
        self.output_folder: Path = exports_dir()
        self.preview_frame_path: Path | None = None
        self.thread: QThread | None = None
        self.worker: CaptionWorker | None = None
        self.style_library: dict[str, CaptionStyle] = {}
        self._build_ui()
        self._load_style_options()
        self._apply_caption_style()
        self._set_status("Ready", 0)

    def _build_ui(self) -> None:
        self._apply_theme()

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_preview_area(), 4)
        body.addWidget(self._build_settings_area(), 5)
        layout.addLayout(body, 1)

        layout.addWidget(self._build_status_bar())
        self.setCentralWidget(root)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("VCG AutoCaption")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Local caption generation for creator videos")
        subtitle.setObjectName("SubtleText")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        self.generate_button = QPushButton("Generate Video")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self.generate)

        header.addLayout(title_block, 1)
        header.addWidget(self.generate_button)
        return header

    def _build_preview_area(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PreviewShell")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        label_block = QVBoxLayout()
        label = QLabel("Preview")
        label.setObjectName("SectionTitle")
        self.video_label = QLabel("No video selected")
        self.video_label.setObjectName("SubtleText")
        label_block.addWidget(label)
        label_block.addWidget(self.video_label)

        choose_video = QPushButton("Choose Video")
        choose_video.clicked.connect(self.choose_video)
        choose_output = QPushButton("Output Folder")
        choose_output.clicked.connect(self.choose_output_folder)

        top.addLayout(label_block, 1)
        top.addWidget(choose_video)
        top.addWidget(choose_output)

        self.preview = PreviewPanel()
        self.output_label = QLabel(f"Output: {self.output_folder}")
        self.output_label.setObjectName("SubtleText")

        layout.addLayout(top)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.output_label)
        return panel

    def _build_settings_area(self) -> QWidget:
        content = QWidget()
        layout = QGridLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        layout.addWidget(self._section("Caption Setup", self._caption_setup_form()), 0, 0)
        layout.addWidget(self._section("Grouping", self._grouping_form()), 0, 1)
        layout.addWidget(self._section("Caption Style", self._style_form()), 1, 0)
        layout.addWidget(self._section("Effects", self._effects_form()), 1, 1)
        layout.addWidget(self._section("Style Library", self._style_library_form()), 2, 0)
        layout.addWidget(self._section("Position", self._position_form()), 2, 1)
        layout.setRowStretch(3, 1)
        return content

    def _caption_setup_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self._compact_form(form)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS.keys())
        self.preset_combo.setCurrentText("Creator")
        self.preset_combo.currentTextChanged.connect(self._apply_preset_defaults)

        self.model_combo = QComboBox()
        self.model_combo.addItems(MODEL_OPTIONS.keys())
        self.model_combo.setCurrentText("Base - balanced")

        self.compute_combo = QComboBox()
        self.compute_combo.addItems(COMPUTE_OPTIONS.keys())
        self.compute_combo.setCurrentText("CPU")

        form.addRow("Caption preset", self.preset_combo)
        form.addRow("Whisper model", self.model_combo)
        form.addRow("Compute device", self.compute_combo)
        return widget

    def _style_library_form(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        self.style_combo = QComboBox()
        self.style_combo.currentTextChanged.connect(self._apply_saved_style)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_style)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_style)
        grid.addWidget(self.style_combo, 0, 0, 1, 2)
        grid.addWidget(save_button, 1, 0)
        grid.addWidget(delete_button, 1, 1)
        return widget

    def _style_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self._compact_form(form)
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Montserrat", "Open Sans", "Poppins", "Inter", "Anton", "Oswald", "Roboto", "Lato", "Arial"])
        self.font_combo.setCurrentText("Montserrat")

        self.main_size = NumericInput(24, 160, 72)
        self.active_size = NumericInput(24, 180, 78)
        self.outline_width = NumericInput(0, 20, 5)
        self.main_color = ColorButton("#FFFFFF")
        self.active_color = ColorButton(MAGENTA)
        self.bold_check = ToggleSwitch("Bold")
        self.bold_check.setChecked(True)
        self.active_bold_check = ToggleSwitch("Active word bold")
        self.active_bold_check.setChecked(True)

        for control in (self.font_combo, self.main_size, self.active_size):
            signal = getattr(control, "currentTextChanged", None) or getattr(control, "valueChanged", None)
            signal.connect(self._apply_caption_style)
        for button in (self.main_color, self.active_color):
            button.color_changed.connect(self._apply_caption_style)
        self.bold_check.toggled.connect(self._apply_caption_style)
        self.active_bold_check.toggled.connect(self._apply_caption_style)

        form.addRow("Font", self.font_combo)
        form.addRow("Main size", self.main_size)
        form.addRow("Active size", self.active_size)
        form.addRow("Text color", self.main_color)
        form.addRow("Active color", self.active_color)
        form.addRow("Main weight", self.bold_check)
        form.addRow("Active weight", self.active_bold_check)
        return widget

    def _effects_form(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(7)
        self.outline_enabled = ToggleSwitch("Outline")
        self.outline_enabled.setChecked(True)
        self.outline_color = ColorButton("#05050A")
        self.shadow_enabled = ToggleSwitch("Shadow")
        self.shadow_color = ColorButton("#000000")
        self.shadow_depth = NumericInput(0, 20, 5)
        self.glow_enabled = ToggleSwitch("Glow")
        self.glow_color = ColorButton(MAGENTA)
        self.glow_strength = NumericInput(0, 20, 5)

        for control in (self.outline_width, self.shadow_depth, self.glow_strength):
            control.valueChanged.connect(self._apply_caption_style)
        self.outline_enabled.toggled.connect(self._apply_caption_style)
        self.shadow_enabled.toggled.connect(lambda enabled: self._effect_toggled(enabled, self.shadow_depth))
        self.glow_enabled.toggled.connect(lambda enabled: self._effect_toggled(enabled, self.glow_strength))
        for button in (self.outline_color, self.shadow_color, self.glow_color):
            button.color_changed.connect(self._apply_caption_style)

        grid.addWidget(QLabel("Effect"), 0, 0)
        grid.addWidget(QLabel("Color"), 0, 1)
        grid.addWidget(QLabel("Size"), 0, 2)
        grid.addWidget(self.outline_enabled, 1, 0)
        grid.addWidget(self.outline_color, 1, 1)
        grid.addWidget(self.outline_width, 1, 2)
        grid.addWidget(self.shadow_enabled, 2, 0)
        grid.addWidget(self.shadow_color, 2, 1)
        grid.addWidget(self.shadow_depth, 2, 2)
        grid.addWidget(self.glow_enabled, 3, 0)
        grid.addWidget(self.glow_color, 3, 1)
        grid.addWidget(self.glow_strength, 3, 2)
        grid.setColumnStretch(1, 1)
        return widget

    def _effect_toggled(self, enabled: bool, value_control: NumericInput) -> None:
        if enabled and value_control.value() == 0:
            value_control.setValue(5)
        self._apply_caption_style()

    def _position_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self._compact_form(form)
        self.position_combo = QComboBox()
        self.position_combo.addItems(["Bottom", "Middle", "Top"])
        self.margin_v = NumericInput(0, 600, 220, step=10)
        self.position_combo.currentTextChanged.connect(self._apply_caption_style)
        self.margin_v.valueChanged.connect(self._apply_caption_style)
        form.addRow("Placement", self.position_combo)
        form.addRow("Offset", self.margin_v)
        return widget

    def _grouping_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self._compact_form(form)
        self.max_words = NumericInput(1, 12, 4)
        self.max_duration = NumericInput(0.5, 8.0, 2.2, step=0.1, decimals=1)
        self.max_chars = NumericInput(10, 120, 32)
        form.addRow("Max words", self.max_words)
        form.addRow("Max seconds", self.max_duration)
        form.addRow("Max characters", self.max_chars)
        return widget

    def _build_status_bar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("StatusBar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("StatusText")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(260)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.progress)
        return panel

    def _section(self, title: str, content: QWidget) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SettingsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(9, 7, 9, 8)
        layout.setSpacing(5)
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        label.setFixedHeight(22)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label)
        layout.addWidget(content, 0, Qt.AlignmentFlag.AlignTop)
        return panel

    def _compact_form(self, form: QFormLayout) -> None:
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: {SURFACE};
                color: {TEXT};
                font-family: "Open Sans", "Segoe UI", Arial;
                font-size: 13px;
            }}
            QLabel#AppTitle {{
                font-family: "Montserrat", "Segoe UI", Arial;
                font-size: 26px;
                font-weight: 800;
                color: {TEXT};
            }}
            QLabel#SectionTitle {{
                font-family: "Montserrat", "Segoe UI", Arial;
                font-size: 13px;
                font-weight: 800;
                color: {TEXT};
            }}
            QLabel#SubtleText, QLabel#StatusText {{
                color: {MUTED};
            }}
            QFrame#PreviewShell, QFrame#SettingsPanel, QFrame#StatusBar {{
                background: {PANEL};
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            QScrollArea#SettingsScroll {{
                border: none;
                background: transparent;
            }}
            QScrollArea#SettingsScroll > QWidget > QWidget {{
                background: transparent;
            }}
            QPushButton {{
                background: {PANEL_ALT};
                border: 1px solid {BORDER};
                border-radius: 7px;
                color: {TEXT};
                font-weight: 700;
                padding: 8px 12px;
            }}
            QPushButton:hover {{
                border-color: {TEAL};
                background: #252938;
            }}
            QPushButton#PrimaryButton {{
                background: {MAGENTA};
                border-color: {MAGENTA};
                color: white;
                padding: 10px 18px;
            }}
            QPushButton#PrimaryButton:hover {{
                background: #E600B9;
            }}
            QPushButton#StepButton {{
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                padding: 0;
                font-size: 14px;
            }}
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
                background: #0F1118;
                border: 1px solid {BORDER};
                border-radius: 7px;
                color: {TEXT};
                min-height: 24px;
                padding: 2px 7px;
            }}
            QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
                border: 2px solid {TEAL};
            }}
            QComboBox QAbstractItemView {{
                background: {PANEL_ALT};
                color: {TEXT};
                selection-background-color: {TEAL};
            }}
            QCheckBox {{
                color: {TEXT};
                spacing: 6px;
            }}
            QProgressBar {{
                background: #0F1118;
                border: 1px solid {BORDER};
                border-radius: 6px;
                color: {TEXT};
                text-align: center;
                height: 16px;
            }}
            QProgressBar::chunk {{
                background: {MAGENTA};
                border-radius: 5px;
            }}
            """
        )

    def _load_style_options(self) -> None:
        current = self.style_combo.currentText() if hasattr(self, "style_combo") else ""
        self.style_library = load_style_library()
        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        self.style_combo.addItems(self.style_library.keys())
        if current and current in self.style_library:
            self.style_combo.setCurrentText(current)
        else:
            self.style_combo.setCurrentText("Magenta Pop")
        self.style_combo.blockSignals(False)
        self._apply_saved_style(self.style_combo.currentText())

    def _apply_preset_defaults(self, preset_name: str) -> None:
        preset = PRESETS[preset_name]
        self.max_words.setValue(preset.max_words)
        self.max_duration.setValue(preset.max_duration)
        self.max_chars.setValue(preset.max_chars)

    def _apply_saved_style(self, name: str) -> None:
        style = self.style_library.get(name)
        if style is None:
            return
        self._set_style_controls(style)

    def _set_style_controls(self, style: CaptionStyle) -> None:
        controls = [
            self.font_combo,
            self.main_size,
            self.active_size,
            self.outline_width,
            self.outline_enabled,
            self.shadow_enabled,
            self.shadow_depth,
            self.glow_enabled,
            self.glow_strength,
            self.position_combo,
            self.margin_v,
            self.bold_check,
            self.active_bold_check,
        ]
        for control in controls:
            control.blockSignals(True)
        self.font_combo.setCurrentText(style.font_family)
        self.main_size.setValue(style.main_font_size)
        self.active_size.setValue(style.active_font_size)
        self.outline_width.setValue(style.outline_width)
        self.outline_enabled.setChecked(style.outline_enabled)
        self.shadow_enabled.setChecked(style.shadow_enabled)
        self.shadow_depth.setValue(style.shadow_depth)
        self.glow_enabled.setChecked(style.glow_enabled)
        self.glow_strength.setValue(style.glow_strength)
        self.position_combo.setCurrentText(style.position)
        self.margin_v.setValue(style.margin_v)
        self.bold_check.setChecked(style.bold)
        self.active_bold_check.setChecked(style.active_bold)
        for control in controls:
            control.blockSignals(False)

        for button, color in (
            (self.main_color, style.main_color),
            (self.active_color, style.active_color),
            (self.outline_color, style.outline_color),
            (self.shadow_color, style.shadow_color),
            (self.glow_color, style.glow_color),
        ):
            button.blockSignals(True)
            button.set_color(color)
            button.blockSignals(False)
        self._apply_caption_style()

    def _apply_caption_style(self) -> None:
        if hasattr(self, "preview"):
            self.preview.set_caption_style(self._style())

    def choose_video(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Choose video",
            "",
            "Videos (*.mp4 *.mov *.mkv *.avi *.webm)",
        )
        if not file_name:
            return
        self.input_video_path = Path(file_name)
        self.video_label.setText(str(self.input_video_path))
        self._load_preview_frame()

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", str(self.output_folder))
        if not folder:
            return
        self.output_folder = Path(folder)
        self.output_label.setText(f"Output: {self.output_folder}")

    def save_style(self) -> None:
        name, ok = QInputDialog.getText(self, "Save style", "Style name:", QLineEdit.EchoMode.Normal, self.style_combo.currentText())
        if not ok:
            return
        try:
            save_user_style(name, self._style())
        except ValueError as exc:
            QMessageBox.warning(self, "Could not save style", str(exc))
            return
        self._load_style_options()
        self.style_combo.setCurrentText(name.strip())

    def delete_style(self) -> None:
        name = self.style_combo.currentText()
        if not name:
            return
        if is_built_in_style(name):
            QMessageBox.information(self, "Built-in style", "Built-in styles cannot be deleted.")
            return
        if delete_user_style(name):
            self._load_style_options()

    def _load_preview_frame(self) -> None:
        if self.input_video_path is None:
            self.preview.set_frame(None)
            return
        try:
            ffmpeg = find_ffmpeg()
            target = temp_dir() / "preview_frame.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    str(ffmpeg),
                    "-y",
                    "-ss",
                    "0",
                    "-i",
                    str(self.input_video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.preview_frame_path = target
            self.preview.set_frame(target)
        except Exception as exc:  # noqa: BLE001
            self.preview.set_frame(None)
            self._set_status(f"Preview unavailable: {exc}", 0)

    def _style(self) -> CaptionStyle:
        return CaptionStyle(
            font_family=self.font_combo.currentText(),
            main_font_size=int(self.main_size.value()),
            active_font_size=int(self.active_size.value()),
            main_color=self.main_color.color,
            active_color=self.active_color.color,
            outline_color=self.outline_color.color,
            outline_width=int(self.outline_width.value()),
            bold=self.bold_check.isChecked(),
            active_bold=self.active_bold_check.isChecked(),
            position=self.position_combo.currentText(),
            margin_v=int(self.margin_v.value()),
            outline_enabled=self.outline_enabled.isChecked(),
            shadow_enabled=self.shadow_enabled.isChecked(),
            shadow_color=self.shadow_color.color,
            shadow_depth=int(self.shadow_depth.value()),
            glow_enabled=self.glow_enabled.isChecked(),
            glow_color=self.glow_color.color,
            glow_strength=int(self.glow_strength.value()),
        )

    def _output_path(self) -> Path:
        assert self.input_video_path is not None
        return self.output_folder / f"{self.input_video_path.stem}_captioned.mp4"

    def generate(self) -> None:
        if self.input_video_path is None:
            QMessageBox.warning(self, "No video selected", "Please choose a video file first.")
            return

        settings = JobSettings(
            input_video_path=str(self.input_video_path),
            output_video_path=str(self._output_path()),
            working_dir=str(temp_dir()),
            style=self._style(),
            preset=CaptionPreset(
                name=self.preset_combo.currentText(),
                max_words=int(self.max_words.value()),
                max_duration=float(self.max_duration.value()),
                max_chars=int(self.max_chars.value()),
            ),
            model_size=MODEL_OPTIONS[self.model_combo.currentText()],
            compute_mode=self.compute_combo.currentText(),
        )

        self._set_busy(True)
        self._set_status("Starting...", 0)
        self.thread = QThread()
        self.worker = CaptionWorker(settings)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._set_status)
        self.worker.finished.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _set_busy(self, busy: bool) -> None:
        self.generate_button.setDisabled(busy)

    def _set_status(self, message: str, value: int) -> None:
        self.status_label.setText(message)
        self.progress.setValue(value)

    def _finished(self, output_path: str) -> None:
        self._set_busy(False)
        self._set_status(f"Done. Exported: {output_path}", 100)
        QMessageBox.information(self, "Finished", f"Captioned video exported:\n{output_path}")

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self._set_status("Failed.", 0)
        QMessageBox.critical(self, "Could not generate video", message)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
