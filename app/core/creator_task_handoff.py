from __future__ import annotations

from pathlib import Path

from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    WORKFLOW_ID,
    canonical_hash,
    utc_now,
)
from app.core.file_utils import sha256_file


ALLOWED_TECHNICAL_CAPABILITIES = frozenset(
    {
        "codex:command-execution",
        "codex:local-image-inspection",
        "codex:mcp:node_repl:js",
    }
)


def _matches_forbidden_skill(skill_id: str, forbidden_skill_ids: set[str]) -> bool:
    normalized = skill_id.strip().lower()
    return any(
        normalized == forbidden or normalized.endswith(f":{forbidden}")
        for forbidden in forbidden_skill_ids
    )


def create_task_handoff_packet(
    *,
    private_project_root: Path,
    job_id: str,
    task_kind: str,
    workflow_lock: dict,
    instruction_receipt: dict,
    task_path: Path,
    output_schema_path: Path,
    output_path: Path,
) -> dict:
    root = private_project_root.resolve()
    for path in (task_path, output_schema_path):
        if not path.is_file():
            raise ValueError(f"Production handoff input is missing: {path.name}")
    packet = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "jobId": job_id,
        "taskKind": task_kind,
        "workflowId": WORKFLOW_ID,
        "workflowHash": workflow_lock["workflowHash"],
        "instructionReceiptHash": instruction_receipt["receiptHash"],
        "executionHost": "user-visible-codex-task",
        "monitoringMode": "user-visible",
        "nestedCodexProcessAllowed": False,
        "openaiApiKeyRequired": False,
        "task": {
            "path": task_path.relative_to(root).as_posix(),
            "sha256": sha256_file(task_path),
        },
        "outputSchema": {
            "path": output_schema_path.relative_to(root).as_posix(),
            "sha256": sha256_file(output_schema_path),
        },
        "output": {"path": output_path.relative_to(root).as_posix()},
        "createdAt": utc_now(),
    }
    packet["packetHash"] = canonical_hash(packet)
    return packet


def verify_task_handoff_packet(
    *,
    private_project_root: Path,
    packet: dict,
    expected_job_id: str,
    expected_workflow_hash: str,
) -> None:
    root = private_project_root.resolve()
    unsigned = {key: value for key, value in packet.items() if key != "packetHash"}
    if canonical_hash(unsigned) != packet.get("packetHash"):
        raise RuntimeError("Creator Production handoff packet was modified.")
    if packet.get("jobId") != expected_job_id:
        raise RuntimeError("Creator Production handoff belongs to a different job.")
    if packet.get("workflowHash") != expected_workflow_hash:
        raise RuntimeError("Creator Production handoff belongs to a different workflow.")
    if packet.get("executionHost") != "user-visible-codex-task":
        raise RuntimeError("Nested or unrecognized Creator Production execution is forbidden.")
    if packet.get("nestedCodexProcessAllowed") is not False:
        raise RuntimeError("Creator Production handoff may not authorize a nested Codex process.")
    for key in ("task", "outputSchema"):
        reference = packet.get(key) or {}
        path = (root / str(reference.get("path") or "")).resolve()
        if root not in path.parents or not path.is_file():
            raise RuntimeError(f"Creator Production handoff {key} is unavailable.")
        if sha256_file(path) != reference.get("sha256"):
            raise RuntimeError(f"Creator Production handoff {key} was modified.")


def create_task_claim_receipt(
    *,
    workflow_lock: dict,
    handoff_packet: dict,
    task_id: str,
    visible_skill_ids: list[str],
) -> dict:
    task_id = task_id.strip()
    if not task_id:
        raise ValueError("A visible Codex task ID is required to claim Production work.")
    normalized_skills = sorted(
        {skill.strip() for skill in visible_skill_ids if skill.strip()}
    )
    forbidden = {
        str(value).lower()
        for value in workflow_lock.get("forbiddenWorkflowSkills", [])
    }
    present = [
        skill
        for skill in normalized_skills
        if _matches_forbidden_skill(skill, forbidden)
    ]
    if present:
        raise RuntimeError(
            "The visible Codex task contains forbidden video workflow skills: "
            + ", ".join(present)
        )
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "jobId": handoff_packet["jobId"],
        "taskId": task_id,
        "workflowId": WORKFLOW_ID,
        "workflowHash": workflow_lock["workflowHash"],
        "handoffPacketHash": handoff_packet["packetHash"],
        "executionHost": "user-visible-codex-task",
        "monitoringMode": "user-visible",
        "nestedCodexProcessSpawned": False,
        "skillInventorySource": "visible-task-startup-context",
        "visibleSkillIds": normalized_skills,
        "forbiddenSkillIdsPresent": [],
        "openaiApiKeyRequired": False,
        "claimedAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    return receipt


def create_agent_run_receipt(
    *,
    workflow_lock: dict,
    instruction_receipt: dict,
    claim_receipt: dict,
    task_id: str,
    output_artifact_hash: str,
    technical_capability_ids: list[str],
) -> dict:
    if claim_receipt.get("executionHost") != "user-visible-codex-task":
        raise RuntimeError("Only a user-visible Codex task may complete Production work.")
    if claim_receipt.get("nestedCodexProcessSpawned") is not False:
        raise RuntimeError("Nested Codex execution may not create a Production run receipt.")
    if claim_receipt.get("workflowHash") != workflow_lock.get("workflowHash"):
        raise RuntimeError("Task claim belongs to a different workflow.")
    if instruction_receipt.get("workflowHash") != workflow_lock.get("workflowHash"):
        raise RuntimeError("Instruction receipt belongs to a different workflow.")
    if claim_receipt.get("taskId") != task_id:
        raise RuntimeError("A different Codex task attempted to complete this handoff.")
    technical = sorted(set(technical_capability_ids))
    unknown = sorted(set(technical) - ALLOWED_TECHNICAL_CAPABILITIES)
    if unknown:
        raise RuntimeError(
            "Creator Production used an unapproved technical capability: "
            + ", ".join(unknown)
        )
    receipt = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "jobId": claim_receipt["jobId"],
        "taskId": task_id,
        "owningWorkflowId": WORKFLOW_ID,
        "workflowHash": workflow_lock["workflowHash"],
        "executionHost": "user-visible-codex-task",
        "monitoringMode": "user-visible",
        "openaiApiKeyUsed": False,
        "nestedCodexProcessSpawned": False,
        "claimReceiptHash": claim_receipt["receiptHash"],
        "instructionReceiptHash": instruction_receipt["receiptHash"],
        "technicalCapabilityIds": technical,
        "outputArtifactHash": output_artifact_hash,
        "forbiddenFallbackOccurred": False,
        "createdAt": utc_now(),
    }
    receipt["receiptHash"] = canonical_hash(receipt)
    return receipt
