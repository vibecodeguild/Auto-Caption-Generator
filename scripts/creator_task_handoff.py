from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.creator_jobs import CreatorJobStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Claim, resolve application-owned planning references, validate, and "
            "complete a Creator Production job from this visible Codex task."
        )
    )
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--job", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")

    claim = subparsers.add_parser("claim")
    claim.add_argument("--task-id", required=True)
    claim.add_argument("--visible-skill", action="append", default=[])

    resolve_span = subparsers.add_parser("resolve-span")
    resolve_span.add_argument("--task-id", required=True)
    resolve_span.add_argument("--proposition-id", required=True)
    resolve_span.add_argument("--phrase", required=True)
    resolve_span.add_argument("--candidate-ref")

    submit = subparsers.add_parser("submit-decisions")
    submit.add_argument("--task-id", required=True)
    submit.add_argument("--output", required=True, type=Path)

    complete = subparsers.add_parser("complete")
    complete.add_argument("--task-id", required=True)
    complete.add_argument("--output", type=Path)
    complete.add_argument("--technical-capability", action="append", default=[])

    fail = subparsers.add_parser("fail")
    fail.add_argument("--task-id", required=True)
    fail.add_argument("--error", required=True)

    subparsers.add_parser("cancel")
    return parser


def main() -> int:
    args = _parser().parse_args()
    store = CreatorJobStore(args.project)
    if args.command == "status":
        result = store.handoff(args.job)
    elif args.command == "claim":
        result = store.claim(
            args.job,
            task_id=args.task_id,
            visible_skill_ids=args.visible_skill,
        )
    elif args.command == "resolve-span":
        result = store.resolve_spoken_span(
            args.job,
            task_id=args.task_id,
            proposition_id=args.proposition_id,
            exact_phrase=args.phrase,
            candidate_ref=args.candidate_ref,
        )
    elif args.command == "submit-decisions":
        result = store.submit_plan_decisions(
            args.job,
            task_id=args.task_id,
            output=json.loads(args.output.read_text(encoding="utf-8")),
        )
    elif args.command == "complete":
        output = None
        if args.output:
            output = json.loads(args.output.read_text(encoding="utf-8"))
        result = store.complete(
            args.job,
            task_id=args.task_id,
            output=output,
            technical_capability_ids=args.technical_capability,
        )
    elif args.command == "fail":
        result = store.fail(args.job, task_id=args.task_id, error=args.error)
    else:
        result = store.cancel(args.job)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") not in {"failed", "interrupted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
