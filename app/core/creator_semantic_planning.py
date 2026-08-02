from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from app.core.creator_capabilities import direct_capability_source_resource
from app.core.creator_production_menu import (
    density_errors,
    planning_capability_ids_for_profile,
    vcg_density_enabled,
)
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    canonical_hash,
    transcript_word_timing_payload,
    utc_now,
    validate_artifact,
)


class PlanningDecisionError(ValueError):
    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(
            "; ".join(str(item.get("message") or item.get("code")) for item in errors)
        )


@dataclass(frozen=True)
class TranscriptIndex:
    words: list[dict]
    by_id: dict[str, dict]
    positions: dict[str, int]


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


_SPAN_EDGE_PUNCTUATION = ".,!?;:…\"'“”‘’()[]{}"


def _normalized_span_lookup_text(value: str) -> str:
    return _normalized_text(value).strip(_SPAN_EDGE_PUNCTUATION)


_NON_SEQUENCE_BOUNDARY_RELATIONSHIPS = {"continuation", "elaboration"}
_CHAPTER_BOUNDARY_RELATIONSHIPS = {
    "runtime-start",
    "new-example",
    "new-section",
    "transition",
    "conclusion",
}
_SOURCE_CHANGE_KINDS = {"performance-beat", "demonstration-beat"}
_PERFORMANCE_EVIDENCE_KINDS = {"gesture", "reaction", "joke-payoff"}
_DEMONSTRATION_EVIDENCE_KINDS = {
    "ui-state-change",
    "demonstration-action",
    "source-composition-change",
}
_COPY_EVIDENCE_KINDS = {
    "exact-ui-label": "exact-ui-label",
    "verbatim-command": "verbatim-command",
}


def copy_evidence_choices(analysis: dict) -> list[dict]:
    """Issue content-bound opaque references for analyzed copy evidence."""
    return [
        {
            "copyEvidenceRef": f"copy-evidence:{canonical_hash(item)}",
            **item,
        }
        for item in analysis.get("copyEvidence", [])
    ]


def specialize_editorial_plan_schema(
    schema: dict,
    *,
    issued_copy_evidence_refs: list[str],
) -> dict:
    """Bind a frozen plan schema to this job's issued copy-evidence receipts."""
    specialized = copy.deepcopy(schema)
    allowed = sorted(set(issued_copy_evidence_refs))
    beat = specialized["$defs"]["spokenBeat"]
    issued_ref_schema = {"type": "string", "enum": allowed}
    beat["properties"]["copyEvidenceRef"] = {
        "oneOf": [
            {"type": "null"},
            issued_ref_schema,
        ]
    }
    for rule in beat.get("allOf", []):
        copy_modes = (
            rule.get("if", {})
            .get("properties", {})
            .get("copyMode", {})
            .get("enum", [])
        )
        if set(copy_modes) == set(_COPY_EVIDENCE_KINDS):
            rule["then"]["properties"]["copyEvidenceRef"] = issued_ref_schema
    return specialized


def validate_editorial_plan_decisions(decisions: dict) -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "creator-production"
        / "schemas"
        / "editorial-plan-decisions.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(decisions),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise PlanningDecisionError(
            [
                {
                    "code": "editorial-decision-schema",
                    "path": "/".join(
                        str(part) for part in error.absolute_path
                    ) or "document root",
                    "message": error.message,
                }
                for error in errors
            ]
        )


def transcript_index(document: dict) -> TranscriptIndex:
    words = transcript_word_timing_payload(document)["words"]
    project = document.get("project") if isinstance(document.get("project"), dict) else document
    source_words = {
        str(item["id"]): item
        for item in project["words"]
    }
    normalized = [
        {
            **word,
            "text": str(source_words[word["id"]].get("text") or source_words[word["id"]].get("raw") or ""),
        }
        for word in words
    ]
    return TranscriptIndex(
        words=normalized,
        by_id={item["id"]: item for item in normalized},
        positions={item["id"]: index for index, item in enumerate(normalized)},
    )


def validate_analysis_against_transcript(analysis: dict, transcript_document: dict) -> None:
    index = transcript_index(transcript_document)
    errors: list[dict] = []
    previous_start = -1
    for proposition in analysis["propositions"]:
        start_id = proposition["startWordId"]
        end_id = proposition["endWordId"]
        if start_id not in index.positions or end_id not in index.positions:
            errors.append(
                {
                    "code": "unknown-proposition-word",
                    "propositionId": proposition["id"],
                    "message": f"Proposition {proposition['id']} references an unknown locked word.",
                }
            )
            continue
        start_position = index.positions[start_id]
        end_position = index.positions[end_id]
        if end_position < start_position:
            errors.append(
                {
                    "code": "reversed-proposition-span",
                    "propositionId": proposition["id"],
                    "message": f"Proposition {proposition['id']} reverses its locked word span.",
                }
            )
            continue
        words = index.words[start_position : end_position + 1]
        expected_start = words[0]["startFrame"]
        expected_end = words[-1]["endFrame"] + 1
        expected_text = " ".join(item["text"] for item in words)
        if proposition["absoluteStartFrame"] != expected_start:
            errors.append(
                {
                    "code": "proposition-start-frame-mismatch",
                    "propositionId": proposition["id"],
                    "expectedFrame": expected_start,
                    "actualFrame": proposition["absoluteStartFrame"],
                    "message": f"Proposition {proposition['id']} does not start on its first locked word.",
                }
            )
        if proposition["absoluteEndFrameExclusive"] != expected_end:
            errors.append(
                {
                    "code": "proposition-end-frame-mismatch",
                    "propositionId": proposition["id"],
                    "expectedFrame": expected_end,
                    "actualFrame": proposition["absoluteEndFrameExclusive"],
                    "message": f"Proposition {proposition['id']} does not end after its last locked word.",
                }
            )
        if _normalized_text(proposition["text"]) != _normalized_text(expected_text):
            errors.append(
                {
                    "code": "proposition-text-mismatch",
                    "propositionId": proposition["id"],
                    "message": f"Proposition {proposition['id']} does not match its locked words.",
                }
            )
        if start_position <= previous_start:
            errors.append(
                {
                    "code": "proposition-order-invalid",
                    "propositionId": proposition["id"],
                    "message": "Analysis propositions are not in locked transcript order.",
                }
            )
        previous_start = start_position
    if errors:
        raise PlanningDecisionError(errors)


def boundary_choices(
    *,
    job_id: str,
    analysis_sha256: str,
    analysis: dict,
    transcript_document: dict,
) -> list[dict]:
    validate_analysis_against_transcript(analysis, transcript_document)
    index = transcript_index(transcript_document)
    propositions = {item["id"]: item for item in analysis["propositions"]}
    choices = []
    for semantic_unit in analysis["semanticUnits"]:
        if (
            semantic_unit["relationshipToPrevious"]
            in _NON_SEQUENCE_BOUNDARY_RELATIONSHIPS
        ):
            continue
        proposition = propositions[semantic_unit["startPropositionId"]]
        boundary_ref = "boundary:" + canonical_hash(
            {
                "jobId": job_id,
                "analysisSha256": analysis_sha256,
                "semanticUnitId": semantic_unit["id"],
                "propositionId": proposition["id"],
            }
        )
        cause_ref = "boundary-cause:" + canonical_hash(
            {
                "jobId": job_id,
                "analysisSha256": analysis_sha256,
                "semanticUnitId": semantic_unit["id"],
                "relationshipToPrevious": semantic_unit[
                    "relationshipToPrevious"
                ],
                "sourceEventRefs": semantic_unit["sourceEventRefs"],
                "evidenceRefs": semantic_unit["evidenceRefs"],
            }
        )
        choices.append(
            {
                "boundaryRef": boundary_ref,
                "boundaryCauseRef": cause_ref,
                "semanticUnitId": semantic_unit["id"],
                "propositionId": proposition["id"],
                "spokenContext": proposition["text"],
                "absoluteFrame": index.by_id[proposition["startWordId"]]["startFrame"],
                "relationshipToPrevious": semantic_unit[
                    "relationshipToPrevious"
                ],
                "sourceEventRefs": semantic_unit["sourceEventRefs"],
                "evidenceRefs": semantic_unit["evidenceRefs"],
            }
        )
    return choices


def resolve_spoken_span_candidates(
    *,
    job_id: str,
    task_id: str,
    episode_id: str,
    transcript_sha256: str,
    word_timing_sha256: str,
    analysis_sha256: str,
    analysis: dict,
    transcript_document: dict,
    proposition_id: str,
    exact_phrase: str,
) -> list[dict]:
    validate_analysis_against_transcript(analysis, transcript_document)
    propositions = {
        item["id"]: item for item in analysis["propositions"]
    }
    proposition = propositions.get(proposition_id)
    if proposition is None:
        raise PlanningDecisionError(
            [
                {
                    "code": "unknown-proposition",
                    "message": f"Unknown analysis proposition: {proposition_id}",
                }
            ]
        )
    phrase = _normalized_span_lookup_text(exact_phrase)
    if not phrase:
        raise PlanningDecisionError(
            [{"code": "empty-spoken-phrase", "message": "Spoken phrase cannot be empty."}]
        )
    index = transcript_index(transcript_document)
    start = index.positions[proposition["startWordId"]]
    end = index.positions[proposition["endWordId"]]
    proposition_words = index.words[start : end + 1]
    matches = []
    for left in range(len(proposition_words)):
        for right in range(left, len(proposition_words)):
            words = proposition_words[left : right + 1]
            canonical_phrase = " ".join(item["text"] for item in words)
            if _normalized_span_lookup_text(canonical_phrase) != phrase:
                continue
            first = words[0]
            last = words[-1]
            unsigned = {
                "schemaVersion": ARTIFACT_SCHEMA_VERSION,
                "jobId": job_id,
                "taskId": task_id,
                "episodeId": episode_id,
                "propositionId": proposition_id,
                "transcriptSha256": transcript_sha256,
                "wordTimingSha256": word_timing_sha256,
                "analysisSha256": analysis_sha256,
                "sourceWordIds": [item["id"] for item in words],
                "spokenPhrase": canonical_phrase,
                "startWordId": first["id"],
                "endWordId": last["id"],
                "startFrame": first["startFrame"],
                "endFrameExclusive": last["endFrame"] + 1,
            }
            candidate_ref = "span-candidate:" + canonical_hash(unsigned)
            before = proposition_words[max(0, left - 4) : left]
            after = proposition_words[right + 1 : right + 5]
            matches.append(
                {
                    **unsigned,
                    "candidateRef": candidate_ref,
                    "leftContext": " ".join(item["text"] for item in before),
                    "rightContext": " ".join(item["text"] for item in after),
                }
            )
    if not matches:
        raise PlanningDecisionError(
            [
                {
                    "code": "spoken-phrase-not-found",
                    "propositionId": proposition_id,
                    "message": "The exact spoken phrase does not occur inside the selected proposition.",
                }
            ]
        )
    return matches


def create_spoken_span_receipt(candidate: dict) -> dict:
    receipt = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidateRef", "leftContext", "rightContext"}
    }
    receipt["id"] = "spoken-span:" + canonical_hash(receipt)
    receipt["createdAt"] = utc_now()
    receipt["receiptHash"] = canonical_hash(receipt)
    validate_artifact("spoken-span-receipt", receipt)
    return receipt


def _anchor_frame(anchor: dict, spans: dict[str, dict], sequence: dict, *, exclusive: bool) -> int:
    if "spanRef" in anchor:
        span = spans.get(anchor["spanRef"])
        if span is None:
            raise PlanningDecisionError(
                [{"code": "unknown-span-ref", "message": f"Unknown span reference: {anchor['spanRef']}"}]
            )
        return span["startFrame"] if anchor["edge"] == "start" else span["endFrameExclusive"]
    if anchor["sequenceEdge"] == "start":
        return sequence["absoluteStartFrame"]
    return (
        sequence["absoluteEndFrameExclusive"]
        if exclusive
        else sequence["absoluteEndFrameExclusive"] - 1
    )


def _plan_structure_and_evidence_errors(
    *,
    decisions: dict,
    starts: list[dict],
    sequence_skeletons: list[dict],
    spans: dict[str, dict],
    analysis: dict,
    channel_profile: dict,
    total_frames: int,
    fps: dict,
) -> list[dict]:
    errors: list[dict] = []
    observed_changes = {
        item["id"]: item for item in analysis["observedVisualChanges"]
    }
    carry_spans = {
        item["id"]: item for item in analysis["intentionalCarrySpans"]
    }
    copy_choices = copy_evidence_choices(analysis)
    copy_evidence_by_ref = {
        item["copyEvidenceRef"]: item for item in copy_choices
    }
    used_change_refs: set[str] = set()
    verified_change_frames: list[int] = []
    verified_carries: list[dict] = []
    change_ids: set[str] = set()
    sequence_states: list[dict] = []

    for sequence_index, (decision, boundary, sequence) in enumerate(
        zip(decisions["sequences"], starts, sequence_skeletons)
    ):
        if decision["boundaryCauseRef"] != boundary["boundaryCauseRef"]:
            errors.append(
                {
                    "code": "unsupported-sequence-boundary",
                    "sequenceId": decision["id"],
                    "retentionScope": "none",
                    "message": (
                        "The sequence boundary is not backed by the application-issued "
                        "semantic-unit cause."
                    ),
                }
            )
        directive = decision["editorialDirective"]
        beats = {item["id"]: item for item in directive["spokenBeats"]}
        for beat_index, beat in enumerate(directive["spokenBeats"]):
            copy_mode = beat["copyMode"]
            copy_ref = beat["copyEvidenceRef"]
            expected_kind = _COPY_EVIDENCE_KINDS.get(copy_mode)
            span = spans.get(beat["spanRef"])
            compatible_choices = [
                {
                    "copyEvidenceRef": item["copyEvidenceRef"],
                    "observedText": item["observedText"],
                    "propositionId": item["propositionId"],
                    "sourceEventId": item["sourceEventId"],
                    "absoluteFrame": item["absoluteFrame"],
                }
                for item in copy_choices
                if item["kind"] == expected_kind
                and (
                    span is None
                    or item["propositionId"] == span["propositionId"]
                )
            ]
            path = (
                f"sequences/{sequence_index}/editorialDirective/"
                f"spokenBeats/{beat_index}/copyEvidenceRef"
            )
            if expected_kind is None:
                if copy_ref is not None:
                    errors.append(
                        {
                            "code": "unexpected-copy-evidence",
                            "sequenceId": decision["id"],
                            "spokenBeatId": beat["id"],
                            "path": path,
                            "invalidValue": copy_ref,
                            "expectedReferenceType": "null",
                            "retentionScope": "none",
                            "message": (
                                "Concise editorial labels and non-copy beats may not "
                                "claim exact copy evidence."
                            ),
                        }
                    )
                continue
            evidence = copy_evidence_by_ref.get(copy_ref)
            if evidence is None:
                errors.append(
                    {
                        "code": "missing-or-unknown-copy-evidence",
                        "sequenceId": decision["id"],
                        "spokenBeatId": beat["id"],
                        "path": path,
                        "invalidValue": copy_ref,
                        "expectedReferenceType": "copy-evidence",
                        "validChoices": compatible_choices,
                        "retentionScope": "none",
                        "message": (
                            "Exact UI labels and verbatim commands must select one "
                            "application-issued copyEvidenceRef. Source-event IDs "
                            "are not copy evidence."
                        ),
                    }
                )
                continue
            if (
                evidence["kind"] != expected_kind
                or (
                    span is not None
                    and evidence["propositionId"] != span["propositionId"]
                )
            ):
                errors.append(
                    {
                        "code": "incompatible-copy-evidence",
                        "sequenceId": decision["id"],
                        "spokenBeatId": beat["id"],
                        "path": path,
                        "invalidValue": copy_ref,
                        "expectedCopyMode": copy_mode,
                        "expectedPropositionId": (
                            span["propositionId"] if span is not None else None
                        ),
                        "validChoices": compatible_choices,
                        "retentionScope": "none",
                        "message": (
                            "The selected copy evidence has the wrong kind or belongs "
                            "to another transcript proposition."
                        ),
                    }
                )
                continue
            if beat["onScreenText"] != evidence["observedText"]:
                errors.append(
                    {
                        "code": "copy-evidence-text-mismatch",
                        "sequenceId": decision["id"],
                        "spokenBeatId": beat["id"],
                        "path": (
                            f"sequences/{sequence_index}/editorialDirective/"
                            f"spokenBeats/{beat_index}/onScreenText"
                        ),
                        "copyEvidenceRef": copy_ref,
                        "expectedText": evidence["observedText"],
                        "actualText": beat["onScreenText"],
                        "retentionScope": "none",
                        "message": (
                            "Exact UI labels and verbatim commands must match the "
                            "issued copy evidence exactly."
                        ),
                    }
                )
        has_authored_change = False
        has_source_change = False
        sequence_change_frames: list[int] = []
        accepted_carry: dict | None = None
        for change in directive["meaningfulChanges"]:
            if change["id"] in change_ids:
                errors.append(
                    {
                        "code": "duplicate-meaningful-change-id",
                        "sequenceId": decision["id"],
                        "retentionScope": "none",
                        "message": "Meaningful-change IDs must be unique across the plan.",
                    }
                )
            change_ids.add(change["id"])
            source_ref = change["sourceVisualChangeRef"]
            beat_id = change["spokenBeatId"]
            if change["kind"] in _SOURCE_CHANGE_KINDS:
                has_source_change = True
                observed = observed_changes.get(source_ref)
                allowed_kinds = (
                    _PERFORMANCE_EVIDENCE_KINDS
                    if change["kind"] == "performance-beat"
                    else _DEMONSTRATION_EVIDENCE_KINDS
                )
                if (
                    observed is None
                    or beat_id is not None
                    or observed["kind"] not in allowed_kinds
                ):
                    errors.append(
                        {
                            "code": "unverified-source-change",
                            "sequenceId": decision["id"],
                            "retentionScope": "none",
                            "message": (
                                "Performance and demonstration changes require one "
                                "compatible observed visual-change reference."
                            ),
                        }
                    )
                    continue
                actual_frame = observed["absoluteFrame"]
                if source_ref in used_change_refs:
                    errors.append(
                        {
                            "code": "reused-source-change-evidence",
                            "sequenceId": decision["id"],
                            "retentionScope": "none",
                            "message": (
                                "One observed visual change cannot be reused to justify "
                                "multiple planned changes."
                            ),
                        }
                    )
                    continue
                used_change_refs.add(source_ref)
            else:
                has_authored_change = True
                try:
                    actual_frame = _anchor_frame(
                        change["at"], spans, sequence, exclusive=False
                    )
                except PlanningDecisionError as exc:
                    errors.extend(
                        {
                            **item,
                            "sequenceId": decision["id"],
                            "retentionScope": "none",
                        }
                        for item in exc.errors
                    )
                    continue
                beat = beats.get(beat_id)
                if source_ref is not None or beat is None:
                    errors.append(
                        {
                            "code": "unbound-authored-change",
                            "sequenceId": decision["id"],
                            "retentionScope": "none",
                            "message": (
                                "An authored meaningful change must bind one spoken beat "
                                "and may not claim source-change evidence."
                            ),
                        }
                    )
                    continue
                target_anchor = (
                    beat["exitAt"]
                    if change["kind"] == "treatment-exit"
                    else beat["revealAt"]
                )
                try:
                    expected_frame = _anchor_frame(
                        target_anchor,
                        spans,
                        sequence,
                        exclusive=change["kind"] == "treatment-exit",
                    )
                except PlanningDecisionError as exc:
                    errors.extend(
                        {
                            **item,
                            "sequenceId": decision["id"],
                            "retentionScope": "none",
                        }
                        for item in exc.errors
                    )
                    continue
                if actual_frame != expected_frame:
                    errors.append(
                        {
                            "code": "authored-change-frame-mismatch",
                            "sequenceId": decision["id"],
                            "retentionScope": "none",
                            "message": (
                                "An authored meaningful change must use its spoken beat "
                                "reveal or exit frame."
                            ),
                        }
                    )
                    continue
            inside_sequence = (
                sequence["absoluteStartFrame"]
                <= actual_frame
                < sequence["absoluteEndFrameExclusive"]
            ) or (
                change["kind"] == "treatment-exit"
                and actual_frame == sequence["absoluteEndFrameExclusive"]
            )
            if not inside_sequence:
                errors.append(
                    {
                        "code": "meaningful-change-outside-sequence",
                        "sequenceId": decision["id"],
                        "retentionScope": "none",
                        "message": "A meaningful change falls outside its sequence.",
                    }
                )
                continue
            verified_change_frames.append(actual_frame)
            sequence_change_frames.append(actual_frame)

        carry_decision = directive["intentionalVisualCarry"]
        if carry_decision is not None:
            carry = carry_spans.get(carry_decision["carrySpanRef"])
            if (
                carry is None
                or carry["kind"] != carry_decision["kind"]
            ):
                errors.append(
                    {
                        "code": "unverified-intentional-carry",
                        "sequenceId": decision["id"],
                        "retentionScope": "none",
                        "message": (
                            "An intentional carry must use one compatible analysis "
                            "carry-span reference."
                        ),
                    }
                )
            elif carry["sourceEventId"] not in boundary["sourceEventRefs"]:
                errors.append(
                    {
                        "code": "carry-source-event-mismatch",
                        "sequenceId": decision["id"],
                        "retentionScope": "none",
                        "message": (
                            "Intentional carry evidence must belong to the source "
                            "event analyzed for this sequence."
                        ),
                    }
                )
            else:
                scoped_start = max(
                    sequence["absoluteStartFrame"],
                    carry["absoluteStartFrame"],
                )
                scoped_end = min(
                    sequence["absoluteEndFrameExclusive"],
                    carry["absoluteEndFrameExclusive"],
                )
                if scoped_start >= scoped_end:
                    errors.append(
                        {
                            "code": "carry-outside-sequence",
                            "sequenceId": decision["id"],
                            "retentionScope": "none",
                            "message": (
                                "Intentional carry evidence does not overlap this "
                                "coherent sequence."
                            ),
                        }
                    )
                else:
                    accepted_carry = {
                        **carry,
                        "absoluteStartFrame": scoped_start,
                        "absoluteEndFrameExclusive": scoped_end,
                    }
                    verified_carries.append(accepted_carry)

        if decision["presentationRole"] == "source-led":
            if has_authored_change:
                errors.append(
                    {
                        "code": "source-led-authored-change",
                        "sequenceId": decision["id"],
                        "retentionScope": "none",
                        "message": (
                            "A source-led sequence with an authored visual change must "
                            "be classified as hybrid."
                        ),
                    }
                )
            if not has_source_change and carry_decision is None:
                errors.append(
                    {
                        "code": "unsupported-source-pass-through",
                        "sequenceId": decision["id"],
                        "retentionScope": "none",
                        "message": (
                            "Source-led footage requires exact observed visual-change "
                            "or intentional-carry evidence."
                        ),
                    }
                )
        elif not has_authored_change:
            errors.append(
                {
                    "code": "authored-sequence-without-change",
                    "sequenceId": decision["id"],
                    "retentionScope": "none",
                    "message": (
                        "Authored and hybrid sequences require at least one "
                        "spoken-beat-bound authored change."
                    ),
                }
            )
        sequence_states.append(
            {
                "id": decision["id"],
                "chapterId": decision["chapterId"],
                "presentationRole": decision["presentationRole"],
                "sourceStrategy": directive["sourceStrategy"],
                "sourceEventRefs": tuple(sorted(boundary["sourceEventRefs"])),
                "startFrame": sequence["absoluteStartFrame"],
                "endFrame": sequence["absoluteEndFrameExclusive"],
                "changeFrames": tuple(sequence_change_frames),
                "carry": accepted_carry,
            }
        )

    for left, right in zip(sequence_states, sequence_states[1:]):
        if not (
            left["presentationRole"] == right["presentationRole"] == "source-led"
            and left["chapterId"] == right["chapterId"]
            and left["sourceStrategy"] == right["sourceStrategy"]
            and left["sourceEventRefs"] == right["sourceEventRefs"]
        ):
            continue
        boundary_frame = right["startFrame"]
        source_change_at_boundary = boundary_frame in right["changeFrames"]
        carry_changes_at_boundary = bool(
            (left["carry"] or {}).get("absoluteEndFrameExclusive")
            == boundary_frame
            or (right["carry"] or {}).get("absoluteStartFrame")
            == boundary_frame
        )
        if not source_change_at_boundary and not carry_changes_at_boundary:
            errors.append(
                {
                    "code": "mergeable-adjacent-sequences",
                    "sequenceIds": [left["id"], right["id"]],
                    "retentionScope": "none",
                    "message": (
                        "Adjacent source-led sequences with the same source state and "
                        "strategy must remain one coherent sequence unless verified "
                        "visual evidence changes at their boundary."
                    ),
                }
            )

    chapter_ids = [item["id"] for item in decisions["chapters"]]
    sequence_chapters = [item["chapterId"] for item in decisions["sequences"]]
    if set(sequence_chapters) != set(chapter_ids):
        errors.append(
            {
                "code": "chapter-sequence-set-mismatch",
                "retentionScope": "none",
                "message": "Chapters and sequence chapter assignments do not match.",
            }
        )
    else:
        observed_chapter_order = []
        for chapter_id in sequence_chapters:
            if not observed_chapter_order or observed_chapter_order[-1] != chapter_id:
                observed_chapter_order.append(chapter_id)
        if observed_chapter_order != chapter_ids:
            errors.append(
                {
                    "code": "noncontiguous-chapter-ownership",
                    "retentionScope": "none",
                    "message": (
                        "Each chapter must own one contiguous run of sequences in "
                        "declared chapter order."
                    ),
                }
            )

    vcg_contract = channel_profile.get("id") == "vcg" and int(
        channel_profile.get("version", 0)
    ) >= 2
    if vcg_contract:
        maximum_gap = round(
            float(
                channel_profile["pacing"]["maximumMeaningfulChangeGapSec"]
            )
            * (fps["numerator"] / fps["denominator"])
        )
        if maximum_gap > 0:
            merged_carries = []
            for carry in sorted(
                verified_carries,
                key=lambda item: item["absoluteStartFrame"],
            ):
                if (
                    merged_carries
                    and carry["absoluteStartFrame"]
                    <= merged_carries[-1][1]
                ):
                    merged_carries[-1] = (
                        merged_carries[-1][0],
                        max(
                            merged_carries[-1][1],
                            carry["absoluteEndFrameExclusive"],
                        ),
                    )
                else:
                    merged_carries.append(
                        (
                            carry["absoluteStartFrame"],
                            carry["absoluteEndFrameExclusive"],
                        )
                    )
            checkpoints = sorted(
                {
                    0,
                    total_frames,
                    *verified_change_frames,
                    *(item for carry in merged_carries for item in carry),
                }
            )
            for start, end in zip(checkpoints, checkpoints[1:]):
                if end - start <= maximum_gap:
                    continue
                if any(
                    carry_start <= start and carry_end >= end
                    for carry_start, carry_end in merged_carries
                ):
                    continue
                errors.append(
                    {
                        "code": "unverified-meaningful-change-cadence",
                        "retentionScope": "none",
                        "absoluteStartFrame": start,
                        "absoluteEndFrameExclusive": end,
                        "maximumFrames": maximum_gap,
                        "message": (
                            "The plan exceeds the meaningful-change interval without "
                            "a verified change or evidence-backed carry."
                        ),
                    }
                )
        if vcg_density_enabled(channel_profile):
            # Spoken-beat changes and multi-beat reveals are the density clock.
            # Long carries no longer blank an entire teaching video.
            authored_frames: list[int] = []
            spoken_word_frames: list[int] = []
            for decision, sequence in zip(
                decisions["sequences"], sequence_skeletons
            ):
                directive = decision["editorialDirective"]
                for beat in directive.get("spokenBeats") or []:
                    # Multi-beat lists: each spoken beat with on-screen copy is a moment.
                    if str(beat.get("onScreenText") or "").strip():
                        span = spans.get(beat.get("spanRef"))
                        if span is not None:
                            authored_frames.append(int(span["startFrame"]))
            for span in spans.values():
                spoken_word_frames.append(int(span["startFrame"]))
            spoken_word_frames.extend(verified_change_frames)
            # Pure silence between held labels is not a density failure.
            speech_aware = []
            for item in errors:
                if item.get("code") != "unverified-meaningful-change-cadence":
                    speech_aware.append(item)
                    continue
                left = int(item["absoluteStartFrame"])
                right = int(item["absoluteEndFrameExclusive"])
                if any(left < frame < right for frame in spoken_word_frames):
                    speech_aware.append(item)
            errors[:] = speech_aware
            errors.extend(
                density_errors(
                    verified_change_frames=verified_change_frames,
                    verified_carries=verified_carries,
                    total_frames=total_frames,
                    fps=fps,
                    channel_profile=channel_profile,
                    authored_emphasis_frames=authored_frames,
                    spoken_word_frames=spoken_word_frames,
                )
            )
    return errors


def materialize_semantic_manifest(
    *,
    decisions: dict,
    current: dict,
    workflow_lock_hash: str,
    transcript_receipt: dict,
    transcript_document: dict,
    analysis: dict,
    analysis_sha256: str,
    catalog: dict,
    channel_profile: dict,
    total_frames: int,
    fps: dict,
    span_receipts: list[dict],
    job_id: str,
) -> dict:
    validate_editorial_plan_decisions(decisions)
    validate_analysis_against_transcript(analysis, transcript_document)
    if decisions["jobId"] != job_id or decisions["episodeId"] != current["episodeId"]:
        raise PlanningDecisionError(
            [{"code": "decision-identity-mismatch", "message": "Editorial decisions target another job or episode."}]
        )
    index = transcript_index(transcript_document)
    boundaries = {
        item["boundaryRef"]: item
        for item in boundary_choices(
            job_id=job_id,
            analysis_sha256=analysis_sha256,
            analysis=analysis,
            transcript_document=transcript_document,
        )
    }
    spans = {
        item["id"]: item
        for item in span_receipts
        if item["jobId"] == job_id
        and item["episodeId"] == current["episodeId"]
        and item["transcriptSha256"] == transcript_receipt["transcriptSha256"]
        and item["wordTimingSha256"] == transcript_receipt["wordTimingSha256"]
        and item["analysisSha256"] == analysis_sha256
    }
    proposition_order = {
        item["id"]: position for position, item in enumerate(analysis["propositions"])
    }
    sequence_decisions = decisions["sequences"]
    identity_errors = []
    for key, items in (
        ("sequence", sequence_decisions),
        ("chapter", decisions["chapters"]),
    ):
        ids = [item["id"] for item in items]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            identity_errors.append(
                {
                    "code": f"duplicate-{key}-id",
                    "ids": duplicates,
                    "message": f"Editorial decisions contain duplicate {key} IDs.",
                }
            )
    if identity_errors:
        raise PlanningDecisionError(identity_errors)
    starts = []
    boundary_errors = []
    for item in sequence_decisions:
        boundary = boundaries.get(item["startBoundaryRef"])
        if boundary is None:
            boundary_errors.append(
                {
                    "code": "unknown-boundary-ref",
                    "sequenceId": item["id"],
                    "retentionScope": "none",
                    "message": "Sequence uses an unknown boundary reference.",
                }
            )
        else:
            starts.append(boundary)
    if boundary_errors:
        raise PlanningDecisionError(boundary_errors)
    if starts[0]["propositionId"] != analysis["propositions"][0]["id"]:
        raise PlanningDecisionError(
            [
                {
                    "code": "first-sequence-must-start-at-runtime",
                    "sequenceId": sequence_decisions[0]["id"],
                    "retentionScope": "none",
                    "message": (
                        "The first sequence must use the first locked proposition "
                        "boundary so its editorial start matches frame zero."
                    ),
                }
            ]
        )
    if any(
        proposition_order[right["propositionId"]]
        <= proposition_order[left["propositionId"]]
        for left, right in zip(starts, starts[1:])
    ):
        raise PlanningDecisionError(
            [{"code": "sequence-boundary-order", "message": "Sequence boundaries are not in transcript order."}]
        )
    sequence_skeletons = [
        {
            "id": decision["id"],
            "chapterId": decision["chapterId"],
            "absoluteStartFrame": (
                0 if position == 0 else start_choice["absoluteFrame"]
            ),
            "absoluteEndFrameExclusive": (
                starts[position + 1]["absoluteFrame"]
                if position + 1 < len(starts)
                else total_frames
            ),
        }
        for position, (decision, start_choice) in enumerate(
            zip(sequence_decisions, starts)
        )
    ]
    structure_errors = _plan_structure_and_evidence_errors(
        decisions=decisions,
        starts=starts,
        sequence_skeletons=sequence_skeletons,
        spans=spans,
        analysis=analysis,
        channel_profile=channel_profile,
        total_frames=total_frames,
        fps=fps,
    )
    if structure_errors:
        raise PlanningDecisionError(structure_errors)
    capabilities = {item["id"]: item for item in catalog["capabilities"]}
    observed_changes = {
        item["id"]: item for item in analysis["observedVisualChanges"]
    }
    carry_spans = {
        item["id"]: item for item in analysis["intentionalCarrySpans"]
    }
    planning_ids = planning_capability_ids_for_profile(catalog, channel_profile)
    disabled = set(channel_profile.get("capabilities", {}).get("disabled", []))
    full_catalog_required = bool(
        channel_profile.get("selection", {}).get(
            "fullCatalogEvaluationRequired",
            False,
        )
    )
    semantic_sequences = []
    for position, (decision, start_choice) in enumerate(zip(sequence_decisions, starts)):
        sequence = sequence_skeletons[position]
        start_frame = sequence["absoluteStartFrame"]
        end_frame = sequence["absoluteEndFrameExclusive"]
        primary_position = proposition_order.get(decision["primaryPropositionId"])
        next_position = (
            proposition_order[starts[position + 1]["propositionId"]]
            if position + 1 < len(starts)
            else len(analysis["propositions"])
        )
        if primary_position is None or not (
            proposition_order[start_choice["propositionId"]] <= primary_position < next_position
        ):
            raise PlanningDecisionError(
                [{
                    "code": "primary-proposition-outside-sequence",
                    "sequenceId": decision["id"],
                    "message": "The primary proposition is outside the application-derived sequence.",
                }]
            )
        sequence_words = [
            word for word in index.words if start_frame <= word["startFrame"] < end_frame
        ]
        if not sequence_words:
            raise PlanningDecisionError(
                [{"code": "sequence-without-words", "sequenceId": decision["id"], "message": "A transcript-anchored sequence contains no locked words."}]
            )
        beats = []
        beat_errors = []
        previous_span_start = -1
        beat_ids = [
            beat["id"] for beat in decision["editorialDirective"]["spokenBeats"]
        ]
        if len(beat_ids) != len(set(beat_ids)):
            beat_errors.append(
                {
                    "code": "duplicate-spoken-beat-id",
                    "sequenceId": decision["id"],
                    "message": "Spoken beat IDs must be unique inside a sequence.",
                }
            )
        for beat in decision["editorialDirective"]["spokenBeats"]:
            span = spans.get(beat["spanRef"])
            if span is None:
                beat_errors.append(
                    {
                        "code": "unknown-span-ref",
                        "sequenceId": decision["id"],
                        "spokenBeatId": beat["id"],
                        "message": f"Unknown or stale span reference: {beat['spanRef']}",
                    }
                )
                continue
            if not (
                start_frame <= span["startFrame"] < span["endFrameExclusive"] <= end_frame
            ):
                beat_errors.append(
                    {
                        "code": "span-outside-sequence",
                        "sequenceId": decision["id"],
                        "spokenBeatId": beat["id"],
                        "message": (
                            "A spoken span is outside its application-derived sequence."
                        ),
                    }
                )
                continue
            if span["startFrame"] < previous_span_start:
                beat_errors.append(
                    {
                        "code": "spoken-beat-order",
                        "sequenceId": decision["id"],
                        "spokenBeatId": beat["id"],
                        "message": "Spoken beats are not in locked transcript order.",
                    }
                )
            previous_span_start = span["startFrame"]
            reveal = _anchor_frame(beat["revealAt"], spans, sequence, exclusive=False)
            fully = _anchor_frame(beat["fullyVisibleAt"], spans, sequence, exclusive=False)
            exit_frame = _anchor_frame(beat["exitAt"], spans, sequence, exclusive=True)
            if reveal != span["startFrame"]:
                beat_errors.append(
                    {
                        "code": "early-or-late-semantic-reveal",
                        "sequenceId": decision["id"],
                        "spokenBeatId": beat["id"],
                        "expectedFrame": span["startFrame"],
                        "actualFrame": reveal,
                        "message": (
                            "A spoken beat must begin revealing on the first locked "
                            "word of its selected spoken span."
                        ),
                    }
                )
            beats.append(
                {
                    "id": beat["id"],
                    "sourceWordIds": span["sourceWordIds"],
                    "spokenPhrase": span["spokenPhrase"],
                    "onScreenText": beat["onScreenText"],
                    "copyMode": beat["copyMode"],
                    "revealFrame": reveal,
                    "fullyVisibleFrame": fully,
                    "exitFrameExclusive": exit_frame,
                    "editorialPurpose": beat["editorialPurpose"],
                    "copyEvidenceRef": beat["copyEvidenceRef"],
                    "behavior": beat["behavior"],
                }
            )
        if len(beats) > 1:
            for beat in beats:
                if beat["behavior"] == "single":
                    beat_errors.append(
                        {
                            "code": "multi-beat-behavior",
                            "sequenceId": decision["id"],
                            "spokenBeatId": beat["id"],
                            "message": (
                                "Every beat in a multi-beat treatment must declare "
                                "accumulate or replace behavior."
                            ),
                        }
                    )
        if beat_errors:
            raise PlanningDecisionError(beat_errors)
        assessment_by_id = {
            item["capabilityId"]: item for item in decision["capabilityAssessments"]
        }
        if len(assessment_by_id) != len(decision["capabilityAssessments"]):
            raise PlanningDecisionError(
                [
                    {
                        "code": "duplicate-capability-assessment",
                        "sequenceId": decision["id"],
                        "message": "A capability may be assessed only once per sequence.",
                    }
                ]
            )
        if decision["presentationRole"] == "source-led":
            candidate_ids = []
            assessments = []
            if assessment_by_id:
                raise PlanningDecisionError(
                    [{"code": "source-led-capabilities", "sequenceId": decision["id"], "message": "Source-led sequences cannot carry capability assessments."}]
                )
        else:
            unknown = sorted(set(assessment_by_id) - set(planning_ids))
            missing = (
                [
                    capability_id
                    for capability_id in planning_ids
                    if capability_id not in assessment_by_id
                ]
                if full_catalog_required
                else []
            )
            if missing or unknown:
                raise PlanningDecisionError(
                    [{
                        "code": "capability-assessment-set",
                        "sequenceId": decision["id"],
                        "missing": missing,
                        "unknown": unknown,
                        "message": (
                            "Capability assessments must cover the exact planning catalog."
                        ),
                    }]
                )
            candidate_ids = [
                capability_id
                for capability_id in planning_ids
                if capability_id in assessment_by_id
            ]
            assessments = []
            for capability_id in planning_ids:
                authored = assessment_by_id[capability_id]
                capability = capabilities[capability_id]
                direct_source = direct_capability_source_resource(catalog, capability_id)
                maturity = {
                    "source-only": 0.0,
                    "native-runtime-probed": 0.25,
                    "compiled": 0.5,
                    "technically-proven": 0.75,
                    "delivery-proven": 1.0,
                }[capability["implementationMaturity"]]
                agent_exclusions = authored["editorialExclusions"]
                assessments.append(
                    {
                        "capabilityId": capability_id,
                        "recipeEvidence": {
                            "sourceResourceId": direct_source["id"],
                            "sourceSha256": direct_source["sha256"],
                            "compatibleRecipeRole": authored["compatibleRecipeRole"],
                            "compatibilityRationale": authored["compatibilityRationale"],
                        },
                        "hardExclusions": {
                            "globallyBlocked": (
                                capability.get("inventoryState")
                                == "catalog-integrity-blocked"
                                or capability.get("sourceAvailability")
                                == "globally-blocked"
                            ),
                            "creatorProhibited": (
                                capability_id in disabled
                                or capability.get("channelPreference") == "disabled"
                            ),
                            "episodeRestricted": False,
                            "semanticallyIncompatible": agent_exclusions["semanticallyIncompatible"],
                            "assetUnavailable": agent_exclusions["assetUnavailable"],
                            "speakerUnsafe": agent_exclusions["speakerUnsafe"],
                            "runtimeIncompatible": (
                                capability.get("technicalAdmission") == "blocked"
                            ),
                            "contentCapacityFailure": agent_exclusions["contentCapacityFailure"],
                            "timingInvalid": agent_exclusions["timingInvalid"],
                            "repetitionProhibited": False,
                        },
                        "criterionValues": {
                            **authored["criterionValues"],
                            "implementation-maturity": maturity,
                        },
                        "assumptions": authored["assumptions"],
                    }
                )
        meaningful = [
            {
                "id": item["id"],
                "absoluteFrame": (
                    observed_changes[item["sourceVisualChangeRef"]][
                        "absoluteFrame"
                    ]
                    if item["sourceVisualChangeRef"] is not None
                    else _anchor_frame(
                        item["at"], spans, sequence, exclusive=False
                    )
                ),
                "kind": item["kind"],
                "description": item["description"],
                "spokenBeatId": item["spokenBeatId"],
                "sourceVisualChangeRef": item["sourceVisualChangeRef"],
                "verificationKind": (
                    "source-evidence"
                    if item["sourceVisualChangeRef"] is not None
                    else "spoken-beat"
                ),
            }
            for item in decision["editorialDirective"]["meaningfulChanges"]
        ]
        carry_decision = decision["editorialDirective"]["intentionalVisualCarry"]
        carry_evidence = (
            None
            if carry_decision is None
            else carry_spans[carry_decision["carrySpanRef"]]
        )
        carry = (
            None
            if carry_decision is None
            else {
                "carrySpanRef": carry_evidence["id"],
                "sourceEventId": carry_evidence["sourceEventId"],
                "absoluteStartFrame": max(
                    sequence["absoluteStartFrame"],
                    carry_evidence["absoluteStartFrame"],
                ),
                "absoluteEndFrameExclusive": min(
                    sequence["absoluteEndFrameExclusive"],
                    carry_evidence["absoluteEndFrameExclusive"],
                ),
                "kind": carry_decision["kind"],
                "rationale": carry_decision["rationale"],
                "evidenceRefs": carry_evidence["evidenceRefs"],
            }
        )
        semantic_sequences.append(
            {
                **sequence,
                "startWordId": sequence_words[0]["id"],
                "endWordId": sequence_words[-1]["id"],
                "conceptId": decision["conceptId"],
                "seriesId": decision["seriesId"],
                "callbackTo": decision["callbackTo"],
                "propositionId": decision["primaryPropositionId"],
                "semanticBeatKind": decision["semanticBeatKind"],
                "editorialJob": decision["editorialJob"],
                "semanticForm": decision["semanticForm"],
                "presentationRole": decision["presentationRole"],
                "narrativeStateRole": decision["narrativeStateRole"],
                "editorialDirective": {
                    "visualPurpose": decision["editorialDirective"]["visualPurpose"],
                    "sourceStrategy": decision["editorialDirective"]["sourceStrategy"],
                    "spokenBeats": beats,
                    "meaningfulChanges": meaningful,
                    "intentionalVisualCarry": carry,
                    "copyReview": decision["editorialDirective"]["copyReview"],
                },
                "candidateCanvasTopologies": decision["candidateCanvasTopologies"],
                "candidateCapabilityIds": candidate_ids,
                "candidateAssessments": assessments,
                "assetRequirements": decision["assetRequirements"],
                "semanticEvidenceRefs": decision["semanticEvidenceRefs"],
                "unresolvedReasons": decision["unresolvedReasons"],
            }
        )
    chapter_decisions = decisions["chapters"]
    chapters = []
    for position, chapter in enumerate(chapter_decisions):
        owned = [item for item in semantic_sequences if item["chapterId"] == chapter["id"]]
        if not owned:
            raise PlanningDecisionError(
                [
                    {
                        "code": "empty-chapter",
                        "chapterId": chapter["id"],
                        "message": f"Chapter {chapter['id']} has no sequences.",
                    }
                ]
            )
        if chapter["startBoundaryRef"] != sequence_decisions[semantic_sequences.index(owned[0])]["startBoundaryRef"]:
            raise PlanningDecisionError(
                [
                    {
                        "code": "chapter-boundary-mismatch",
                        "chapterId": chapter["id"],
                        "message": (
                            f"Chapter {chapter['id']} does not start with its first sequence."
                        ),
                    }
                ]
            )
        chapter_boundary = boundaries[chapter["startBoundaryRef"]]
        if (
            chapter_boundary["relationshipToPrevious"]
            not in _CHAPTER_BOUNDARY_RELATIONSHIPS
        ):
            raise PlanningDecisionError(
                [
                    {
                        "code": "unsupported-chapter-boundary",
                        "chapterId": chapter["id"],
                        "retentionScope": "none",
                        "message": (
                            "A chapter must begin at an application-issued completed "
                            "editorial-section boundary."
                        ),
                    }
                ]
            )
        chapters.append(
            {
                "id": chapter["id"],
                "editorialSectionId": chapter["editorialSectionId"],
                "title": chapter["title"],
                "completionRationale": chapter["completionRationale"],
                "absoluteStartFrame": owned[0]["absoluteStartFrame"],
                "absoluteEndFrameExclusive": owned[-1]["absoluteEndFrameExclusive"],
            }
        )
    transitions = []
    for left, right, decision in zip(
        semantic_sequences,
        semantic_sequences[1:],
        sequence_decisions,
    ):
        intent = decision["transitionToNextIntent"]
        if not intent:
            raise PlanningDecisionError(
                [{"code": "missing-transition-intent", "sequenceId": left["id"], "message": "Every nonfinal sequence needs a transition intent."}]
            )
        transitions.append(
            {
                "id": f"transition:{left['id']}:{right['id']}",
                "fromSequenceId": left["id"],
                "toSequenceId": right["id"],
                "semanticIntent": intent,
            }
        )
    if sequence_decisions[-1]["transitionToNextIntent"] is not None:
        raise PlanningDecisionError(
            [
                {
                    "code": "final-transition-intent",
                    "sequenceId": sequence_decisions[-1]["id"],
                    "message": "The final sequence cannot transition to another sequence.",
                }
            ]
        )
    return {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "episodeId": current["episodeId"],
        "revision": 1,
        "workflowLockHash": workflow_lock_hash,
        "lockedCutSha256": transcript_receipt["lockedCutSha256"],
        "transcriptSha256": transcript_receipt["transcriptSha256"],
        "wordTimingSha256": transcript_receipt["wordTimingSha256"],
        "fps": fps,
        "totalFrames": total_frames,
        "sequences": semantic_sequences,
        "transitionIntents": transitions,
        "chapters": chapters,
        "unresolvedReasons": decisions["unresolvedReasons"],
    }


def semantic_plan_materialization_receipt(
    *,
    job_id: str,
    decisions: dict,
    span_receipts: list[dict],
    semantic_manifest: dict,
) -> dict:
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "jobId": job_id,
        "decisionHash": canonical_hash(decisions),
        "spanReceiptHashes": sorted(item["receiptHash"] for item in span_receipts),
        "semanticManifestHash": canonical_hash(semantic_manifest),
        "createdAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    validate_artifact("semantic-plan-materialization-receipt", receipt)
    return receipt
