"""Tests for the asynchronous training scheduler and its API endpoints."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from app.api_server import CompetitionApiHandler
from app.training_scheduler import SchedulerError, TrainingScheduler
from tools.configuration import write_yaml
from tools.files import read_json


def _synthetic_config(workspace: Path, name: str = "smoke.yaml") -> Path:
    config_path = workspace / "configs" / name
    write_yaml(
        config_path,
        {
            "experiment": {"hypothesis": "A tiny deterministic run validates the scheduler.", "change_type": "baseline"},
            "data": {"version": "scheduler-smoke-v1", "synthetic_samples": 48, "synthetic_features": 4, "synthetic_label_noise": 0.2},
            "model": {"hidden_dim": 8},
            "training": {"runner": "synthetic_binary_classification", "seed": 7, "epochs": 2, "batch_size": 16, "device": "cpu"},
            "optimizer": {"learning_rate": 0.02},
            "validation": {"metric": "accuracy", "direction": "maximize"},
        },
    )
    return config_path


def _wait_for_job(scheduler: TrainingScheduler, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = scheduler.job_status(job_id)
        if job and job.get("status") not in ("queued", "running"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"Job {job_id} did not finish within {timeout}s")


class TrainingSchedulerTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "workspace" / "current_competition"
        for sub in ("configs", "reports", "experiments/manifests", "experiments/results", "experiments/artifacts", "experiments/tracking", "experiments/drafts", "experiments/approvals", "experiments/jobs", "models", "input", "data/raw", "data/interim", "data/processed", "docs", "research", "reproductions", "submissions/validation"):
            (workspace / sub).mkdir(parents=True, exist_ok=True)
        (root / "database").mkdir(parents=True, exist_ok=True)
        return workspace

    def test_submit_runs_synthetic_job_to_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            config_path = _synthetic_config(workspace)
            scheduler = TrainingScheduler(root, workspace)
            job = scheduler.submit(config_path)
            self.assertEqual(job["status"], "queued")
            self.assertTrue(job["job_id"].startswith("JOB-"))
            finished = _wait_for_job(scheduler, job["job_id"])
            self.assertEqual(finished["status"], "completed")
            self.assertIsNotNone(finished["experiment_id"])
            self.assertIsNotNone(finished["validation_metric"])
            result_path = workspace / "experiments" / "results" / f"{finished['experiment_id']}.json"
            self.assertTrue(result_path.exists())

    def test_submit_rejects_missing_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            scheduler = TrainingScheduler(root, workspace)
            with self.assertRaises(SchedulerError):
                scheduler.submit(workspace / "configs" / "nonexistent.yaml")

    def test_only_one_active_job_at_a_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            config_a = _synthetic_config(workspace, "a.yaml")
            config_b = _synthetic_config(workspace, "b.yaml")
            scheduler = TrainingScheduler(root, workspace)
            job_a = scheduler.submit(config_a)
            try:
                with self.assertRaises(SchedulerError):
                    scheduler.submit(config_b)
            finally:
                _wait_for_job(scheduler, job_a["job_id"])

    def test_job_status_returns_none_for_unknown_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            scheduler = TrainingScheduler(root, workspace)
            self.assertIsNone(scheduler.job_status("JOB-9999"))

    def test_list_jobs_returns_all_in_reverse_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            config = _synthetic_config(workspace)
            scheduler = TrainingScheduler(root, workspace)
            job_a = scheduler.submit(config)
            _wait_for_job(scheduler, job_a["job_id"])
            job_b = scheduler.submit(config)
            _wait_for_job(scheduler, job_b["job_id"])
            jobs = scheduler.list_jobs()
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["job_id"], "JOB-0002")
            self.assertEqual(jobs[1]["job_id"], "JOB-0001")

    def test_failed_job_records_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            config_path = workspace / "configs" / "broken.yaml"
            write_yaml(config_path, {
                "experiment": {"hypothesis": "broken config"},
                "data": {"version": "v1"},
                "training": {"runner": "nonexistent_runner", "seed": 1, "epochs": 1, "batch_size": 1, "device": "cpu"},
                "validation": {"metric": "accuracy", "direction": "maximize"},
            })
            scheduler = TrainingScheduler(root, workspace)
            job = scheduler.submit(config_path)
            finished = _wait_for_job(scheduler, job["job_id"])
            self.assertEqual(finished["status"], "failed")
            self.assertIsNotNone(finished["error"])

    def test_recovery_marks_interrupted_job_as_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            jobs_dir = workspace / "experiments" / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            from tools.files import write_json_atomic
            write_json_atomic(jobs_dir / "JOB-0001.json", {
                "job_id": "JOB-0001",
                "status": "running",
                "config_path": str(workspace / "configs" / "x.yaml"),
                "created_at": "2026-01-01T00:00:00Z",
                "started_at": "2026-01-01T00:00:01Z",
                "finished_at": None,
                "experiment_id": None,
                "validation_metric": None,
                "error": None,
            })
            scheduler = TrainingScheduler(root, workspace)
            recovered = scheduler.job_status("JOB-0001")
            self.assertEqual(recovered["status"], "failed")
            self.assertIn("interrupted", recovered["error"].lower())


class TrainingSchedulerApiTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "workspace" / "current"
        for sub in ("configs", "reports", "experiments/manifests", "experiments/results", "experiments/artifacts", "experiments/tracking", "experiments/drafts", "experiments/approvals", "experiments/jobs", "models", "input", "data/raw", "data/interim", "data/processed", "docs", "research", "reproductions", "submissions/validation"):
            (workspace / sub).mkdir(parents=True, exist_ok=True)
        (root / "database").mkdir(parents=True, exist_ok=True)
        return workspace

    def test_execute_endpoint_submits_and_completes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            config_path = _synthetic_config(workspace)
            handler = type(
                "TestApiHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace},
            )
            from app.training_scheduler import TrainingScheduler
            handler.scheduler = TrainingScheduler(root, workspace)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                request = Request(
                    base + "/api/experiments/execute",
                    data=json.dumps({"config_path": "configs/smoke.yaml"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=15) as response:  # nosec B310
                    job = json.loads(response.read())
                self.assertEqual(response.status, 202)
                self.assertTrue(job["job_id"].startswith("JOB-"))
                deadline = time.time() + 60
                status = None
                while time.time() < deadline:
                    try:
                        with urlopen(base + f"/api/experiments/jobs/{job['job_id']}", timeout=15) as r:  # nosec B310
                            status = json.loads(r.read())
                    except Exception:
                        time.sleep(0.2)
                        continue
                    if status.get("status") not in ("queued", "running"):
                        break
                    time.sleep(0.2)
                self.assertIsNotNone(status)
                self.assertEqual(status["status"], "completed")
                with urlopen(base + "/api/experiments/jobs", timeout=15) as r:  # nosec B310
                    jobs_payload = json.loads(r.read())
                self.assertEqual(len(jobs_payload["jobs"]), 1)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
                time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()
