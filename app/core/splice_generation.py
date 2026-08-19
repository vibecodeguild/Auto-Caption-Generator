from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.edit_decisions import EditDecisionList, ManualCut
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
    right_whisper_in_frame: int
    right_suggested_in_frame: int
    left_out_adjustment: int
    right_in_adjustment: int
    left_context: str
    right_context: str
    reviewed: bool
    kind: str = "transcript"
    manual_cut_id: str = ""


@dataclass(frozen=True)
class SplicePlan:
    kept_ranges: list[KeptRange]
    splices: list[DynamicSplice]

    def export_intervals(self) -> list[tuple[int, int]]:
        return [(item.adjusted_start_frame, item.adjusted_end_frame) for item in self.kept_ranges]


def generate_splices(project: TranscriptProject, edits: EditDecisionList) -> SplicePlan:
    kept_ranges, transcript_splices = _transcript_kept_ranges(project, edits)
    kept_ranges = _apply_manual_cuts(project, kept_ranges, edits.manual_cuts)
    kept_ranges = _apply_final_out_frame(project, kept_ranges, edits.final_out_frame)
    splices = _finalize_splices(project, kept_ranges, transcript_splices, edits.manual_cuts)
    plan = SplicePlan(kept_ranges=kept_ranges, splices=splices)
    validate_cut_plan(plan)
    return plan


def reconcile_cut_plan_polish(project: TranscriptProject, edits: EditDecisionList) -> dict[str, object]:
    """Drop Stage 4 polish that no longer fits the current Stage 3 keep/delete plan.

    Manual cuts and a custom final OUT are refinements on top of transcript edits.
    When the user returns to Stage 3 and changes deletes/restores, those refinements
    can land outside every kept section. That must not hard-block the editor — Stage 3
    is authority; incompatible Stage 4 polish is removed so splice generation can proceed.
    """

    kept_ranges, _transcript_splices = _transcript_kept_ranges(project, edits)
    working_ranges = list(kept_ranges)
    kept_manual_ids: set[str] = set()
    dropped_manual_ids: list[str] = []

    for cut in sorted(edits.manual_cuts, key=lambda item: (item.out_frame, item.in_frame, item.id)):
        if cut.out_frame < 0 or cut.in_frame < cut.out_frame + 2:
            dropped_manual_ids.append(cut.id)
            continue
        containing = next(
            (
                item
                for item in working_ranges
                if item.adjusted_start_frame <= cut.out_frame and cut.in_frame <= item.adjusted_end_frame
            ),
            None,
        )
        if containing is None:
            dropped_manual_ids.append(cut.id)
            continue
        cut_index = working_ranges.index(containing)
        left = replace(
            containing,
            id=f"{containing.id}__{cut.id}_left",
            end_word_id=_nearest_word_id(project, cut.out_frame, prefer_left=True, fallback=containing.end_word_id),
            adjusted_end_frame=cut.out_frame,
        )
        right = replace(
            containing,
            id=f"{containing.id}__{cut.id}_right",
            start_word_id=_nearest_word_id(project, cut.in_frame, prefer_left=False, fallback=containing.start_word_id),
            adjusted_start_frame=cut.in_frame,
        )
        working_ranges[cut_index : cut_index + 1] = [left, right]
        kept_manual_ids.add(cut.id)

    if dropped_manual_ids:
        edits.manual_cuts = [cut for cut in edits.manual_cuts if cut.id in kept_manual_ids]

    cleared_final_out = False
    if edits.final_out_frame is not None:
        try:
            trial = _apply_final_out_frame(project, list(working_ranges), edits.final_out_frame)
            validate_cut_plan(SplicePlan(kept_ranges=trial, splices=[]))
        except InvalidCutPlanError:
            edits.final_out_frame = None
            cleared_final_out = True

    return {
        "changed": bool(dropped_manual_ids) or cleared_final_out,
        "droppedManualCutIds": dropped_manual_ids,
        "clearedFinalOutFrame": cleared_final_out,
    }


def _transcript_kept_ranges(
    project: TranscriptProject, edits: EditDecisionList
) -> tuple[list[KeptRange], list[DynamicSplice]]:
    """Kept source ranges + transcript splices before manual cuts / final OUT."""

    deleted_word_indexes = _deleted_word_indexes(project, edits)
    boundaries = _deleted_boundaries(project, edits, deleted_word_indexes)
    kept_groups = _kept_word_groups(project.words, deleted_word_indexes, boundaries)
    kept_ranges = _build_kept_ranges(kept_groups)
    transcript_splices = _build_splices(project, kept_ranges, boundaries, edits)
    kept_ranges = _apply_splice_adjustments(kept_ranges, transcript_splices)
    return kept_ranges, transcript_splices


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
        suggested_in_frame = (
            adjustment.assisted_right_in_frame
            if adjustment and adjustment.assisted_right_in_frame is not None
            else right_word.start_frame
        )
        splices.append(
            DynamicSplice(
                id="splice_001",
                anchor_key=anchor_key,
                left_keep_range_id="",
                right_keep_range_id=first_kept.id,
                left_word_id="",
                right_word_id=right_word.id,
                left_out_frame=0,
                right_in_frame=suggested_in_frame + right_delta,
                left_whisper_out_frame=0,
                left_suggested_out_frame=0,
                right_whisper_in_frame=right_word.start_frame,
                right_suggested_in_frame=suggested_in_frame,
                left_out_adjustment=0,
                right_in_adjustment=right_delta,
                left_context="Start of source",
                right_context=_context_after(project.words, right_word.id),
                reviewed=adjustment.reviewed if adjustment else False,
                kind="front_trim",
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
        suggested_in_frame = (
            adjustment.assisted_right_in_frame
            if adjustment and adjustment.assisted_right_in_frame is not None
            else right_word.start_frame
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
                right_in_frame=suggested_in_frame + right_delta,
                left_whisper_out_frame=left_word.end_frame,
                left_suggested_out_frame=suggested_out_frame,
                right_whisper_in_frame=right_word.start_frame,
                right_suggested_in_frame=suggested_in_frame,
                left_out_adjustment=left_delta,
                right_in_adjustment=right_delta,
                left_context=_context_before(project.words, left_word.id),
                right_context=_context_after(project.words, right_word.id),
                reviewed=adjustment.reviewed if adjustment else False,
            )
        )
    return splices


def _apply_manual_cuts(
    project: TranscriptProject,
    kept_ranges: list[KeptRange],
    manual_cuts: list[ManualCut],
) -> list[KeptRange]:
    ranges = list(kept_ranges)
    for cut in sorted(manual_cuts, key=lambda item: (item.out_frame, item.in_frame, item.id)):
        if cut.out_frame < 0 or cut.in_frame < cut.out_frame + 2:
            raise InvalidCutPlanError("A manual cut must remove at least one complete frame between OUT and IN.")
        containing = next(
            (
                item
                for item in ranges
                if item.adjusted_start_frame <= cut.out_frame
                and cut.in_frame <= item.adjusted_end_frame
            ),
            None,
        )
        if containing is None:
            raise InvalidCutPlanError(
                "Manual cut boundaries must stay inside one currently kept section and cannot overlap another cut."
            )
        cut_index = ranges.index(containing)
        left = replace(
            containing,
            id=f"{containing.id}__{cut.id}_left",
            end_word_id=_nearest_word_id(project, cut.out_frame, prefer_left=True, fallback=containing.end_word_id),
            adjusted_end_frame=cut.out_frame,
        )
        right = replace(
            containing,
            id=f"{containing.id}__{cut.id}_right",
            start_word_id=_nearest_word_id(project, cut.in_frame, prefer_left=False, fallback=containing.start_word_id),
            adjusted_start_frame=cut.in_frame,
        )
        ranges[cut_index : cut_index + 1] = [left, right]
    return ranges


def _apply_final_out_frame(
    project: TranscriptProject,
    kept_ranges: list[KeptRange],
    final_out_frame: int | None,
) -> list[KeptRange]:
    if final_out_frame is None:
        return kept_ranges
    if not kept_ranges:
        raise InvalidCutPlanError("A final OUT frame requires at least one kept transcript section.")

    final_range = kept_ranges[-1]
    final_word_index = project.word_index(final_range.end_word_id)
    if final_word_index + 1 < len(project.words):
        maximum_out_frame = project.words[final_word_index + 1].start_frame - 1
        if final_out_frame > maximum_out_frame:
            raise InvalidCutPlanError(
                f"The final OUT frame must stay before deleted trailing content at frame {maximum_out_frame + 1}."
            )

    return [
        *kept_ranges[:-1],
        replace(final_range, adjusted_end_frame=final_out_frame),
    ]


def _finalize_splices(
    project: TranscriptProject,
    kept_ranges: list[KeptRange],
    transcript_splices: list[DynamicSplice],
    manual_cuts: list[ManualCut],
) -> list[DynamicSplice]:
    finalized: list[DynamicSplice] = []
    for splice in transcript_splices:
        left_range = _range_ending_at(kept_ranges, splice.left_out_frame) if splice.left_keep_range_id else None
        right_range = _range_starting_at(kept_ranges, splice.right_in_frame)
        finalized.append(
            replace(
                splice,
                left_keep_range_id=left_range.id if left_range else "",
                right_keep_range_id=right_range.id if right_range else splice.right_keep_range_id,
            )
        )
    for cut in manual_cuts:
        left_range = _range_ending_at(kept_ranges, cut.out_frame)
        right_range = _range_starting_at(kept_ranges, cut.in_frame)
        if left_range is None or right_range is None:
            raise InvalidCutPlanError(f"Manual cut {cut.id} does not align with the current cut plan.")
        left_word_id = _nearest_word_id(project, cut.out_frame, prefer_left=True, fallback="")
        right_word_id = _nearest_word_id(project, cut.in_frame, prefer_left=False, fallback="")
        finalized.append(
            DynamicSplice(
                id="",
                anchor_key=f"MANUAL:{cut.id}",
                left_keep_range_id=left_range.id,
                right_keep_range_id=right_range.id,
                left_word_id=left_word_id,
                right_word_id=right_word_id,
                left_out_frame=cut.out_frame,
                right_in_frame=cut.in_frame,
                left_whisper_out_frame=cut.suggested_out_frame,
                left_suggested_out_frame=cut.suggested_out_frame,
                right_whisper_in_frame=cut.suggested_in_frame,
                right_suggested_in_frame=cut.suggested_in_frame,
                left_out_adjustment=cut.out_frame - cut.suggested_out_frame,
                right_in_adjustment=cut.in_frame - cut.suggested_in_frame,
                left_context=_context_around_frame(project.words, cut.out_frame, before=True),
                right_context=_context_around_frame(project.words, cut.in_frame, before=False),
                reviewed=cut.reviewed,
                kind="manual",
                manual_cut_id=cut.id,
            )
        )
    finalized.sort(key=lambda item: (item.right_in_frame, item.left_out_frame, item.anchor_key))
    return [replace(splice, id=f"splice_{index:03d}") for index, splice in enumerate(finalized, start=1)]


def _range_ending_at(ranges: list[KeptRange], frame: int) -> KeptRange | None:
    return next((item for item in ranges if item.adjusted_end_frame == frame), None)


def _range_starting_at(ranges: list[KeptRange], frame: int) -> KeptRange | None:
    return next((item for item in ranges if item.adjusted_start_frame == frame), None)


def _nearest_word_id(project: TranscriptProject, frame: int, *, prefer_left: bool, fallback: str) -> str:
    if prefer_left:
        candidates = [word for word in project.words if word.start_frame <= frame]
        return candidates[-1].id if candidates else fallback
    candidates = [word for word in project.words if word.end_frame >= frame]
    return candidates[0].id if candidates else fallback


def _context_around_frame(words: list[TranscriptWord], frame: int, *, before: bool, count: int = 6) -> str:
    if before:
        selected = [word for word in words if word.start_frame <= frame][-count:]
        return ("..." if selected else "") + " ".join(word.text for word in selected)
    selected = [word for word in words if word.end_frame >= frame][:count]
    return " ".join(word.text for word in selected) + ("..." if selected else "")


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
