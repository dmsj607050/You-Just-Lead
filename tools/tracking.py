"""Experiment tracking with native MLflow when available and a local fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.files import append_jsonl


def _scalar_params(value: Any, prefix: str = "") -> dict[str, str]:
    flattened: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_scalar_params(child, next_prefix))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        flattened[prefix] = str(value)
    return flattened


class ExperimentTracker:
    """Write a completed run into MLflow or a portable local JSONL ledger."""

    def __init__(self, tracking_dir: Path, experiment_name: str = "current_competition"):
        self.tracking_dir = tracking_dir
        self.experiment_name = experiment_name
        self.tracking_dir.mkdir(parents=True, exist_ok=True)

    def log_completed_run(
        self,
        manifest: dict[str, Any],
        result: dict[str, Any],
        artifact_dir: Path,
    ) -> str:
        try:
            import mlflow
        except ImportError:
            append_jsonl(
                self.tracking_dir / "mlflow_fallback.jsonl",
                {
                    "backend": "local-jsonl",
                    "manifest": manifest,
                    "result": result,
                    "artifact_dir": str(artifact_dir),
                },
            )
            return "local-jsonl"

        mlflow.set_tracking_uri(self.tracking_dir.resolve().as_uri())
        mlflow.set_experiment(self.experiment_name)
        with mlflow.start_run(run_name=manifest["experiment_id"]):
            mlflow.log_params(_scalar_params(manifest.get("config", {})))
            mlflow.set_tags(
                {
                    "experiment_id": manifest["experiment_id"],
                    "hypothesis": manifest["hypothesis"],
                    "git_commit": str(manifest["git"].get("commit")),
                }
            )
            for key, value in result.get("metrics", {}).items():
                if isinstance(value, (int, float)):
                    mlflow.log_metric(key, float(value))
            if artifact_dir.exists():
                mlflow.log_artifacts(str(artifact_dir))
        return "mlflow"
