"""Discoverable task-adapter catalogue for the competition orchestrator."""

from __future__ import annotations

from typing import Any


RUNNER_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "runner": "synthetic_binary_classification",
        "kind": "infrastructure_smoke_test",
        "task_types": ["synthetic"],
        "template": "configs/baseline_synthetic.yaml",
        "data_contract": "Generated in memory; never use this result as a competition score.",
    },
    {
        "runner": "tabular_classification",
        "kind": "classification",
        "task_types": ["tabular_classification", "binary_classification", "multiclass_classification"],
        "template": "configs/tabular_classification.template.yaml",
        "data_contract": "Numeric train/test CSV plus target and optional ID columns.",
    },
    {
        "runner": "tabular_regression",
        "kind": "regression",
        "task_types": ["tabular_regression", "regression"],
        "template": "configs/tabular_regression.template.yaml",
        "data_contract": "Numeric train/test CSV plus numeric target and optional ID columns.",
    },
    {
        "runner": "image_segmentation",
        "kind": "binary_segmentation",
        "task_types": ["image_segmentation", "semantic_segmentation", "binary_segmentation"],
        "template": "configs/image_segmentation.template.yaml",
        "data_contract": "Train image and binary-mask folders with matching filename stems; optional test-image folder.",
    },
)


def supported_runners() -> list[dict[str, Any]]:
    """Return copies so API clients cannot mutate global capability metadata."""
    return [dict(item) for item in RUNNER_CAPABILITIES]


def recommend_runner(task_type: str | None) -> dict[str, Any] | None:
    """Choose an implemented adapter only for an unambiguous task type."""
    if not task_type:
        return None
    normalized = task_type.strip().lower().replace("-", "_").replace(" ", "_")
    for capability in RUNNER_CAPABILITIES:
        if normalized in capability["task_types"]:
            return dict(capability)
    return None
