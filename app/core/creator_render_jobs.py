from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from app.core.creator_project import (
    promote_creator_artifacts,
    transition_creator_project,
    verify_creator_project,
)
from app.core.creator_production import (
    ARTIFACT_SCHEMA_VERSION,
    atomic_write_json,
    canonical_hash,
    create_review_state,
    calculate_localized_invalidation,
    next_artifact_version,
    require_private_root,
    utc_now,
    write_versioned_artifact,
)
from app.core.creator_rendering import (
    augment_build_lock_with_browser_receipts,
    assemble_verified_chapters,
    build_chapter_compositions,
    creator_renderer_environment,
    hyperframes_chapter_render_command,
    plan_chapter_renders,
    record_verified_chapter_render,
    resolve_creator_renderer_assets,
)
from app.core.process_utils import hidden_subprocess_flags


FINAL_RENDER_JOB_STATES = frozenset({"completed", "failed", "canceled", "interrupted"})


class CreatorRenderJobStore:
    def __init__(self, private_root: Path, repository_root: Path):
        self.root = require_private_root(private_root)
        self.repository_root = repository_root.resolve()
        self.jobs_root = self.root / "creator-production" / "render-jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def create(self) -> dict:
        with self._lock:
            verify_creator_project(self.root)
            active = [
                item
                for item in self.list()
                if item["status"] in {"queued", "running", "canceling"}
            ]
            if active:
                raise ValueError(f"A render job is already active: {active[0]['id']}")
            current = self._current()
            if current["state"] != "PREFLIGHT":
                raise ValueError(
                    f"Review rendering requires PREFLIGHT state, found {current['state']}."
                )
            for key in ("episodeManifest", "compiledEpisode", "buildLock"):
                if key not in current["artifacts"]:
                    raise ValueError(f"Review rendering requires current artifact: {key}")
            build = self._read(current["artifacts"]["buildLock"])
            existing_review = current["artifacts"].get("reviewState")
            if existing_review and self._read(existing_review)["buildHash"] == build["buildHash"]:
                raise ValueError(
                    "This exact build already has a final-quality review render."
                )
            job = {
                "schemaVersion": ARTIFACT_SCHEMA_VERSION,
                "id": uuid.uuid4().hex,
                "status": "queued",
                "stage": "queued",
                "value": 0,
                "message": "Final-quality chapter render queued.",
                "buildHash": build["buildHash"],
                "chapterStates": [],
                "outputArtifactRef": None,
                "error": None,
                "cancelRequested": False,
                "createdAt": utc_now(),
                "updatedAt": utc_now(),
            }
            self._save(job)
            return job

    def load(self, job_id: str) -> dict:
        path = self._job_path(job_id)
        if not path.is_file():
            raise ValueError(f"Creator render job does not exist: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        jobs = []
        for path in self.jobs_root.glob("*/job.json"):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(jobs, key=lambda item: item["createdAt"], reverse=True)

    def recover_interrupted(self) -> list[str]:
        recovered = []
        with self._lock:
            for job in self.list():
                if job["status"] in {"running", "canceling"}:
                    job["status"] = "interrupted"
                    job["stage"] = "blocked"
                    job["message"] = "Rendering was interrupted. Verified chapter cache entries remain reusable."
                    job["error"] = "Retry the same build; only missing or unverified chapters will render."
                    job["updatedAt"] = utc_now()
                    self._save(job)
                    recovered.append(job["id"])
        return recovered

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self.load(job_id)
            if job["status"] in FINAL_RENDER_JOB_STATES:
                return job
            job["cancelRequested"] = True
            job["status"] = "canceling"
            job["stage"] = "canceling"
            job["updatedAt"] = utc_now()
            self._save(job)
            process = self._processes.get(job_id)
            if process is not None and process.poll() is None:
                process.terminate()
            return job

    def run(self, job_id: str) -> dict:
        with self._lock:
            job = self.load(job_id)
            if job["status"] != "queued":
                raise ValueError(f"Render job cannot start from {job['status']}.")
            job["status"] = "running"
            job["stage"] = "building-chapters"
            job["message"] = "Building exact standalone chapter compositions."
            job["updatedAt"] = utc_now()
            self._save(job)
        try:
            return self._execute(job)
        except Exception as exc:
            with self._lock:
                failed = self.load(job_id)
                failed["status"] = "canceled" if failed.get("cancelRequested") else "failed"
                failed["stage"] = "canceled" if failed.get("cancelRequested") else "blocked"
                failed["error"] = None if failed.get("cancelRequested") else str(exc)
                failed["message"] = (
                    "Render canceled; verified chapter cache preserved."
                    if failed.get("cancelRequested")
                    else "Render blocked. No review artifact was promoted."
                )
                failed["updatedAt"] = utc_now()
                self._save(failed)
                return failed
        finally:
            with self._lock:
                self._processes.pop(job_id, None)

    def _execute(self, job: dict) -> dict:
        current = self._current()
        verify_creator_project(self.root, current)
        manifest = self._read(current["artifacts"]["episodeManifest"])
        compiled = self._read(current["artifacts"]["compiledEpisode"])
        build_lock = self._read(current["artifacts"]["buildLock"])
        if build_lock["buildHash"] != job["buildHash"]:
            raise ValueError("Render job targets a stale build.")
        compositions = build_chapter_compositions(
            self.root,
            manifest=manifest,
            compiled=compiled,
            build_lock=build_lock,
            locked_cut=self.root / current["lockedCutPath"],
            repository_root=self.repository_root,
        )
        node = shutil.which("node")
        renderer_assets = resolve_creator_renderer_assets(self.repository_root)
        cli = renderer_assets["hyperframesCli"]
        if not node:
            raise RuntimeError("Pinned Node.js and HyperFrames CLI are required for review rendering.")
        renderer_environment = creator_renderer_environment(self.repository_root)
        browser_receipts = {}
        receipt_ids_by_chapter = {}
        existing_browser_ref = current["artifacts"].get("browserPreflight")
        if existing_browser_ref:
            existing_browser_index = self._read(existing_browser_ref)
        else:
            existing_browser_index = None
        browser_is_current = bool(
            existing_browser_index
            and existing_browser_index.get("buildHash") == build_lock["buildHash"]
        )
        if browser_is_current:
            browser_receipts = existing_browser_index["chapters"]
            for chapter_id, reference in browser_receipts.items():
                receipt_ids_by_chapter[chapter_id] = [
                    self._read(reference)["receiptHash"]
                ]
        for chapter_id, composition in (
            {} if browser_is_current else compositions
        ).items():
            chapter = next(item for item in manifest["chapters"] if item["id"] == chapter_id)
            fps_value = manifest["fps"]["numerator"] / manifest["fps"]["denominator"]
            transition_frames = sorted(
                {
                    frame
                    for sequence in manifest["sequences"]
                    if sequence["chapterId"] == chapter_id
                    and sequence["absoluteStartFrame"] > chapter["absoluteStartFrame"]
                    for offset in (-2, -1, 0, 1, 2)
                    for frame in [sequence["absoluteStartFrame"] + offset]
                    if chapter["absoluteStartFrame"]
                    <= frame
                    < chapter["absoluteEndFrameExclusive"]
                }
            )
            at_value = ",".join(
                f"{(frame - chapter['absoluteStartFrame']) / fps_value:.9f}"
                for frame in transition_frames
            )
            command = [
                node,
                str(cli),
                "check",
                str(composition.parent),
                "--json",
                "--at-transitions",
                *(["--at", at_value] if at_value else []),
                "--frame-check=severity=error;seek=.25,.5,.75;tol=0",
                "--strict",
            ]
            checked = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                env=renderer_environment,
                creationflags=hidden_subprocess_flags(),
            )
            if checked.returncode != 0:
                raise RuntimeError(
                    f"HyperFrames browser preflight failed for {chapter_id}: "
                    + (checked.stderr or checked.stdout)[-1200:]
                )
            try:
                report = json.loads(checked.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"HyperFrames browser preflight did not return JSON for {chapter_id}."
                ) from exc
            receipt = {
                "schemaVersion": ARTIFACT_SCHEMA_VERSION,
                "chapterId": chapter_id,
                "manifestHash": build_lock["manifestHash"],
                "compositionSha256": __import__("hashlib").sha256(
                    composition.read_bytes()
                ).hexdigest(),
                "command": {
                    "atTransitions": True,
                    "explicitTransitionFrames": transition_frames,
                    "frameCheck": "severity=error;seek=.25,.5,.75;tol=0",
                    "strict": True,
                },
                "report": report,
                "passed": True,
                "createdAt": utc_now(),
            }
            receipt["receiptHash"] = canonical_hash(receipt)
            version = self._next_artifact_version(
                "browser-preflight-receipts", chapter_id
            )
            reference = write_versioned_artifact(
                self.root,
                artifact_kind="browser-preflight-receipts",
                artifact_id=chapter_id,
                version=version,
                value=receipt,
            )
            browser_receipts[chapter_id] = reference
            receipt_ids_by_chapter[chapter_id] = [receipt["receiptHash"]]
        build_lock = augment_build_lock_with_browser_receipts(
            build_lock,
            manifest=manifest,
            receipt_ids_by_chapter=receipt_ids_by_chapter,
        )
        if browser_is_current:
            build_ref = current["artifacts"]["buildLock"]
            browser_index_ref = existing_browser_ref
        else:
            build_ref = write_versioned_artifact(
                self.root,
                artifact_kind="build-locks",
                artifact_id=current["episodeId"],
                version=self._next_artifact_version("build-locks", current["episodeId"]),
                value=build_lock,
                schema_name="build-lock",
            )
            browser_index = {
                "schemaVersion": ARTIFACT_SCHEMA_VERSION,
                "buildHash": build_lock["buildHash"],
                "chapters": browser_receipts,
                "createdAt": utc_now(),
            }
            browser_index["indexHash"] = canonical_hash(browser_index)
            browser_index_ref = write_versioned_artifact(
                self.root,
                artifact_kind="browser-preflight-indexes",
                artifact_id=current["episodeId"],
                version=self._next_artifact_version(
                    "browser-preflight-indexes", current["episodeId"]
                ),
                value=browser_index,
            )
            promote_creator_artifacts(
                self.root,
                artifact_references={
                    "buildLock": build_ref,
                    "browserPreflight": browser_index_ref,
                },
            )
        with self._lock:
            active = self.load(job["id"])
            active["buildHash"] = build_lock["buildHash"]
            active["stage"] = "browser-preflight-passed"
            active["message"] = "Browser layout, motion, contrast, and transition-boundary gates passed."
            active["updatedAt"] = utc_now()
            self._save(active)
        current = self._current()
        render_profile = {
            "quality": "high",
            "format": "mp4",
            "pictureOnly": True,
            "strict": True,
        }
        chapter_jobs = plan_chapter_renders(
            self.root,
            build_lock=build_lock,
            composition_paths=compositions,
            render_profile=render_profile,
        )
        with self._lock:
            active = self.load(job["id"])
            active["chapterStates"] = [
                {
                    "chapterId": item["chapterId"],
                    "cacheStatus": item["cacheStatus"],
                    "status": "verified" if item["cacheStatus"] == "verified-hit" else "queued",
                }
                for item in chapter_jobs
            ]
            active["stage"] = "rendering-chapters"
            active["updatedAt"] = utc_now()
            self._save(active)
        receipts = []
        for index, chapter_job in enumerate(chapter_jobs):
            if self.load(job["id"]).get("cancelRequested"):
                raise RuntimeError("Render canceled.")
            if chapter_job["cacheStatus"] == "verified-hit":
                receipts.append(
                    json.loads(Path(chapter_job["receiptPath"]).read_text(encoding="utf-8"))
                )
                continue
            output = Path(chapter_job["outputPath"])
            output.parent.mkdir(parents=True, exist_ok=True)
            command = hyperframes_chapter_render_command(
                node_executable=Path(node),
                hyperframes_cli=cli,
                project_directory=Path(chapter_job["compositionPath"]).parent,
                composition_path=Path(chapter_job["compositionPath"]),
                output_path=output,
                fps=(
                    f"{manifest['fps']['numerator']}/{manifest['fps']['denominator']}"
                ),
                quality="high",
            )
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=renderer_environment,
                creationflags=hidden_subprocess_flags(),
            )
            with self._lock:
                self._processes[job["id"]] = process
            _output, _ = process.communicate()
            if process.returncode != 0:
                raise RuntimeError(
                    f"HyperFrames chapter render failed for {chapter_job['chapterId']}: "
                    + (_output or "")[-1200:]
                )
            receipts.append(
                record_verified_chapter_render(
                    self.root,
                    job=chapter_job,
                    render_profile=render_profile,
                    command=command,
                )
            )
            with self._lock:
                active = self.load(job["id"])
                active["chapterStates"][index]["status"] = "verified"
                active["value"] = round(((index + 1) / len(chapter_jobs)) * 85)
                active["message"] = f"Verified chapter {index + 1} of {len(chapter_jobs)}."
                active["updatedAt"] = utc_now()
                self._save(active)
        destination = (
            self.root
            / "creator-production"
            / "review"
            / build_lock["buildHash"]
            / "review.mp4"
        )
        assembly = assemble_verified_chapters(
            self.root,
            receipts=receipts,
            locked_audio_source=self.root / current["lockedCutPath"],
            destination=destination,
            expected_total_frames=manifest["totalFrames"],
            expected_locked_audio_sha256=manifest["lockedAudioSha256"],
            provenance={
                "workflowLockHash": build_lock["workflowLockHash"],
                "resolvedProfileHash": build_lock["resolvedProfileHash"],
                "capabilityCatalogSnapshotHash": build_lock["runtime"][
                    "capabilityCatalogSnapshotHash"
                ],
                "manifestHash": build_lock["manifestHash"],
                "buildHash": build_lock["buildHash"],
                "lockedCutSha256": build_lock["lockedCutSha256"],
                "transcriptSha256": build_lock["transcriptSha256"],
                "wordTimingSha256": build_lock["wordTimingSha256"],
                "runtime": build_lock["runtime"],
                "renderConfiguration": render_profile,
                "browserPreflightIndexHash": self._read(browser_index_ref)[
                    "indexHash"
                ],
            },
        )
        render_ref = write_versioned_artifact(
            self.root,
            artifact_kind="review-render-receipts",
            artifact_id=current["episodeId"],
            version=next_artifact_version(
                self.root, "review-render-receipts", current["episodeId"]
            ),
            value=assembly,
            schema_name="render-receipt",
        )
        existing_review_ref = current["artifacts"].get("reviewState")
        if existing_review_ref:
            existing_review = self._read(existing_review_ref)
        else:
            existing_review = None
        if existing_review and existing_review["buildHash"] == build_lock["buildHash"]:
            review = existing_review
        elif existing_review:
            old_build = self._find_build(existing_review["buildHash"])
            review = create_review_state(episode_id=current["episodeId"], build_lock=build_lock)
            review["revision"] = existing_review["revision"] + 1
            review["approvalRecords"] = existing_review["approvalRecords"]
            review["noteHistory"] = existing_review["noteHistory"]
            review["activeNotes"] = [
                {
                    **note,
                    "buildHash": build_lock["buildHash"],
                    "status": "ready-for-review",
                    "saveStatus": "saved",
                    "savedAt": utc_now(),
                    "supersedesBuildHash": existing_review["buildHash"],
                }
                for note in existing_review["activeNotes"]
            ]
            review["localizedInvalidation"] = calculate_localized_invalidation(
                old_build, build_lock
            )
        else:
            review = create_review_state(episode_id=current["episodeId"], build_lock=build_lock)
        review_ref = write_versioned_artifact(
            self.root,
            artifact_kind="review-states",
            artifact_id=current["episodeId"],
            version=next_artifact_version(
                self.root, "review-states", current["episodeId"]
            ),
            value=review,
            schema_name="review-state",
        )
        promote_creator_artifacts(
            self.root,
            artifact_references={
                "reviewRenderReceipt": render_ref,
                "reviewState": review_ref,
            },
        )
        latest = self._current()
        if latest["state"] == "PREFLIGHT":
            transition_creator_project(
                self.root,
                target_state="REVIEW_READY",
                gate_receipt_refs=[render_ref["sha256"], review_ref["sha256"]],
            )
        with self._lock:
            completed = self.load(job["id"])
            completed["status"] = "completed"
            completed["stage"] = "review-ready"
            completed["value"] = 100
            completed["message"] = "Final-quality review render is ready. Approval will reuse these exact bytes."
            completed["outputArtifactRef"] = render_ref
            completed["updatedAt"] = utc_now()
            self._save(completed)
            return completed

    def _current(self) -> dict:
        return json.loads(
            (self.root / "creator-production" / "current.json").read_text(encoding="utf-8")
        )

    def _read(self, reference: dict) -> dict:
        return json.loads((self.root / reference["path"]).read_text(encoding="utf-8"))

    def _find_build(self, build_hash: str) -> dict:
        builds_root = self.root / "creator-production" / "artifacts" / "build-locks"
        for path in builds_root.rglob("*.json"):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if candidate.get("buildHash") == build_hash:
                return candidate
        raise RuntimeError("Previous review build is unavailable for localized invalidation.")

    def _next_artifact_version(self, artifact_kind: str, artifact_id: str) -> int:
        return next_artifact_version(self.root, artifact_kind, artifact_id)

    def _job_path(self, job_id: str) -> Path:
        if not job_id or any(character not in "0123456789abcdef" for character in job_id):
            raise ValueError("Invalid render job id.")
        return self.jobs_root / job_id / "job.json"

    def _save(self, job: dict) -> None:
        atomic_write_json(self._job_path(job["id"]), job)
