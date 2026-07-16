"""Smoke test for the folder-label image-classification adapter."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from agents.analysis_agent import analyze_history
from training.image_classification import run_image_classification


class ImageClassificationTrainingTests(unittest.TestCase):
    def test_folder_labels_train_and_emit_csv_predictions(self) -> None:
        try:
            from PIL import Image, ImageDraw
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch and Pillow are required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train_dir, test_dir = root / "train", root / "test"
            for label, colour in (("amber", (220, 150, 30)), ("indigo", (40, 60, 210))):
                class_dir = train_dir / label
                class_dir.mkdir(parents=True)
                for index in range(3):
                    image = Image.new("RGB", (24, 20), color=(8, 8, 8))
                    ImageDraw.Draw(image).rectangle((3 + index, 4, 18, 16), fill=colour)
                    image.save(class_dir / f"{label}_{index}.png")
            test_dir.mkdir()
            Image.new("RGB", (24, 20), color=(220, 150, 30)).save(test_dir / "test_a.png")
            Image.new("RGB", (24, 20), color=(40, 60, 210)).save(test_dir / "test_b.png")
            config = {
                "experiment": {"hypothesis": "smoke", "change_type": "baseline"},
                "data": {"version": "smoke-v1", "train_images_dir": str(train_dir), "test_images_dir": str(test_dir), "image_size": [16, 16], "validation_fraction": 0.34, "id_column": "id", "prediction_column": "label"},
                "model": {"base_channels": 2, "dropout": 0.0},
                "training": {"runner": "image_classification", "seed": 7, "epochs": 2, "batch_size": 2, "num_workers": 0, "device": "cpu"},
                "optimizer": {"learning_rate": 0.01},
                "validation": {"metric": "accuracy", "direction": "maximize"},
            }

            outcome = run_image_classification(config, root / "artifacts")

            self.assertEqual(len(outcome["history"]), 2)
            self.assertIn("val_accuracy", outcome["metrics"])
            self.assertEqual(analyze_history(outcome["history"], "maximize", "accuracy")["metric_name"], "val_accuracy")
            self.assertTrue((root / "artifacts" / "model.pt").exists())
            with (root / "artifacts" / "submission.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(set(rows[0]), {"id", "label"})


if __name__ == "__main__":
    unittest.main()
