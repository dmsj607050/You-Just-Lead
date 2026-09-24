"""Tests for the external detection-project bridge.

The bridge never trains anything itself: it freezes the user's project source,
runs one reviewed entry point and reads that project's own results.csv back into
the experiment contract.  These tests use a real (tiny) fake entry point and a
real subprocess so the command construction, the CSV contract and the fingerprint
gate are all exercised for real, without a GPU.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agents.analysis_agent import analyze_history
from training.external_detection import (
    PRIMARY_METRIC_COLUMN,
    read_results_csv,
    run_external_detection,
    source_inventory,
)

import sys


FAKE_TRAINER = '''"""A stand-in for the detection project's training entry point."""

import argparse
import csv
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
parser.add_argument("--source-root", required=True)
parser.add_argument("--stage", default="rgb")
parser.add_argument("--weights")
parser.add_argument("--model-config")
parser.add_argument("--train-list")
parser.add_argument("--val-list")
parser.add_argument("--dataset-root")
parser.add_argument("--device")
parser.add_argument("--epochs", type=int, default=1)
parser.add_argument("--batch-size", type=int, default=2)
parser.add_argument("--image-size", type=int, default=640)
parser.add_argument("--workers", type=int, default=0)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--fraction", type=float, default=1.0)
args = parser.parse_args()

assert Path(args.source_root).is_dir()
out = Path(args.output_dir)
out.mkdir(parents=True, exist_ok=True)
with (out / "results.csv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow([
        "epoch", "train/box_loss", "train/cls_loss", "train/dfl_loss",
        "val/box_loss", "val/cls_loss", "val/dfl_loss",
        "metrics/mAP50(B)", "metrics/mAP50-95(B)",
    ])
    writer.writerow([1, 1.5, 2.0, 1.0, 1.4, 1.9, 0.9, 0.3010, 0.1200])
    writer.writerow([2, 1.1, 1.5, 0.8, 1.2, 1.6, 0.7, 0.4210, 0.1875])
(out / "console.log").write_text("fake run\\n", encoding="utf-8")
'''

FAILING_TRAINER = '''"""A stand-in entry point that fails the way a broken run does."""

import sys

print("boom: no CUDA memory", flush=True)
sys.exit(3)
'''


def _project(workspace: Path, trainer: str = FAKE_TRAINER) -> Path:
    """Create a miniature detection project plus one audited data directory."""
    project = workspace / "detection_project"
    (project / "configs").mkdir(parents=True)
    (project / "datasets" / "train").mkdir(parents=True)
    (project / "pretrained_weights").mkdir()
    (project / "runs" / "old_run").mkdir(parents=True)
    (project / "train.py").write_text(trainer, encoding="utf-8")
    (project / "configs" / "aic_rgb.yaml").write_text("names: {}\n", encoding="utf-8")
    # 下面这些都不该进指纹：数据、权重、历史产物。
    (project / "datasets" / "train" / "a.txt").write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    (project / "pretrained_weights" / "yolo26n.pt").write_bytes(b"weights")
    (project / "runs" / "old_run" / "results.csv").write_text("epoch\n1\n", encoding="utf-8")
    return project


def _config(project: Path, data_root: Path, digest: str) -> dict[str, Any]:
    return {
        "data": {"version": "0" * 64, "train_images_dir": str(data_root)},
        "model": {"pretrained_model": "yolo26n.pt"},
        "training": {"runner": "external_detection", "seed": 42, "epochs": 2, "batch_size": 2, "device": "cpu"},
        "validation": {"metric": "map50_95", "direction": "maximize"},
        "external": {
            "project_dir": str(project),
            "source_inventory_sha256": digest,
            "python_executable": sys.executable,
            "stage": "rgb",
            "train_list": "splits/train.txt",
            "val_list": "splits/val.txt",
            "dataset_root": "datasets/ultralytics_aic",
            "epochs": 2,
            "batch_size": 2,
            "image_size": 640,
            "workers": 0,
            "seed": 7,
            "fraction": 0.05,
            "device": "cpu",
            "require_cuda": False,
            "timeout_seconds": 300,
        },
    }


class SourceFingerprintTests(unittest.TestCase):
    def test_fingerprint_covers_source_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = _project(workspace)

            digest, records = source_inventory(project)

            self.assertEqual(len(digest), 64)
            paths = {record["path"] for record in records}
            self.assertIn("train.py", paths)
            self.assertIn("configs/aic_rgb.yaml", paths)
            # 数据、权重、历史产物都不进指纹：否则每次训练都会让上一份复核失效。
            self.assertFalse(any(path.startswith("datasets/") for path in paths))
            self.assertFalse(any(path.startswith("pretrained_weights/") for path in paths))
            self.assertFalse(any(path.startswith("runs/") for path in paths))

    def test_fingerprint_moves_when_the_reviewed_source_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = _project(Path(temporary))
            before, _ = source_inventory(project)

            (project / "train.py").write_text(FAKE_TRAINER + "\n# edited\n", encoding="utf-8")

            after, _ = source_inventory(project)
            self.assertNotEqual(before, after)


class ResultsCsvTests(unittest.TestCase):
    def test_history_is_read_in_epoch_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.csv"
            path.write_text(
                "epoch, train/box_loss, metrics/mAP50(B), metrics/mAP50-95(B)\n"
                "1, 1.5, 0.30, 0.12\n"
                "2, 1.1, 0.42, 0.1875\n",
                encoding="utf-8",
            )

            history, rows = read_results_csv(path)

            self.assertEqual(len(history), 2)
            self.assertEqual(len(rows), 2)
            self.assertEqual(history[0]["epoch"], 1.0)
            # 键带 val_ 前缀：下游诊断按 val_<metric> 取数，裸名会让它 KeyError。
            self.assertAlmostEqual(history[1]["val_map50_95"], 0.1875)
            self.assertAlmostEqual(history[1]["train_box_loss"], 1.1)

    def test_a_csv_without_the_official_metric_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.csv"
            path.write_text("epoch, train/box_loss\n1, 1.5\n", encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                read_results_csv(path)

            self.assertIn(PRIMARY_METRIC_COLUMN, str(caught.exception))


class ExternalDetectionRunTests(unittest.TestCase):
    def test_a_reviewed_fingerprint_is_required_before_anything_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = _project(workspace)
            data_root = workspace / "audited"
            data_root.mkdir()
            config = _config(project, data_root, "a" * 64)

            with self.assertRaises(PermissionError) as caught:
                run_external_detection(config, workspace / "artifacts")

            self.assertIn("source changed", str(caught.exception))
            self.assertFalse((workspace / "artifacts").exists(), "被拦下时不该留下任何产物目录")

    def test_the_bridge_runs_the_entry_point_and_reads_its_metric(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = _project(workspace)
            data_root = workspace / "audited"
            data_root.mkdir()
            digest, _ = source_inventory(project)
            artifact_dir = workspace / "artifacts"
            config = _config(project, data_root, digest)

            outcome = run_external_detection(config, artifact_dir)

            self.assertEqual(outcome["best_epoch"], 2)
            self.assertAlmostEqual(outcome["validation_metric"], 0.1875)
            self.assertAlmostEqual(outcome["metrics"]["val_map50"], 0.4210)
            self.assertEqual(outcome["metrics"]["epochs_scored"], 2.0)
            self.assertEqual(len(outcome["history"]), 2)
            # 诊断代理要按 val_<validation.metric> 取数，且必须有 val_loss 兜底。
            self.assertIn("val_map50_95", outcome["history"][0])
            self.assertIn("val_loss", outcome["history"][0])
            # 产物必须落在这次实验自己的 artifact 目录里，并且真的存在。
            for path in outcome["artifact_paths"]:
                self.assertTrue(Path(path).is_file(), path)
            manifest = json.loads((artifact_dir / "detection_source_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["inventory_sha256"], digest)
            self.assertIn(str(data_root), manifest["command"])
            # 权重只从 model.pretrained_model 来：政策审的键与真正传给训练脚本的参数必须是同一个。
            command = manifest["command"]
            self.assertIn("--weights", command)
            self.assertEqual(command[command.index("--weights") + 1], "yolo26n.pt")

    def test_a_failed_run_reports_the_log_instead_of_a_metric(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = _project(workspace, trainer=FAILING_TRAINER)
            data_root = workspace / "audited"
            data_root.mkdir()
            digest, _ = source_inventory(project)
            config = _config(project, data_root, digest)

            with self.assertRaises(RuntimeError) as caught:
                run_external_detection(config, workspace / "artifacts")

            message = str(caught.exception)
            self.assertIn("exit code 3", message)
            self.assertIn("detection_train.log", message)
            log = (workspace / "artifacts" / "detection_train.log").read_text(encoding="utf-8")
            self.assertIn("no CUDA memory", log)

    def test_the_recorded_history_feeds_the_diagnosis_without_a_key_error(self) -> None:
        """真实踩过的坑：历史键名不合产品约定，诊断代理会 KeyError。

        这条测试钉的是**跨模块约定**，不是字段长相：适配器产出的 history 必须能直接喂给
        `analyze_history`，否则一条跑成功的实验会在记录结果时崩掉。
        """
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = _project(workspace)
            data_root = workspace / "audited"
            data_root.mkdir()
            digest, _ = source_inventory(project)
            config = _config(project, data_root, digest)

            outcome = run_external_detection(config, workspace / "artifacts")

            diagnosis = analyze_history(outcome["history"], "maximize", "map50_95")
            self.assertEqual(diagnosis["best_epoch"], 2)
            self.assertEqual(diagnosis["metric_name"], "val_map50_95")
            self.assertTrue(diagnosis["recommendations"])

    def test_a_metric_the_run_does_not_measure_is_refused_before_the_gpu(self) -> None:
        """配置声明的指标与适配器读的指标对不上时，先卡住，不要先烧 GPU。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = _project(workspace)
            data_root = workspace / "audited"
            data_root.mkdir()
            digest, _ = source_inventory(project)
            config = _config(project, data_root, digest)
            config["validation"]["metric"] = "accuracy"

            with self.assertRaises(ValueError) as caught:
                run_external_detection(config, workspace / "artifacts")

            self.assertIn("validation.metric", str(caught.exception))
            self.assertFalse((workspace / "artifacts").exists(), "被拦下时不该留下任何产物目录")

    def test_a_data_root_outside_the_audited_scope_is_absent_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            project = _project(workspace)
            digest, _ = source_inventory(project)
            config = _config(project, workspace / "nope", digest)

            with self.assertRaises(FileNotFoundError) as caught:
                run_external_detection(config, workspace / "artifacts")

            self.assertIn("train_images_dir", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
