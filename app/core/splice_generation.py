from __future__ import annotations

from dataclasses import dataclass

from app.core.edit_decisions import EditDecisionList
from app.core.transcript_model import TranscriptProject, TranscriptWord


class InvalidCutPlanError(ValueError):
    """Raised when adjusted cut boundaries cannot produce ordered video ranges."""


@dataclass(frozen=True)
class KeptRange:
    id: str
    start_word_id: str
    end_word_id: str
    suggested_start_frame: int
    suggested_end_frame: int
    adjusted_start_frame: int
    adjusted_end_frame: int


@dataclass(frozen=True)
class DynamicSplice:
    id: str
    anchor_key: str
    left_keep_range_id: str
    right_keep_range_id: str
    left_word_id: str
    right_word_id: str
    left_out_frame: int
    right_in_frame: int
    left_whisper_out_frame: int
    left_suggested_out_frame: int
    left_out_adjustment: int
    right_in_adjustment: int
    left_context: str
    right_context: str
    reviewed: bool


@dataclass(frozen=True)
class SplicePlan:
    kept_ranges: list[KeptRange]
    splices: list[DynamicSplice]

    def export_intervals(self) -> list[tuple[int, int]]:
        return [(item.adjusted_start_frame, item.adjusted_end_frame) for item in self.kept_ranges]


def generate_splices(project: TranscriptProject, edits: EditDecisionList) -> SplicePlan:
    deleted_word_indexes = _deleted_word_indexes(project, edits)
    boundaries = _deleted_boundaries(project, edits, deleted_word_indexes)
    kept_groups = _kept_word_groups(project.words, deleted_word_indexes, boundaries)
    kept_ranges = _build_kept_ranges(kept_groups)
    splices = _build_splices(project, kept_ranges, boundaries, edits)
    kept_ranges = _apply_splice_adjustments(kept_ranges, splices)
    plan = SplicePlan(kept_ranges=kept_ranges, splices=splices)
    validate_cut_plan(plan)
    return plan


def validate_cut_plan(plan: SplicePlan) -> None:
    """Reject collapsed, reversed, or overlapping adjusted source ranges."""

    previous: KeptRange | None = None
    for kept_range in plan.kept_ranges:
        if kept_range.adjusted_start_frame < 0:
            raise InvalidCutPlanError(
                f"{kept_range.id} starts before frame 0. Move its IN point later."
            )
        if kept_range.adjusted_end_frame < kept_range.adjusted_start_frame:
            raise InvalidCutPlanError(
                f"{kept_range.id} is collapsed because its IN point is after its OUT point. "
                "Move the nearby cut points farther apart."
            )
        if previous is not None and previous.adjusted_end_frame >= kept_range.adjusted_start_frame:
            raise InvalidCutPlanError(
                f"{previous.id} and {kept_range.id} overlap at the current cut points. "
                "Move the previous OUT earlier or the next IN later."
            )
        previous = kept_range


def _deleted_word_indexes(project: TranscriptProject, edits: EditDecisionList) -> set[int]:
    indexes: set[int] = set()
    for deleted_range in edits.deleted_word_ranges:
        start = project.word_index(deleted_range.start_word_id)
        end = project.word_index(deleted_range.end_word_id)
        if end < start:
            start, end = end, start
        indexes.update(range(start, end + 1))
    return indexes


def _deleted_boundaries(project: TranscriptProject, edits: EditDecisionList, deleted_word_indexes: set[int]) -> set[tuple[str, str]]:
    boundaries: set[tuple[str, str]] = set()

    for index in sorted(deleted_word_indexes):
        left = _nearest_kept_left(project.words, deleted_word_indexes, index)
        right = _nearest_kept_right(project.words, deleted_word_indexes, index)
        if left is not None and right is not None:
            boundaries.add((left.id, right.id))

    for deleted_silence in edits.deleted_silence_ranges:
        silence = project.silence_by_id(deleted_silence.silence_id)
        left = _nearest_word_ending_before(project.words, silence.start_frame, deleted_word_indexes)
        right = _nearest_word_starting_after(project.words, silence.end_frame, deleted_word_indexes)
        if left is not None and right is not None:
            boundaries.add((left.id, right.id))

    return boundaries


def _kept_word_groups(
    words: list[TranscriptWord],
    deleted_word_indexes: set[int],
    boundaries: set[tuple[str, str]],
) -> list[list[TranscriptWord]]:
    groups: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for index, word in enumerate(words):
        if index in deleted_word_indexes:
            if current:
                groups.append(current)
                current = []
            continue
        if current and (current[-1].id, word.id) in boundaries:
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _build_kept_ranges(groups: list[list[TranscriptWord]]) -> list[KeptRange]:
    ranges: list[KeptRange] = []
    for index, group in enumerate(groups, start=1):
        first = group[0]
        last = group[-1]
        ranges.append(
            KeptRange(
                id=f"keep_{index:03d}",
                start_word_id=first.id,
                end_word_id=last.id,
                suggested_start_frame=first.start_frame,
                suggested_end_frame=last.end_frame,
                adjusted_start_frame=first.start_frame,
                adjusted_end_frame=last.end_frame,
            )
        )
    return ranges


def _build_splices(
    project: TranscriptProject,
    kept_ranges: list[KeptRange],
    boundaries: set[tuple[str, str]],
    edits: EditDecisionList,
) -> list[DynamicSplice]:
    splices: list[DynamicSplice] = []
    first_kept = kept_ranges[0] if kept_ranges else None
    if first_kept is not None and first_kept.start_word_id != project.words[0].id:
        anchor_key = f"START->{first_kept.start_word_id}"
        adjustment = edits.splice_adjustments.get(anchor_key)
        right_delta = adjustment.right_in_delta if adjustment else 0
        right_word = project.word_by_id(first_kept.start_word_id)
        splices.append(
            DynamicSplice(
                id="splice_001",
                anchor_key=anchor_key,
                left_keep_range_id="",
                right_keep_range_id=first_kept.id,
                left_word_id="",
                right_word_id=right_word.id,
                left_out_frame=0,
                right_in_frame=right_word.start_frame + right_delta,
                left_whisper_out_frame=0,
                left_suggested_out_frame=0,
                left_out_adjustment=0,
                right_in_adjustment=right_delta,
                left_context="Start of source",
                right_context=_context_after(project.words, right_word.id),
                reviewed=adjustment.reviewed if adjustment else False,
            )
        )

    for index, (left_range, right_range) in enumerate(zip(kept_ranges, kept_ranges[1:]), start=len(splices) + 1):
        if (left_range.end_word_id, right_range.start_word_id) not in boundaries:
            continue
        anchor_key = f"{left_range.end_word_id}->{right_range.start_word_id}"
        adjustment = edits.splice_adjustments.get(anchor_key)
        left_delta = adjustment.left_out_delta if adjustment else 0
        right_delta = adjustment.right_in_delta if adjustment else 0
        left_word = project.word_by_id(left_range.end_word_id)
        right_word = project.word_by_id(right_range.start_word_id)
        suggested_out_frame = (
            adjustment.assisted_left_out_frame
            if adjustment and adjustment.assisted_left_out_frame is not None
            else left_word.end_frame
        )
        splices.append(
            DynamicSplice(
                id=f"splice_{index:03d}",
                anchor_key=anchor_key,
                left_keep_range_id=left_range.id,
                right_keep_range_id=right_range.id,
                left_word_id=left_word.id,
                right_word_id=right_word.id,
                left_out_frame=suggested_out_frame + left_delta,
                right_in_frame=right_word.start_frame + right_delta,
                left_whisper_out_frame=left_word.end_frame,
                left_suggested_out_frame=suggested_out_frame,
                left_out_adjustment=left_delta,
                right_in_adjustment=right_delta,
                left_context=_context_before(project.words, left_word.id),
                right_context=_context_after(project.words, right_word.id),
                reviewed=adjustment.reviewed if adjustment else False,
            )
        )
    return splices


def _apply_splice_adjustments(kept_ranges: list[KeptRange], splices: list[DynamicSplice]) -> list[KeptRange]:
    adjusted = {kept_range.id: kept_range for kept_range in kept_ranges}
    for splice in splices:
        if splice.left_keep_range_id:
            left = adjusted[splice.left_keep_range_id]
            adjusted[splice.left_keep_range_id] = KeptRange(
                id=left.id,
                start_word_id=left.start_word_id,
                end_word_id=left.end_word_id,
                suggested_start_frame=left.suggested_start_frame,
                suggested_end_frame=left.suggested_end_frame,
                adjusted_start_frame=left.adjusted_start_frame,
                adjusted_end_frame=splice.left_out_frame,
            )
        adjusted[splice.right_keep_range_id] = KeptRange(
            id=adjusted[splice.right_keep_range_id].id,
            start_word_id=adjusted[splice.right_keep_range_id].start_word_id,
            end_word_id=adjusted[splice.right_keep_range_id].end_word_id,
            suggested_start_frame=adjusted[splice.right_keep_range_id].suggested_start_frame,
            suggested_end_frame=adjusted[splice.right_keep_range_id].suggested_end_frame,
            adjusted_start_frame=splice.right_in_frame,
            adjusted_end_frame=adjusted[splice.right_keep_range_id].adjusted_end_frame,
        )
    return [adjusted[kept_range.id] for kept_range in kept_ranges]


def _nearest_kept_left(words: list[TranscriptWord], deleted_indexes: set[int], index: int) -> TranscriptWord | None:
    for candidate in range(index - 1, -1, -1):
        if candidate not in deleted_indexes:
            return words[candidate]
    return None


def _nearest_kept_right(words: list[TranscriptWord], deleted_indexes: set[int], index: int) -> TranscriptWord | None:
    for candidate in range(index + 1, len(words)):
        if candidate not in deleted_indexes:
            return words[candidate]
    return None


def _nearest_word_ending_before(words: list[TranscriptWord], frame: int, deleted_indexes: set[int]) -> TranscriptWord | None:
    for index in range(len(words) - 1, -1, -1):
        if index not in deleted_indexes and words[index].end_frame < frame:
            return words[index]
    return None


def _nearest_word_starting_after(words: list[TranscriptWord], frame: int, deleted_indexes: set[int]) -> TranscriptWord | None:
    for index, word in enumerate(words):
        if index not in deleted_indexes and word.start_frame > frame:
            return word
    return None


def _context_before(words: list[TranscriptWord], word_id: str, count: int = 2) -> str:
    index = next(i for i, word in enumerate(words) if word.id == word_id)
    selected = words[max(0, index - count + 1) : index + 1]
    return "..." + " ".join(word.text for word in selected)


def _context_after(words: list[TranscriptWord], word_id: str, count: int = 2) -> str:
    index = next(i for i, word in enumerate(words) if word.id == word_id)
    selected = words[index : index + count]
    return " ".join(word.text for word in selected) + "..."
