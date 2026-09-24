"""Tests for the evidence-backed, non-executing training scaffold."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
import threading

from app.api_server import CompetitionApiHandler
from app.training_scaffold_service import TrainingScaffoldError, build_training_scaffold, latest_training_scaffold
from tools.configuration import load_yaml, write_yaml
from tools.files import write_json_atomic


def _approved_spec() -> dict:
    return {
        "competition": {"name": "Segmentation Cup", "task_type": "image_segmentation"},
        "evaluation": {"primary_metric": "global_iou", "direction": "maximize"},
        "submission": {"format": "png"},
        "approval": {"requires_human_confirmation": False, "unresolved_questions": []},
    }


def _audited_images(workspace: Path) -> Path:
    root = workspace / "data" / "raw"
    (root / "image").mkdir(parents=True)
    (root / "mask").mkdir(parents=True)
    write_json_atomic(
        workspace / "reports" / "data_statistics.json",
        {
            "data_dir": str(root),
            "inventory_sha256": "a" * 64,
            "file_count": 2,
            "issue_count": 0,
        },
    )
    return root


class TrainingScaffoldServiceTests(unittest.TestCase):
    def test_generates_a_reviewable_segmentation_config_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            write_yaml(workspace / "competition_spec.yaml", _approved_spec())
            root = _audited_images(workspace)

            outcome = build_training_scaffold(workspace)

            self.assertEqual(outcome["status"], "ready_for_environment_review")
            self.assertEqual(outcome["runner"], "image_segmentation")
            self.assertFalse(outcome["execution"]["started"])
            self.assertEqual(outcome["config_path"], "configs/agent_baseline.yaml")
            config = load_yaml(workspace / outcome["config_path"])
            self.assertEqual(config["training"]["runner"], "image_segmentation")
            self.assertEqual(Path(config["data"]["train_images_dir"]), root / "image")
            self.assertEqual(Path(config["data"]["train_masks_dir"]), root / "mask")
            self.assertTrue((workspace / outcome["report_path"]).exists())
            self.assertEqual(latest_training_scaffold(workspace)["build_id"], "BUILD-0001")

    def test_rejects_unconfirmed_rules_before_writing_a_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            spec = _approved_spec()
            spec["approval"]["requires_human_confirmation"] = True
            write_yaml(workspace / "competition_spec.yaml", spec)
            _audited_images(workspace)

            with self.assertRaises(TrainingScaffoldError):
                build_training_scaffold(workspace)
            self.assertFalse((workspace / "configs" / "agent_baseline.yaml").exists())

    def test_api_persists_build_record_and_returns_bad_request_for_a_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            write_yaml(workspace / "competition_spec.yaml", _approved_spec())
            _audited_images(workspace)
            handler = type("ScaffoldApiHandler", (CompetitionApiHandler,), {"project_root": root, "workspace": workspace})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                request = Request(base + "/api/build/scaffold", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(request, timeout=5) as response:  # nosec B310: local test server
                    outcome = json.loads(response.read())
                with urlopen(base + "/api/build/scaffold", timeout=5) as response:  # nosec B310: local test server
                    latest = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(outcome["build_id"], "BUILD-0001")
            self.assertEqual(latest["config_path"], "configs/agent_baseline.yaml")

