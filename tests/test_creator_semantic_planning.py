from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.core.creator_production import canonical_hash, validate_artifact
from app.core.creator_semantic_planning import (
    PlanningDecisionError,
    _plan_structure_and_evidence_errors,
    boundary_choices,
    copy_evidence_choices,
    create_spoken_span_receipt,
    materialize_semantic_manifest,
    resolve_spoken_span_candidates,
    specialize_editorial_plan_schema,
    validate_analysis_against_transcript,
)


SHA = "a" * 64


def _command_copy_evidence() -> dict:
    return {
        "kind": "verbatim-command",
        "observedText": "/plan",
        "propositionId": "prop-1",
        "sourceEventId": None,
        "absoluteFrame": None,
        "observationMethod": "transcript-verification",
        "evidenceRefs": ["evidence-1"],
        "confidence": 1,
    }


def _command_copy_evidence_ref() -> str:
    return copy_evidence_choices(
        {"copyEvidence": [_command_copy_evidence()]}
    )[0]["copyEvidenceRef"]


def _transcript() -> dict:
    texts = ["plan", "this", "plan", "this"]
    return {
        "project": {
            "fps": 30,
            "words": [
                {
                    "id": f"w{index + 1}",
                    "text": text,
                    "start": index / 3,
                    "end": (index + 1) / 3,
                    "start_frame": index * 10,
                    "end_frame": index * 10 + 9,
                }
                for index, text in enumerate(texts)
            ],
        }
    }


def _analysis() -> dict:
    return {
        "propositions": [
            {
                "id": "prop-1",
                "startWordId": "w1",
                "endWordId": "w4",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 40,
                "text": "plan this plan this",
            }
        ],
        "semanticUnits": [
            {
                "id": "unit-1",
                "startPropositionId": "prop-1",
                "endPropositionId": "prop-1",
                "summary": "Plan this.",
                "relationshipToPrevious": "runtime-start",
                "sourceEventRefs": [],
                "evidenceRefs": ["evidence-1"],
                "unresolvedReasons": [],
            }
        ],
        "sourceEvents": [],
        "observedVisualChanges": [],
        "copyEvidence": [_command_copy_evidence()],
        "intentionalCarrySpans": [],
    }


def _span_candidates() -> list[dict]:
    return resolve_spoken_span_candidates(
        job_id="job-1",
        task_id="task-1",
        episode_id="episode-1",
        transcript_sha256=SHA,
        word_timing_sha256=SHA,
        analysis_sha256=SHA,
        analysis=_analysis(),
        transcript_document=_transcript(),
        proposition_id="prop-1",
        exact_phrase="plan this",
    )


def _materialize_fixture(
    *,
    analysis: dict,
    transcript: dict,
    decisions: dict,
    span_receipts: list[dict],
) -> dict:
    return materialize_semantic_manifest(
        decisions=decisions,
        current={"episodeId": "episode-1"},
        workflow_lock_hash=SHA,
        transcript_receipt={
            "lockedCutSha256": SHA,
            "transcriptSha256": SHA,
            "wordTimingSha256": SHA,
        },
        transcript_document=transcript,
        analysis=analysis,
        analysis_sha256=SHA,
        catalog={"capabilities": []},
        channel_profile={"capabilities": {"disabled": []}},
        total_frames=40,
        fps={"numerator": 30, "denominator": 1},
        span_receipts=span_receipts,
        job_id="job-1",
    )


def test_analysis_must_use_locked_inclusive_end_as_exclusive_plus_one() -> None:
    broken = copy.deepcopy(_analysis())
    broken["propositions"][0]["absoluteEndFrameExclusive"] = 39

    with pytest.raises(PlanningDecisionError) as error:
        validate_analysis_against_transcript(broken, _transcript())

    assert error.value.errors[0]["code"] == "proposition-end-frame-mismatch"
    assert error.value.errors[0]["expectedFrame"] == 40


def test_repeated_phrase_resolution_is_scoped_and_requires_candidate_choice() -> None:
    candidates = _span_candidates()

    assert len(candidates) == 2
    assert candidates[0]["sourceWordIds"] == ["w1", "w2"]
    assert candidates[1]["sourceWordIds"] == ["w3", "w4"]
    assert candidates[0]["candidateRef"] != candidates[1]["candidateRef"]


def test_spoken_span_resolution_ignores_edge_punctuation() -> None:
    transcript = _transcript()
    transcript["project"]["words"][1]["text"] = "this,"
    analysis = _analysis()
    analysis["propositions"][0]["text"] = "plan this, plan this"

    candidates = resolve_spoken_span_candidates(
        job_id="job-1",
        task_id="task-1",
        episode_id="episode-1",
        transcript_sha256=SHA,
        word_timing_sha256=SHA,
        analysis_sha256=SHA,
        analysis=analysis,
        transcript_document=transcript,
        proposition_id="prop-1",
        exact_phrase="plan this",
    )

    assert len(candidates) == 2
    assert candidates[0]["spokenPhrase"] == "plan this,"
    assert candidates[0]["sourceWordIds"] == ["w1", "w2"]


def test_spoken_span_resolution_preserves_internal_command_punctuation() -> None:
    transcript = _transcript()
    transcript["project"]["words"][0]["text"] = "/plan"
    analysis = _analysis()
    analysis["propositions"][0].update(
        {
            "endWordId": "w1",
            "absoluteEndFrameExclusive": 10,
            "text": "/plan",
        }
    )

    with pytest.raises(PlanningDecisionError) as error:
        resolve_spoken_span_candidates(
            job_id="job-1",
            task_id="task-1",
            episode_id="episode-1",
            transcript_sha256=SHA,
            word_timing_sha256=SHA,
            analysis_sha256=SHA,
            analysis=analysis,
            transcript_document=transcript,
            proposition_id="prop-1",
            exact_phrase="plan",
        )

    assert error.value.errors[0]["code"] == "spoken-phrase-not-found"


def test_spoken_span_receipt_owns_word_ids_and_frames() -> None:
    receipt = create_spoken_span_receipt(_span_candidates()[1])

    validate_artifact("spoken-span-receipt", receipt)
    assert receipt["sourceWordIds"] == ["w3", "w4"]
    assert receipt["startFrame"] == 20
    assert receipt["endFrameExclusive"] == 40
    assert receipt["receiptHash"] == canonical_hash(
        {key: value for key, value in receipt.items() if key != "receiptHash"}
    )


def test_editorial_decisions_schema_rejects_agent_authored_frames() -> None:
    decisions = _decisions(span_ref="spoken-span:any", boundary_ref="boundary:any")
    decisions["sequences"][0]["absoluteStartFrame"] = 0

    with pytest.raises(ValueError, match="Additional properties are not allowed"):
        validate_artifact("editorial-plan-decisions", decisions)


def test_plan_schema_accepts_only_application_issued_copy_evidence_refs() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "creator-production"
        / "schemas"
        / "editorial-plan-decisions.schema.json"
    )
    issued_ref = _command_copy_evidence_ref()
    schema = specialize_editorial_plan_schema(
        json.loads(schema_path.read_text(encoding="utf-8")),
        issued_copy_evidence_refs=[issued_ref],
    )
    decisions = _decisions(
        span_ref="spoken-span:any",
        boundary_ref="boundary:any",
    )
    decisions["sequences"][0]["editorialDirective"]["spokenBeats"][0][
        "copyEvidenceRef"
    ] = "copy-evidence:" + ("b" * 64)

    errors = list(Draft202012Validator(schema).iter_errors(decisions))

    assert errors
    assert any(
        list(error.absolute_path)[-1] == "copyEvidenceRef"
        for error in errors
    )


def test_copy_evidence_and_cadence_errors_are_returned_together() -> None:
    span_ref = "spoken-span:fixture"
    anchor = {"spanRef": span_ref, "edge": "start"}
    beats = [
        {
            "id": f"beat-{index}",
            "spanRef": span_ref,
            "onScreenText": label,
            "copyMode": "exact-ui-label",
            "editorialPurpose": "Show the exact visible UI label.",
            "copyEvidenceRef": invalid_ref,
            "revealAt": anchor,
            "fullyVisibleAt": anchor,
            "exitAt": {"spanRef": span_ref, "edge": "end"},
            "behavior": "single",
        }
        for index, (label, invalid_ref) in enumerate(
            (
                ("Get It Now", "source-install"),
                ("Open in PowerPoint", "source-install"),
                ("Grok", "source-example-02"),
            ),
            start=1,
        )
    ]
    decisions = {
        "chapters": [{"id": "chapter-1"}],
        "sequences": [
            {
                "id": "sequence-1",
                "chapterId": "chapter-1",
                "boundaryCauseRef": "cause-1",
                "presentationRole": "hybrid",
                "editorialDirective": {
                    "sourceStrategy": "screen-share-demo",
                    "spokenBeats": beats,
                    "meaningfulChanges": [
                        {
                            "id": f"change-{index}",
                            "at": anchor,
                            "kind": "ui-callout",
                            "description": "Call out the visible label.",
                            "spokenBeatId": f"beat-{index}",
                            "sourceVisualChangeRef": None,
                        }
                        for index in range(1, 4)
                    ],
                    "intentionalVisualCarry": None,
                },
            }
        ],
    }
    analysis = {
        "observedVisualChanges": [],
        "intentionalCarrySpans": [],
        "copyEvidence": [
            {
                "kind": "exact-ui-label",
                "observedText": label,
                "propositionId": "prop-1",
                "sourceEventId": f"source-{index}",
                "absoluteFrame": index,
                "observationMethod": "frame-inspection",
                "evidenceRefs": [f"locked-cut:frame:{index}"],
                "confidence": 1,
            }
            for index, label in enumerate(
                ("Get It Now", "Open in PowerPoint", "Grok"),
                start=1,
            )
        ],
    }

    errors = _plan_structure_and_evidence_errors(
        decisions=decisions,
        starts=[{"boundaryCauseRef": "cause-1", "sourceEventRefs": []}],
        sequence_skeletons=[
            {
                "id": "sequence-1",
                "chapterId": "chapter-1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 400,
            }
        ],
        spans={
            span_ref: {
                "propositionId": "prop-1",
                "startFrame": 0,
                "endFrameExclusive": 30,
            }
        },
        analysis=analysis,
        channel_profile={
            "id": "vcg",
            "version": 2,
            "pacing": {"maximumMeaningfulChangeGapSec": 5},
        },
        total_frames=400,
        fps={"numerator": 30, "denominator": 1},
    )

    copy_errors = [
        item
        for item in errors
        if item["code"] == "missing-or-unknown-copy-evidence"
    ]
    assert [item["spokenBeatId"] for item in copy_errors] == [
        "beat-1",
        "beat-2",
        "beat-3",
    ]
    assert all(item["validChoices"] for item in copy_errors)
    assert "unverified-meaningful-change-cadence" in {
        item["code"] for item in errors
    }


def test_exact_copy_text_must_match_issued_evidence() -> None:
    analysis = _analysis()
    issued_ref = _command_copy_evidence_ref()
    decisions = _decisions(
        span_ref="spoken-span:fixture",
        boundary_ref="boundary:any",
    )
    beat = decisions["sequences"][0]["editorialDirective"]["spokenBeats"][0]
    beat["onScreenText"] = "/Plan"
    beat["copyEvidenceRef"] = issued_ref

    errors = _plan_structure_and_evidence_errors(
        decisions=decisions,
        starts=[
            {
                "boundaryCauseRef": "boundary-cause:any",
                "sourceEventRefs": [],
            }
        ],
        sequence_skeletons=[
            {
                "id": "sequence-1",
                "chapterId": "chapter-1",
                "absoluteStartFrame": 0,
                "absoluteEndFrameExclusive": 40,
            }
        ],
        spans={
            "spoken-span:fixture": {
                "propositionId": "prop-1",
                "startFrame": 0,
                "endFrameExclusive": 20,
            }
        },
        analysis=analysis,
        channel_profile={},
        total_frames=40,
        fps={"numerator": 30, "denominator": 1},
    )

    mismatch = next(
        item for item in errors if item["code"] == "copy-evidence-text-mismatch"
    )
    assert mismatch["expectedText"] == "/plan"
    assert mismatch["actualText"] == "/Plan"


def test_application_materializes_frames_and_word_ids_from_opaque_refs() -> None:
    analysis = _analysis()
    transcript = _transcript()
    choices = boundary_choices(
        job_id="job-1",
        analysis_sha256=SHA,
        analysis=analysis,
        transcript_document=transcript,
    )
    span = create_spoken_span_receipt(_span_candidates()[0])
    decisions = _decisions(
        span_ref=span["id"],
        boundary_ref=choices[0]["boundaryRef"],
        boundary_cause_ref=choices[0]["boundaryCauseRef"],
    )
    semantic = materialize_semantic_manifest(
        decisions=decisions,
        current={"episodeId": "episode-1"},
        workflow_lock_hash=SHA,
        transcript_receipt={
            "lockedCutSha256": SHA,
            "transcriptSha256": SHA,
            "wordTimingSha256": SHA,
        },
        transcript_document=transcript,
        analysis=analysis,
        analysis_sha256=SHA,
        catalog={"capabilities": []},
        channel_profile={"capabilities": {"disabled": []}},
        total_frames=40,
        fps={"numerator": 30, "denominator": 1},
        span_receipts=[span],
        job_id="job-1",
    )

    sequence = semantic["sequences"][0]
    beat = sequence["editorialDirective"]["spokenBeats"][0]
    assert (sequence["absoluteStartFrame"], sequence["absoluteEndFrameExclusive"]) == (
        0,
        40,
    )
    assert (sequence["startWordId"], sequence["endWordId"]) == ("w1", "w4")
    assert (beat["revealFrame"], beat["fullyVisibleFrame"], beat["exitFrameExclusive"]) == (
        0,
        0,
        20,
    )
    assert beat["behavior"] == "single"


def test_continuation_propositions_are_not_issued_as_sequence_boundaries() -> None:
    analysis = _analysis()
    analysis["propositions"] = [
        {
            "id": "prop-1",
            "startWordId": "w1",
            "endWordId": "w2",
            "absoluteStartFrame": 0,
            "absoluteEndFrameExclusive": 20,
            "text": "plan this",
        },
        {
            "id": "prop-2",
            "startWordId": "w3",
            "endWordId": "w4",
            "absoluteStartFrame": 20,
            "absoluteEndFrameExclusive": 40,
            "text": "plan this",
        },
    ]
    analysis["semanticUnits"] = [
        {
            **analysis["semanticUnits"][0],
            "endPropositionId": "prop-1",
        },
        {
            "id": "unit-2",
            "startPropositionId": "prop-2",
            "endPropositionId": "prop-2",
            "summary": "Continue the same idea.",
            "relationshipToPrevious": "continuation",
            "sourceEventRefs": [],
            "evidenceRefs": ["evidence-2"],
            "unresolvedReasons": [],
        },
    ]

    choices = boundary_choices(
        job_id="job-1",
        analysis_sha256=SHA,
        analysis=analysis,
        transcript_document=_transcript(),
    )

    assert [item["semanticUnitId"] for item in choices] == ["unit-1"]


def test_source_change_shortcut_requires_exact_observed_evidence() -> None:
    analysis = _analysis()
    choices = boundary_choices(
        job_id="job-1",
        analysis_sha256=SHA,
        analysis=analysis,
        transcript_document=_transcript(),
    )
    decisions = _decisions(
        span_ref="spoken-span:unused",
        boundary_ref=choices[0]["boundaryRef"],
        boundary_cause_ref=choices[0]["boundaryCauseRef"],
    )
    sequence = decisions["sequences"][0]
    sequence["presentationRole"] = "source-led"
    sequence["editorialDirective"]["sourceStrategy"] = "protected-performance"
    sequence["editorialDirective"]["spokenBeats"] = []
    sequence["editorialDirective"]["meaningfulChanges"] = [
        {
            "id": "change-source",
            "at": None,
            "kind": "performance-beat",
            "description": "Claimed performance beat.",
            "spokenBeatId": None,
            "sourceVisualChangeRef": "observed:missing",
        }
    ]

    with pytest.raises(PlanningDecisionError) as error:
        _materialize_fixture(
            analysis=analysis,
            transcript=_transcript(),
            decisions=decisions,
            span_receipts=[],
        )

    assert "unverified-source-change" in {
        item["code"] for item in error.value.errors
    }
    assert all(
        item.get("retentionScope") == "none" for item in error.value.errors
    )


def test_exact_observed_source_change_can_support_source_led_sequence() -> None:
    analysis = _analysis()
    analysis["sourceEvents"] = [
        {
            "id": "source-1",
            "absoluteStartFrame": 0,
            "absoluteEndFrameExclusive": 40,
        }
    ]
    analysis["semanticUnits"][0]["sourceEventRefs"] = ["source-1"]
    analysis["observedVisualChanges"] = [
        {
            "id": "observed-1",
            "absoluteFrame": 0,
            "kind": "gesture",
            "sourceEventId": "source-1",
            "description": "A visible explanatory gesture.",
            "evidenceRefs": ["frame:0"],
            "confidence": 1,
        }
    ]
    choices = boundary_choices(
        job_id="job-1",
        analysis_sha256=SHA,
        analysis=analysis,
        transcript_document=_transcript(),
    )
    decisions = _decisions(
        span_ref="spoken-span:unused",
        boundary_ref=choices[0]["boundaryRef"],
        boundary_cause_ref=choices[0]["boundaryCauseRef"],
    )
    sequence = decisions["sequences"][0]
    sequence["presentationRole"] = "source-led"
    sequence["editorialDirective"]["sourceStrategy"] = "protected-performance"
    sequence["editorialDirective"]["spokenBeats"] = []
    sequence["editorialDirective"]["meaningfulChanges"] = [
        {
            "id": "change-source",
            "at": None,
            "kind": "performance-beat",
            "description": "Use the observed explanatory gesture.",
            "spokenBeatId": None,
            "sourceVisualChangeRef": "observed-1",
        }
    ]

    semantic = _materialize_fixture(
        analysis=analysis,
        transcript=_transcript(),
        decisions=decisions,
        span_receipts=[],
    )

    change = semantic["sequences"][0]["editorialDirective"][
        "meaningfulChanges"
    ][0]
    assert change["verificationKind"] == "source-evidence"
    assert change["sourceVisualChangeRef"] == "observed-1"


def test_adjacent_source_led_sequences_without_boundary_change_must_merge() -> None:
    analysis = _analysis()
    analysis["propositions"] = [
        {
            "id": "prop-1",
            "startWordId": "w1",
            "endWordId": "w2",
            "absoluteStartFrame": 0,
            "absoluteEndFrameExclusive": 20,
            "text": "plan this",
        },
        {
            "id": "prop-2",
            "startWordId": "w3",
            "endWordId": "w4",
            "absoluteStartFrame": 20,
            "absoluteEndFrameExclusive": 40,
            "text": "plan this",
        },
    ]
    analysis["sourceEvents"] = [
        {
            "id": "source-1",
            "absoluteStartFrame": 0,
            "absoluteEndFrameExclusive": 40,
        }
    ]
    analysis["semanticUnits"] = [
        {
            **analysis["semanticUnits"][0],
            "endPropositionId": "prop-1",
            "sourceEventRefs": ["source-1"],
        },
        {
            "id": "unit-2",
            "startPropositionId": "prop-2",
            "endPropositionId": "prop-2",
            "summary": "A second claimed idea.",
            "relationshipToPrevious": "new-idea",
            "sourceEventRefs": ["source-1"],
            "evidenceRefs": ["evidence-2"],
            "unresolvedReasons": [],
        },
    ]
    analysis["observedVisualChanges"] = [
        {
            "id": "observed-1",
            "absoluteFrame": 0,
            "kind": "gesture",
            "sourceEventId": "source-1",
            "description": "Opening gesture.",
            "evidenceRefs": ["frame:0"],
            "confidence": 1,
        },
        {
            "id": "observed-2",
            "absoluteFrame": 30,
            "kind": "gesture",
            "sourceEventId": "source-1",
            "description": "Later gesture.",
            "evidenceRefs": ["frame:30"],
            "confidence": 1,
        },
    ]
    choices = boundary_choices(
        job_id="job-1",
        analysis_sha256=SHA,
        analysis=analysis,
        transcript_document=_transcript(),
    )
    decisions = _decisions(
        span_ref="spoken-span:unused",
        boundary_ref=choices[0]["boundaryRef"],
        boundary_cause_ref=choices[0]["boundaryCauseRef"],
    )
    first = decisions["sequences"][0]
    first["presentationRole"] = "source-led"
    first["editorialDirective"]["sourceStrategy"] = "protected-performance"
    first["editorialDirective"]["spokenBeats"] = []
    first["editorialDirective"]["meaningfulChanges"] = [
        {
            "id": "change-1",
            "at": None,
            "kind": "performance-beat",
            "description": "Opening gesture.",
            "spokenBeatId": None,
            "sourceVisualChangeRef": "observed-1",
        }
    ]
    first["transitionToNextIntent"] = "Continue the same source state."
    second = copy.deepcopy(first)
    second.update(
        {
            "id": "sequence-2",
            "startBoundaryRef": choices[1]["boundaryRef"],
            "boundaryCauseRef": choices[1]["boundaryCauseRef"],
            "primaryPropositionId": "prop-2",
            "conceptId": "concept-2",
            "transitionToNextIntent": None,
        }
    )
    second["editorialDirective"]["meaningfulChanges"] = [
        {
            "id": "change-2",
            "at": None,
            "kind": "performance-beat",
            "description": "Later gesture.",
            "spokenBeatId": None,
            "sourceVisualChangeRef": "observed-2",
        }
    ]
    decisions["sequences"] = [first, second]

    with pytest.raises(PlanningDecisionError) as error:
        _materialize_fixture(
            analysis=analysis,
            transcript=_transcript(),
            decisions=decisions,
            span_receipts=[],
        )

    assert "mergeable-adjacent-sequences" in {
        item["code"] for item in error.value.errors
    }


def _bulk_source_led_structure(*, count: int, evidenced: bool) -> tuple:
    starts = []
    skeletons = []
    sequences = []
    observed = []
    for index in range(count):
        change_ref = f"observed-{index}" if evidenced else f"missing-{index}"
        starts.append(
            {
                "boundaryCauseRef": f"cause-{index}",
                "sourceEventRefs": ["source-1"],
            }
        )
        skeletons.append(
            {
                "id": f"sequence-{index}",
                "chapterId": "chapter-1",
                "absoluteStartFrame": index,
                "absoluteEndFrameExclusive": index + 1,
            }
        )
        sequences.append(
            {
                "id": f"sequence-{index}",
                "chapterId": "chapter-1",
                "boundaryCauseRef": f"cause-{index}",
                "presentationRole": "source-led",
                "editorialDirective": {
                    "sourceStrategy": "protected-performance",
                    "spokenBeats": [],
                    "meaningfulChanges": [
                        {
                            "id": f"change-{index}",
                            "at": None,
                            "kind": "performance-beat",
                            "description": "Use a distinct observed performance beat.",
                            "spokenBeatId": None,
                            "sourceVisualChangeRef": change_ref,
                        }
                    ],
                    "intentionalVisualCarry": None,
                },
            }
        )
        if evidenced:
            observed.append(
                {
                    "id": change_ref,
                    "absoluteFrame": index,
                    "kind": "gesture",
                }
            )
    return (
        {
            "sequences": sequences,
            "chapters": [{"id": "chapter-1"}],
        },
        starts,
        skeletons,
        {
            "observedVisualChanges": observed,
            "intentionalCarrySpans": [],
        },
    )


def test_proposition_per_sequence_shortcut_is_rejected_by_evidence_not_count() -> None:
    decisions, starts, skeletons, analysis = _bulk_source_led_structure(
        count=204,
        evidenced=False,
    )

    errors = _plan_structure_and_evidence_errors(
        decisions=decisions,
        starts=starts,
        sequence_skeletons=skeletons,
        spans={},
        analysis=analysis,
        channel_profile={},
        total_frames=204,
        fps={"numerator": 30, "denominator": 1},
    )

    assert "unverified-source-change" in {item["code"] for item in errors}
    assert all(item.get("retentionScope") == "none" for item in errors)


def test_many_sequences_are_allowed_with_distinct_boundary_change_evidence() -> None:
    decisions, starts, skeletons, analysis = _bulk_source_led_structure(
        count=204,
        evidenced=True,
    )

    errors = _plan_structure_and_evidence_errors(
        decisions=decisions,
        starts=starts,
        sequence_skeletons=skeletons,
        spans={},
        analysis=analysis,
        channel_profile={},
        total_frames=204,
        fps={"numerator": 30, "denominator": 1},
    )

    assert errors == []


def _continuous_carry_structure() -> tuple[dict, list[dict], list[dict], dict]:
    carry_ref = "carry-screen-demo"
    source_ref = "source-screen-demo"
    sequences = []
    starts = []
    skeletons = []
    for index, (start_frame, end_frame) in enumerate(((0, 200), (200, 400)), start=1):
        sequences.append(
            {
                "id": f"sequence-{index}",
                "chapterId": "chapter-1",
                "boundaryCauseRef": f"cause-{index}",
                "presentationRole": "source-led",
                "editorialDirective": {
                    "sourceStrategy": "screen-share-demo",
                    "spokenBeats": [],
                    "meaningfulChanges": [],
                    "intentionalVisualCarry": {
                        "carrySpanRef": carry_ref,
                        "kind": "demonstration",
                        "rationale": "The useful software demonstration remains visible.",
                    },
                },
            }
        )
        starts.append(
            {
                "boundaryCauseRef": f"cause-{index}",
                "sourceEventRefs": [source_ref],
            }
        )
        skeletons.append(
            {
                "id": f"sequence-{index}",
                "chapterId": "chapter-1",
                "absoluteStartFrame": start_frame,
                "absoluteEndFrameExclusive": end_frame,
            }
        )
    return (
        {
            "sequences": sequences,
            "chapters": [{"id": "chapter-1"}],
        },
        starts,
        skeletons,
        {
            "observedVisualChanges": [],
            "copyEvidence": [],
            "intentionalCarrySpans": [
                {
                    "id": carry_ref,
                    "sourceEventId": source_ref,
                    "absoluteStartFrame": 0,
                    "absoluteEndFrameExclusive": 400,
                    "kind": "demonstration",
                    "rationale": "Continuous useful screen demonstration.",
                    "evidenceRefs": ["locked-cut:frames:0-399"],
                    "confidence": 1,
                }
            ],
        },
    )


def test_continuous_carry_is_scoped_across_independent_semantic_sequences() -> None:
    decisions, starts, skeletons, analysis = _continuous_carry_structure()

    errors = _plan_structure_and_evidence_errors(
        decisions=decisions,
        starts=starts,
        sequence_skeletons=skeletons,
        spans={},
        analysis=analysis,
        channel_profile={
            "id": "vcg",
            "version": 2,
            "pacing": {"maximumMeaningfulChangeGapSec": 5},
        },
        total_frames=400,
        fps={"numerator": 30, "denominator": 1},
    )

    assert errors == []


def test_continuous_carry_cannot_cover_an_unrelated_source_event() -> None:
    decisions, starts, skeletons, analysis = _continuous_carry_structure()
    starts[1]["sourceEventRefs"] = ["source-unrelated"]

    errors = _plan_structure_and_evidence_errors(
        decisions=decisions,
        starts=starts,
        sequence_skeletons=skeletons,
        spans={},
        analysis=analysis,
        channel_profile={},
        total_frames=400,
        fps={"numerator": 30, "denominator": 1},
    )

    assert "carry-source-event-mismatch" in {
        item["code"] for item in errors
    }


def _decisions(
    *,
    span_ref: str,
    boundary_ref: str,
    boundary_cause_ref: str = "boundary-cause:any",
) -> dict:
    anchor_start = {"spanRef": span_ref, "edge": "start"}
    return {
        "schemaVersion": 1,
        "jobId": "job-1",
        "episodeId": "episode-1",
        "revision": 1,
        "chapters": [
            {
                "id": "chapter-1",
                "editorialSectionId": "section-1",
                "title": "Plan this",
                "completionRationale": "One complete editorial idea.",
                "startBoundaryRef": boundary_ref,
            }
        ],
        "sequences": [
            {
                "id": "sequence-1",
                "chapterId": "chapter-1",
                "startBoundaryRef": boundary_ref,
                "boundaryCauseRef": boundary_cause_ref,
                "primaryPropositionId": "prop-1",
                "conceptId": "concept-1",
                "seriesId": None,
                "callbackTo": None,
                "semanticBeatKind": "instruction",
                "editorialJob": "emphasize the command",
                "semanticForm": "source demonstration",
                "presentationRole": "hybrid",
                "narrativeStateRole": "establish",
                "editorialDirective": {
                    "visualPurpose": "Emphasize the spoken command.",
                    "sourceStrategy": "screen-share-demo",
                    "spokenBeats": [
                        {
                            "id": "beat-1",
                            "spanRef": span_ref,
                            "onScreenText": "/plan",
                            "copyMode": "verbatim-command",
                            "editorialPurpose": "Identify the command.",
                            "copyEvidenceRef": _command_copy_evidence_ref(),
                            "revealAt": anchor_start,
                            "fullyVisibleAt": anchor_start,
                            "exitAt": {"spanRef": span_ref, "edge": "end"},
                            "behavior": "single",
                        }
                    ],
                    "meaningfulChanges": [
                        {
                            "id": "change-1",
                            "at": anchor_start,
                            "kind": "ui-callout",
                            "description": "Call out the command.",
                            "spokenBeatId": "beat-1",
                            "sourceVisualChangeRef": None,
                        }
                    ],
                    "intentionalVisualCarry": None,
                    "copyReview": {
                        "spellingPassed": True,
                        "punctuationPassed": True,
                        "grammarPassed": True,
                    },
                },
                "candidateCanvasTopologies": ["source-overlay"],
                "capabilityAssessments": [],
                "assetRequirements": [],
                "semanticEvidenceRefs": ["evidence-1"],
                "unresolvedReasons": [],
                "transitionToNextIntent": None,
            }
        ],
        "unresolvedReasons": [],
    }
