"""Asynchronous training scheduler for the local Competition Agent.

Submits approved training configurations to a background thread so the API can
return immediately instead of blocking on a long-running GPU job. Job state is
persisted to ``experiments/jobs/`` so it survives API restarts and can be
queried by the dashboard.

The scheduler does NOT bypass any approval gate. ``ExperimentService.run`` still
verifies GPU approvals, rule readiness and data audit integrity before
executing. If any of those checks fail, the job is marked failed with the
reason recorded in the job file and the ledger.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.experiment_service import ExperimentService
from database.ledger import ExperimentLedger
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


class SchedulerError(RuntimeError):
    """Raised when a training job cannot be submitted or queried."""


class TrainingScheduler:
    """Single-slot background training executor grounded in persisted state."""

    def __init__(self, project_root: Path, workspace: Path):
        self.project_root = project_root.resolve()
        self.workspace = workspace.resolve()
        self.jobs_dir = self.workspace / "experiments" / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = ExperimentLedger(self.project_root / "database" / "competition_agent.sqlite")
        self._lock = threading.Lock()
        self._active_job_id: str | None = self._recover_active_job_id()

    def submit(
        self,
        config_path: Path,
        *,
        hypothesis: str | None = None,
        parent_id: str | None = None,
        command: str = "",
    ) -> dict[str, Any]:
        """Queue a training job. Returns the initial job record."""
        config_path = config_path.resolve() if not config_path.is_absolute() else config_path
        if not config_path.is_file():
            raise SchedulerError(f"Configuration does not exist: {config_path}")

        with self._lock:
            if self._active_job_id is not None:
                active = self._load_job(self._active_job_id)
                if active and active.get("status") in ("queued", "running"):
                    raise SchedulerError(
                        f"Another training job is already running: {self._active_job_id}. "
                        "Wait for it to finish or check its status before submitting again."
                    )
            job_id = self._next_job_id()
            resolved_command = command or self._default_command(config_path)
            job: dict[str, Any] = {
                "job_id": job_id,
                "status": "queued",
                "config_path": str(config_path),
                "hypothesis": hypothesis,
                "parent_id": parent_id,
                "command": resolved_command,
                "created_at": utc_now(),
                "started_at": None,
                "finished_at": None,
                "experiment_id": None,
                "validation_metric": None,
                "error": None,
                "safety_note": "Job execution honours the same approval and rule gates as `python main.py run`.",
            }
            self._save_job(job)
            self._active_job_id = job_id
            self.ledger.record_event(
                "training_job_submitted",
                {"job_id": job_id, "config_path": str(config_path)},
            )

        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return job

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        return self._load_job(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        if not self.jobs_dir.exists():
            return []
        return sorted(
            (read_json(path) for path in self.jobs_dir.glob("JOB-*.json")),
            key=lambda item: str(item.get("job_id", "")),
            reverse=True,
        )

    def active_job(self) -> dict[str, Any] | None:
        if self._active_job_id is None:
            return None
        return self._load_job(self._active_job_id)

    def _run_job(self, job_id: str) -> None:
        job = self._load_job(job_id)
        if job is None:
            return
        job["status"] = "running"
        job["started_at"] = utc_now()
        self._save_job(job)
        self.ledger.record_event(
            "training_job_started",
            {"job_id": job_id, "config_path": job["config_path"]},
        )
        try:
            service = ExperimentService(self.project_root, self.workspace)
            config_path = Path(job["config_path"])
            manifest, result = service.run(
                config_path,
                hypothesis=job.get("hypothesis"),
                parent_id=job.get("parent_id"),
                command=job.get("command") or "",
            )
            job["experiment_id"] = manifest["experiment_id"]
            job["validation_metric"] = result.get("validation_metric")
            job["status"] = "completed" if result.get("status") == "completed" else "failed"
            job["finished_at"] = utc_now()
            if result.get("status") != "completed":
                job["error"] = result.get("error") or result.get("conclusion")
            self.ledger.record_event(
                "training_job_finished",
                {
                    "job_id": job_id,
                    "experiment_id": manifest["experiment_id"],
                    "status": job["status"],
                    "validation_metric": job["validation_metric"],
                },
            )
        except Exception as exc:
            job["status"] = "failed"
            job["finished_at"] = utc_now()
            job["error"] = f"{type(exc).__name__}: {exc}"
            self.ledger.record_event(
                "training_job_failed",
                {"job_id": job_id, "error": job["error"]},
            )
        finally:
            self._save_job(job)
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def _default_command(self, config_path: Path) -> str:
        try:
            relative = config_path.relative_to(self.workspace)
        except ValueError:
            relative = config_path
        return f"python main.py run --config {relative}"

    def _next_job_id(self) -> str:
        existing = [path.stem for path in self.jobs_dir.glob("JOB-*.json")]
        numbers = [int(name.split("-", 1)[1]) for name in existing if name.split("-", 1)[1].isdigit()]
        return f"JOB-{max(numbers, default=0) + 1:04d}"

    def _save_job(self, job: dict[str, Any]) -> None:
        write_json_atomic(self.jobs_dir / f"{job['job_id']}.json", job)

    def _load_job(self, job_id: str) -> dict[str, Any] | None:
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            return read_json(path)
        except (OSError, ValueError):
            return None

    def _recover_active_job_id(self) -> str | None:
        """Mark a previously-running job as failed if the API process was restarted."""
        for job in self.list_jobs():
            if job.get("status") in ("queued", "running"):
                job["status"] = "failed"
                job["finished_at"] = utc_now()
                if not job.get("error"):
                    job["error"] = "Job was interrupted by an API process restart."
                self._save_job(job)
                self.ledger.record_event(
                    "training_job_interrupted",
                    {"job_id": job["job_id"], "error": job["error"]},
                )
                return None
        return None
