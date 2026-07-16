"""Smoke test for the numeric CSV regression adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.analysis_agent import analyze_history
from training.regression import run_tabular_regression


class RegressionTrainingTests(unittest.TestCase):
    def test_numeric_csv_regression_and_submission(self) -> None:
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train = root / "train.csv"
            test = root / "test.csv"
            rows = ["id,x1,x2,target"]
            for index in range(30):
                first, second = index / 10, (index % 7) / 5
                rows.append(f"{index},{first},{second},{2 * first - second + 0.5}")
            train.write_text("\n".join(rows) + "\n", encoding="utf-8")
            test.write_text("id,x1,x2\nA,0.1,0.2\nB,1.2,0.4\n", encoding="utf-8")
            config = {
                "experiment": {"hypothesis": "smoke", "change_type": "baseline"},
                "data": {"version": "smoke-v1", "train_csv": str(train), "test_csv": str(test), "target_column": "target", "id_column": "id", "prediction_column": "prediction", "validation_fraction": 0.2},
                "model": {"hidden_dim": 8, "dropout": 0.0},
                "training": {"runner": "tabular_regression", "seed": 12, "epochs": 4, "batch_size": 8, "device": "cpu"},
                "optimizer": {"learning_rate": 0.03},
                "validation": {"metric": "rmse", "direction": "minimize"},
            }

            outcome = run_tabular_regression(config, root / "artifacts")

            self.assertEqual(len(outcome["history"]), 4)
            self.assertGreaterEqual(outcome["validation_metric"], 0)
            diagnosis = analyze_history(outcome["history"], "minimize", "rmse")
            self.assertEqual(diagnosis["metric_name"], "val_rmse")
            self.assertTrue((root / "artifacts" / "model.pt").exists())
            self.assertTrue((root / "artifacts" / "submission.csv").exists())


if __name__ == "__main__":
    unittest.main()
