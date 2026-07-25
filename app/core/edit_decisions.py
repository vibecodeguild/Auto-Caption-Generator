from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeletedWordRange:
    id: str
    start_word_id: str
    end_word_id: str
    reason: str


@dataclass(frozen=True)
class DeletedSilenceRange:
    id: str
    silence_id: str


@dataclass
class ManualCut:
    id: str
    suggested_out_frame: int
    suggested_in_frame: int
    out_frame: int
    in_frame: int
    reviewed: bool = False


@dataclass
class SpliceAdjustment:
    anchor_key: str
    left_out_delta: int = 0
    right_in_delta: int = 0
    reviewed: bool = False
    assisted_left_out_frame: int | None = None
    assisted_right_in_frame: int | None = None


@dataclass
class EditorSettings:
    dead_space_min_seconds: float = 0.8


@dataclass
class EditDecisionList:
    deleted_word_ranges: list[DeletedWordRange] = field(default_factory=list)
    deleted_silence_ranges: list[DeletedSilenceRange] = field(default_factory=list)
    manual_cuts: list[ManualCut] = field(default_factory=list)
    splice_adjustments: dict[str, SpliceAdjustment] = field(default_factory=dict)
    final_out_frame: int | None = None
    settings: EditorSettings = field(default_factory=EditorSettings)

    def delete_words(self, decision_id: str, start_word_id: str, end_word_id: str, reason: str) -> None:
        self.deleted_word_ranges.append(DeletedWordRange(decision_id, start_word_id, end_word_id, reason))

    def delete_word_selection(self, start_word_id: str, end_word_id: str) -> None:
        decision_id = f"delete_{start_word_id}_{end_word_id}"
        self.delete_words(decision_id, start_word_id, end_word_id, reason="selection")

    def restore_word_selection(self, start_word_id: str, end_word_id: str) -> None:
        start_num = _word_number(start_word_id)
        end_num = _word_number(end_word_id)
        if end_num < start_num:
            start_num, end_num = end_num, start_num
        self.deleted_word_ranges = [
            item
            for item in self.deleted_word_ranges
            if not _ranges_overlap(start_num, end_num, _word_number(item.start_word_id), _word_number(item.end_word_id))
        ]

    def delete_silence(self, decision_id: str, silence_id: str) -> None:
        self.deleted_silence_ranges.append(DeletedSilenceRange(decision_id, silence_id))

    def restore_silence(self, silence_id: str) -> None:
        self.deleted_silence_ranges = [item for item in self.deleted_silence_ranges if item.silence_id != silence_id]

    def toggle_word(self, word_id: str) -> None:
        existing = next(
            (
                item
                for item in self.deleted_word_ranges
                if item.start_word_id == word_id and item.end_word_id == word_id
            ),
            None,
        )
        if existing:
            self.deleted_word_ranges.remove(existing)
            return
        self.delete_words(f"delete_{word_id}", word_id, word_id, reason="word")

    def toggle_silence(self, silence_id: str) -> None:
        existing = next((item for item in self.deleted_silence_ranges if item.silence_id == silence_id), None)
        if existing:
            self.deleted_silence_ranges.remove(existing)
            return
        self.delete_silence(f"delete_{silence_id}", silence_id)

    def add_manual_cut(self, cut_id: str, out_frame: int, in_frame: int) -> None:
        self.manual_cuts.append(
            ManualCut(
                id=cut_id,
                suggested_out_frame=out_frame,
                suggested_in_frame=in_frame,
                out_frame=out_frame,
                in_frame=in_frame,
            )
        )

    def adjust_manual_cut(self, cut_id: str, *, out_delta: int = 0, in_delta: int = 0) -> None:
        cut = self.manual_cut_by_id(cut_id)
        cut.out_frame += out_delta
        cut.in_frame += in_delta

    def review_manual_cut(self, cut_id: str, reviewed: bool) -> None:
        self.manual_cut_by_id(cut_id).reviewed = reviewed

    def remove_manual_cut(self, cut_id: str) -> None:
        before = len(self.manual_cuts)
        self.manual_cuts = [cut for cut in self.manual_cuts if cut.id != cut_id]
        if len(self.manual_cuts) == before:
            raise KeyError(f"Unknown manual cut: {cut_id}")

    def manual_cut_by_id(self, cut_id: str) -> ManualCut:
        cut = next((item for item in self.manual_cuts if item.id == cut_id), None)
        if cut is None:
            raise KeyError(f"Unknown manual cut: {cut_id}")
        return cut

    def set_final_out_frame(self, frame: int | None) -> None:
        self.final_out_frame = frame

    def adjust_splice(
        self,
        anchor_key: str,
        *,
        left_out_delta: int = 0,
        right_in_delta: int = 0,
        reviewed: bool | None = None,
    ) -> None:
        adjustment = self.splice_adjustments.get(anchor_key)
        if adjustment is None:
            adjustment = SpliceAdjustment(anchor_key)
            self.splice_adjustments[anchor_key] = adjustment
        adjustment.left_out_delta += left_out_delta
        adjustment.right_in_delta += right_in_delta
        if reviewed is not None:
            adjustment.reviewed = reviewed

    def set_assisted_out_frame(self, anchor_key: str, frame: int | None) -> None:
        adjustment = self.splice_adjustments.get(anchor_key)
        if adjustment is None:
            adjustment = SpliceAdjustment(anchor_key)
            self.splice_adjustments[anchor_key] = adjustment
        adjustment.assisted_left_out_frame = frame

    def set_assisted_in_frame(self, anchor_key: str, frame: int | None) -> None:
        adjustment = self.splice_adjustments.get(anchor_key)
        if adjustment is None:
            adjustment = SpliceAdjustment(anchor_key)
            self.splice_adjustments[anchor_key] = adjustment
        adjustment.assisted_right_in_frame = frame


def _word_number(word_id: str) -> int:
    digits = "".join(char for char in word_id if char.isdigit())
    if not digits:
        raise ValueError(f"Word id does not include a numeric index: {word_id}")
    return int(digits)


def _ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    if b_end < b_start:
        b_start, b_end = b_end, b_start
    return a_start <= b_end and b_start <= a_end
