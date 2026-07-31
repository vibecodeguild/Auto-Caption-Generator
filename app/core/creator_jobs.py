from __future__ import annotations

import json
import threading
import uuid
from fractions import Fraction
from pathlib import Path

from app.core.creator_task_handoff import (
    create_agent_run_receipt,
    create_task_claim_receipt,
    create_task_handoff_packet,
    verify_task_handoff_packet,
)
from app.core.creator_adaptation import admit_project_capability
from app.core.creator_build import finalize_materialized_build
from app.core.creator_capabilities import (
    planning_capability_resource_ids,
    required_capability_resource_ids,
)
from app.core.creator_evidence import (
    create_source_evidence_from_classification,
    validate_source_layout_classification,
)
from app.core.creator_project import (
    promote_creator_artifact,
    promote_creator_artifacts,
    transition_creator_project,
    verify_live_workflow_package_matches_lock,
    verify_creator_project,
)
from app.core.creator_governance import (
    validate_analysis_ledger,
    validate_materialized_capability_bindings,
    validate_semantic_manifest,
    validate_targeted_revision,
)
from app.core.creator_semantic_planning import (
    PlanningDecisionError,
    boundary_choices,
    copy_evidence_choices,
    create_spoken_span_receipt,
    materialize_semantic_manifest,
    resolve_spoken_span_candidates,
    semantic_plan_materialization_receipt,
    specialize_editorial_plan_schema,
    validate_analysis_against_transcript,
)
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    atomic_write_json,
    build_instruction_context,
    canonical_hash,
    canonical_json_bytes,
    read_frozen_bytes,
    require_private_root,
    transcript_word_timing_hash,
    utc_now,
    validate_artifact,
    validate_episode_manifest,
    write_versioned_artifact,
)
from app.core.file_utils import is_within, sha256_file
from app.core.creator_rendering import probe_video_identity
from app.core.creator_selection import refresh_sequence_decisions


TASK_SCHEMAS = {
    "analyze": "analysis-ledger",
    "plan": "editorial-plan-decisions",
    "classify-layouts": "source-layout-classification",
    "adapt": "capability-adaptation",
    "materialize": "episode-manifest",
    "revise": "episode-manifest",
}
TASK_RESOURCE_IDS = {
    "analyze": "workflow:task:analyze",
    "plan": "workflow:task:plan",
    "classify-layouts": "workflow:task:classify-layouts",
    "adapt": "workflow:task:adapt",
    "materialize": "workflow:task:materialize",
    "revise": "workflow:task:revise",
}
FINAL_JOB_STATES = frozenset({"completed", "failed", "canceled", "interrupted"})
TASK_ARTIFACT_KEYS = {
    "analyze": "analysisLedger",
    "plan": "editorialPlanDecisions",
    "classify-layouts": "sourceLayoutClassification",
    "materialize": "episodeManifest",
    "revise": "episodeManifest",
}

class CreatorJobStore:
    def __init__(self, private_root: Path):
        self.root = require_private_root(private_root)
        self.jobs_root = self.root / "creator-production" / "jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(
        self,
        *,
        task_kind: str,
        requested_resource_ids: list[str],
        input_artifact_refs: list[dict],
        task_parameters: dict | None = None,
    ) -> dict:
        if task_kind not in TASK_SCHEMAS:
            raise ValueError(f"Unknown Creator Production task kind: {task_kind}")
        with self._lock:
            verify_creator_project(self.root)
            verify_live_workflow_package_matches_lock(self.root)
            current = json.loads(
                (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
            )
            allowed_states = {
                "analyze": {"INGESTING", "ANALYZING"},
                "plan": {"ANALYZING"},
                "classify-layouts": {"ANALYZING"},
                "adapt": {"ANALYZING"},
                "materialize": {"ANALYZING", "MATERIALIZING"},
                "revise": {"REVISION_REQUESTED", "MATERIALIZING"},
            }
            if current["state"] not in allowed_states[task_kind]:
                raise ValueError(
                    f"{task_kind} cannot run from Production state {current['state']}."
                )
            if task_kind in {"materialize", "revise"}:
                self._require_materialization_readiness()
            if task_kind == "classify-layouts":
                self._require_layout_classification_readiness()
            if task_kind == "adapt":
                self._require_adaptation_readiness(task_parameters or {})
            active = [
                item for item in self.list()
                if item["status"] in {"queued", "running", "canceling"}
            ]
            if active:
                raise ValueError(
                    f"Creator Production already has an active job: {active[0]['id']}"
                )
            job_id = uuid.uuid4().hex
            job = {
            "schemaVersion": ARTIFACT_SCHEMA_VERSION,
            "id": job_id,
            "taskKind": task_kind,
            "status": "queued",
            "stage": "preparing-handoff",
            "requestedResourceIds": list(dict.fromkeys(requested_resource_ids)),
            "inputArtifactRefs": input_artifact_refs,
            "taskParameters": task_parameters or {},
            "outputArtifactRef": None,
            "instructionReceiptRef": None,
            "handoffPacketRef": None,
            "claimReceiptRef": None,
            "agentRunReceiptRef": None,
            "spanReceiptRefs": [],
            "validationAttemptCount": 0,
            "validationAttemptHistory": [],
            "error": None,
            "cancelRequested": False,
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
            }
            self._save(job)
            try:
                return self.prepare(job_id)
            except Exception as exc:
                job["status"] = "failed"
                job["stage"] = "blocked"
                job["error"] = str(exc)
                job["updatedAt"] = utc_now()
                self._save(job)
                raise

    def _require_layout_classification_readiness(self) -> None:
        current = json.loads(
            (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        required = {
            "semanticManifest",
            "analysisLedger",
            "transcriptReceipt",
            "captureLayoutCatalog",
        }
        missing = sorted(required - set(current["artifacts"]))
        if missing:
            raise ValueError(
                "Source layout classification requires frozen inputs: "
                + ", ".join(missing)
            )

    def _require_materialization_readiness(self) -> None:
        current = json.loads(
            (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        semantic_reference = current["artifacts"].get("semanticManifest")
        evidence_reference = current["artifacts"].get("sourceEvidence")
        if not semantic_reference or not evidence_reference:
            raise ValueError(
                "Materialization requires the semantic manifest and measured source evidence."
            )
        semantic = self._read_artifact(semantic_reference)
        catalog = self._read_artifact(current["artifacts"]["capabilityCatalog"])
        decision_reference = current["artifacts"].get("sequenceDecisionIndex")
        if not decision_reference:
            raise ValueError("Materialization requires deterministic sequence decisions.")
        decisions = self._read_artifact(decision_reference)
        decisions_by_id = {item["sequenceId"]: item for item in decisions["items"]}
        adaptation_debt = []
        for sequence in semantic["sequences"]:
            if sequence["presentationRole"] == "source-led":
                continue
            decision = decisions_by_id.get(sequence["id"])
            if not decision or decision["disposition"] != "selected":
                adaptation_debt.append(
                    {
                        "sequenceId": sequence["id"],
                        "topRankedCapabilityId": (
                            decision.get("topRankedCapabilityId") if decision else None
                        ),
                    }
                )
        if adaptation_debt:
            raise ValueError(
                "Materialization is blocked by explicit capability adaptation debt: "
                + json.dumps(adaptation_debt, ensure_ascii=False)
            )

    def _require_adaptation_readiness(
        self,
        task_parameters: dict,
    ) -> None:
        sequence_id = task_parameters.get("sequenceId")
        capability_id = task_parameters.get("capabilityId")
        if not sequence_id or not capability_id:
            raise ValueError("Capability adaptation requires sequenceId and capabilityId.")
        current = json.loads(
            (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        semantic_reference = current["artifacts"].get("semanticManifest")
        if not semantic_reference:
            raise ValueError("Capability adaptation requires a semantic manifest.")
        semantic = self._read_artifact(semantic_reference)
        sequences = [item for item in semantic["sequences"] if item["id"] == sequence_id]
        if not sequences:
            raise ValueError(f"Capability adaptation sequence does not exist: {sequence_id}")
        if capability_id not in sequences[0]["candidateCapabilityIds"]:
            raise ValueError("Capability is not an approved semantic candidate for this sequence.")
        catalog = self._read_artifact(current["artifacts"]["capabilityCatalog"])
        capabilities = [item for item in catalog["capabilities"] if item["id"] == capability_id]
        if not capabilities or capabilities[0]["sourceAvailability"] != "source-enabled":
            raise ValueError("Capability source is unavailable for adaptation.")
        if capabilities[0]["adaptationEligibility"] not in {
            "adaptable",
            "adaptation-authorized",
        }:
            raise ValueError("Capability is not eligible for project adaptation.")
        required_capability_resource_ids(catalog, capability_id)

    def load(self, job_id: str) -> dict:
        path = self._job_path(job_id)
        if not path.is_file():
            raise ValueError(f"Creator Production job does not exist: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        jobs = []
        for path in sorted(self.jobs_root.glob("*/job.json")):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(jobs, key=lambda item: item["createdAt"], reverse=True)

    def recover_interrupted(self) -> list[str]:
        # A visible task handoff is durable and independent of the app process.
        # The creator explicitly completes or cancels it, so an app restart is
        # not evidence that the task was interrupted.
        return []

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self.load(job_id)
            if job["status"] in FINAL_JOB_STATES:
                return job
            job["cancelRequested"] = True
            job["status"] = "canceled"
            job["stage"] = "canceled"
            job["error"] = None
            job["updatedAt"] = utc_now()
            self._save(job)
            return job

    def run(self, job_id: str) -> dict:
        raise RuntimeError(
            "Nested Codex execution is retired. Claim the prepared handoff "
            "from a normal user-visible Codex task."
        )

    def prepare(self, job_id: str) -> dict:
        with self._lock:
            job = self.load(job_id)
            if job["status"] != "queued":
                raise ValueError(f"Creator Production handoff is not queued: {job['status']}")
        current = json.loads(
            (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        verify_live_workflow_package_matches_lock(self.root, current)
        workflow_lock = self._read_artifact(current["artifacts"]["workflowLock"])
        if workflow_lock["executionHost"]["kind"] != "user-visible-codex-task":
            raise RuntimeError(
                "This project still uses the superseded nested Codex execution lock. "
                "Apply an explicit workflow upgrade before preparing another task."
            )
        requested = [
            "workflow:main",
            TASK_RESOURCE_IDS[job["taskKind"]],
            *job["requestedResourceIds"],
        ]
        if job["taskKind"] == "adapt":
            catalog = self._read_artifact(current["artifacts"]["capabilityCatalog"])
            capability_id = str(job["taskParameters"].get("capabilityId") or "")
            requested.extend(required_capability_resource_ids(catalog, capability_id))
        if job["taskKind"] == "plan":
            catalog = self._read_artifact(current["artifacts"]["capabilityCatalog"])
            requested.extend(planning_capability_resource_ids(catalog))
        if job["taskKind"] in {"plan", "adapt", "materialize", "revise"}:
            channel_profile = self._read_artifact(current["artifacts"]["channelProfile"])
            grammar_name = channel_profile["referenceGrammarRef"].replace("@", ".v")
            requested.append(
                f"workflow:package:reference-grammars/{grammar_name}.md"
            )
        loaded, instruction_receipt = build_instruction_context(
            self.root,
            workflow_lock=workflow_lock,
            workflow_bundle=current["workflowBundle"],
            capability_bundle=current["capabilityBundle"],
            requested_resource_ids=requested,
        )
        instruction_ref = write_versioned_artifact(
            self.root,
            artifact_kind="instruction-receipts",
            artifact_id=job["id"],
            version=1,
            value=instruction_receipt,
            schema_name="instruction-receipt",
        )
        task_directory = self.jobs_root / job["id"]
        schema_name = TASK_SCHEMAS[job["taskKind"]]
        schema_resource_id = f"workflow:package:schemas/{schema_name}.schema.json"
        schema_entries = {
            entry["id"]: entry
            for entry in current["workflowBundle"].get("resources", [])
        }
        schema_entry = schema_entries.get(schema_resource_id)
        if schema_entry is None:
            raise RuntimeError(
                f"Locked workflow output schema is unavailable: {schema_resource_id}"
            )
        expected_schema_hash = workflow_lock["allowedDomainResources"].get(
            schema_resource_id
        )
        if expected_schema_hash != schema_entry["object"]["sha256"]:
            raise RuntimeError(
                f"Locked workflow output schema is not allowlisted: {schema_resource_id}"
            )
        frozen_schema = task_directory / "output.schema.json"
        frozen_schema_bytes = read_frozen_bytes(
            self.root, schema_entry["object"]
        )
        if job["taskKind"] == "plan":
            planning_context = self._planning_context(job, current)
            schema = specialize_editorial_plan_schema(
                json.loads(frozen_schema_bytes.decode("utf-8")),
                issued_copy_evidence_refs=[
                    item["copyEvidenceRef"]
                    for item in copy_evidence_choices(
                        planning_context["analysis"]
                    )
                ],
            )
            frozen_schema.write_text(
                json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            frozen_schema.write_bytes(frozen_schema_bytes)
        task_prompt = self._build_task_prompt(job, workflow_lock, loaded)
        task_path = task_directory / "task.md"
        task_path.write_text(task_prompt, encoding="utf-8")
        output_path = task_directory / "agent-output.json"
        packet = create_task_handoff_packet(
            private_project_root=self.root,
            job_id=job["id"],
            task_kind=job["taskKind"],
            workflow_lock=workflow_lock,
            instruction_receipt=instruction_receipt,
            task_path=task_path,
            output_schema_path=frozen_schema,
            output_path=output_path,
        )
        packet_path = task_directory / "handoff.json"
        atomic_write_json(packet_path, packet)
        packet_ref = {
            "path": packet_path.relative_to(self.root).as_posix(),
            "sha256": sha256_file(packet_path),
            "packetHash": packet["packetHash"],
        }
        handoff_prompt = (
            f"Process Creator Production job {job['id']} in {self.root}. "
            "Use the repository's monitored Creator Production task-handoff protocol. "
            "Do not spawn another Codex process. Read the immutable handoff packet at "
            f"{packet_path}, claim it from this visible task, produce the schema-bound "
            "agent-output.json, and use the application-owned span resolution, decision "
            "submission, and completion commands. Do not calculate transcript timing."
        )
        with self._lock:
            prepared = self.load(job["id"])
            prepared["stage"] = "awaiting-visible-codex"
            prepared["instructionReceiptRef"] = instruction_ref
            prepared["handoffPacketRef"] = packet_ref
            prepared["handoffPrompt"] = handoff_prompt
            prepared["updatedAt"] = utc_now()
            self._save(prepared)
            return prepared

    def handoff(self, job_id: str) -> dict:
        job = self.load(job_id)
        reference = job.get("handoffPacketRef")
        if not reference:
            raise RuntimeError("Creator Production handoff is not prepared.")
        path = (self.root / reference["path"]).resolve()
        if not path.is_file() or sha256_file(path) != reference["sha256"]:
            raise RuntimeError("Creator Production handoff packet is missing or changed.")
        return {
            "job": job,
            "packet": json.loads(path.read_text(encoding="utf-8")),
            "handoffPrompt": job["handoffPrompt"],
        }

    def claim(
        self,
        job_id: str,
        *,
        task_id: str,
        visible_skill_ids: list[str],
    ) -> dict:
        with self._lock:
            job = self.load(job_id)
            if job["status"] != "queued":
                raise ValueError(f"Creator Production handoff cannot be claimed from {job['status']}.")
            current = json.loads(
                (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
            )
            verify_live_workflow_package_matches_lock(self.root, current)
            workflow_lock = self._read_artifact(current["artifacts"]["workflowLock"])
            packet = self.handoff(job_id)["packet"]
            verify_task_handoff_packet(
                private_project_root=self.root,
                packet=packet,
                expected_job_id=job_id,
                expected_workflow_hash=workflow_lock["workflowHash"],
            )
            claim_receipt = create_task_claim_receipt(
                workflow_lock=workflow_lock,
                handoff_packet=packet,
                task_id=task_id,
                visible_skill_ids=visible_skill_ids,
            )
            claim_ref = write_versioned_artifact(
                self.root,
                artifact_kind="task-claim-receipts",
                artifact_id=job_id,
                version=1,
                value=claim_receipt,
            )
            if job["taskKind"] == "analyze" and current["state"] == "INGESTING":
                transition_creator_project(
                    self.root,
                    target_state="ANALYZING",
                    gate_receipt_refs=[current["artifacts"]["transcriptReceipt"]["sha256"]],
                )
            elif job["taskKind"] in {"materialize", "revise"} and current["state"] in {
                "ANALYZING",
                "REVISION_REQUESTED",
            }:
                transition_creator_project(
                    self.root,
                    target_state="MATERIALIZING",
                    gate_receipt_refs=[
                        current["artifacts"]["semanticManifest"]["sha256"],
                        current["artifacts"]["sourceEvidence"]["sha256"],
                    ],
                )
            job["status"] = "running"
            job["stage"] = "visible-codex-task"
            job["claimReceiptRef"] = claim_ref
            job["operatorTaskId"] = task_id.strip()
            job["updatedAt"] = utc_now()
            self._save(job)
            return job

    def resolve_spoken_span(
        self,
        job_id: str,
        *,
        task_id: str,
        proposition_id: str,
        exact_phrase: str,
        candidate_ref: str | None = None,
    ) -> dict:
        with self._lock:
            job = self._require_claimed_plan_job(job_id, task_id)
            current = self._load_current()
            context = self._planning_context(job, current)
            candidates = resolve_spoken_span_candidates(
                job_id=job_id,
                task_id=task_id.strip(),
                episode_id=current["episodeId"],
                transcript_sha256=context["transcriptReceipt"]["transcriptSha256"],
                word_timing_sha256=context["transcriptReceipt"]["wordTimingSha256"],
                analysis_sha256=context["analysisReference"]["sha256"],
                analysis=context["analysis"],
                transcript_document=context["transcriptDocument"],
                proposition_id=proposition_id,
                exact_phrase=exact_phrase,
            )
            if candidate_ref is None and len(candidates) > 1:
                return {
                    "status": "ambiguous",
                    "message": (
                        "The phrase occurs more than once in this proposition. "
                        "Choose one candidateRef using the supplied local context."
                    ),
                    "candidates": [
                        {
                            "candidateRef": item["candidateRef"],
                            "occurrenceNumber": position,
                            "occurrenceCount": len(candidates),
                            "spokenPhrase": item["spokenPhrase"],
                            "leftContext": item["leftContext"],
                            "rightContext": item["rightContext"],
                        }
                        for position, item in enumerate(candidates, start=1)
                    ],
                }
            selected = (
                candidates[0]
                if candidate_ref is None
                else next(
                    (
                        item
                        for item in candidates
                        if item["candidateRef"] == candidate_ref
                    ),
                    None,
                )
            )
            if selected is None:
                raise PlanningDecisionError(
                    [
                        {
                            "code": "unknown-span-candidate",
                            "message": (
                                "The selected candidate does not match this proposition "
                                "and spoken phrase."
                            ),
                        }
                    ]
                )
            unsigned_receipt_id = "spoken-span:" + canonical_hash(
                {
                    key: value
                    for key, value in selected.items()
                    if key not in {"candidateRef", "leftContext", "rightContext"}
                }
            )
            for reference in job.get("spanReceiptRefs", []):
                existing = self._read_artifact(reference)
                if existing["id"] == unsigned_receipt_id:
                    return {"status": "resolved", "receipt": existing, "reference": reference}
            receipt = create_spoken_span_receipt(selected)
            reference = write_versioned_artifact(
                self.root,
                artifact_kind="spoken-span-receipts",
                artifact_id=receipt["id"],
                version=1,
                value=receipt,
                schema_name="spoken-span-receipt",
            )
            job.setdefault("spanReceiptRefs", []).append(reference)
            job["updatedAt"] = utc_now()
            self._save(job)
            return {"status": "resolved", "receipt": receipt, "reference": reference}

    def submit_plan_decisions(
        self,
        job_id: str,
        *,
        task_id: str,
        output: dict,
    ) -> dict:
        with self._lock:
            job = self._require_claimed_plan_job(job_id, task_id)
            if job["stage"] == "decisions-validated":
                raise ValueError("This plan submission is already validated; complete the job.")
            attempt = int(job.get("validationAttemptCount", 0)) + 1
            if attempt > 3:
                raise ValueError("This plan job has exhausted its three validation submissions.")
            output_path = self.jobs_root / job_id / "agent-output.json"
            atomic_write_json(output_path, output)
            try:
                semantic, receipt = self._materialize_plan_output(job, output)
            except PlanningDecisionError as exc:
                return self._record_plan_validation_failure(
                    job=job,
                    attempt=attempt,
                    output=output,
                    errors=exc.errors,
                )
            except Exception as exc:
                job["status"] = "failed"
                job["stage"] = "blocked"
                job["error"] = (
                    "Semantic planning infrastructure failed without consuming "
                    f"a correction submission: {exc}"
                )
                job["updatedAt"] = utc_now()
                self._save(job)
                return job
            atomic_write_json(self.jobs_root / job_id / "materialized-semantic.json", semantic)
            atomic_write_json(
                self.jobs_root / job_id / "materialization-receipt.json",
                receipt,
            )
            job["validationAttemptCount"] = attempt
            job["stage"] = "decisions-validated"
            job["decisionValidation"] = {
                "status": "passed",
                "attempt": attempt,
                "remainingAttempts": max(0, 3 - attempt),
                "semanticManifestHash": canonical_hash(semantic),
                "materializationReceiptHash": receipt["receiptHash"],
            }
            job["validatedDecisionHash"] = canonical_hash(output)
            job["acceptedDecisionIds"] = {
                "sequenceIds": [item["id"] for item in output["sequences"]],
                "chapterIds": [item["id"] for item in output["chapters"]],
            }
            job["acceptedPlanRef"] = self._freeze_validated_plan_decisions(
                job=job,
                output=output,
                version=attempt,
            )
            job["error"] = None
            job["updatedAt"] = utc_now()
            self._save(job)
            return job

    def complete(
        self,
        job_id: str,
        *,
        task_id: str,
        output: dict | None = None,
        technical_capability_ids: list[str] | None = None,
    ) -> dict:
        with self._lock:
            job = self.load(job_id)
            if job["status"] != "running":
                raise ValueError(f"Creator Production handoff cannot complete from {job['status']}.")
            if job.get("operatorTaskId") != task_id.strip():
                raise ValueError("A different Codex task claimed this Production job.")
            if job["taskKind"] == "plan" and job["stage"] != "decisions-validated":
                raise ValueError(
                    "Submit and validate editorial plan decisions before completion."
                )
            output_path = self.jobs_root / job_id / "agent-output.json"
            if job["taskKind"] == "plan" and output is not None:
                if (
                    not output_path.is_file()
                    or json.loads(output_path.read_text(encoding="utf-8")) != output
                ):
                    raise ValueError(
                        "Plan completion cannot replace the validated editorial decisions."
                    )
            elif output is not None:
                atomic_write_json(output_path, output)
            if not output_path.is_file():
                raise RuntimeError("The visible Codex task has not written agent-output.json.")
            if job["taskKind"] == "plan":
                completed_output = json.loads(output_path.read_text(encoding="utf-8"))
                if canonical_hash(completed_output) != job.get("validatedDecisionHash"):
                    raise ValueError(
                        "The validated editorial decisions changed before completion."
                    )
        try:
            return self._promote_completed_output(
                job,
                task_id=task_id.strip(),
                output=json.loads(output_path.read_text(encoding="utf-8")),
                technical_capability_ids=technical_capability_ids or [],
            )
        except Exception as exc:
            with self._lock:
                failed = self.load(job_id)
                failed["status"] = "failed"
                failed["stage"] = "blocked"
                failed["error"] = str(exc)
                failed["updatedAt"] = utc_now()
                self._save(failed)
                return failed

    def fail(self, job_id: str, *, task_id: str, error: str) -> dict:
        with self._lock:
            job = self.load(job_id)
            if job["status"] != "running" or job.get("operatorTaskId") != task_id.strip():
                raise ValueError("Only the visible task that claimed this job may fail it.")
            job["status"] = "failed"
            job["stage"] = "blocked"
            job["error"] = error.strip() or "The visible Codex task reported a failure."
            job["updatedAt"] = utc_now()
            self._save(job)
            return job

    def _promote_completed_output(
        self,
        job: dict,
        *,
        task_id: str,
        output: dict,
        technical_capability_ids: list[str],
    ) -> dict:
        current = json.loads(
            (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )
        verify_live_workflow_package_matches_lock(self.root, current)
        workflow_lock = self._read_artifact(current["artifacts"]["workflowLock"])
        packet = self.handoff(job["id"])["packet"]
        verify_task_handoff_packet(
            private_project_root=self.root,
            packet=packet,
            expected_job_id=job["id"],
            expected_workflow_hash=workflow_lock["workflowHash"],
        )
        instruction_receipt = self._read_artifact(job["instructionReceiptRef"])
        claim_receipt = self._read_artifact(job["claimReceiptRef"])
        schema_name = TASK_SCHEMAS[job["taskKind"]]
        build_result = None
        semantic_output = None
        materialization_receipt = None
        validate_artifact(schema_name, output)
        if job["taskKind"] not in {"adapt", "plan"}:
            self._validate_locked_output_identity(
                task_kind=job["taskKind"],
                output=output,
                current=current,
                workflow_lock=workflow_lock,
            )
        if job["taskKind"] == "analyze":
            validate_analysis_ledger(output)
            _transcript_receipt, transcript_document = (
                self._locked_transcript_document(current)
            )
            validate_analysis_against_transcript(output, transcript_document)
        elif job["taskKind"] == "plan":
            semantic_output, materialization_receipt = self._materialize_plan_output(
                job,
                output,
            )
        elif job["taskKind"] == "classify-layouts":
            semantic = self._read_artifact(current["artifacts"]["semanticManifest"])
            catalog = self._read_artifact(current["artifacts"]["captureLayoutCatalog"])
            validate_source_layout_classification(
                output,
                expected_ranges={
                    sequence["id"]: (
                        sequence["absoluteStartFrame"],
                        sequence["absoluteEndFrameExclusive"],
                    )
                    for sequence in semantic["sequences"]
                },
                capture_layout_catalog=catalog,
            )
        elif job["taskKind"] in {"materialize", "revise"}:
            validate_episode_manifest(output)
            catalog_reference = current["artifacts"]["capabilityCatalog"]
            catalog = self._read_artifact(catalog_reference)
            validate_materialized_capability_bindings(output, catalog)
            if job["taskKind"] == "revise":
                validate_targeted_revision(
                    self._read_artifact(current["artifacts"]["episodeManifest"]),
                    output,
                    self._read_artifact(current["artifacts"]["reviewState"]),
                )
        output_ref = write_versioned_artifact(
            self.root,
            artifact_kind=f"{job['taskKind']}-outputs",
            artifact_id=job["id"],
            version=1,
            value=output,
            schema_name=schema_name,
        )
        decision_index_ref = None
        semantic_output_ref = None
        materialization_receipt_ref = None
        source_evidence_ref = None
        source_evidence_unresolved = []
        if job["taskKind"] == "plan":
            assert semantic_output is not None
            assert materialization_receipt is not None
            semantic_output_ref = write_versioned_artifact(
                self.root,
                artifact_kind="semantic-manifests",
                artifact_id=job["id"],
                version=1,
                value=semantic_output,
                schema_name="semantic-manifest",
            )
            materialization_receipt_ref = write_versioned_artifact(
                self.root,
                artifact_kind="semantic-plan-materialization-receipts",
                artifact_id=job["id"],
                version=1,
                value=materialization_receipt,
                schema_name="semantic-plan-materialization-receipt",
            )
            _index, decision_index_ref = refresh_sequence_decisions(
                self.root,
                semantic_output,
                promote=False,
            )
        elif job["taskKind"] == "classify-layouts":
            source_evidence_ref, source_evidence_unresolved = (
                create_source_evidence_from_classification(
                    self.root,
                    classification=output,
                    classification_reference=output_ref,
                )
            )
        if job["taskKind"] == "adapt":
            parameters = job["taskParameters"]
            if not parameters.get("sequenceId") or not parameters.get("capabilityId"):
                raise ValueError("Capability adaptation requires a sequence and capability.")
            adaptation_ref, catalog_ref, admitted_catalog = admit_project_capability(
                self.root,
                adaptation=output,
                expected_sequence_id=parameters["sequenceId"],
                expected_capability_id=parameters["capabilityId"],
                promote=False,
            )
            _index, adaptation_decision_ref = refresh_sequence_decisions(
                self.root,
                catalog=admitted_catalog,
                promote=False,
            )
            promote_creator_artifacts(
                self.root,
                artifact_references={
                    "capabilityCatalog": catalog_ref,
                    "capabilityAdaptation": adaptation_ref,
                    "sequenceDecisionIndex": adaptation_decision_ref,
                },
            )
        elif job["taskKind"] in {"materialize", "revise"}:
            build_result = finalize_materialized_build(self.root, output)
            if not build_result["passed"]:
                promote_creator_artifact(
                    self.root,
                    artifact_key="structuralPreflight",
                    artifact_reference=build_result["preflightRef"],
                )
                with self._lock:
                    blocked = self.load(job["id"])
                    blocked["diagnosticArtifactRefs"] = [build_result["preflightRef"]]
                    self._save(blocked)
                raise ValueError(
                    "Materialized episode failed deterministic preflight; "
                    "inspect the structural preflight receipt."
                )
        run_receipt = create_agent_run_receipt(
            workflow_lock=workflow_lock,
            instruction_receipt=instruction_receipt,
            claim_receipt=claim_receipt,
            task_id=task_id,
            output_artifact_hash=output_ref["sha256"],
            technical_capability_ids=technical_capability_ids,
        )
        run_ref = write_versioned_artifact(
            self.root,
            artifact_kind="agent-run-receipts",
            artifact_id=job["id"],
            version=1,
            value=run_receipt,
        )
        artifact_key = TASK_ARTIFACT_KEYS.get(job["taskKind"])
        if build_result and artifact_key:
            promote_creator_artifacts(
                self.root,
                artifact_references={
                    artifact_key: output_ref,
                    "compiledEpisode": build_result["compiledEpisodeRef"],
                    "structuralPreflight": build_result["preflightRef"],
                    "buildLock": build_result["buildLockRef"],
                },
            )
            transition_creator_project(
                self.root,
                target_state="PREFLIGHT",
                gate_receipt_refs=[
                    build_result["preflightRef"]["sha256"],
                    build_result["buildLockRef"]["sha256"],
                ],
            )
        elif job["taskKind"] == "plan" and artifact_key and decision_index_ref:
            assert semantic_output_ref is not None
            assert materialization_receipt_ref is not None
            promote_creator_artifacts(
                self.root,
                artifact_references={
                    artifact_key: output_ref,
                    "semanticManifest": semantic_output_ref,
                    "semanticPlanMaterialization": materialization_receipt_ref,
                    "sequenceDecisionIndex": decision_index_ref,
                },
            )
        elif job["taskKind"] == "classify-layouts" and artifact_key:
            references = {artifact_key: output_ref}
            if source_evidence_ref is not None:
                references["sourceEvidence"] = source_evidence_ref
            promote_creator_artifacts(
                self.root,
                artifact_references=references,
            )
        elif artifact_key:
            promote_creator_artifact(
                self.root,
                artifact_key=artifact_key,
                artifact_reference=output_ref,
            )
        with self._lock:
            completed = self.load(job["id"])
            completed["status"] = "completed"
            completed["stage"] = "completed"
            completed["outputArtifactRef"] = output_ref
            completed["agentRunReceiptRef"] = run_ref
            if semantic_output_ref is not None:
                completed["materializedSemanticManifestRef"] = semantic_output_ref
            if materialization_receipt_ref is not None:
                completed["semanticPlanMaterializationRef"] = (
                    materialization_receipt_ref
                )
            if source_evidence_unresolved:
                completed["blockingLayoutAmbiguities"] = source_evidence_unresolved
            completed["updatedAt"] = utc_now()
            self._save(completed)
            return completed

    def _validate_locked_output_identity(
        self,
        *,
        task_kind: str,
        output: dict,
        current: dict,
        workflow_lock: dict,
    ) -> None:
        transcript_receipt = self._read_artifact(current["artifacts"]["transcriptReceipt"])
        video = probe_video_identity(self.root / current["lockedCutPath"])
        rate = Fraction(video["rFrameRate"])
        expected = {
            "episodeId": current["episodeId"],
            "lockedCutSha256": transcript_receipt["lockedCutSha256"],
            "wordTimingSha256": transcript_receipt["wordTimingSha256"],
            "totalFrames": video["frameCount"],
        }
        if task_kind in {"plan", "materialize", "revise"}:
            expected.update(
                {
                    "transcriptSha256": transcript_receipt["transcriptSha256"],
                    "workflowLockHash": canonical_hash(workflow_lock),
                }
            )
            if output.get("fps") != {
                "numerator": rate.numerator,
                "denominator": rate.denominator,
            }:
                raise ValueError("Agent output changed the locked source frame rate.")
        if task_kind in {"materialize", "revise"}:
            expected["lockedAudioSha256"] = transcript_receipt["lockedAudioSha256"]
            if output.get("canvas") != {
                "width": video["width"],
                "height": video["height"],
            }:
                raise ValueError("Agent output changed the locked source canvas.")
            if task_kind == "materialize" and output.get("revision") != 1:
                raise ValueError("Initial materialization must create manifest revision 1.")
            if output.get("state") != "MATERIALIZING":
                raise ValueError("Agent output may not advance the Production state machine.")
        for key, value in expected.items():
            if output.get(key) != value:
                raise ValueError(f"Agent output changed locked identity field: {key}")

    def _build_task_prompt(self, job: dict, workflow_lock: dict, loaded: dict[str, str]) -> str:
        current = self._load_current()
        input_refs = []
        for reference in job["inputArtifactRefs"]:
            content = read_frozen_bytes(self.root, reference["object"])
            input_refs.append(
                {
                    "artifactKind": reference["artifactKind"],
                    "artifactId": reference["artifactId"],
                    "sha256": reference["sha256"],
                    "content": json.loads(content.decode("utf-8")),
                }
            )
        sections = [
            f"# {workflow_lock['workflowId']} task",
            f"Workflow bundle hash: `{workflow_lock['workflowHash']}`",
            (
                "Workflow lock canonical hash (use this exact value for "
                f"`workflowLockHash`): `{canonical_hash(workflow_lock)}`"
            ),
            "The following resources are the complete allowed instruction context for this task.",
            "## Verified private source inputs",
            json.dumps(
                {
                    "lockedCutPath": str((self.root / current["lockedCutPath"]).resolve()),
                    "finalTranscriptPath": str(
                        (self.root / current["finalTranscriptPath"]).resolve()
                    ),
                    "sourceIdentity": next(
                        (
                            item["content"]
                            for item in input_refs
                            if item["artifactKind"] == "transcript-receipts"
                        ),
                        None,
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        ]
        for resource_id in ["workflow:main", TASK_RESOURCE_IDS[job["taskKind"]]]:
            sections.extend([f"## Resource `{resource_id}`", loaded[resource_id]])
        capability_resources = {
            resource_id: content
            for resource_id, content in loaded.items()
            if resource_id not in {"workflow:main", TASK_RESOURCE_IDS[job["taskKind"]]}
        }
        if job["taskKind"] == "plan":
            catalog_input = next(
                (
                    item["content"]
                    for item in input_refs
                    if item["artifactKind"] == "capability-catalogs"
                ),
                None,
            )
            if not isinstance(catalog_input, dict):
                raise RuntimeError("Semantic planning requires the frozen capability catalog.")
            exact_capability_ids = sorted(
                str(item["id"]) for item in catalog_input["capabilities"]
                if item.get("scope") == "blueprint-macro"
                and item.get("category") != "workflow-specific-transition-source"
            )
            planning_context = self._planning_context(job, current)
            issued_boundaries = boundary_choices(
                job_id=job["id"],
                analysis_sha256=planning_context["analysisReference"]["sha256"],
                analysis=planning_context["analysis"],
                transcript_document=planning_context["transcriptDocument"],
            )
            public_boundaries = [
                {
                    "boundaryRef": item["boundaryRef"],
                    "boundaryCauseRef": item["boundaryCauseRef"],
                    "semanticUnitId": item["semanticUnitId"],
                    "propositionId": item["propositionId"],
                    "spokenContext": item["spokenContext"],
                    "relationshipToPrevious": item[
                        "relationshipToPrevious"
                    ],
                    "sourceEventRefs": item["sourceEventRefs"],
                }
                for item in issued_boundaries
            ]
            issued_copy_evidence = copy_evidence_choices(
                planning_context["analysis"]
            )
            sections.extend(
                [
                    "## Exact planning capability IDs",
                    (
                        "Every authored or hybrid sequence must assess each ID below "
                        "exactly once. Do not order or shortlist them; the application "
                        "restores locked catalog order."
                    ),
                    json.dumps(exact_capability_ids, ensure_ascii=False, indent=2),
                    "## Application-issued sequence and chapter boundary choices",
                    (
                        "Use only these opaque boundaryRef and boundaryCauseRef pairs. "
                        "They are issued only for analyzed semantic-unit starts; a "
                        "sentence or proposition boundary alone is not eligible. Do "
                        "not copy or calculate absoluteFrame values into the output."
                    ),
                    json.dumps(public_boundaries, ensure_ascii=False, indent=2),
                    "## Application-issued exact copy evidence",
                    (
                        "For `exact-ui-label` and `verbatim-command` beats, copy "
                        "one compatible `copyEvidenceRef` from this list. The "
                        "on-screen text must exactly equal its `observedText`, and "
                        "the evidence proposition must match the resolved spoken "
                        "span. Source-event IDs and raw evidence strings are not "
                        "copy evidence. If no compatible receipt exists, record "
                        "the issue as unresolved instead of inventing a reference."
                    ),
                    json.dumps(
                        issued_copy_evidence,
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "## Required planning handoff commands",
                    (
                        "Use the claiming visible task ID in place of <TASK_ID>. "
                        "These are the production commands; do not write a parallel "
                        "resolver or calculate timing yourself."
                    ),
                    (
                        f'.\\.venv\\Scripts\\python.exe scripts\\creator_task_handoff.py '
                        f'--project "{self.root}" --job "{job["id"]}" resolve-span '
                        '--task-id "<TASK_ID>" --proposition-id "<PROPOSITION_ID>" '
                        '--phrase "<EXACT_SPOKEN_PHRASE>"'
                    ),
                    (
                        "If resolution is ambiguous, repeat that command with "
                        '`--candidate-ref "<CANDIDATE_REF>"`.'
                    ),
                    (
                        f'.\\.venv\\Scripts\\python.exe scripts\\creator_task_handoff.py '
                        f'--project "{self.root}" --job "{job["id"]}" submit-decisions '
                        '--task-id "<TASK_ID>" --output "<OUTPUT_JSON_PATH>"'
                    ),
                    (
                        f'.\\.venv\\Scripts\\python.exe scripts\\creator_task_handoff.py '
                        f'--project "{self.root}" --job "{job["id"]}" complete '
                        '--task-id "<TASK_ID>"'
                    ),
                ]
            )
        if job["taskKind"] == "adapt":
            catalog = self._read_artifact(current["artifacts"]["capabilityCatalog"])
            required_ids = required_capability_resource_ids(
                catalog,
                str(job["taskParameters"].get("capabilityId") or ""),
            )
            resource_index = {
                item["id"]: item
                for item in [*catalog["sourceResources"], *catalog["supportResources"]]
            }
            sections.extend(
                [
                    "## Exact required HyperFrames instruction dependencies",
                    (
                        "Copy these resource IDs and hashes exactly into "
                        "`sourceResourceIds` and `sourceHashes` in this order."
                    ),
                    json.dumps(
                        [
                            {
                                "id": resource_id,
                                "sha256": resource_index[resource_id]["sha256"],
                            }
                            for resource_id in required_ids
                        ],
                        ensure_ascii=False,
                        indent=2,
                    ),
                ]
            )
        sections.extend(
            [
                "## Frozen task inputs",
                json.dumps(input_refs, ensure_ascii=False, indent=2),
                "## Authorized task parameters",
                json.dumps(job["taskParameters"], ensure_ascii=False, indent=2),
                "## Bounded capability resources",
                json.dumps(capability_resources, ensure_ascii=False, indent=2),
                "Return only the JSON document required by the supplied output schema.",
            ]
        )
        return "\n\n".join(sections)

    def _load_current(self) -> dict:
        return json.loads(
            (self.root / "creator-production" / "current.json").read_text(
                encoding="utf-8"
            )
        )

    def _require_claimed_plan_job(self, job_id: str, task_id: str) -> dict:
        job = self.load(job_id)
        if job["taskKind"] != "plan":
            raise ValueError("Spoken-span and decision submission commands require a plan job.")
        if job["status"] != "running":
            raise ValueError(f"Creator Production plan job is not running: {job['status']}.")
        if job.get("operatorTaskId") != task_id.strip():
            raise ValueError("A different Codex task claimed this Production job.")
        return job

    def _planning_context(self, job: dict, current: dict) -> dict:
        verify_live_workflow_package_matches_lock(self.root, current)
        analysis_reference = current["artifacts"].get("analysisLedger")
        if analysis_reference is None:
            raise ValueError("Semantic planning requires a promoted analysis ledger.")
        transcript_receipt, transcript_document = self._locked_transcript_document(
            current
        )
        analysis = self._read_artifact(analysis_reference)
        validate_analysis_ledger(analysis)
        validate_analysis_against_transcript(analysis, transcript_document)
        return {
            "analysis": analysis,
            "analysisReference": analysis_reference,
            "transcriptDocument": transcript_document,
            "transcriptReceipt": transcript_receipt,
        }

    def _locked_transcript_document(self, current: dict) -> tuple[dict, dict]:
        transcript_receipt = self._read_artifact(
            current["artifacts"]["transcriptReceipt"]
        )
        transcript_path = (self.root / current["finalTranscriptPath"]).resolve()
        if not is_within(transcript_path, self.root) or not transcript_path.is_file():
            raise RuntimeError("The locked transcript is unavailable.")
        if sha256_file(transcript_path) != transcript_receipt["transcriptSha256"]:
            raise RuntimeError("The locked transcript bytes changed.")
        transcript_document = json.loads(transcript_path.read_text(encoding="utf-8"))
        if (
            transcript_word_timing_hash(transcript_document)
            != transcript_receipt["wordTimingSha256"]
        ):
            raise RuntimeError("The locked transcript word timing changed.")
        return transcript_receipt, transcript_document

    def _materialize_plan_output(
        self,
        job: dict,
        output: dict,
    ) -> tuple[dict, dict]:
        current = self._load_current()
        context = self._planning_context(job, current)
        workflow_lock = self._read_artifact(current["artifacts"]["workflowLock"])
        catalog = self._read_artifact(current["artifacts"]["capabilityCatalog"])
        channel_profile = self._read_artifact(current["artifacts"]["channelProfile"])
        span_receipts = []
        for reference in job.get("spanReceiptRefs", []):
            receipt = self._read_artifact(reference)
            validate_artifact("spoken-span-receipt", receipt)
            if canonical_hash(
                {key: value for key, value in receipt.items() if key != "receiptHash"}
            ) != receipt["receiptHash"]:
                raise PlanningDecisionError(
                    [
                        {
                            "code": "changed-span-receipt",
                            "message": "A spoken-span receipt failed its content hash.",
                        }
                    ]
                )
            span_receipts.append(receipt)
        video = probe_video_identity(self.root / current["lockedCutPath"])
        rate = Fraction(video["rFrameRate"])
        semantic = materialize_semantic_manifest(
            decisions=output,
            current=current,
            workflow_lock_hash=canonical_hash(workflow_lock),
            transcript_receipt=context["transcriptReceipt"],
            transcript_document=context["transcriptDocument"],
            analysis=context["analysis"],
            analysis_sha256=context["analysisReference"]["sha256"],
            catalog=catalog,
            channel_profile=channel_profile,
            total_frames=video["frameCount"],
            fps={"numerator": rate.numerator, "denominator": rate.denominator},
            span_receipts=span_receipts,
            job_id=job["id"],
        )
        self._validate_locked_output_identity(
            task_kind="plan",
            output=semantic,
            current=current,
            workflow_lock=workflow_lock,
        )
        try:
            validate_semantic_manifest(
                semantic,
                catalog,
                context["analysis"],
                channel_profile,
            )
        except ValueError as exc:
            message = str(exc)
            matching_sequence_ids = [
                sequence["id"]
                for sequence in semantic["sequences"]
                if f"sequence {sequence['id']}" in message
            ]
            error = {
                "code": "semantic-plan-validation",
                "message": message,
            }
            if len(matching_sequence_ids) == 1:
                error["sequenceId"] = matching_sequence_ids[0]
            raise PlanningDecisionError(
                [error]
            ) from exc
        receipt = semantic_plan_materialization_receipt(
            job_id=job["id"],
            decisions=output,
            span_receipts=span_receipts,
            semantic_manifest=semantic,
        )
        return semantic, receipt

    def _record_plan_validation_failure(
        self,
        *,
        job: dict,
        attempt: int,
        output: dict,
        errors: list[dict],
    ) -> dict:
        submission_ref = write_versioned_artifact(
            self.root,
            artifact_kind="plan-validation-submissions",
            artifact_id=job["id"],
            version=attempt,
            value=output,
        )
        diagnostic = {
            "schemaVersion": ARTIFACT_SCHEMA_VERSION,
            "jobId": job["id"],
            "attempt": attempt,
            "submissionHash": canonical_hash(output),
            "submissionRef": submission_ref,
            "errors": errors,
            "createdAt": utc_now(),
        }
        accepted = {"sequenceIds": [], "chapterIds": []}
        job.pop("acceptedPlanRef", None)
        job["acceptedDecisionIds"] = accepted
        diagnostic["acceptedSequenceIds"] = accepted["sequenceIds"]
        diagnostic["acceptedChapterIds"] = accepted["chapterIds"]
        diagnostic["diagnosticHash"] = canonical_hash(diagnostic)
        diagnostic_ref = write_versioned_artifact(
            self.root,
            artifact_kind="plan-validation-diagnostics",
            artifact_id=job["id"],
            version=attempt,
            value=diagnostic,
        )
        job["validationAttemptCount"] = attempt
        job.setdefault("validationAttemptHistory", []).append(diagnostic_ref)
        job.setdefault("failedSubmissionRefs", []).append(submission_ref)
        job["diagnosticArtifactRefs"] = [
            *job.get("diagnosticArtifactRefs", []),
            diagnostic_ref,
        ]
        job["decisionValidation"] = {
            "status": "failed",
            "attempt": attempt,
            "remainingAttempts": max(0, 3 - attempt),
            "errors": errors,
            "acceptedSequenceIds": accepted["sequenceIds"],
            "acceptedChapterIds": accepted["chapterIds"],
            "diagnosticRef": diagnostic_ref,
        }
        job["error"] = None
        if attempt >= 3:
            job["status"] = "failed"
            job["stage"] = "blocked"
            job["error"] = "Editorial planning failed three bounded validation submissions."
        else:
            job["stage"] = "correction-required"
        job["updatedAt"] = utc_now()
        self._save(job)
        return job

    def _freeze_validated_plan_decisions(
        self,
        *,
        job: dict,
        output: dict,
        version: int,
    ) -> dict:
        frozen = {
            "schemaVersion": ARTIFACT_SCHEMA_VERSION,
            "sequences": {
                item["id"]: item for item in output["sequences"]
            },
            "chapters": {
                item["id"]: item for item in output["chapters"]
            },
            "validatedDecisionHash": canonical_hash(output),
            "updatedAt": utc_now(),
        }
        return write_versioned_artifact(
            self.root,
            artifact_kind="accepted-plan-decisions",
            artifact_id=job["id"],
            version=version,
            value=frozen,
        )

    def _read_artifact(self, reference: dict) -> dict:
        path = (self.root / reference["path"]).resolve()
        if not is_within(path, self.root) or not path.is_file():
            raise RuntimeError("Creator Production artifact reference is unavailable.")
        if sha256_file(path) != reference["sha256"]:
            raise RuntimeError("Creator Production artifact revision changed.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _job_path(self, job_id: str) -> Path:
        if not job_id or any(character not in "0123456789abcdef" for character in job_id):
            raise ValueError("Invalid Creator Production job id.")
        return self.jobs_root / job_id / "job.json"

    def _save(self, job: dict) -> None:
        atomic_write_json(self._job_path(job["id"]), job)
