from __future__ import annotations

from pathlib import Path

import pytest

from app.core.creator_production import canonical_hash
from app.core.creator_task_handoff import (
    create_agent_run_receipt,
    create_task_claim_receipt,
    create_task_handoff_packet,
    verify_task_handoff_packet,
)


SHA = "a" * 64


def _lock() -> dict:
    return {
        "workflowHash": SHA,
        "forbiddenWorkflowSkills": [
            "motion-graphics",
            "talking-head-recut",
        ],
    }


def _instruction_receipt() -> dict:
    receipt = {"workflowHash": SHA, "owningWorkflowId": "creator-video-production"}
    receipt["receiptHash"] = canonical_hash(receipt)
    return receipt


def test_handoff_packet_binds_task_schema_and_visible_execution(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    schema = tmp_path / "output.schema.json"
    task.write_text("task", encoding="utf-8")
    schema.write_text("{}", encoding="utf-8")
    packet = create_task_handoff_packet(
        private_project_root=tmp_path,
        job_id="a" * 32,
        task_kind="analyze",
        workflow_lock=_lock(),
        instruction_receipt=_instruction_receipt(),
        task_path=task,
        output_schema_path=schema,
        output_path=tmp_path / "agent-output.json",
    )

    assert packet["executionHost"] == "user-visible-codex-task"
    assert packet["nestedCodexProcessAllowed"] is False
    verify_task_handoff_packet(
        private_project_root=tmp_path,
        packet=packet,
        expected_job_id="a" * 32,
        expected_workflow_hash=SHA,
    )

    task.write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="task was modified"):
        verify_task_handoff_packet(
            private_project_root=tmp_path,
            packet=packet,
            expected_job_id="a" * 32,
            expected_workflow_hash=SHA,
        )


def test_visible_task_claim_rejects_forbidden_skill() -> None:
    packet = {
        "jobId": "a" * 32,
        "packetHash": SHA,
    }
    with pytest.raises(RuntimeError, match="forbidden video workflow skills"):
        create_task_claim_receipt(
            workflow_lock=_lock(),
            handoff_packet=packet,
            task_id="visible-task",
            visible_skill_ids=["browser:control", "motion-graphics"],
        )

    receipt = create_task_claim_receipt(
        workflow_lock=_lock(),
        handoff_packet=packet,
        task_id="visible-task",
        visible_skill_ids=["browser:control", "doc"],
    )
    assert receipt["monitoringMode"] == "user-visible"
    assert receipt["nestedCodexProcessSpawned"] is False
    assert receipt["forbiddenSkillIdsPresent"] == []


def test_run_receipt_accepts_only_declared_technical_capabilities() -> None:
    claim = create_task_claim_receipt(
        workflow_lock=_lock(),
        handoff_packet={"jobId": "a" * 32, "packetHash": SHA},
        task_id="visible-task",
        visible_skill_ids=[],
    )
    receipt = create_agent_run_receipt(
        workflow_lock=_lock(),
        instruction_receipt=_instruction_receipt(),
        claim_receipt=claim,
        task_id="visible-task",
        output_artifact_hash=SHA,
        technical_capability_ids=["codex:command-execution"],
    )
    assert receipt["executionHost"] == "user-visible-codex-task"
    assert receipt["technicalCapabilityIds"] == ["codex:command-execution"]

    with pytest.raises(RuntimeError, match="unapproved technical capability"):
        create_agent_run_receipt(
            workflow_lock=_lock(),
            instruction_receipt=_instruction_receipt(),
            claim_receipt=claim,
            task_id="visible-task",
            output_artifact_hash=SHA,
            technical_capability_ids=["codex:mcp:legacy-video:render"],
        )
