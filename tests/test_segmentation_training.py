"""Smoke test for the binary image-segmentation adapter and PNG submission output."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.analysis_agent import analyze_history
from training.segmentation import run_image_segmentation


class SegmentationTrainingTests(unittest.TestCase):
    def test_paired_images_train_and_emit_png_masks(self) -> None:
        try:
            from PIL import Image, ImageDraw
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch and Pillow are required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_dir = root / "train" / "images"
            mask_dir = root / "train" / "masks"
            test_dir = root / "test" / "images"
            image_dir.mkdir(parents=True)
            mask_dir.mkdir(parents=True)
            test_dir.mkdir(parents=True)
            for index in range(6):
                image = Image.new("RGB", (20, 18), color=(15, 20, 25))
                mask = Image.new("L", (20, 18), color=0)
                offset = 2 + index % 3
                ImageDraw.Draw(image).rectangle((offset, 4, offset + 6, 12), fill=(220, 80, 70))
                ImageDraw.Draw(mask).rectangle((offset, 4, offset + 6, 12), fill=255)
                image.save(image_dir / f"sample_{index}.png")
                mask.save(mask_dir / f"sample_{index}.png")
            Image.new("RGB", (20, 18), color=(10, 10, 10)).save(test_dir / "test_a.png")
            Image.new("RGB", (20, 18), color=(30, 30, 30)).save(test_dir / "test_b.png")
            config = {
                "experiment": {"hypothesis": "smoke", "change_type": "baseline"},
                "data": {"version": "smoke-v1", "train_images_dir": str(image_dir), "train_masks_dir": str(mask_dir), "test_images_dir": str(test_dir), "image_size": [16, 16], "validation_fraction": 0.34, "mask_foreground_threshold": 0, "prediction_threshold": 0.5},
                "model": {"base_channels": 2, "dice_loss_weight": 0.5},
                "training": {"runner": "image_segmentation", "seed": 7, "epochs": 2, "batch_size": 2, "num_workers": 0, "device": "cpu"},
                "optimizer": {"learning_rate": 0.01},
                "validation": {"metric": "mean_iou", "direction": "maximize"},
            }

            outcome = run_image_segmentation(config, root / "artifacts")

            self.assertEqual(len(outcome["history"]), 2)
            self.assertIn("val_mean_iou", outcome["metrics"])
            diagnosis = analyze_history(outcome["history"], "maximize", "mean_iou")
            self.assertEqual(diagnosis["metric_name"], "val_mean_iou")
            self.assertTrue((root / "artifacts" / "model.pt").exists())
            self.assertEqual(len(list((root / "artifacts" / "submission_png").glob("*.png"))), 2)


if __name__ == "__main__":
    unittest.main()
