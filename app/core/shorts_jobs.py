"""Background jobs scoped to a private project and short, with durable status."""
from __future__ import annotations

import copy
import subprocess
import threading
import uuid

from app.core.process_utils import terminate_process_tree
from app.core.shorts import ShortsProject, execute, now, read_json, write_json
from app.core.video_cutter import CutCanceled


class ShortsJob:
    def __init__(self, project: ShortsProject, short: dict, operation: str):
        self.id = uuid.uuid4().hex
        self.project = project
        self.short = copy.deepcopy(short)
        self.operation = operation
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.data = {"id": self.id, "shortId": short["id"], "operation": operation,
                     "status": "running", "value": 0, "message": "Starting…", "error": None,
                     "result": None, "createdAt": now(), "updatedAt": now()}
        self.receipt = project.path(f"shorts/{short['id']}/job.json")
        self.persist()

    def persist(self):
        write_json(self.receipt, self.data)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def update(self, value, message):
        with self.lock:
            self.data.update(value=value, message=message, updatedAt=now())
            self.persist()

    def set_process(self, process):
        with self.lock:
            self.process = process
            if self.cancel.is_set():
                terminate_process_tree(process)

    def check(self):
        if self.cancel.is_set():
            raise CutCanceled("Shorts operation canceled. Previous outputs were preserved.")

    def request_cancel(self):
        with self.lock:
            if self.data["status"] in ("running", "canceling"):
                self.cancel.set()
                self.data.update(status="canceling", message="Canceling… Transcription stops after the current local inference returns.", updatedAt=now())
                self.persist()
                terminate_process_tree(self.process)
            return self.snapshot()

    def run(self):
        try:
            result = execute(self.project, self.short, self.operation, self)
            with self.lock:
                self.data.update(status="complete", value=100,
                                 message=f"Short ready. {result.get('transcriptionNotice', '')}".strip(), result=result)
        except CutCanceled as exc:
            with self.lock:
                self.data.update(status="canceled", message=str(exc))
        except Exception as exc:
            with self.lock:
                self.data.update(status="failed", error=str(exc), message=str(exc))
        finally:
            with self.lock:
                self.data["updatedAt"] = now()
                self.persist()


class ShortsJobs:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs: dict[tuple[str, str], ShortsJob] = {}

    def active(self, project: ShortsProject, short_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get((str(project.root), short_id))
            if job:
                return job.snapshot()
            receipt = read_json(project.path(f"shorts/{short_id}/job.json"))
            if receipt and receipt.get("status") in ("running", "canceling"):
                receipt.update(status="failed", error="The application restarted before this operation completed. Run it again.", message="Interrupted by application restart.", updatedAt=now())
                write_json(project.path(f"shorts/{short_id}/job.json"), receipt)
            return receipt

    def start(self, project: ShortsProject, short_id: str, operation: str) -> dict:
        if operation not in ("assemble", "captions", "export"):
            raise ValueError("Choose assemble, captions, or export.")
        with self.lock, project.lock:
            short = project.find(project.load(), short_id)
            key = (str(project.root), short_id)
            previous = self.jobs.get(key)
            if previous and previous.snapshot()["status"] in ("running", "canceling"):
                if previous.operation != operation:
                    raise ValueError("Wait for the current short operation or cancel it first.")
                return previous.snapshot()
            job = ShortsJob(project, short, operation)
            self.jobs[key] = job
            threading.Thread(target=job.run, name=f"shorts-{job.id[:8]}", daemon=True).start()
            return job.snapshot()

    def cancel_job(self, project: ShortsProject, short_id: str, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get((str(project.root), short_id))
            if not job or job.id != job_id:
                raise ValueError("This job is no longer active in this project.")
            return job.request_cancel()


jobs = ShortsJobs()
