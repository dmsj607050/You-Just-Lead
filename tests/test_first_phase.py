"""End-to-end tests for the first-phase experiment infrastructure."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.experiment_service import ExperimentService
from app.reporting import generate_reports
from tools.configuration import write_yaml
from tools.files import read_json
from tools.tracking import ExperimentTracker


class FirstPhaseWorkflowTests(unittest.TestCase):
    def test_config_run_ledger_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary) / "project"
            workspace = project_root / "workspace" / "current_competition"
            config_path = workspace / "configs" / "smoke.yaml"
            write_yaml(
                config_path,
                {
                    "experiment": {
                        "hypothesis": "A tiny deterministic run validates the workflow.",
                        "change_type": "baseline",
                    },
                    "data": {
                        "version": "smoke-v1",
                        "synthetic_samples": 96,
                        "synthetic_features": 4,
                        "synthetic_label_noise": 0.2,
                    },
                    "model": {"hidden_dim": 8},
                    "training": {
                        "runner": "synthetic_binary_classification",
                        "seed": 7,
                        "epochs": 3,
                        "batch_size": 16,
                        "device": "cpu",
                    },
                    "optimizer": {"learning_rate": 0.02},
                    "validation": {"metric": "accuracy", "direction": "maximize"},
                },
            )
            service = ExperimentService(project_root, workspace)
            manifest, result = service.run(
                config_path,
                experiment_id="EXP-0001",
                command="python main.py run --experiment-id EXP-0001",
            )

            self.assertEqual(manifest["experiment_id"], "EXP-0001")
            self.assertEqual(result["status"], "completed")
            self.assertIsNotNone(result["validation_metric"])
            self.assertTrue(
                (workspace / "experiments" / "manifests" / "EXP-0001.json").exists()
            )
            stored_result = read_json(workspace / "experiments" / "results" / "EXP-0001.json")
            self.assertEqual(stored_result["status"], "completed")

            report = generate_reports(workspace)
            self.assertEqual(report["best_experiment_id"], "EXP-0001")
            log = (workspace / "experiments" / "EXPERIMENT_LOG.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("EXP-0001", log)
            self.assertTrue(
                (workspace / "experiments" / "tracking" / "mlflow_fallback.jsonl").exists()
            )
            self.assertEqual(len(service.ledger.summaries()), 1)

    def test_native_mlflow_branch_is_used_when_dependency_is_present(self) -> None:
        calls: dict[str, object] = {}

        def set_tracking_uri(value: str) -> None:
            calls["tracking_uri"] = value

        def set_experiment(value: str) -> None:
            calls["experiment"] = value

        def start_run(run_name: str):
            calls["run_name"] = run_name
            return nullcontext()

        def log_params(value: dict[str, str]) -> None:
            calls["params"] = value

        def set_tags(value: dict[str, str]) -> None:
            calls["tags"] = value

        def log_metric(key: str, value: float) -> None:
            calls.setdefault("metrics", []).append((key, value))

        def log_artifacts(value: str) -> None:
            calls["artifacts"] = value

        fake_mlflow = SimpleNamespace(
            set_tracking_uri=set_tracking_uri,
            set_experiment=set_experiment,
            start_run=start_run,
            log_params=log_params,
            set_tags=set_tags,
            log_metric=log_metric,
            log_artifacts=log_artifacts,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "history.json").write_text("{}", encoding="utf-8")
            tracker = ExperimentTracker(root / "tracking")
            with patch.dict("sys.modules", {"mlflow": fake_mlflow}):
                backend = tracker.log_completed_run(
                    {
                        "experiment_id": "EXP-0001",
                        "hypothesis": "verify native tracker",
                        "git": {"commit": "abc123"},
                        "config": {"training": {"epochs": 3}},
                    },
                    {"metrics": {"val_accuracy": 0.8}},
                    artifacts,
                )

        self.assertEqual(backend, "mlflow")
        self.assertEqual(calls["run_name"], "EXP-0001")
        self.assertEqual(calls["experiment"], "current_competition")
        self.assertIn(("val_accuracy", 0.8), calls["metrics"])


if __name__ == "__main__":
    unittest.main()
