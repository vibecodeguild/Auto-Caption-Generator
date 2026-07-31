from __future__ import annotations

from app.core.creator_governance import evaluate_episode_repetition, validate_source_evidence
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    canonical_hash,
    transcript_word_timing_payload,
    utc_now,
    validate_episode_manifest,
)


def _intersects(first: dict, second: dict) -> bool:
    return not (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )


def _inside_canvas(rect: dict) -> bool:
    return (
        rect["x"] >= 0
        and rect["y"] >= 0
        and rect["x"] + rect["width"] <= 1
        and rect["y"] + rect["height"] <= 1
    )


def _resolved_geometry_at_frame(
    element: dict,
    events: list[dict],
    absolute_frame: int,
) -> tuple[dict, list[str]]:
    geometry = dict(element["geometry"])
    unresolved = []
    for event in sorted(events, key=lambda item: item["absoluteFrame"]):
        if event["targetElementId"] != element["id"] or event["absoluteFrame"] > absolute_frame:
            continue
        if event["operation"] not in {"move", "scale", "enter", "exit"}:
            continue
        resolved = (event.get("parameters") or {}).get("resolvedGeometry")
        if not isinstance(resolved, dict):
            unresolved.append(event["id"])
            continue
        geometry.update(
            {
                key: float(resolved[key])
                for key in ("x", "y", "width", "height")
                if key in resolved
            }
        )
    return geometry, unresolved


def _speaker_gaps(sequence: dict) -> list[tuple[int, int]]:
    start = sequence["absoluteStartFrame"]
    end = sequence["absoluteEndFrameExclusive"]
    ranges = []
    for element in sequence["compositionGraph"]["elements"]:
        if element["properties"].get("role") != "speaker-source":
            continue
        element_ranges = element["properties"].get("visibleRanges")
        if not isinstance(element_ranges, list):
            ranges.append((start, end))
            continue
        for item in element_ranges:
            ranges.append((max(start, int(item["startFrame"])), min(end, int(item["endFrameExclusive"]))))
    ranges.sort()
    merged = []
    for range_start, range_end in ranges:
        if range_end <= range_start:
            continue
        if merged and range_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], range_end))
        else:
            merged.append((range_start, range_end))
    gaps = []
    cursor = start
    for range_start, range_end in merged:
        if range_start > cursor:
            gaps.append((cursor, range_start))
        cursor = max(cursor, range_end)
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def run_structural_preflight(
    *,
    manifest: dict,
    compiled: dict,
    transcript_document: dict,
    source_evidence: dict,
    capability_catalog: dict,
    channel_profile: dict | None = None,
    maximum_speaker_absence_seconds: float = 2.0,
) -> dict:
    """Run deterministic gates before browser/render parity checks."""

    validate_episode_manifest(manifest)
    validate_source_evidence(source_evidence, [item["id"] for item in manifest["sequences"]])
    timing = transcript_word_timing_payload(transcript_document)
    words = {word["id"]: word for word in timing["words"]}
    source_anchors = {item["id"]: item for item in manifest["sourceEventAnchors"]}
    evidence_by_sequence = {item["sequenceId"]: item for item in source_evidence["sequences"]}
    capabilities = {item["id"]: item for item in capability_catalog["capabilities"]}
    fps = manifest["fps"]["numerator"] / manifest["fps"]["denominator"]
    visibility_policy = (channel_profile or {}).get("speaker", {}).get(
        "visibilityPolicy", {}
    )
    maximum_absence_frames = round(
        float(
            visibility_policy.get(
                "continuousAbsenceMaximumSeconds",
                maximum_speaker_absence_seconds,
            )
        )
        * fps
    )
    allowed_absence_layouts = set(
        visibility_policy.get("absenceAllowedLayoutIds", [])
    )
    vcg_contract = (channel_profile or {}).get("id") == "vcg" and int(
        (channel_profile or {}).get("version", 0)
    ) >= 2
    findings = []

    for sequence in manifest["sequences"]:
        graph = sequence["compositionGraph"]
        elements = {element["id"]: element for element in graph["elements"]}
        if vcg_contract:
            directive = sequence.get("editorialDirective")
            selected_family = sequence.get("selectedVisualFamilyId")
            if not isinstance(directive, dict):
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "missing-editorial-directive",
                        "sequenceId": sequence["id"],
                    }
                )
            else:
                if not all(directive.get("copyReview", {}).values()):
                    findings.append(
                        {
                            "severity": "blocking",
                            "gate": "copy-review",
                            "sequenceId": sequence["id"],
                        }
                    )
                for beat in directive.get("spokenBeats", []):
                    if beat.get("onScreenText") is None:
                        continue
                    matching_elements = [
                        item
                        for item in graph["elements"]
                        if item["properties"].get("editorialBeatId") == beat["id"]
                        and item["properties"].get("text") == beat["onScreenText"]
                    ]
                    matching_events = [
                        item
                        for item in graph["events"]
                        if item["absoluteFrame"] == beat["revealFrame"]
                        and item.get("wordId") == beat["sourceWordIds"][0]
                        and item["operation"] in {"reveal", "enter", "show", "type-reveal"}
                        and any(
                            element["id"] == item["targetElementId"]
                            for element in matching_elements
                        )
                    ]
                    if len(matching_elements) != 1 or len(matching_events) != 1:
                        findings.append(
                            {
                                "severity": "blocking",
                                "gate": "semantic-copy-binding",
                                "sequenceId": sequence["id"],
                                "spokenBeatId": beat["id"],
                            }
                        )
                    elif (
                        matching_events[0]["absoluteFrame"]
                        + matching_events[0]["durationFrames"]
                        != beat["fullyVisibleFrame"]
                    ):
                        findings.append(
                            {
                                "severity": "blocking",
                                "gate": "fully-visible-timing",
                                "sequenceId": sequence["id"],
                                "spokenBeatId": beat["id"],
                            }
                        )
            if sequence["presentationRole"] in {"authored", "hybrid"}:
                selected_ids = {
                    binding.get("capabilityId")
                    for binding in sequence["selectedCapabilityBindings"]
                }
                if selected_family is None or selected_family not in selected_ids:
                    findings.append(
                        {
                            "severity": "blocking",
                            "gate": "visual-family-provenance",
                            "sequenceId": sequence["id"],
                        }
                    )
        for element in graph["elements"]:
            if not _inside_canvas(element["geometry"]):
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "off-canvas",
                        "sequenceId": sequence["id"],
                        "elementId": element["id"],
                    }
                )
        for event in graph["events"]:
            if not event["contentBearing"]:
                continue
            expected_frame = None
            if event.get("wordId"):
                word = words.get(event["wordId"])
                if word is None:
                    findings.append(
                        {
                            "severity": "blocking",
                            "gate": "unknown-word-anchor",
                            "sequenceId": sequence["id"],
                            "eventId": event["id"],
                        }
                    )
                    continue
                expected_frame = word["startFrame"]
            elif event.get("sourceEventAnchorId"):
                anchor = source_anchors.get(event["sourceEventAnchorId"])
                if anchor is None:
                    findings.append(
                        {
                            "severity": "blocking",
                            "gate": "unknown-source-anchor",
                            "sequenceId": sequence["id"],
                            "eventId": event["id"],
                        }
                    )
                    continue
                expected_frame = anchor["absoluteFrame"]
            if event["absoluteFrame"] != expected_frame:
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "invented-timing-offset",
                        "sequenceId": sequence["id"],
                        "eventId": event["id"],
                        "expectedFrame": expected_frame,
                        "actualFrame": event["absoluteFrame"],
                    }
                )
            target = elements[event["targetElementId"]]
            if event["operation"] in {"reveal", "enter", "show", "type-reveal"} and target[
                "properties"
            ].get("initiallyVisible", False):
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "visible-before-cue",
                        "sequenceId": sequence["id"],
                        "eventId": event["id"],
                        "cueMinusOneFrame": event["absoluteFrame"] - 1,
                    }
                )

        overlay_elements = [
            element
            for element in graph["elements"]
            if element["properties"].get("role") not in {"speaker-source", "locked-source"}
        ]
        sequence_evidence = evidence_by_sequence[sequence["id"]]
        evidence_spans = sequence_evidence["layoutSpans"]
        validation_frames = {
            sequence["absoluteStartFrame"],
            sequence["absoluteEndFrameExclusive"] - 1,
            *(
                frame
                for span in evidence_spans
                for frame in (
                    span["absoluteStartFrame"],
                    span["absoluteEndFrameExclusive"] - 1,
                    *span["evidenceFrames"],
                )
            ),
            *(event["absoluteFrame"] for event in graph["events"]),
        }
        protected_samples = {
            sample["absoluteFrame"]: sample["protectedMasks"]
            for sample in sequence_evidence["protectedRegionSamples"]
        }
        for absolute_frame in sorted(validation_frames):
            source_span = next(
                (
                    span
                    for span in evidence_spans
                    if span["absoluteStartFrame"]
                    <= absolute_frame
                    < span["absoluteEndFrameExclusive"]
                ),
                None,
            )
            if source_span is None:
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "missing-source-layout-evidence",
                        "sequenceId": sequence["id"],
                        "absoluteFrame": absolute_frame,
                    }
                )
                continue
            protected_regions = [
                region
                for region in [
                    source_span["subjectBounds"],
                    *source_span["protectedMasks"],
                    *protected_samples.get(absolute_frame, []),
                ]
                if region is not None
            ]
            for element in overlay_elements:
                resolved_geometry, unresolved_geometry_events = _resolved_geometry_at_frame(
                    element,
                    graph["events"],
                    absolute_frame,
                )
                for event_id in unresolved_geometry_events:
                    findings.append(
                        {
                            "severity": "blocking",
                            "gate": "unresolved-dynamic-geometry",
                            "sequenceId": sequence["id"],
                            "elementId": element["id"],
                            "eventId": event_id,
                            "absoluteFrame": absolute_frame,
                        }
                    )
                for protected_mask in protected_regions:
                    if _intersects(resolved_geometry, protected_mask):
                        findings.append(
                            {
                                "severity": "blocking",
                                "gate": "protected-region-intersection",
                                "sequenceId": sequence["id"],
                                "elementId": element["id"],
                                "absoluteFrame": absolute_frame,
                                "sourceLayoutId": source_span["layoutId"],
                            }
                        )
        for gap_start, gap_end in _speaker_gaps(sequence):
            gap_layouts = {
                span["layoutId"]
                for span in evidence_spans
                if span["absoluteStartFrame"] < gap_end
                and gap_start < span["absoluteEndFrameExclusive"]
            }
            wrong_layout = bool(
                allowed_absence_layouts and not gap_layouts.issubset(allowed_absence_layouts)
            )
            if wrong_layout or gap_end - gap_start > maximum_absence_frames:
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "speaker-absence",
                        "sequenceId": sequence["id"],
                        "absoluteStartFrame": gap_start,
                        "absoluteEndFrameExclusive": gap_end,
                        "maximumFrames": maximum_absence_frames,
                        "sourceLayoutIds": sorted(gap_layouts),
                    }
                )

    for boundary in manifest["transitionBoundaries"]:
        if boundary["mode"] != "transition":
            continue
        from_sequence = next(
            item
            for item in manifest["sequences"]
            if item["id"] == boundary["fromSequenceId"]
        )
        to_sequence = next(
            item
            for item in manifest["sequences"]
            if item["id"] == boundary["toSequenceId"]
        )
        capability = capabilities.get(boundary["implementationRef"])
        if capability is None:
            findings.append(
                {
                    "severity": "blocking",
                    "gate": "unknown-transition",
                    "boundaryId": boundary["id"],
                }
            )
        elif capability["productionSelection"] != "production-selectable":
            findings.append(
                {
                    "severity": "blocking",
                    "gate": "unadmitted-transition",
                    "boundaryId": boundary["id"],
                    "implementationRef": boundary["implementationRef"],
                }
            )
        bindings = [
            (sequence, binding)
            for sequence in (from_sequence, to_sequence)
            for binding in sequence["selectedCapabilityBindings"]
            if binding.get("capabilityId") == boundary["implementationRef"]
        ]
        if len(bindings) != 1:
            findings.append(
                {
                    "severity": "blocking",
                    "gate": "transition-ownership",
                    "boundaryId": boundary["id"],
                    "implementationRef": boundary["implementationRef"],
                }
            )
            continue
        owner, binding = bindings[0]
        owned_event_ids = binding.get("eventIds")
        owner_events = {
            event["id"]: event for event in owner["compositionGraph"]["events"]
        }
        if not isinstance(owned_event_ids, list) or not owned_event_ids:
            findings.append(
                {
                    "severity": "blocking",
                    "gate": "transition-event-provenance",
                    "boundaryId": boundary["id"],
                    "sequenceId": owner["id"],
                }
            )
            continue
        boundary_frame = from_sequence["absoluteEndFrameExclusive"]
        window_start = boundary_frame - boundary["durationFrames"]
        window_end = boundary_frame + boundary["durationFrames"]
        transition_events = [
            owner_events[event_id]
            for event_id in owned_event_ids
            if event_id in owner_events
        ]
        if len(transition_events) != len(owned_event_ids) or any(
            event["absoluteFrame"] < window_start
            or event["absoluteFrame"] >= window_end
            or event["absoluteFrame"] + event["durationFrames"] > window_end
            for event in transition_events
        ):
            findings.append(
                {
                    "severity": "blocking",
                    "gate": "transition-event-window",
                    "boundaryId": boundary["id"],
                    "sequenceId": owner["id"],
                }
            )
        if (
            from_sequence["chapterId"] != to_sequence["chapterId"]
            and boundary["overlapFrames"] > 0
        ):
            findings.append(
                {
                    "severity": "blocking",
                    "gate": "unsupported-cross-chapter-overlap",
                    "boundaryId": boundary["id"],
                }
            )

    if vcg_contract:
        maximum_gap = round(
            float(channel_profile["pacing"]["maximumMeaningfulChangeGapSec"]) * fps
        )
        change_frames = []
        carries = []
        used_source_change_refs: set[str] = set()
        carry_receipts: dict[str, dict] = {}
        for sequence in manifest["sequences"]:
            directive = sequence.get("editorialDirective") or {}
            graph_events = sequence["compositionGraph"]["events"]
            for change in directive.get("meaningfulChanges", []):
                verified = False
                if change.get("verificationKind") == "source-evidence":
                    source_ref = change.get("sourceVisualChangeRef")
                    verified = bool(source_ref) and source_ref not in used_source_change_refs
                    if verified:
                        used_source_change_refs.add(source_ref)
                elif change.get("verificationKind") == "spoken-beat":
                    verified = any(
                        event["absoluteFrame"] == change["absoluteFrame"]
                        and (event.get("parameters") or {}).get(
                            "meaningfulChangeId"
                        )
                        == change["id"]
                        for event in graph_events
                    )
                if verified:
                    change_frames.append(change["absoluteFrame"])
                else:
                    findings.append(
                        {
                            "severity": "blocking",
                            "gate": "meaningful-change-not-materialized",
                            "sequenceId": sequence["id"],
                            "meaningfulChangeId": change.get("id"),
                        }
                    )
            carry = directive.get("intentionalVisualCarry")
            if carry is not None:
                carry_ref = carry.get("carrySpanRef")
                carry_start = carry.get("absoluteStartFrame", -1)
                carry_end = carry.get("absoluteEndFrameExclusive", -1)
                source_event_id = carry.get("sourceEventId")
                evidence_refs = carry.get("evidenceRefs")
                identity = (
                    source_event_id,
                    tuple(sorted(evidence_refs))
                    if isinstance(evidence_refs, list)
                    and all(isinstance(item, str) and item for item in evidence_refs)
                    else (),
                )
                prior_receipt = carry_receipts.get(carry_ref)
                verified = (
                    bool(carry_ref)
                    and bool(source_event_id)
                    and bool(identity[1])
                    and sequence["absoluteStartFrame"]
                    <= carry_start
                    < carry_end
                    <= sequence["absoluteEndFrameExclusive"]
                    and (
                        prior_receipt is None
                        or (
                            prior_receipt["identity"] == identity
                            and carry_start <= prior_receipt["absoluteEndFrameExclusive"]
                        )
                    )
                )
                if verified:
                    carry_receipts[carry_ref] = {
                        "identity": identity,
                        "absoluteEndFrameExclusive": max(
                            carry_end,
                            prior_receipt["absoluteEndFrameExclusive"]
                            if prior_receipt is not None
                            else carry_end,
                        ),
                    }
                    carries.append(carry)
                else:
                    findings.append(
                        {
                            "severity": "blocking",
                            "gate": "intentional-carry-not-evidenced",
                            "sequenceId": sequence["id"],
                        }
                    )
        merged_carries = []
        for carry in sorted(carries, key=lambda item: item["absoluteStartFrame"]):
            if (
                merged_carries
                and carry["absoluteStartFrame"] <= merged_carries[-1][1]
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
                manifest["totalFrames"],
                *change_frames,
                *(frame for carry in merged_carries for frame in carry),
            }
        )
        for start, end in zip(checkpoints, checkpoints[1:]):
            if end - start <= maximum_gap:
                continue
            covered = any(
                carry_start <= start and carry_end >= end
                for carry_start, carry_end in merged_carries
            )
            if not covered:
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "meaningful-change-cadence",
                        "absoluteStartFrame": start,
                        "absoluteEndFrameExclusive": end,
                        "maximumFrames": maximum_gap,
                    }
                )
        maximum_family_uses = int(
            channel_profile["reuse"]["maximumUsesPerVisualFamily"]
        )
        family_sequences: dict[str, list[str]] = {}
        for sequence in manifest["sequences"]:
            family = sequence.get("selectedVisualFamilyId")
            if family:
                family_sequences.setdefault(family, []).append(sequence["id"])
        for family, sequence_ids in family_sequences.items():
            if len(sequence_ids) > maximum_family_uses:
                findings.append(
                    {
                        "severity": "blocking",
                        "gate": "visual-family-reuse",
                        "visualFamilyId": family,
                        "sequenceIds": sequence_ids,
                        "maximumUses": maximum_family_uses,
                    }
                )

    repetition = evaluate_episode_repetition(manifest, compiled)
    findings.extend(repetition["findings"])
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "evaluatorVersion": "1",
        "manifestHash": canonical_hash(manifest),
        "compiledBuildHash": compiled["buildHash"],
        "wordTimingSha256": manifest["wordTimingSha256"],
        "sourceEvidenceHash": canonical_hash(source_evidence),
        "gates": {
            "exactWordAndSourceTiming": True,
            "cueMinusOneVisibility": True,
            "canvasBounds": True,
            "protectedRegionsAtAllSampleRoles": True,
            "speakerVisibility": True,
            "explicitTransitionResolution": True,
            "adjacentRepetition": True,
        },
        "findings": findings,
        "passed": not any(item["severity"] == "blocking" for item in findings),
        "createdAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    return receipt
