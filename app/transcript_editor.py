from __future__ import annotations

import subprocess
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QKeyEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QDialog,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.action_logger import ActionLogger
from app.core.editor_pipeline import generate_editor_transcript
from app.core.editor_tokens import token_ids_between, transcript_tokens
from app.core.edit_decisions import EditDecisionList
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.project_store import load_editor_project, save_editor_project
from app.core.settings import COMPUTE_OPTIONS, MODEL_OPTIONS, exports_dir, temp_dir
from app.core.splice_preview import source_splice_preview_segments
from app.core.splice_generation import DynamicSplice, SplicePlan, generate_splices
from app.core.process_utils import hidden_subprocess_flags
from app.core.transcript_model import SilenceRange, TranscriptProject, TranscriptWord
from app.core.video_cutter import frame_intervals_to_seconds, run_cut


MAGENTA = "#FF00CE"
TEAL = "#007C7D"
BORDER = "#303443"
PANEL_ALT = "#20232F"
MUTED = "#A7AABD"


DEFAULT_SHORTCUTS = {
    "play_splice_2s": "2",
    "play_splice_4s": "4",
    "play_splice_6s": "6",
    "toggle_loop": "L",
    "out_frame_back": "A",
    "out_frame_forward": "S",
    "in_frame_back": "D",
    "in_frame_forward": "F",
    "previous_splice": "J",
    "next_splice": "K",
    "mark_reviewed": "Return",
    "delete_selection": "D",
    "restore_selection": "R",
}


@dataclass(frozen=True)
class SentenceBlock:
    id: int
    words: list[TranscriptWord]


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 4):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            widget = item.widget()
            if (
                widget is not None
                and widget.property("flow_line_break_before")
                and x != effective.x()
                and line_height > 0
            ):
                x = effective.x()
                y += line_height + self.spacing()
                line_height = 0
            next_x = x + hint.width() + self.spacing()
            if next_x - self.spacing() > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self.spacing()
                next_x = x + hint.width() + self.spacing()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()


class TranscriptWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, video_path: Path, model_size: str, compute_mode: str, log_path: Path):
        super().__init__()
        self.video_path = video_path
        self.model_size = model_size
        self.compute_mode = compute_mode
        self.log_path = log_path

    @Slot()
    def run(self) -> None:
        logger = ActionLogger(self.log_path)
        try:
            project = generate_editor_transcript(
                input_video_path=self.video_path,
                working_dir=temp_dir(),
                model_size=self.model_size,
                compute_mode=self.compute_mode,
                logger=logger,
                progress_callback=lambda value, message: self.progress.emit(message, value),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Transcript generation failed", traceback.format_exc())
            self.failed.emit(str(exc))
            return
        logger.info("Transcript generation finished")
        self.finished.emit(project)


class CutExportWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, project: TranscriptProject, intervals: list[tuple[int, int]], output_path: Path):
        super().__init__()
        self.project = project
        self.intervals = intervals
        self.output_path = output_path

    @Slot()
    def run(self) -> None:
        try:
            seconds = frame_intervals_to_seconds(self.intervals, self.project.fps)
            run_cut(
                ffmpeg=find_ffmpeg(),
                input_video=Path(self.project.source),
                output_video=self.output_path,
                intervals=seconds,
                progress_callback=lambda value: self.progress.emit("Exporting cut...", int(value * 100)),
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished.emit(str(self.output_path))


class TranscriptEditor(QWidget):
    def __init__(self):
        super().__init__()
        self.project = sample_transcript_project()
        self.edits = sample_edit_decisions()
        self.plan = generate_splices(self.project, self.edits)
        self.selected_splice_index = 0
        self.loop_enabled = False
        self.current_project_file: Path | None = None
        self.selected_video_path: Path | None = None
        self.preview_frame_path: Path | None = None
        self.current_log_path: Path | None = None
        self.editor_log_path = self._new_editor_log_path()
        self.editor_logger = ActionLogger(self.editor_log_path)
        self.preview_pixmap = QPixmap()
        self.preview_segments: list[tuple[float, float]] = []
        self.preview_segment_index = 0
        self.preview_jump_pending = False
        self.preview_loaded_source: Path | None = None
        self.selected_token_ids: set[str] = set()
        self.selection_anchor_token_id: str | None = None
        self.word_buttons: dict[str, QPushButton] = {}
        self.silence_buttons: dict[str, QPushButton] = {}
        self.thread: QThread | None = None
        self.worker: QObject | None = None
        self.progress_dialog: QDialog | None = None
        self.progress_label: QLabel | None = None
        self.progress_bar: QProgressBar | None = None
        self.progress_ok_button: QPushButton | None = None
        self.last_status_message = ""
        self._shortcut_objects: list[QShortcut] = []
        self._build_ui()
        self._log_info("Transcript editor initialized")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._install_shortcuts()
        self._render()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self._build_preview_panel(), 3)
        top.addWidget(self._build_splice_detail_panel(), 2)
        root.addLayout(top, 0)

        transcript_shell = QFrame()
        transcript_shell.setObjectName("EditorPanel")
        transcript_layout = QVBoxLayout(transcript_shell)
        transcript_layout.setContentsMargins(14, 12, 14, 12)
        transcript_layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Transcript Edit")
        title.setObjectName("SectionTitle")
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("SubtleText")
        header.addWidget(title)
        header.addWidget(self.summary_label, 1, Qt.AlignmentFlag.AlignRight)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("TranscriptScroll")
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.transcript_body = QWidget()
        self.transcript_layout = QVBoxLayout(self.transcript_body)
        self.transcript_layout.setContentsMargins(0, 0, 6, 0)
        self.transcript_layout.setSpacing(8)
        self.scroll_area.setWidget(self.transcript_body)

        transcript_layout.addLayout(header)
        transcript_layout.addWidget(self.scroll_area, 1)
        root.addWidget(transcript_shell, 1)

    def _build_preview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("EditorPanel")
        shell = QHBoxLayout(panel)
        shell.setContentsMargins(14, 12, 14, 12)
        shell.setSpacing(12)

        action_rail = QFrame()
        action_rail.setObjectName("ActionRail")
        action_layout = QVBoxLayout(action_rail)
        action_layout.setContentsMargins(8, 8, 8, 8)
        action_layout.setSpacing(8)

        self.choose_video_button = QPushButton("Choose Video")
        self.choose_video_button.clicked.connect(self.choose_video)
        self.transcribe_button = QPushButton("Transcribe")
        self.transcribe_button.clicked.connect(self.transcribe_video)
        self.open_project_button = QPushButton("Open Project")
        self.open_project_button.clicked.connect(self.open_project)
        self.save_project_button = QPushButton("Save Project")
        self.save_project_button.clicked.connect(self.save_project)
        self.export_cut_button = QPushButton("Export Cut")
        self.export_cut_button.setObjectName("PrimaryButton")
        self.export_cut_button.clicked.connect(self.export_cut)
        self.model_combo = QComboBox()
        self.model_combo.addItems(MODEL_OPTIONS.keys())
        self.model_combo.setCurrentText("Base - balanced")
        self.compute_combo = QComboBox()
        self.compute_combo.addItems(COMPUTE_OPTIONS.keys())
        self.compute_combo.setCurrentText("CPU")
        for widget in (
            self.choose_video_button,
            self.transcribe_button,
            self.open_project_button,
            self.save_project_button,
            self.export_cut_button,
            self.model_combo,
            self.compute_combo,
        ):
            widget.setMinimumWidth(150)
            action_layout.addWidget(widget)
        action_layout.addStretch(1)

        preview_area = QVBoxLayout()
        preview_area.setSpacing(8)

        title = QLabel("Splice Preview")
        title.setObjectName("SectionTitle")
        self.source_label = QLabel("Demo transcript loaded. Choose a video and transcribe to create a real editor project.")
        self.source_label.setObjectName("SubtleText")
        self.preview_stack = QStackedWidget()
        self.preview_stack.setMinimumHeight(170)
        self.preview_surface = QLabel("Source video preview\n\nPlay splice preview from the selected row")
        self.preview_surface.setObjectName("VideoPreview")
        self.preview_surface.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_surface.setMinimumHeight(170)
        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("VideoPreview")
        self.audio_output = QAudioOutput(self)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.positionChanged.connect(self._preview_position_changed)
        self.media_player.mediaStatusChanged.connect(lambda status: self._log_info(f"Preview media status: {status.name}"))
        self.media_player.errorOccurred.connect(self._preview_player_error)
        self.preview_stack.addWidget(self.preview_surface)
        self.preview_stack.addWidget(self.video_widget)
        self.preview_stack.setCurrentWidget(self.video_widget)

        preview_area.addWidget(title)
        preview_area.addWidget(self.source_label)
        preview_area.addWidget(self.preview_stack, 1)

        shell.addWidget(action_rail, 0)
        shell.addLayout(preview_area, 1)
        return panel

    def _build_splice_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("EditorPanel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        self.detail_title = QLabel("Selected Splice")
        self.detail_title.setObjectName("SectionTitle")
        self.detail_context = QLabel("")
        self.detail_context.setWordWrap(True)
        self.detail_context.setObjectName("SubtleText")
        self.out_frame_label = QLabel("")
        self.in_frame_label = QLabel("")
        self.reviewed_label = QLabel("")

        layout.addWidget(self.detail_title, 0, 0, 1, 2)
        layout.addWidget(self.detail_context, 1, 0, 1, 2)
        layout.addWidget(QLabel("OUT frame"), 2, 0)
        layout.addWidget(QLabel("IN frame"), 2, 1)
        layout.addWidget(self.out_frame_label, 3, 0)
        layout.addWidget(self.in_frame_label, 3, 1)
        layout.addWidget(self._frame_strip("Before cut"), 4, 0)
        layout.addWidget(self._frame_strip("After cut"), 4, 1)
        layout.addWidget(self.reviewed_label, 5, 0, 1, 2)
        return panel

    def _frame_strip(self, label: str) -> QWidget:
        widget = QFrame()
        widget.setObjectName("FrameStrip")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel(label)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("SubtleText")
        frames = QLabel("-1   CUT   +1")
        frames.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(frames)
        return widget

    def _install_shortcuts(self) -> None:
        bindings = {
            "play_splice_2s": lambda: self._play_selected(2),
            "play_splice_4s": lambda: self._play_selected(4),
            "play_splice_6s": lambda: self._play_selected(6),
            "toggle_loop": self._toggle_loop,
        }
        for action, handler in bindings.items():
            shortcut = QShortcut(QKeySequence(DEFAULT_SHORTCUTS[action]), self)
            shortcut.activated.connect(handler)
            self._shortcut_objects.append(shortcut)

    def _render(self) -> None:
        self.plan = generate_splices(self.project, self.edits)
        if self.selected_splice_index >= len(self.plan.splices):
            self.selected_splice_index = max(0, len(self.plan.splices) - 1)

        while self.transcript_layout.count():
            item = self.transcript_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.word_buttons = {}
        self.silence_buttons = {}

        splice_by_right = {splice.right_word_id: splice for splice in self.plan.splices}
        for block in _sentence_blocks(self.project.words):
            sentence_widget = self._sentence_widget(block, splice_by_right)
            self.transcript_layout.addWidget(sentence_widget)

        self.transcript_layout.addStretch(1)
        reviewed = sum(1 for splice in self.plan.splices if splice.reviewed)
        self.summary_label.setText(f"{len(self.plan.splices)} dynamic splices | {reviewed} reviewed")
        self._refresh_detail()

    def _sentence_widget(self, block: SentenceBlock, splice_by_right: dict[str, DynamicSplice]) -> QWidget:
        container = QFrame()
        container.setObjectName("SentenceBlock")
        row = FlowLayout(container, margin=8, spacing=4)
        for word in block.words:
            if word.id in splice_by_right:
                row.addWidget(self._splice_row(splice_by_right[word.id]))
            token = QPushButton(word.text)
            token.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.word_buttons[word.id] = token
            self._style_word_button(word.id)
            token.clicked.connect(lambda checked=False, word_id=word.id: self._select_word(word_id))
            row.addWidget(token)
            silence = self._silence_after_word(word.id)
            if silence is not None:
                chip = QPushButton(f"DEAD SPACE {silence.end - silence.start:.1f}s")
                chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.silence_buttons[silence.id] = chip
                self._style_silence_button(silence.id)
                chip.clicked.connect(lambda checked=False, silence_id=silence.id: self._select_silence(silence_id))
                row.addWidget(chip)
        return container

    def _splice_row(self, splice: DynamicSplice) -> QWidget:
        index = self.plan.splices.index(splice)
        selected = index == self.selected_splice_index
        row = QFrame()
        row.setObjectName("SpliceRow")
        row.setProperty("flow_line_break_before", True)
        row.setFixedSize(710, 38)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        label = QPushButton(f"{splice.id.replace('_', ' ').title()}")
        label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        label.setFixedSize(88, 28)
        label.clicked.connect(lambda checked=False, value=index: self._select_splice(value))
        context = QLabel(f"{splice.left_context}  ->  {splice.right_context}")
        context.setObjectName("SubtleText")
        context.setFixedWidth(170)

        layout.addWidget(label)
        layout.addWidget(context)
        layout.addWidget(QLabel("Play"))
        for seconds in (2, 4, 6):
            button = QPushButton(str(seconds))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(32, 28)
            button.clicked.connect(lambda checked=False, value=seconds, splice_index=index: self._play_splice(splice_index, value))
            layout.addWidget(button)
        loop = QPushButton("Loop")
        loop.setCheckable(True)
        loop.setChecked(self.loop_enabled and selected)
        loop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        loop.setFixedSize(58, 28)
        loop.clicked.connect(lambda checked=False, splice_index=index: self._loop_splice(splice_index))
        layout.addWidget(loop)
        layout.addSpacing(4)
        layout.addWidget(QLabel("Out"))
        layout.addWidget(self._nudge_button("-", index, left=-1))
        layout.addWidget(self._nudge_button("+", index, left=1))
        layout.addSpacing(4)
        layout.addWidget(QLabel("In"))
        layout.addWidget(self._nudge_button("-", index, right=-1))
        layout.addWidget(self._nudge_button("+", index, right=1))
        reviewed = QPushButton("Reviewed" if splice.reviewed else "Review")
        reviewed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        reviewed.setObjectName("ReviewedButton" if splice.reviewed else "")
        reviewed.setFixedSize(66, 28)
        reviewed.clicked.connect(lambda checked=False, splice_index=index: self._toggle_reviewed(splice_index))
        layout.addWidget(reviewed)
        return row

    def _expanded_splice(self, splice: DynamicSplice) -> QWidget:
        expanded = QFrame()
        expanded.setObjectName("ExpandedSplice")
        layout = QGridLayout(expanded)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel("OUT: end previous keep"), 0, 0)
        layout.addWidget(QLabel(str(splice.left_out_frame)), 0, 1)
        layout.addWidget(QLabel("IN: start next keep"), 0, 2)
        layout.addWidget(QLabel(str(splice.right_in_frame)), 0, 3)
        layout.addWidget(self._frame_strip("Before cut"), 1, 0, 1, 2)
        layout.addWidget(self._frame_strip("After cut"), 1, 2, 1, 2)
        return expanded

    def _nudge_button(self, text: str, splice_index: int, *, left: int = 0, right: int = 0) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("StepButton")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(26, 26)
        button.clicked.connect(lambda checked=False: self._adjust_splice(splice_index, left=left, right=right))
        return button

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_D:
            self.delete_selection()
            event.accept()
            return
        if key == Qt.Key.Key_R:
            self.restore_selection()
            event.accept()
            return
        if key == Qt.Key.Key_A:
            self._adjust_selected(left=-1)
            event.accept()
            return
        if key == Qt.Key.Key_S:
            self._adjust_selected(left=1)
            event.accept()
            return
        if key == Qt.Key.Key_F:
            self._adjust_selected(right=1)
            event.accept()
            return
        if key == Qt.Key.Key_J:
            self._previous_splice()
            event.accept()
            return
        if key == Qt.Key.Key_K:
            self._next_splice()
            event.accept()
            return
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._toggle_reviewed()
            event.accept()
            return
        super().keyPressEvent(event)

    def _is_word_deleted(self, word_id: str) -> bool:
        word_index = self.project.word_index(word_id)
        for deleted_range in self.edits.deleted_word_ranges:
            start = self.project.word_index(deleted_range.start_word_id)
            end = self.project.word_index(deleted_range.end_word_id)
            if start <= word_index <= end:
                return True
        return False

    def _is_silence_deleted(self, silence_id: str) -> bool:
        return any(item.silence_id == silence_id for item in self.edits.deleted_silence_ranges)

    def _silence_after_word(self, word_id: str) -> SilenceRange | None:
        word = self.project.word_by_id(word_id)
        for silence in self.project.silence_ranges:
            if silence.start_frame == word.end_frame + 1:
                return silence
        return None

    def _select_word(self, word_id: str) -> None:
        self._select_token(word_id)

    def _select_silence(self, silence_id: str) -> None:
        self._select_token(silence_id)

    def _select_token(self, token_id: str) -> None:
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self.selection_anchor_token_id is not None:
            tokens = transcript_tokens(self.project)
            self.selected_token_ids = set(token_ids_between(tokens, self.selection_anchor_token_id, token_id))
        else:
            self.selection_anchor_token_id = token_id
            self.selected_token_ids = {token_id}
        self._refresh_selection_styles()
        words = len(self._selected_word_ids())
        silences = len(self._selected_silence_ids())
        message = f"Selected {words} word(s) and {silences} dead-space chip(s). Press D to delete or R to restore."
        self._set_status(message)

    def delete_selection(self) -> None:
        selected_word_ids = self._selected_word_ids()
        selected_silence_ids = self._selected_silence_ids()
        if selected_word_ids:
            start, end = self._selected_word_bounds()
            self.edits.delete_word_selection(start, end)
        for silence_id in selected_silence_ids:
            self.edits.delete_silence(f"delete_{silence_id}", silence_id)
        if selected_word_ids or selected_silence_ids:
            self._render()

    def restore_selection(self) -> None:
        selected_word_ids = self._selected_word_ids()
        selected_silence_ids = self._selected_silence_ids()
        if selected_word_ids:
            start, end = self._selected_word_bounds()
            self.edits.restore_word_selection(start, end)
        for silence_id in selected_silence_ids:
            self.edits.restore_silence(silence_id)
        if selected_word_ids or selected_silence_ids:
            self._render()

    def _word_ids_between(self, start_word_id: str, end_word_id: str) -> list[str]:
        start = self.project.word_index(start_word_id)
        end = self.project.word_index(end_word_id)
        if end < start:
            start, end = end, start
        return [word.id for word in self.project.words[start : end + 1]]

    def _selected_word_bounds(self) -> tuple[str, str]:
        indexes = sorted(self.project.word_index(word_id) for word_id in self._selected_word_ids())
        return self.project.words[indexes[0]].id, self.project.words[indexes[-1]].id

    def _selected_word_ids(self) -> set[str]:
        word_ids = {word.id for word in self.project.words}
        return self.selected_token_ids & word_ids

    def _selected_silence_ids(self) -> set[str]:
        silence_ids = {silence.id for silence in self.project.silence_ranges}
        return self.selected_token_ids & silence_ids

    def _style_word_button(self, word_id: str) -> None:
        button = self.word_buttons[word_id]
        if word_id in self.selected_token_ids:
            button.setObjectName("SelectedToken")
        elif self._is_word_deleted(word_id):
            button.setObjectName("DeletedToken")
        else:
            button.setObjectName("WordToken")
        button.style().unpolish(button)
        button.style().polish(button)

    def _style_silence_button(self, silence_id: str) -> None:
        button = self.silence_buttons[silence_id]
        if silence_id in self.selected_token_ids:
            button.setObjectName("SelectedToken")
        elif self._is_silence_deleted(silence_id):
            button.setObjectName("DeletedToken")
        else:
            button.setObjectName("SilenceToken")
        button.style().unpolish(button)
        button.style().polish(button)

    def _refresh_selection_styles(self) -> None:
        for word_id in self.word_buttons:
            self._style_word_button(word_id)
        for silence_id in self.silence_buttons:
            self._style_silence_button(silence_id)

    def choose_video(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Choose video",
            "",
            "Videos (*.mp4 *.mov *.mkv *.avi *.webm)",
        )
        if not file_name:
            return
        self.selected_video_path = Path(file_name)
        self.source_label.setText(str(self.selected_video_path))
        self._load_preview_frame()

    def transcribe_video(self) -> None:
        if self.selected_video_path is None:
            self.choose_video()
        if self.selected_video_path is None:
            return
        self.current_log_path = self._new_log_path(self.selected_video_path)
        self._set_busy(True)
        self._set_progress("Starting transcription...", 0)
        self.thread = QThread()
        self.worker = TranscriptWorker(
            video_path=self.selected_video_path,
            model_size=MODEL_OPTIONS[self.model_combo.currentText()],
            compute_mode=self.compute_combo.currentText(),
            log_path=self.current_log_path,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._set_progress)
        self.worker.finished.connect(self._transcription_finished)
        self.worker.failed.connect(self._operation_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _transcription_finished(self, project: TranscriptProject) -> None:
        self.project = project
        self.edits = EditDecisionList()
        self.selected_splice_index = 0
        self.current_project_file = None
        self.selected_video_path = Path(project.source)
        self.source_label.setText(project.source)
        self._load_preview_frame()
        self._set_busy(False)
        self._finish_progress("Transcript ready. Click words or dead-space chips to cut.", 100)
        self._render()

    def save_project(self) -> None:
        path = self.current_project_file
        if path is None:
            default_name = "editor-project.vcg.json"
            source_path = Path(self.project.source)
            if source_path.exists():
                default_name = f"{source_path.stem}.vcg.json"
            file_name, _ = QFileDialog.getSaveFileName(
                self,
                "Save editor project",
                default_name,
                "VCG Editor Project (*.vcg.json);;JSON (*.json)",
            )
            if not file_name:
                return
            path = Path(file_name)
        save_editor_project(path, self.project, self.edits)
        self.current_project_file = path
        self._set_status(f"Saved project: {path}")

    def open_project(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open editor project",
            "",
            "VCG Editor Project (*.vcg.json);;JSON (*.json)",
        )
        if not file_name:
            return
        try:
            self.project, self.edits = load_editor_project(Path(file_name))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not open project", str(exc))
            return
        self.current_project_file = Path(file_name)
        self.selected_video_path = Path(self.project.source)
        self.selected_splice_index = 0
        self.source_label.setText(self.project.source)
        self._load_preview_frame()
        self._set_status(f"Opened project: {file_name}")
        self._render()

    def _load_preview_frame(self) -> None:
        if self.selected_video_path is None or not self.selected_video_path.exists():
            self.preview_pixmap = QPixmap()
            self.preview_stack.setCurrentWidget(self.video_widget)
            self.media_player.stop()
            self.preview_loaded_source = None
            return
        self._load_preview_player_source(self.selected_video_path)
        try:
            target = temp_dir() / "editor_preview_frame.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    str(find_ffmpeg()),
                    "-y",
                    "-ss",
                    "0",
                    "-i",
                    str(self.selected_video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=hidden_subprocess_flags(),
            )
            self.preview_frame_path = target
            self.preview_pixmap = QPixmap(str(target))
            self.preview_stack.setCurrentWidget(self.video_widget)
            self._refresh_preview_pixmap()
        except Exception as exc:  # noqa: BLE001
            self.preview_pixmap = QPixmap()
            self.preview_stack.setCurrentWidget(self.video_widget)
            self.preview_surface.setPixmap(QPixmap())
            self._log_error("Preview frame unavailable", traceback.format_exc())

    def _load_preview_player_source(self, source_path: Path) -> None:
        source_path = source_path.resolve()
        if self.preview_loaded_source == source_path:
            return
        self.preview_loaded_source = source_path
        self.preview_segments = []
        self.preview_segment_index = 0
        self.preview_jump_pending = False
        self.media_player.stop()
        self.media_player.setSource(QUrl.fromLocalFile(str(source_path)))
        self._log_info(f"Preview media source loaded: {source_path}")

    def _refresh_preview_pixmap(self) -> None:
        if self.preview_pixmap.isNull():
            return
        if self.preview_stack.currentWidget() is not self.preview_surface:
            return
        scaled = self.preview_pixmap.scaled(
            self.preview_surface.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_surface.setText("")
        self.preview_surface.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_preview_pixmap()

    def export_cut(self) -> None:
        source_path = Path(self.project.source)
        if not source_path.exists():
            QMessageBox.warning(self, "No source video", "Choose and transcribe a real source video before exporting a cut.")
            return
        intervals = self.plan.export_intervals()
        if not intervals:
            QMessageBox.warning(self, "No kept ranges", "There are no kept transcript ranges to export.")
            return
        default_output = exports_dir() / f"{source_path.stem}_cut.mp4"
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Export cut video",
            str(default_output),
            "MP4 Video (*.mp4)",
        )
        if not file_name:
            return
        self._set_busy(True)
        self._set_progress("Starting cut export...", 0)
        self.thread = QThread()
        self.worker = CutExportWorker(self.project, intervals, Path(file_name))
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._set_progress)
        self.worker.finished.connect(self._export_finished)
        self.worker.failed.connect(self._operation_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _export_finished(self, output_path: str) -> None:
        self._set_busy(False)
        self._finish_progress(f"Exported cut: {output_path}", 100)

    def _operation_failed(self, message: str) -> None:
        self._set_busy(False)
        self._finish_progress(f"Failed: {message}", 0)
        QMessageBox.critical(self, "Operation failed", message)

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.choose_video_button,
            self.transcribe_button,
            self.open_project_button,
            self.save_project_button,
            self.export_cut_button,
            self.model_combo,
            self.compute_combo,
        ):
            widget.setDisabled(busy)

    def _set_progress(self, message: str, value: int) -> None:
        self._ensure_progress_dialog()
        display = self._progress_message(message)
        if self.progress_label is not None:
            self.progress_label.setText(display)
        if value < 0:
            if self.progress_bar is not None:
                self.progress_bar.setRange(0, 0)
            return
        if self.progress_bar is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)

    def _ensure_progress_dialog(self) -> None:
        if self.progress_dialog is not None:
            self.progress_dialog.show()
            self.progress_dialog.raise_()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Working")
        dialog.setModal(True)
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_ok_button = QPushButton("OK")
        self.progress_ok_button.setEnabled(False)
        self.progress_ok_button.clicked.connect(dialog.accept)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_ok_button, 0, Qt.AlignmentFlag.AlignRight)
        dialog.finished.connect(self._clear_progress_dialog)
        self.progress_dialog = dialog
        dialog.show()
        dialog.raise_()

    def _clear_progress_dialog(self) -> None:
        self.progress_dialog = None
        self.progress_label = None
        self.progress_bar = None
        self.progress_ok_button = None

    def _finish_progress(self, message: str, value: int = 100) -> None:
        self._set_progress(message, value)
        if self.progress_bar is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
        if self.progress_ok_button is not None:
            self.progress_ok_button.setEnabled(True)

    def _progress_message(self, message: str) -> str:
        if self.current_log_path:
            return f"{message}\n\nLog: {self.current_log_path}"
        return message

    def _set_status(self, message: str) -> None:
        self.last_status_message = message
        self.source_label.setText(message)

    def _new_log_path(self, video_path: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_stem = "".join(char if char.isalnum() or char in "-_" else "_" for char in video_path.stem)
        return temp_dir() / "logs" / f"{safe_stem}-{stamp}.log"

    def _new_editor_log_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return temp_dir() / "logs" / f"editor-session-{stamp}.log"

    def _log_info(self, message: str, details: str | None = None) -> None:
        self.editor_logger.info(message, details)

    def _log_error(self, message: str, details: str | None = None) -> None:
        self.editor_logger.error(message, details)

    def _select_splice(self, index: int) -> None:
        self.selected_splice_index = index
        self._render()

    def _selected_splice(self) -> DynamicSplice | None:
        if not self.plan.splices:
            return None
        return self.plan.splices[self.selected_splice_index]

    def _refresh_detail(self) -> None:
        splice = self._selected_splice()
        if splice is None:
            self.detail_title.setText("Selected Splice")
            self.detail_context.setText("No dynamic splices yet.")
            self.out_frame_label.setText("-")
            self.in_frame_label.setText("-")
            self.reviewed_label.setText("")
            return
        self.detail_title.setText(splice.id.replace("_", " ").title())
        self.detail_context.setText(f'{splice.left_context}" -> "{splice.right_context}')
        self.out_frame_label.setText(f"{splice.left_out_frame} ({splice.left_out_adjustment:+d})")
        self.in_frame_label.setText(f"{splice.right_in_frame} ({splice.right_in_adjustment:+d})")
        self.reviewed_label.setText("Reviewed" if splice.reviewed else "Needs review")

    def _play_selected(self, seconds: int) -> None:
        self._play_splice(self.selected_splice_index, seconds)

    def _play_splice(self, splice_index: int, seconds: int) -> None:
        if not self.plan.splices:
            return
        source_path = Path(self.project.source)
        if not source_path.exists():
            QMessageBox.warning(self, "No source video", "Open or transcribe a project with an available source video first.")
            return
        self.selected_splice_index = splice_index
        splice = self.plan.splices[splice_index]
        before_after = seconds // 2
        self._set_status(
            f"{splice.id}: building {before_after}s before + {before_after}s after "
            f"OUT {splice.left_out_frame} -> IN {splice.right_in_frame}"
        )
        self._render()
        self._play_source_splice(splice, seconds)

    def _play_source_splice(self, splice: DynamicSplice, seconds: int) -> None:
        source_path = Path(self.project.source)
        self._load_preview_player_source(source_path)
        self.preview_segments = source_splice_preview_segments(
            splice,
            fps=self.project.fps,
            seconds=seconds,
        )
        self.preview_segment_index = 0
        self.preview_jump_pending = True
        self._log_info(
            "Loading source splice preview",
            (
                f"source={source_path}\n"
                f"splice={splice.id}\n"
                f"seconds={seconds}\n"
                f"out_frame={splice.left_out_frame}\n"
                f"in_frame={splice.right_in_frame}\n"
                f"fps={self.project.fps}\n"
                f"segments={self.preview_segments}"
            ),
        )
        self.preview_stack.setCurrentWidget(self.video_widget)
        self.media_player.setPosition(round(self.preview_segments[0][0] * 1000))
        self.media_player.play()

    def _preview_position_changed(self, position_ms: int) -> None:
        if not self.preview_segments:
            return
        position = position_ms / 1000
        _, segment_end = self.preview_segments[self.preview_segment_index]
        if position < segment_end:
            return
        if self.preview_segment_index == 0:
            self.preview_segment_index = 1
            self.preview_jump_pending = True
            self.media_player.setPosition(round(self.preview_segments[1][0] * 1000))
            self.media_player.play()
            self._log_info(f"Preview jumped to IN segment at {self.preview_segments[1][0]:.3f}s")
            return
        if self.loop_enabled:
            self.preview_segment_index = 0
            self.preview_jump_pending = True
            self.media_player.setPosition(round(self.preview_segments[0][0] * 1000))
            self.media_player.play()
            self._log_info(f"Preview looped to OUT segment at {self.preview_segments[0][0]:.3f}s")
            return
        self.media_player.pause()
        self.preview_segments = []
        self._log_info("Preview playback complete")

    def _preview_failed(self, message: str) -> None:
        self.preview_stack.setCurrentWidget(self.video_widget)
        self._set_status(f"Preview failed: {message}")
        self._log_error("Splice preview failed", message)
        QMessageBox.critical(self, "Preview failed", message)

    def _preview_player_error(self, error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self._log_error(f"Preview media player error: {error.name}", error_string)
        self._set_status(f"Preview error: {error_string}")

    def _loop_splice(self, splice_index: int) -> None:
        self.selected_splice_index = splice_index
        self._toggle_loop()

    def _toggle_loop(self) -> None:
        self.loop_enabled = not self.loop_enabled
        state = "Loop on" if self.loop_enabled else "Loop off"
        self._set_status(state)
        self._render()

    def _adjust_selected(self, *, left: int = 0, right: int = 0) -> None:
        self._adjust_splice(self.selected_splice_index, left=left, right=right)

    def _adjust_splice(self, splice_index: int, *, left: int = 0, right: int = 0) -> None:
        if not self.plan.splices:
            return
        self.selected_splice_index = splice_index
        splice = self.plan.splices[splice_index]
        self.edits.adjust_splice(splice.anchor_key, left_out_delta=left, right_in_delta=right)
        self._render()

    def _toggle_reviewed(self, splice_index: int | None = None) -> None:
        if not self.plan.splices:
            return
        if splice_index is not None:
            self.selected_splice_index = splice_index
        splice = self.plan.splices[self.selected_splice_index]
        self.edits.adjust_splice(splice.anchor_key, reviewed=not splice.reviewed)
        self._render()

    def _previous_splice(self) -> None:
        if self.plan.splices:
            self.selected_splice_index = max(0, self.selected_splice_index - 1)
            self._render()

    def _next_splice(self) -> None:
        if self.plan.splices:
            self.selected_splice_index = min(len(self.plan.splices) - 1, self.selected_splice_index + 1)
            self._render()


def sample_transcript_project() -> TranscriptProject:
    words = [
        TranscriptWord("w1", " When", "When", 0.00, 0.24, 0, 7, 1),
        TranscriptWord("w2", " you", "you", 0.25, 0.39, 8, 12, 1),
        TranscriptWord("w3", " make", "make", 0.40, 0.60, 13, 18, 1),
        TranscriptWord("w4", " short-form", "short-form", 0.61, 0.98, 19, 29, 1),
        TranscriptWord("w5", " content", "content", 0.99, 1.30, 30, 39, 1),
        TranscriptWord("w6", " captions", "captions", 2.21, 2.55, 66, 76, 2),
        TranscriptWord("w7", " save", "save", 2.56, 2.82, 77, 84, 2),
        TranscriptWord("w8", " a", "a", 2.83, 2.90, 85, 87, 2),
        TranscriptWord("w9", " ton", "ton", 2.91, 3.08, 88, 92, 2),
        TranscriptWord("w10", " Build", "Build", 3.50, 3.76, 105, 112, 3),
        TranscriptWord("w11", " fast", "fast", 3.77, 4.00, 113, 120, 3),
        TranscriptWord("w12", " skip", "skip", 4.01, 4.20, 121, 126, 3),
        TranscriptWord("w13", " the", "the", 4.21, 4.32, 127, 130, 3),
        TranscriptWord("w14", " syntax", "syntax", 4.33, 4.72, 131, 141, 3),
    ]
    return TranscriptProject(
        source="demo-project/source/raw-recording.mp4",
        fps=30.0,
        words=words,
        silence_ranges=[SilenceRange("s1", 1.31, 2.20, 40, 65)],
    )


def sample_edit_decisions() -> EditDecisionList:
    edits = EditDecisionList()
    edits.delete_silence("delete_dead_space_001", "s1")
    edits.delete_words("delete_words_001", "w8", "w9", reason="words")
    return edits


def _sentence_blocks(words: list[TranscriptWord]) -> list[SentenceBlock]:
    blocks: list[SentenceBlock] = []
    current_id: int | None = None
    current_words: list[TranscriptWord] = []
    for word in words:
        if current_id is None:
            current_id = word.sentence_id
        if word.sentence_id != current_id:
            blocks.append(SentenceBlock(current_id, current_words))
            current_id = word.sentence_id
            current_words = []
        current_words.append(word)
    if current_id is not None:
        blocks.append(SentenceBlock(current_id, current_words))
    return blocks
