"""Tests for persisted research, approval and paper-generation workflows."""

from __future__ import annotations

import tempfile
import threading
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from app.api_server import CompetitionApiHandler
from app.orchestrator.workflow import workflow_state
from agents.reproduction_agent import intake_repository
from agents.research_agent import search_research
from agents.strategy_agent import recommend_next_actions
from paper.generator import generate_paper_package
from tools.configuration import write_yaml
from tools.files import read_json, write_json_atomic
from tools.submission import validate_submission


class WorkflowExtensionTests(unittest.TestCase):
    def test_submission_validation_requires_approved_rules_and_checks_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            write_yaml(
                workspace / "competition_spec.yaml",
                {
                    "submission": {"format": "csv", "required_columns": ["id", "prediction"], "id_column": "id", "expected_rows": 2},
                    "approval": {"requires_human_confirmation": False},
                },
            )
            candidate = workspace / "submissions" / "candidate.csv"
            candidate.parent.mkdir(parents=True)
            candidate.write_text("id,prediction\nA,0\nB,1\n", encoding="utf-8")

            outcome = validate_submission(workspace, candidate)

            self.assertEqual(outcome["status"], "passed")
            self.assertTrue(outcome["manual_upload_required"])
            self.assertTrue((workspace / "submissions" / "validation" / "candidate.json").exists())

    def test_local_api_reads_dashboard_and_creates_auditable_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            write_yaml(
                workspace / "competition_spec.yaml",
                {
                    "competition": {"name": "API Cup", "task_type": "classification"},
                    "evaluation": {"primary_metric": "accuracy", "direction": "maximize"},
                    "approval": {"requires_human_confirmation": False, "unresolved_questions": []},
                },
            )
            handler = type(
                "TestApiHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/dashboard", timeout=5) as response:  # nosec B310: local test server
                    dashboard = json.loads(response.read())
                request = Request(
                    base + "/api/experiments/drafts",
                    data=json.dumps({"hypothesis": "Use focal loss to improve rare-class recall."}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:  # nosec B310: local test server
                    draft = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(dashboard["competition"]["name"], "API Cup")
            self.assertEqual(draft["status"], "awaiting_human_approval")
            self.assertTrue((workspace / "experiments" / "drafts" / "DRAFT-0001.json").exists())

    def test_research_persists_multiple_sources_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace" / "current"
            fake_sources = {
                "arxiv": lambda query, limit: [{"paper_id": "arxiv:1", "source": "arxiv", "title": "Boundary supervision", "url": "https://arxiv.org/abs/1", "code_url": None}],
                "github": lambda query, limit: [{"paper_id": "github:repo", "source": "github", "title": "Boundary supervision code", "url": "https://github.com/example/repo", "code_url": "https://github.com/example/repo.git"}],
            }
            with patch("agents.research_agent.SOURCES", fake_sources):
                outcome = search_research(workspace, "boundary loss", sources=["arxiv", "github"], limit=3)

            payload = read_json(workspace / "research" / "papers.json")
            self.assertEqual(outcome["records"], 2)
            self.assertEqual(payload["query"], "boundary loss")
            self.assertTrue((workspace / "research" / "research_radar.md").exists())

    def test_reproduction_requires_approval_before_any_clone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            outcome = intake_repository(workspace, "https://github.com/example/repository.git")
            record = read_json(Path(outcome["record_path"]))

            self.assertEqual(outcome["status"], "awaiting_human_approval")
            self.assertFalse(record["approved"])
            self.assertFalse((workspace / "reproductions" / "sources").exists())

    def test_decision_queue_and_tex_are_grounded_in_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace" / "current"
            write_yaml(
                workspace / "competition_spec.yaml",
                {
                    "competition": {"name": "Demo Cup", "task_type": "classification"},
                    "evaluation": {"primary_metric": "accuracy", "direction": "maximize"},
                    "approval": {"requires_human_confirmation": False, "unresolved_questions": []},
                },
            )
            write_json_atomic(workspace / "reports" / "data_statistics.json", {"file_count": 12, "issue_count": 1, "exact_duplicate_groups": []})
            write_json_atomic(
                workspace / "experiments" / "manifests" / "EXP-0001.json",
                {"experiment_id": "EXP-0001", "change_type": "baseline"},
            )
            write_json_atomic(
                workspace / "experiments" / "results" / "EXP-0001.json",
                {
                    "experiment_id": "EXP-0001",
                    "status": "completed",
                    "validation_metric": 0.8,
                    "diagnosis": {"recommendations": ["Try one regularization change."]},
                },
            )
            plan = recommend_next_actions(workspace)
            package = generate_paper_package(workspace)

            tex = Path(package["tex_path"]).read_text(encoding="utf-8")
            evidence = read_json(Path(package["evidence_map"]))
            self.assertTrue(plan["actions"])
            self.assertIn("EXP-0001", tex)
            self.assertIn("0.8", tex)
            self.assertEqual(evidence["claims"][0]["experiment_id"], "EXP-0001")
            self.assertEqual(workflow_state(workspace)["stage"], "evidence_led_iteration")


if __name__ == "__main__":
    unittest.main()
