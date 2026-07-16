"""End-to-end tests for the first-phase experiment infrastructure."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.experiment_service import ExperimentService
from app.reporting import generate_reports
from tools.configuration import write_yaml
from tools.files import read_json


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


if __name__ == "__main__":
    unittest.main()
