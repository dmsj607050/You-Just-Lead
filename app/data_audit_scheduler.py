"""Persisted background execution for deterministic, read-only data audits."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from agents.data_agent import audit_dataset
from database.ledger import ExperimentLedger
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


class DataAuditSchedulerError(RuntimeError):
    """Raised when an audit job cannot be safely submitted or queried."""


class DataAuditScheduler:
    """One-at-a-time audit worker which never mutates the supplied raw data."""

    def __init__(self, project_root: Path, workspace: Path):
        self.project_root = project_root.resolve()
        self.workspace = workspace.resolve()
        self.jobs_dir = self.workspace / "reports" / "data_audit_jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = ExperimentLedger(self.project_root / "database" / "competition_agent.sqlite")
        self._lock = threading.Lock()
        self._active_job_id: str | None = self._recover_active_job_id()

    def submit(self, data_dir: str | Path | None) -> dict[str, Any]:
        root = self._validated_data_dir(data_dir)
        with self._lock:
            if self._active_job_id:
                active = self._load_job(self._active_job_id)
                if active and active.get("status") in {"queued", "running"}:
                    raise DataAuditSchedulerError(f"Another data audit is already running: {self._active_job_id}.")
            job = {
                "job_id": self._next_job_id(),
                "status": "queued",
                "data_dir": str(root),
                "created_at": utc_now(),
                "started_at": None,
                "finished_at": None,
                "summary": None,
                "error": None,
                "safety_note": "The audit reads source files and writes reports only inside the competition workspace; raw data is never modified.",
            }
            self._save_job(job)
            self._active_job_id = str(job["job_id"])
            self.ledger.record_event("data_audit_submitted", {"job_id": job["job_id"], "data_dir": str(root)})
        threading.Thread(target=self._run_job, args=(str(job["job_id"]),), daemon=True).start()
        return job

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        return self._load_job(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        return sorted(
            (read_json(path) for path in self.jobs_dir.glob("DATA-*.json")),
            key=lambda item: str(item.get("job_id", "")),
            reverse=True,
        )

    def active_job(self) -> dict[str, Any] | None:
        return self._load_job(self._active_job_id) if self._active_job_id else None

    def _run_job(self, job_id: str) -> None:
        job = self._load_job(job_id)
        if job is None:
            return
        job.update({"status": "running", "started_at": utc_now()})
        self._save_job(job)
        self.ledger.record_event("data_audit_started", {"job_id": job_id, "data_dir": job["data_dir"]})
        try:
            report = audit_dataset(self.workspace, Path(str(job["data_dir"])))
            summary = {
                "file_count": report["file_count"],
                "issue_count": report["issue_count"],
                "inventory_sha256": report["inventory_sha256"],
                "file_kinds": report["file_kinds"],
                "splits": report["splits"],
            }
            job.update({"status": "completed", "finished_at": utc_now(), "summary": summary})
            self.ledger.record_event("data_audit_finished", {"job_id": job_id, **summary})
        except Exception as exc:
            job.update({"status": "failed", "finished_at": utc_now(), "error": f"{type(exc).__name__}: {exc}"})
            self.ledger.record_event("data_audit_failed", {"job_id": job_id, "error": job["error"]})
        finally:
            self._save_job(job)
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def _validated_data_dir(self, value: str | Path | None) -> Path:
        raw = str(value or self.workspace / "data" / "raw").strip()
        if not raw:
            raise DataAuditSchedulerError("Provide a local data directory to audit.")
        if raw.startswith("\\\\"):
            raise DataAuditSchedulerError("Network-share data paths are not accepted for local audits; copy or mount data locally first.")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (self.workspace / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.parent == candidate:
            raise DataAuditSchedulerError("Refusing to audit a filesystem root; choose the competition dataset directory instead.")
        if not candidate.is_dir():
            raise DataAuditSchedulerError(f"Data directory does not exist or is not a directory: {candidate}")
        return candidate

    def _next_job_id(self) -> str:
        numbers = [
            int(path.stem.split("-", 1)[1])
            for path in self.jobs_dir.glob("DATA-*.json")
            if path.stem.split("-", 1)[1].isdigit()
        ]
        return f"DATA-{max(numbers, default=0) + 1:04d}"

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
                    "error": job.get("error") or "Data audit was interrupted by an API process restart.",
                })
                self._save_job(job)
                self.ledger.record_event("data_audit_interrupted", {"job_id": job["job_id"], "error": job["error"]})
        return None
