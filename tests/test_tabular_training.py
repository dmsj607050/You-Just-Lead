"""Smoke test for the real CSV tabular training adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from training.tabular import run_tabular_classification


class TabularTrainingTests(unittest.TestCase):
    def test_numeric_csv_training_and_submission(self) -> None:
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train = root / "train.csv"
            test = root / "test.csv"
            rows = ["id,f1,f2,target"]
            for index in range(30):
                first, second = index % 5, (index * 3) % 7
                rows.append(f"{index},{first},{second},{'yes' if first + second > 4 else 'no'}")
            train.write_text("\n".join(rows) + "\n", encoding="utf-8")
            test.write_text("id,f1,f2\nA,1,1\nB,4,6\n", encoding="utf-8")
            config = {
                "experiment": {"hypothesis": "smoke", "change_type": "baseline"},
                "data": {"version": "smoke-v1", "train_csv": str(train), "test_csv": str(test), "target_column": "target", "id_column": "id", "prediction_column": "prediction", "validation_fraction": 0.2},
                "model": {"hidden_dim": 8, "dropout": 0.0},
                "training": {"runner": "tabular_classification", "seed": 12, "epochs": 4, "batch_size": 8, "device": "cpu"},
                "optimizer": {"learning_rate": 0.03},
                "validation": {"metric": "accuracy", "direction": "maximize"},
            }

            outcome = run_tabular_classification(config, root / "artifacts")

            self.assertEqual(len(outcome["history"]), 4)
            self.assertGreaterEqual(outcome["validation_metric"], 0)
            self.assertTrue((root / "artifacts" / "model.pt").exists())
            self.assertTrue((root / "artifacts" / "submission.csv").exists())


if __name__ == "__main__":
    unittest.main()
