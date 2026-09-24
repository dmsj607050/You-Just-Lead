"""Tests for persisted, read-only data-audit background jobs."""

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
from app.data_audit_scheduler import DataAuditScheduler


class DataAuditSchedulerTests(unittest.TestCase):
    def test_job_profiles_data_and_persists_a_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            data = root / "dataset"
            data.mkdir()
            (data / "train.csv").write_text("id,target\n1,0\n2,1\n", encoding="utf-8")
            scheduler = DataAuditScheduler(root, workspace)

            job = scheduler.submit(data)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status = scheduler.job_status(job["job_id"])
                if status and status["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.03)
            status = scheduler.job_status(job["job_id"])

            self.assertIsNotNone(status)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["summary"]["file_count"], 1)
            self.assertTrue((workspace / "reports" / "data_statistics.json").exists())
            self.assertTrue((workspace / "reports" / "data_audit_jobs" / "DATA-0001.json").exists())

    def test_api_queues_a_selected_local_directory(self) -> None:
        class FakeDataAuditScheduler:
            def __init__(self) -> None:
                self.received: str | None = None

            def submit(self, data_dir: str | None) -> dict:
                self.received = data_dir
                return {"job_id": "DATA-0001", "status": "queued", "data_dir": data_dir}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            scheduler = FakeDataAuditScheduler()
            handler = type(
                "DataAuditApiHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace, "data_audit_scheduler": scheduler},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/data-audit/run",
                    data=json.dumps({"data_dir": "B:/datasets/cup"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:  # nosec B310: local test server
                    payload = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(payload["job_id"], "DATA-0001")
            self.assertEqual(scheduler.received, "B:/datasets/cup")

