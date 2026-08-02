from __future__ import annotations

import json
from collections.abc import Iterable

from app.core.creator_capabilities import direct_capability_source_resource
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    canonical_hash,
    utc_now,
    validate_artifact,
)
from app.core.creator_semantic_planning import copy_evidence_choices


HARD_EXCLUSION_KEYS = (
    "globallyBlocked",
    "creatorProhibited",
    "episodeRestricted",
    "semanticallyIncompatible",
    "assetUnavailable",
    "speakerUnsafe",
    "runtimeIncompatible",
    "contentCapacityFailure",
    "timingInvalid",
    "repetitionProhibited",
)


def validate_analysis_ledger(ledger: dict) -> None:
    validate_artifact("analysis-ledger", ledger)
    cursor = 0
    for span in ledger["coverageSpans"]:
        if span["absoluteStartFrame"] != cursor:
            raise ValueError("Analysis coverage must span the complete runtime without gaps.")
        if span["absoluteEndFrameExclusive"] <= span["absoluteStartFrame"]:
            raise ValueError("Analysis coverage spans must be nonempty.")
        cursor = span["absoluteEndFrameExclusive"]
    if cursor != ledger["totalFrames"]:
        raise ValueError("Analysis coverage does not reach the end of the locked runtime.")
    forbidden = {
        "presentationRole",
        "narrativeStateRole",
        "selectedCapabilityId",
        "selectedCanvasTopology",
    }
    for proposition in ledger["propositions"]:
        leaked = forbidden.intersection(proposition)
        if leaked:
            raise ValueError(
                "Channel-neutral analysis may not make presentation decisions: "
                + ", ".join(sorted(leaked))
            )
    proposition_ids = [item["id"] for item in ledger["propositions"]]
    if len(proposition_ids) != len(set(proposition_ids)):
        raise ValueError("Analysis proposition IDs must be unique.")
    proposition_positions = {
        proposition_id: position
        for position, proposition_id in enumerate(proposition_ids)
    }
    semantic_cursor = 0
    semantic_unit_ids: set[str] = set()
    for position, unit in enumerate(ledger["semanticUnits"]):
        if unit["id"] in semantic_unit_ids:
            raise ValueError("Analysis semantic-unit IDs must be unique.")
        semantic_unit_ids.add(unit["id"])
        start = proposition_positions.get(unit["startPropositionId"])
        end = proposition_positions.get(unit["endPropositionId"])
        if start is None or end is None:
            raise ValueError(
                f"Semantic unit {unit['id']} references an unknown proposition."
            )
        if start != semantic_cursor or end < start:
            raise ValueError(
                "Analysis semantic units must cover propositions once, contiguously, "
                "and in transcript order."
            )
        if position == 0 and unit["relationshipToPrevious"] != "runtime-start":
            raise ValueError("The first semantic unit must be the runtime start.")
        if position > 0 and unit["relationshipToPrevious"] == "runtime-start":
            raise ValueError("Only the first semantic unit may be the runtime start.")
        semantic_cursor = end + 1
    if semantic_cursor != len(proposition_ids):
        raise ValueError(
            "Analysis semantic units do not cover every proposition."
        )

    source_events = {item["id"]: item for item in ledger["sourceEvents"]}
    if len(source_events) != len(ledger["sourceEvents"]):
        raise ValueError("Analysis source-event IDs must be unique.")
    for unit in ledger["semanticUnits"]:
        unknown = set(unit["sourceEventRefs"]) - set(source_events)
        if unknown:
            raise ValueError(
                f"Semantic unit {unit['id']} references unknown source events: "
                + ", ".join(sorted(unknown))
            )
    propositions_by_id = {
        item["id"]: item for item in ledger["propositions"]
    }
    proposition_source_events: dict[str, set[str]] = {}
    for unit in ledger["semanticUnits"]:
        start = proposition_positions[unit["startPropositionId"]]
        end = proposition_positions[unit["endPropositionId"]]
        for proposition_id in proposition_ids[start : end + 1]:
            proposition_source_events[proposition_id] = set(
                unit["sourceEventRefs"]
            )
    issued_copy_refs: set[str] = set()
    for evidence in copy_evidence_choices(ledger):
        evidence_ref = evidence["copyEvidenceRef"]
        if evidence_ref in issued_copy_refs:
            raise ValueError("Analysis copy-evidence observations must be unique.")
        issued_copy_refs.add(evidence_ref)
        proposition = propositions_by_id.get(evidence["propositionId"])
        if proposition is None:
            raise ValueError(
                "Analysis copy evidence references an unknown proposition."
            )
        if evidence["kind"] == "exact-ui-label":
            source_event = source_events.get(evidence["sourceEventId"])
            if source_event is None:
                raise ValueError(
                    "Exact UI-label evidence references an unknown source event."
                )
            if evidence["sourceEventId"] not in proposition_source_events.get(
                evidence["propositionId"], set()
            ):
                raise ValueError(
                    "Exact UI-label evidence must use a source event attached to "
                    "its transcript proposition."
                )
            if not (
                source_event["absoluteStartFrame"]
                <= evidence["absoluteFrame"]
                < source_event["absoluteEndFrameExclusive"]
            ):
                raise ValueError(
                    "Exact UI-label evidence must fall inside its source event."
                )
            exact_frame_ref = f"locked-cut:frame:{evidence['absoluteFrame']}"
            if exact_frame_ref not in evidence["evidenceRefs"]:
                raise ValueError(
                    "Exact UI-label evidence requires its exact locked frame "
                    "reference; broad scene evidence is insufficient."
                )
        else:
            if evidence["observedText"] not in proposition["text"]:
                raise ValueError(
                    "Verbatim-command evidence must exactly match text in its "
                    "transcript proposition."
                )
            if not set(evidence["evidenceRefs"]).intersection(
                proposition["evidenceRefs"]
            ):
                raise ValueError(
                    "Verbatim-command evidence must cite its proposition's "
                    "transcript evidence."
                )
    observed_ids: set[str] = set()
    for change in ledger["observedVisualChanges"]:
        if change["id"] in observed_ids:
            raise ValueError("Observed visual-change IDs must be unique.")
        observed_ids.add(change["id"])
        source_event = source_events.get(change["sourceEventId"])
        if source_event is None:
            raise ValueError(
                f"Observed visual change {change['id']} references an unknown source event."
            )
        if not (
            source_event["absoluteStartFrame"]
            <= change["absoluteFrame"]
            < source_event["absoluteEndFrameExclusive"]
        ):
            raise ValueError(
                f"Observed visual change {change['id']} falls outside its source event."
            )
    carry_ids: set[str] = set()
    for carry in ledger["intentionalCarrySpans"]:
        if carry["id"] in carry_ids:
            raise ValueError("Intentional carry-span IDs must be unique.")
        carry_ids.add(carry["id"])
        source_event = source_events.get(carry["sourceEventId"])
        if source_event is None:
            raise ValueError(
                f"Intentional carry {carry['id']} references an unknown source event."
            )
        if not (
            source_event["absoluteStartFrame"]
            <= carry["absoluteStartFrame"]
            < carry["absoluteEndFrameExclusive"]
            <= source_event["absoluteEndFrameExclusive"]
        ):
            raise ValueError(
                f"Intentional carry {carry['id']} must be a nonempty span inside its source event."
            )
    ordered_carries = sorted(
        ledger["intentionalCarrySpans"],
        key=lambda item: (
            item["sourceEventId"],
            item["kind"],
            item["absoluteStartFrame"],
        ),
    )
    for left, right in zip(ordered_carries, ordered_carries[1:]):
        if (
            left["sourceEventId"] == right["sourceEventId"]
            and left["kind"] == right["kind"]
            and right["absoluteStartFrame"]
            <= left["absoluteEndFrameExclusive"]
        ):
            raise ValueError(
                "Adjacent or overlapping carry evidence for one source event must be "
                "recorded as one continuous span."
            )


def validate_semantic_manifest(
    manifest: dict,
    catalog: dict,
    analysis_ledger: dict | None = None,
    channel_profile: dict | None = None,
) -> None:
    validate_artifact("semantic-manifest", manifest)
    validate_artifact("capability-catalog", catalog)
    if manifest["revision"] != 1:
        raise ValueError("Initial semantic planning must create manifest revision 1.")
    capability_ids = {item["id"] for item in catalog["capabilities"]}
    proposition_ids = (
        {item["id"] for item in analysis_ledger["propositions"]}
        if analysis_ledger is not None
        else None
    )
    copy_evidence_by_ref = (
        {
            item["copyEvidenceRef"]: item
            for item in copy_evidence_choices(analysis_ledger)
        }
        if analysis_ledger is not None
        else None
    )
    chapter_ids = {chapter["id"] for chapter in manifest["chapters"]}
    observed_changes = {
        item["id"]: item
        for item in (analysis_ledger or {}).get("observedVisualChanges", [])
    }
    carry_spans = {
        item["id"]: item
        for item in (analysis_ledger or {}).get("intentionalCarrySpans", [])
    }
    used_source_change_refs: set[str] = set()
    cursor = 0
    sequence_ids: list[str] = []
    from app.core.creator_production_menu import planning_capability_ids_for_profile

    full_catalog_required = bool(
        (channel_profile or {}).get("selection", {}).get(
            "fullCatalogEvaluationRequired", False
        )
    )
    planning_capability_ids = planning_capability_ids_for_profile(
        catalog, channel_profile
    )
    for sequence in manifest["sequences"]:
        if sequence["absoluteStartFrame"] != cursor:
            raise ValueError("Semantic sequences must cover the runtime without gaps or overlaps.")
        if sequence["absoluteEndFrameExclusive"] <= sequence["absoluteStartFrame"]:
            raise ValueError(f"Semantic sequence {sequence['id']} has an empty frame range.")
        if sequence["chapterId"] not in chapter_ids:
            raise ValueError(f"Semantic sequence {sequence['id']} references an unknown chapter.")
        if (
            proposition_ids is not None
            and sequence["propositionId"] not in proposition_ids
        ):
            raise ValueError(
                f"Semantic sequence {sequence['id']} references an unknown proposition."
            )
        unknown = set(sequence["candidateCapabilityIds"]) - capability_ids
        if unknown:
            raise ValueError(
                f"Semantic sequence {sequence['id']} references unknown capabilities: "
                + ", ".join(sorted(unknown))
            )
        assessment_ids = [
            item["capabilityId"] for item in sequence["candidateAssessments"]
        ]
        if assessment_ids != sequence["candidateCapabilityIds"]:
            raise ValueError(
                f"Semantic sequence {sequence['id']} candidate assessments are incomplete or reordered."
            )
        for assessment in sequence["candidateAssessments"]:
            capability = next(
                item
                for item in catalog["capabilities"]
                if item["id"] == assessment["capabilityId"]
            )
            recipe_evidence = assessment["recipeEvidence"]
            direct_source = direct_capability_source_resource(
                catalog, assessment["capabilityId"]
            )
            if (
                recipe_evidence["sourceResourceId"] != direct_source["id"]
                or recipe_evidence["sourceSha256"] != direct_source["sha256"]
            ):
                raise ValueError(
                    f"Semantic sequence {sequence['id']} candidate "
                    f"{capability['id']} is not evidenced by its exact frozen recipe."
                )
            if (
                assessment["hardExclusions"]["semanticallyIncompatible"]
                and not full_catalog_required
            ):
                raise ValueError(
                    f"Semantic sequence {sequence['id']} includes semantically "
                    f"incompatible candidate {capability['id']}."
                )
            if (
                assessment["hardExclusions"]["runtimeIncompatible"]
                and capability["sourceAvailability"] == "source-enabled"
                and capability["implementationMaturity"] == "source-only"
                and capability["technicalAdmission"] == "unassessed"
            ):
                raise ValueError(
                    f"Semantic sequence {sequence['id']} treats unassessed "
                    f"source-only capability {capability['id']} as runtime-incompatible; "
                    "that lifecycle state requires adaptation, not hard exclusion."
                )
        if (
            sequence["presentationRole"] in {"authored", "hybrid"}
            and not full_catalog_required
            and len(sequence["candidateCapabilityIds"]) < 3
        ):
            raise ValueError(
                f"Authored sequence {sequence['id']} must expose at least three "
                "ranked capability options; unresolved scarcity must block planning."
            )
        if full_catalog_required:
            directive = sequence.get("editorialDirective")
            if not isinstance(directive, dict):
                raise ValueError(
                    f"VCG sequence {sequence['id']} is missing its editorial directive."
                )
            if not all(directive["copyReview"].values()):
                raise ValueError(
                    f"VCG sequence {sequence['id']} has not passed copy review."
                )
            if sequence["presentationRole"] in {"authored", "hybrid"} and (
                sequence["candidateCapabilityIds"] != planning_capability_ids
            ):
                raise ValueError(
                    f"VCG sequence {sequence['id']} must assess every frozen visual "
                    "treatment in catalog order; excluded treatments remain in the "
                    "assessment with their hard-exclusion reason."
                )
            beat_ids = {beat["id"] for beat in directive["spokenBeats"]}
            beats_by_id = {
                beat["id"]: beat for beat in directive["spokenBeats"]
            }
            for beat in directive["spokenBeats"]:
                if not (
                    sequence["absoluteStartFrame"]
                    <= beat["revealFrame"]
                    <= beat["fullyVisibleFrame"]
                    < beat["exitFrameExclusive"]
                    <= sequence["absoluteEndFrameExclusive"]
                ):
                    raise ValueError(
                        f"VCG sequence {sequence['id']} has invalid editorial beat timing."
                    )
                if beat["copyMode"] == "none" and beat["onScreenText"] is not None:
                    raise ValueError("Copy mode none may not carry on-screen text.")
                if beat["copyMode"] != "none" and not beat["onScreenText"]:
                    raise ValueError("Visible editorial beats require explicit on-screen copy.")
                copy_mode = beat["copyMode"]
                copy_ref = beat["copyEvidenceRef"]
                if copy_mode in {"verbatim-command", "exact-ui-label"}:
                    evidence = (
                        copy_evidence_by_ref.get(copy_ref)
                        if copy_evidence_by_ref is not None
                        else None
                    )
                    if evidence is None:
                        raise ValueError(
                            f"VCG sequence {sequence['id']} must use an issued "
                            "copy-evidence reference."
                        )
                    if (
                        evidence["kind"] != copy_mode
                        or evidence["observedText"] != beat["onScreenText"]
                    ):
                        raise ValueError(
                            f"VCG sequence {sequence['id']} copy does not exactly "
                            "match its issued evidence."
                        )
                elif copy_ref is not None:
                    raise ValueError(
                        f"VCG sequence {sequence['id']} attaches exact copy "
                        "evidence to a non-exact editorial label."
                    )
            for change in directive["meaningfulChanges"]:
                inside_sequence = (
                    sequence["absoluteStartFrame"]
                    <= change["absoluteFrame"]
                    < sequence["absoluteEndFrameExclusive"]
                ) or (
                    change["kind"] == "treatment-exit"
                    and change["absoluteFrame"]
                    == sequence["absoluteEndFrameExclusive"]
                )
                if not inside_sequence:
                    raise ValueError("Meaningful changes must fall inside their sequence.")
                if change["spokenBeatId"] is not None and change["spokenBeatId"] not in beat_ids:
                    raise ValueError("Meaningful change references an unknown spoken beat.")
                source_ref = change["sourceVisualChangeRef"]
                if change["verificationKind"] == "source-evidence":
                    observed = observed_changes.get(source_ref)
                    if observed is None:
                        raise ValueError(
                            f"VCG sequence {sequence['id']} cites an unknown observed "
                            "visual change."
                        )
                    if change["spokenBeatId"] is not None:
                        raise ValueError(
                            "Source-evidenced changes may not masquerade as authored spoken beats."
                        )
                    if change["absoluteFrame"] != observed["absoluteFrame"]:
                        raise ValueError(
                            "Source-evidenced meaningful changes must use the observed frame."
                        )
                    if source_ref in used_source_change_refs:
                        raise ValueError(
                            "One observed visual change may satisfy cadence only once."
                        )
                    used_source_change_refs.add(source_ref)
                else:
                    if source_ref is not None or change["spokenBeatId"] is None:
                        raise ValueError(
                            "Authored meaningful changes require one spoken beat and no source-change claim."
                        )
                    beat = beats_by_id[change["spokenBeatId"]]
                    expected_frame = (
                        beat["exitFrameExclusive"]
                        if change["kind"] == "treatment-exit"
                        else beat["revealFrame"]
                    )
                    if change["absoluteFrame"] != expected_frame:
                        raise ValueError(
                            "Authored meaningful changes must use their spoken beat lifecycle frame."
                        )
            carry = directive["intentionalVisualCarry"]
            if carry is not None:
                expected = carry_spans.get(carry["carrySpanRef"])
                if expected is None:
                    raise ValueError(
                        f"VCG sequence {sequence['id']} cites an unknown intentional carry."
                    )
                expected_start = max(
                    sequence["absoluteStartFrame"],
                    expected["absoluteStartFrame"],
                )
                expected_end = min(
                    sequence["absoluteEndFrameExclusive"],
                    expected["absoluteEndFrameExclusive"],
                )
                if not (
                    expected_start < expected_end
                    and carry["absoluteStartFrame"] == expected_start
                    and carry["absoluteEndFrameExclusive"] == expected_end
                    and carry["kind"] == expected["kind"]
                    and carry["sourceEventId"] == expected["sourceEventId"]
                    and carry["evidenceRefs"] == expected["evidenceRefs"]
                ):
                    raise ValueError(
                        "Intentional carry timing must be the application-derived "
                        "overlap between its analysis evidence and coherent sequence."
                    )
        if (
            sequence["presentationRole"] == "source-led"
            and sequence["candidateCapabilityIds"]
        ):
            raise ValueError(
                f"Source-led sequence {sequence['id']} may not carry placeholder "
                "graphic candidates; classify it as hybrid when a graphic is planned."
            )
        cursor = sequence["absoluteEndFrameExclusive"]
        sequence_ids.append(sequence["id"])
    if cursor != manifest["totalFrames"]:
        raise ValueError("Semantic sequences do not reach the end of the locked runtime.")
    if len(sequence_ids) != len(set(sequence_ids)):
        raise ValueError("Semantic sequence ids must be unique.")
    expected_boundaries = list(zip(sequence_ids, sequence_ids[1:]))
    actual_boundaries = [
        (item["fromSequenceId"], item["toSequenceId"])
        for item in manifest["transitionIntents"]
    ]
    if actual_boundaries != expected_boundaries:
        raise ValueError("Every adjacent semantic sequence requires exactly one ordered transition intent.")
    chapter_cursor = 0
    for chapter in manifest["chapters"]:
        if chapter["absoluteStartFrame"] != chapter_cursor:
            raise ValueError("Editorial chapters must cover the runtime without gaps or overlaps.")
        if chapter["absoluteEndFrameExclusive"] <= chapter["absoluteStartFrame"]:
            raise ValueError(f"Chapter {chapter['id']} has an empty frame range.")
        chapter_cursor = chapter["absoluteEndFrameExclusive"]
    if chapter_cursor != manifest["totalFrames"]:
        raise ValueError("Editorial chapters do not reach the end of the locked runtime.")
    chapters_by_id = {chapter["id"]: chapter for chapter in manifest["chapters"]}
    for chapter_id, chapter in chapters_by_id.items():
        assigned = [
            sequence
            for sequence in manifest["sequences"]
            if sequence["chapterId"] == chapter_id
        ]
        if not assigned:
            raise ValueError(f"Editorial chapter {chapter_id} contains no sequences.")
        if (
            assigned[0]["absoluteStartFrame"] != chapter["absoluteStartFrame"]
            or assigned[-1]["absoluteEndFrameExclusive"]
            != chapter["absoluteEndFrameExclusive"]
        ):
            raise ValueError(
                f"Editorial chapter {chapter_id} does not match its assigned sequence range."
            )


def validate_materialized_capability_bindings(manifest: dict, catalog: dict) -> None:
    capabilities = {item["id"]: item for item in catalog["capabilities"]}
    for sequence in manifest["sequences"]:
        bindings = sequence["selectedCapabilityBindings"]
        if sequence["presentationRole"] != "source-led" and not bindings:
            raise ValueError(
                f"Authored or hybrid sequence {sequence['id']} requires an admitted implementation."
            )
        for binding in bindings:
            capability_id = binding.get("capabilityId")
            capability = capabilities.get(capability_id)
            if capability is None:
                raise ValueError(
                    f"Materialized sequence {sequence['id']} names unknown capability {capability_id}."
                )
            if not (
                capability["productionSelection"] == "production-selectable"
                and capability["technicalAdmission"] in {"project-admitted", "library-admitted"}
            ):
                raise ValueError(
                    f"Materialized sequence {sequence['id']} uses unadmitted capability {capability_id}."
                )
            implementation_id = binding.get("implementationId")
            if capability["technicalAdmission"] == "project-admitted":
                valid = any(
                    admission.get("episodeId") == manifest["episodeId"]
                    and admission.get("sequenceId") == sequence["id"]
                    and admission.get("implementationId") == implementation_id
                    for admission in capability.get("projectAdmissions", [])
                )
                if not valid:
                    raise ValueError(
                        f"Sequence {sequence['id']} does not bind its exact project-admitted implementation."
                    )
            elif capability["technicalAdmission"] == "library-admitted":
                valid = any(
                    admission.get("implementationId") == implementation_id
                    for admission in capability.get("libraryAdmissions", [])
                ) or any(
                    (capability.get("seedKit") or {}).get("implementationId")
                    == implementation_id
                )
                if not valid:
                    raise ValueError(
                        f"Sequence {sequence['id']} does not bind its exact library-admitted seed implementation."
                    )


def validate_targeted_revision(old_manifest: dict, new_manifest: dict, review: dict) -> None:
    validate_artifact("episode-manifest", old_manifest)
    validate_artifact("episode-manifest", new_manifest)
    validate_artifact("review-state", review)
    if new_manifest["revision"] != old_manifest["revision"] + 1:
        raise ValueError("Targeted revision must increment the manifest revision exactly once.")
    noted = {item["sequenceId"] for item in review["activeNotes"]}
    if not noted:
        raise ValueError("Targeted revision requires active creator review notes.")
    old_sequences = old_manifest["sequences"]
    new_sequences = new_manifest["sequences"]
    if [item["id"] for item in old_sequences] != [item["id"] for item in new_sequences]:
        raise ValueError("Targeted revision may not add, remove, or reorder sequences.")
    immutable_episode_fields = (
        "episodeId",
        "workflowLockHash",
        "lockedCutSha256",
        "lockedAudioSha256",
        "transcriptSha256",
        "wordTimingSha256",
        "fps",
        "canvas",
        "totalFrames",
        "sourceEventAnchors",
        "chapters",
    )
    for field in immutable_episode_fields:
        if new_manifest[field] != old_manifest[field]:
            raise ValueError(f"Targeted revision changed immutable episode field: {field}")
    immutable_sequence_fields = (
        "id",
        "chapterId",
        "absoluteStartFrame",
        "absoluteEndFrameExclusive",
        "startWordId",
        "endWordId",
        "conceptId",
        "seriesId",
        "callbackTo",
        "propositionId",
        "semanticBeatKind",
        "editorialJob",
        "semanticForm",
        "presentationRole",
        "narrativeStateRole",
        "selectedCapabilityBindings",
    )
    for old, new in zip(old_sequences, new_sequences):
        if old["id"] not in noted:
            if new != old:
                raise ValueError(f"Unnoted sequence changed: {old['id']}")
            continue
        for field in immutable_sequence_fields:
            if new[field] != old[field]:
                raise ValueError(
                    f"Targeted revision changed protected field {field} in {old['id']}."
                )
    old_boundaries = {
        (item["fromSequenceId"], item["toSequenceId"]): item
        for item in old_manifest["transitionBoundaries"]
    }
    for boundary in new_manifest["transitionBoundaries"]:
        key = (boundary["fromSequenceId"], boundary["toSequenceId"])
        if not set(key).intersection(noted) and boundary != old_boundaries.get(key):
            raise ValueError(f"Unnoted transition boundary changed: {boundary['id']}")


def validate_source_evidence(ledger: dict, sequence_ids: Iterable[str]) -> None:
    validate_artifact("source-evidence-ledger", ledger)
    expected_ranges = (
        dict(sequence_ids)
        if isinstance(sequence_ids, dict)
        else {sequence_id: None for sequence_id in sequence_ids}
    )
    expected = set(expected_ranges)
    actual = {item["sequenceId"] for item in ledger["sequences"]}
    if actual != expected or len(actual) != len(ledger["sequences"]):
        raise ValueError(
            f"Every sequence requires measured source evidence; missing={sorted(expected-actual)}, "
            f"unknown={sorted(actual-expected)}"
        )
    for sequence in ledger["sequences"]:
        expected_range = expected_ranges[sequence["sequenceId"]]
        cursor = expected_range[0] if expected_range is not None else None
        for span in sequence["layoutSpans"]:
            if cursor is not None and span["absoluteStartFrame"] != cursor:
                raise ValueError(
                    f"Measured layout spans are not contiguous in {sequence['sequenceId']}."
                )
            if span["absoluteEndFrameExclusive"] <= span["absoluteStartFrame"]:
                raise ValueError(
                    f"Measured layout span is empty in {sequence['sequenceId']}."
                )
            rectangles = [
                rectangle
                for rectangle in [span["subjectBounds"], *span["protectedMasks"]]
                if rectangle is not None
            ]
            for rectangle in rectangles:
                if (
                    rectangle["x"] + rectangle["width"] > 1
                    or rectangle["y"] + rectangle["height"] > 1
                ):
                    raise ValueError(
                        f"Source evidence rectangle leaves the frame in {sequence['sequenceId']}."
                    )
            cursor = span["absoluteEndFrameExclusive"]
        if expected_range is not None and cursor != expected_range[1]:
            raise ValueError(
                f"Measured layout spans do not cover {sequence['sequenceId']}."
            )
        for sample in sequence["protectedRegionSamples"]:
            if expected_range is not None and not (
                expected_range[0] <= sample["absoluteFrame"] < expected_range[1]
            ):
                raise ValueError(
                    f"Protected-region evidence leaves {sequence['sequenceId']}."
                )


def _candidate_is_hard_valid(candidate: dict) -> bool:
    exclusions = candidate["hardExclusions"]
    return not any(bool(exclusions.get(key)) for key in HARD_EXCLUSION_KEYS)


def resolve_sequence_selection(
    *,
    sequence_id: str,
    candidates: list[dict],
    resolved_channel_profile: dict,
    catalog: dict,
    semantic_evidence_refs: list[str],
    actor_model: str,
    prompt_version: str,
    presentation_role: str | None = None,
) -> tuple[dict | None, dict]:
    """Resolve only among hard-valid candidates and preserve the complete trace."""

    validate_artifact("channel-profile", resolved_channel_profile)
    validate_artifact("capability-catalog", catalog)
    if not candidates and presentation_role != "source-led":
        raise ValueError("Capability selection requires an explicit candidate set.")
    catalog_by_id = {entry["id"]: entry for entry in catalog["capabilities"]}
    criterion_order = resolved_channel_profile["selection"]["criterionOrder"]
    if not criterion_order:
        raise ValueError("Lexicographic selection requires a nonempty criterion order.")
    evaluated = []
    for candidate in candidates:
        candidate_id = candidate["capabilityId"]
        capability = catalog_by_id.get(candidate_id)
        if capability is None:
            raise ValueError(f"Selection candidate is absent from the locked catalog: {candidate_id}")
        item = json.loads(json.dumps(candidate))
        item["catalogLifecycle"] = {
            "sourceAvailability": capability["sourceAvailability"],
            "implementationMaturity": capability["implementationMaturity"],
            "technicalAdmission": capability["technicalAdmission"],
            "productionSelection": capability["productionSelection"],
        }
        item["hardValid"] = _candidate_is_hard_valid(item)
        exact_project_admission = any(
            admission.get("sequenceId") == sequence_id
            for admission in capability.get("projectAdmissions", [])
        )
        item["productionSelectable"] = (
            item["hardValid"]
            and capability["sourceAvailability"] == "source-enabled"
            and capability["productionSelection"] == "production-selectable"
            and (
                capability["technicalAdmission"] == "library-admitted"
                or (
                    capability["technicalAdmission"] == "project-admitted"
                    and exact_project_admission
                )
            )
        )
        evaluated.append(item)

    hard_valid = [item for item in evaluated if item["hardValid"]]
    def sort_key(item: dict) -> tuple:
        values = []
        scores = item["criterionValues"]
        for criterion in criterion_order:
            if criterion in {"hard-validity", "stable-capability-id"}:
                continue
            value = scores.get(criterion)
            if value is None:
                raise ValueError(
                    f"Candidate {item['capabilityId']} lacks criterion {criterion}."
                )
            values.append(-float(value))
        return (*values, item["capabilityId"])

    ranked = sorted(hard_valid, key=sort_key)
    selected = ranked[0] if ranked else None
    disposition = "selected"
    unresolved_reasons = []
    if not candidates and presentation_role == "source-led":
        disposition = "source-led-no-authored-capability"
    elif selected is None:
        disposition = "blocked-no-hard-valid-candidate"
        unresolved_reasons.append("No candidate survived hard policy filtering.")
    elif not selected["productionSelectable"]:
        disposition = "adaptation-required"
        unresolved_reasons.append(
            "The strongest hard-valid semantic fit is not yet compiled and technically admitted."
        )
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "id": f"decision:{sequence_id}",
        "sequenceId": sequence_id,
        "rankingPolicyRef": resolved_channel_profile["selection"]["rankingPolicyRef"],
        "rankingMode": resolved_channel_profile["selection"]["mode"],
        "criterionOrder": criterion_order,
        "stableTieBreaker": "stable-capability-id",
        "semanticEvidenceRefs": semantic_evidence_refs,
        "modelEvidence": {
            "model": actor_model,
            "promptVersion": prompt_version,
        },
        "evaluatedCandidates": evaluated,
        "rankedHardValidCapabilityIds": [item["capabilityId"] for item in ranked],
        "selectedCapabilityId": selected["capabilityId"] if selected else None,
        "disposition": disposition,
        "unresolvedReasons": unresolved_reasons,
        "deviationFromTopRanked": None,
        "createdAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    validate_artifact("sequence-decision-receipt", receipt)
    return selected if disposition == "selected" else None, receipt


def evaluate_episode_repetition(manifest: dict, compiled: dict) -> dict:
    sequences = manifest["sequences"]
    compiled_by_id = {item["sequenceId"]: item for item in compiled["sequences"]}
    findings = []
    for previous, current in zip(sequences, sequences[1:]):
        if (
            previous["presentationRole"] == "source-led"
            and current["presentationRole"] == "source-led"
        ):
            # Locked-source pass-through is not an authored visual signature.
            # Requiring adjacent source footage to differ would force decoration
            # or false callback metadata solely to satisfy the repetition gate.
            continue
        previous_compiled = compiled_by_id[previous["id"]]
        current_compiled = compiled_by_id[current["id"]]
        callback_allowed = (
            previous["conceptId"] == current["conceptId"]
            or (
                previous.get("seriesId")
                and previous.get("seriesId") == current.get("seriesId")
            )
            or current.get("callbackTo") == previous["id"]
        )
        for signature_kind in ("topologyHash", "visualSignature"):
            if (
                previous_compiled[signature_kind] == current_compiled[signature_kind]
                and not callback_allowed
            ):
                findings.append(
                    {
                        "severity": "blocking",
                        "kind": f"adjacent-{signature_kind}",
                        "previousSequenceId": previous["id"],
                        "sequenceId": current["id"],
                        "signature": current_compiled[signature_kind],
                    }
                )
    authored = [
        sequence
        for sequence in sequences
        if sequence["presentationRole"] in {"authored", "hybrid"}
    ]
    for index, previous in enumerate(authored):
        for current in authored[index + 1 :]:
            if compiled_by_id[previous["id"]]["visualSignature"] != compiled_by_id[
                current["id"]
            ]["visualSignature"]:
                continue
            callback_allowed = (
                previous["conceptId"] == current["conceptId"]
                or (
                    previous.get("seriesId")
                    and previous.get("seriesId") == current.get("seriesId")
                )
                or current.get("callbackTo") == previous["id"]
                or previous.get("callbackTo") == current["id"]
            )
            if not callback_allowed:
                findings.append(
                    {
                        "severity": "blocking",
                        "kind": "episode-repeated-completed-visual-signature",
                        "previousSequenceId": previous["id"],
                        "sequenceId": current["id"],
                        "signature": compiled_by_id[current["id"]][
                            "visualSignature"
                        ],
                    }
                )
    return {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "evaluatorVersion": "1",
        "findings": findings,
        "passed": not findings,
    }
