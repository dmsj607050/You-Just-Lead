"""Persisted background executor for explicitly selected research materials.

The scheduler gives public-paper downloads and repository static intake a job
record just like a training run.  It deliberately never runs third-party code.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from agents.materials_agent import intake_selected_materials
from database.ledger import ledger_for_workspace
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


class MaterialSchedulerError(RuntimeError):
    """Raised when a material intake job cannot be submitted or queried."""


class MaterialScheduler:
    """One-at-a-time, persisted static-material intake executor."""

    def __init__(self, project_root: Path, workspace: Path):
        self.project_root = project_root.resolve()
        self.workspace = workspace.resolve()
        self.jobs_dir = self.workspace / "research" / "materials" / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger_for_workspace(self.project_root, self.workspace)
        self._lock = threading.Lock()
        self._active_job_id: str | None = self._recover_active_job_id()

    def submit(self, paper_ids: list[str]) -> dict[str, Any]:
        requested = list(dict.fromkeys(str(item).strip() for item in paper_ids if str(item).strip()))
        if not 1 <= len(requested) <= 12:
            raise MaterialSchedulerError("Select between 1 and 12 research records for intake.")
        with self._lock:
            if self._active_job_id:
                active = self._load_job(self._active_job_id)
                if active and active.get("status") in {"queued", "running"}:
                    raise MaterialSchedulerError(
                        f"Another material intake job is already running: {self._active_job_id}."
                    )
            job = {
                "job_id": self._next_job_id(),
                "status": "queued",
                "paper_ids": requested,
                "created_at": utc_now(),
                "started_at": None,
                "finished_at": None,
                "items": [],
                "report_path": None,
                "markdown_path": None,
                "error": None,
                "safety_note": (
                    "Only user-selected public materials are downloaded. Repositories are cloned "
                    "for static inspection and are never executed by this job."
                ),
            }
            self._save_job(job)
            self._active_job_id = job["job_id"]
            self.ledger.record_event("material_intake_submitted", {"job_id": job["job_id"], "paper_ids": requested})

        threading.Thread(target=self._run_job, args=(job["job_id"],), daemon=True).start()
        return job

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        return self._load_job(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        if not self.jobs_dir.exists():
            return []
        return sorted(
            (read_json(path) for path in self.jobs_dir.glob("MAT-*.json")),
            key=lambda item: str(item.get("job_id", "")),
            reverse=True,
        )

    def active_job(self) -> dict[str, Any] | None:
        return self._load_job(self._active_job_id) if self._active_job_id else None

    def _run_job(self, job_id: str) -> None:
        job = self._load_job(job_id)
        if job is None:
            return
        job["status"] = "running"
        job["started_at"] = utc_now()
        self._save_job(job)
        self.ledger.record_event("material_intake_started", {"job_id": job_id, "paper_ids": job["paper_ids"]})
        try:
            outcome = intake_selected_materials(self.workspace, list(job["paper_ids"]))
            job.update({
                "status": "completed",
                "finished_at": utc_now(),
                "items": outcome["items"],
                "report_path": outcome["report_path"],
                "markdown_path": outcome["markdown_path"],
            })
            self.ledger.record_event(
                "material_intake_finished",
                {
                    "job_id": job_id,
                    "items": len(outcome["items"]),
                    "paper_downloads": sum(item["paper"].get("status") == "downloaded" for item in outcome["items"]),
                    "static_repositories": sum(
                        item["code"].get("status") == "static_inspection_complete" for item in outcome["items"]
                    ),
                },
            )
        except Exception as exc:
            job.update({"status": "failed", "finished_at": utc_now(), "error": f"{type(exc).__name__}: {exc}"})
            self.ledger.record_event("material_intake_failed", {"job_id": job_id, "error": job["error"]})
        finally:
            self._save_job(job)
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def _next_job_id(self) -> str:
        numbers = [
            int(path.stem.split("-", 1)[1])
            for path in self.jobs_dir.glob("MAT-*.json")
            if path.stem.split("-", 1)[1].isdigit()
        ]
        return f"MAT-{max(numbers, default=0) + 1:04d}"

    def _save_job(self, job: dict[str, Any]) -> None:
        write_json_atomic(self.jobs_dir / f"{job['job_id']}.json", job)

    def _load_job(self, job_id: str | None) -> dict[str, Any] | None:
        if not job_id:
            return None
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            return read_json(path)
        except (OSError, ValueError):
            return None

    def _recover_active_job_id(self) -> str | None:
        for job in self.list_jobs():
            if job.get("status") in {"queued", "running"}:
                job.update({
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error": job.get("error") or "Material intake was interrupted by an API process restart.",
                })
                self._save_job(job)
                self.ledger.record_event("material_intake_interrupted", {"job_id": job["job_id"], "error": job["error"]})
        return None
