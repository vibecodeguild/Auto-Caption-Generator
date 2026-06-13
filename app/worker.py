from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot

from app.core.pipeline import generate_captioned_video
from app.core.settings import CaptionPreset, CaptionStyle


@dataclass(frozen=True)
class JobSettings:
    input_video_path: str
    output_video_path: str
    working_dir: str
    style: CaptionStyle
    preset: CaptionPreset
    model_size: str
    compute_mode: str


class CaptionWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, settings: JobSettings):
        super().__init__()
        self.settings = settings

    @Slot()
    def run(self) -> None:
        try:
            output = generate_captioned_video(
                input_video_path=self.settings.input_video_path,
                output_video_path=self.settings.output_video_path,
                working_dir=self.settings.working_dir,
                style=self.settings.style,
                preset=self.settings.preset,
                model_size=self.settings.model_size,
                compute_mode=self.settings.compute_mode,
                progress_callback=lambda value, message: self.progress.emit(message, value),
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.finished.emit(output)
