"""Dispatch reference and future task-specific training runners."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from training.synthetic import run_synthetic_binary_classification
from training.segmentation import run_image_segmentation
from training.regression import run_tabular_regression
from training.tabular import run_tabular_classification


def execute_training(config: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    runner = config["training"]["runner"]
    if runner == "synthetic_binary_classification":
        return run_synthetic_binary_classification(config, artifact_dir)
    if runner == "tabular_classification":
        return run_tabular_classification(config, artifact_dir)
    if runner == "image_segmentation":
        return run_image_segmentation(config, artifact_dir)
    if runner == "tabular_regression":
        return run_tabular_regression(config, artifact_dir)
    raise ValueError(
        f"Unknown training.runner '{runner}'. "
        "Add a task adapter or use synthetic_binary_classification for the smoke test."
    )
