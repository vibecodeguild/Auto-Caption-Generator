from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.creator_jobs import CreatorJobStore
from app.core.creator_production import canonical_hash
from app.core.creator_semantic_planning import PlanningDecisionError


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir()
    (root / ".vcg-private").write_text("private", encoding="utf-8")
    production = root / "creator-production"
    production.mkdir()
    (production / "current.json").write_text(
        json.dumps({"state": "INGESTING"}),
        encoding="utf-8",
    )
    return root


def _job(
    store: CreatorJobStore,
    *,
    status: str = "queued",
    task_kind: str = "analyze",
) -> dict:
    job = {
        "schemaVersion": 1,
        "id": "a" * 32,
        "taskKind": task_kind,
        "status": status,
        "stage": "awaiting-visible-codex",
        "cancelRequested": False,
        "error": None,
        "createdAt": "2026-07-29T00:00:00+00:00",
        "updatedAt": "2026-07-29T00:00:00+00:00",
    }
    store._save(job)
    return job


def test_job_store_rejects_unknown_task_kind(tmp_path: Path) -> None:
    store = CreatorJobStore(_root(tmp_path))
    with pytest.raises(ValueError, match="Unknown Creator Production task"):
        store.create(task_kind="invent", requested_resource_ids=[], input_artifact_refs=[])


def test_visible_handoff_survives_app_restart_without_false_interruption(
    tmp_path: Path,
) -> None:
    store = CreatorJobStore(_root(tmp_path))
    _job(store, status="running")

    assert store.recover_interrupted() == []
    assert store.load("a" * 32)["status"] == "running"


def test_cancel_immediately_blocks_future_promotion(tmp_path: Path) -> None:
    store = CreatorJobStore(_root(tmp_path))
    _job(store, status="running")

    canceled = store.cancel("a" * 32)
    assert canceled["status"] == "canceled"
    assert canceled["cancelRequested"] is True
    with pytest.raises(ValueError, match="cannot complete from canceled"):
        store.complete("a" * 32, task_id="visible-task", output={})


def test_cancel_is_idempotent_for_final_job(tmp_path: Path) -> None:
    store = CreatorJobStore(_root(tmp_path))
    _job(store, status="completed")
    assert store.cancel("a" * 32)["status"] == "completed"


def test_nested_codex_run_path_is_explicitly_retired(tmp_path: Path) -> None:
    store = CreatorJobStore(_root(tmp_path))
    _job(store)
    with pytest.raises(RuntimeError, match="Nested Codex execution is retired"):
        store.run("a" * 32)


def test_plan_validation_loop_stops_after_three_failed_submissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CreatorJobStore(_root(tmp_path))
    job = _job(store, status="running", task_kind="plan")
    job["operatorTaskId"] = "visible-task"
    job["validationAttemptCount"] = 0
    job["validationAttemptHistory"] = []
    store._save(job)

    def reject(_job_value: dict, _output: dict) -> tuple[dict, dict]:
        raise PlanningDecisionError(
            [{"code": "unknown-span-ref", "message": "Unknown span reference."}]
        )

    monkeypatch.setattr(store, "_materialize_plan_output", reject)

    first = store.submit_plan_decisions(
        job["id"], task_id="visible-task", output={}
    )
    second = store.submit_plan_decisions(
        job["id"], task_id="visible-task", output={}
    )
    third = store.submit_plan_decisions(
        job["id"], task_id="visible-task", output={}
    )

    assert first["stage"] == "correction-required"
    assert second["stage"] == "correction-required"
    assert third["status"] == "failed"
    assert third["validationAttemptCount"] == 3
    assert third["decisionValidation"]["remainingAttempts"] == 0
    assert len(third["failedSubmissionRefs"]) == 3
    assert [item["version"] for item in third["failedSubmissionRefs"]] == [1, 2, 3]
    for attempt, diagnostic_ref in enumerate(
        third["validationAttemptHistory"],
        start=1,
    ):
        diagnostic = store._read_artifact(diagnostic_ref)
        assert diagnostic["attempt"] == attempt
        assert diagnostic["submissionRef"] == third["failedSubmissionRefs"][
            attempt - 1
        ]
        assert diagnostic["submissionHash"] == canonical_hash({})


def test_plan_completion_requires_a_validated_submission(tmp_path: Path) -> None:
    store = CreatorJobStore(_root(tmp_path))
    job = _job(store, status="running", task_kind="plan")
    job["operatorTaskId"] = "visible-task"
    store._save(job)

    with pytest.raises(ValueError, match="Submit and validate"):
        store.complete(job["id"], task_id="visible-task", output={})


def test_failed_plan_does_not_freeze_a_locally_valid_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CreatorJobStore(_root(tmp_path))
    job = _job(store, status="running", task_kind="plan")
    job["operatorTaskId"] = "visible-task"
    job["validationAttemptCount"] = 0
    job["validationAttemptHistory"] = []
    store._save(job)

    def reject_second(_job_value: dict, _output: dict) -> tuple[dict, dict]:
        raise PlanningDecisionError(
            [
                {
                    "code": "bad-second-sequence",
                    "sequenceId": "sequence-2",
                    "message": "Second sequence is invalid.",
                }
            ]
        )

    monkeypatch.setattr(store, "_materialize_plan_output", reject_second)
    first_output = {
        "sequences": [
            {"id": "sequence-1", "chapterId": "chapter-1", "value": "accepted"},
            {"id": "sequence-2", "chapterId": "chapter-2", "value": "rejected"},
        ],
        "chapters": [
            {"id": "chapter-1", "value": "accepted"},
            {"id": "chapter-2", "value": "rejected"},
        ],
    }
    first = store.submit_plan_decisions(
        job["id"],
        task_id="visible-task",
        output=first_output,
    )
    assert first["decisionValidation"]["acceptedSequenceIds"] == []
    assert first["decisionValidation"]["acceptedChapterIds"] == []
    assert "acceptedPlanRef" not in first

    changed = json.loads(json.dumps(first_output))
    changed["sequences"][0]["value"] = "rewritten"
    second = store.submit_plan_decisions(
        job["id"],
        task_id="visible-task",
        output=changed,
    )
    assert second["decisionValidation"]["errors"][0]["code"] == (
        "bad-second-sequence"
    )
    assert second["decisionValidation"]["acceptedSequenceIds"] == []


def test_plan_completion_rejects_changes_after_validation(tmp_path: Path) -> None:
    store = CreatorJobStore(_root(tmp_path))
    job = _job(store, status="running", task_kind="plan")
    job["operatorTaskId"] = "visible-task"
    job["stage"] = "decisions-validated"
    job["validatedDecisionHash"] = canonical_hash({"value": "validated"})
    store._save(job)
    output_path = store.jobs_root / job["id"] / "agent-output.json"
    output_path.write_text(json.dumps({"value": "changed"}), encoding="utf-8")

    with pytest.raises(ValueError, match="changed before completion"):
        store.complete(job["id"], task_id="visible-task")


def test_only_a_fully_validated_plan_is_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CreatorJobStore(_root(tmp_path))
    job = _job(store, status="running", task_kind="plan")
    job["operatorTaskId"] = "visible-task"
    job["validationAttemptCount"] = 0
    job["validationAttemptHistory"] = []
    store._save(job)

    monkeypatch.setattr(
        store,
        "_materialize_plan_output",
        lambda _job_value, _output: (
            {"episodeId": "episode", "sequences": []},
            {"receiptHash": "f" * 64},
        ),
    )
    output = {
        "sequences": [{"id": "sequence-1"}],
        "chapters": [{"id": "chapter-1"}],
    }

    validated = store.submit_plan_decisions(
        job["id"],
        task_id="visible-task",
        output=output,
    )

    assert validated["stage"] == "decisions-validated"
    assert validated["acceptedDecisionIds"] == {
        "sequenceIds": ["sequence-1"],
        "chapterIds": ["chapter-1"],
    }
    assert validated["acceptedPlanRef"]["artifactKind"] == (
        "accepted-plan-decisions"
    )


def test_plan_infrastructure_failure_does_not_enter_correction_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CreatorJobStore(_root(tmp_path))
    job = _job(store, status="running", task_kind="plan")
    job["operatorTaskId"] = "visible-task"
    job["validationAttemptCount"] = 0
    job["validationAttemptHistory"] = []
    store._save(job)

    def fail_infrastructure(_job_value: dict, _output: dict) -> tuple[dict, dict]:
        raise RuntimeError("locked catalog unavailable")

    monkeypatch.setattr(store, "_materialize_plan_output", fail_infrastructure)
    failed = store.submit_plan_decisions(
        job["id"],
        task_id="visible-task",
        output={},
    )

    assert failed["status"] == "failed"
    assert failed["validationAttemptCount"] == 0
    assert "infrastructure failed" in failed["error"]
