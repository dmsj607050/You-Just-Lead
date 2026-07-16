"""Application service for a complete config-to-ledger experiment run."""

from __future__ import annotations

import re
import time
import traceback
from pathlib import Path
from typing import Any

from agents.analysis_agent import analyze_history
from app.approval_service import verify_training_config_approval
from database.ledger import ExperimentLedger
from schemas.experiment import ExperimentManifest, ExperimentResult
from tools.configuration import get_mapping, load_yaml, require_experiment_config, write_yaml
from tools.files import write_json_atomic
from tools.provenance import environment_snapshot, file_sha256, git_provenance, utc_now
from tools.tracking import ExperimentTracker
from training.runner import execute_training


def ensure_workspace_layout(workspace: Path) -> None:
    """Create only the directories needed by the first-phase runtime."""
    for relative_path in (
        "configs",
        "reports",
        "experiments/manifests",
        "experiments/results",
        "experiments/artifacts",
        "experiments/tracking",
        "experiments/drafts",
        "experiments/approvals",
        "submissions/validation",
        "models",
        "input",
        "data/raw",
        "data/interim",
        "data/processed",
        "docs",
        "research",
        "reproductions",
    ):
        (workspace / relative_path).mkdir(parents=True, exist_ok=True)


def next_experiment_id(workspace: Path) -> str:
    numbers: list[int] = []
    for record in (workspace / "experiments" / "manifests").glob("EXP-*.json"):
        match = re.fullmatch(r"EXP-(\d+)", record.stem)
        if match:
            numbers.append(int(match.group(1)))
    return f"EXP-{(max(numbers, default=0) + 1):04d}"


class ExperimentService:
    """Runs one approved experiment and persists every observable outcome."""

    def __init__(self, project_root: Path, workspace: Path):
        self.project_root = project_root.resolve()
        self.workspace = workspace.resolve()
        ensure_workspace_layout(self.workspace)
        self.ledger = ExperimentLedger(self.project_root / "database" / "competition_agent.sqlite")
        self.tracker = ExperimentTracker(self.workspace / "experiments" / "tracking")

    def _require_real_training_preflight(self, config: dict[str, Any], config_path: Path) -> None:
        """Block real-data runs until rule and data evidence are available."""
        runner = str(get_mapping(config, "training").get("runner", ""))
        if runner == "synthetic_binary_classification":
            return
        spec_path = self.workspace / "competition_spec.yaml"
        if not spec_path.exists():
            raise PermissionError(
                "Real training requires competition_spec.yaml. Analyze official rules first."
            )
        spec = load_yaml(spec_path)
        if spec.get("approval", {}).get("requires_human_confirmation", True):
            raise PermissionError(
                "Real training is blocked until official rules receive human confirmation."
            )
        if not (self.workspace / "reports" / "data_statistics.json").exists():
            raise PermissionError(
                "Real training is blocked until the deterministic data audit is complete."
            )
        requested_device = str(get_mapping(config, "training").get("device", "cpu"))
        if requested_device.startswith("cuda"):
            verify_training_config_approval(self.workspace, config_path)

    def run(
        self,
        config_path: Path,
        *,
        experiment_id: str | None = None,
        hypothesis: str | None = None,
        parent_id: str | None = None,
        command: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        config_path = config_path.resolve()
        config = load_yaml(config_path)
        require_experiment_config(config)
        self._require_real_training_preflight(config, config_path)
        experiment_config = get_mapping(config, "experiment")
        training_config = get_mapping(config, "training")
        data_config = get_mapping(config, "data")
        validation_config = get_mapping(config, "validation")

        resolved_id = experiment_id or next_experiment_id(self.workspace)
        manifest_path = self.workspace / "experiments" / "manifests" / f"{resolved_id}.json"
        if manifest_path.exists():
            raise FileExistsError(f"Experiment already exists: {resolved_id}")

        try:
            stored_config_path = str(config_path.relative_to(self.workspace))
        except ValueError:
            stored_config_path = str(config_path)

        manifest = ExperimentManifest(
            experiment_id=resolved_id,
            hypothesis=hypothesis
            or str(experiment_config.get("hypothesis") or "Establish a reproducible baseline."),
            config_path=stored_config_path,
            config_sha256=file_sha256(config_path),
            parent_id=parent_id or experiment_config.get("parent_id"),
            change_type=str(experiment_config.get("change_type", "baseline")),
            data_version=str(data_config.get("version", "unversioned")),
            seed=training_config.get("seed"),
            command=command,
            git=git_provenance(self.project_root),
            environment=environment_snapshot(),
            config=config,
            expected_improvement=experiment_config.get("expected_improvement"),
            estimated_gpu_hours=experiment_config.get("estimated_gpu_hours"),
            rollback_plan=experiment_config.get("rollback_plan"),
        ).to_dict()
        write_json_atomic(manifest_path, manifest)
        self.ledger.save_manifest(manifest)

        started_at = utc_now()
        started = time.perf_counter()
        artifact_dir = self.workspace / "experiments" / "artifacts" / resolved_id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        write_yaml(artifact_dir / "config_snapshot.yaml", config)

        try:
            output = execute_training(config, artifact_dir)
            history = output["history"]
            write_json_atomic(artifact_dir / "history.json", {"history": history})
            diagnosis = analyze_history(
                history,
                str(validation_config.get("direction", "maximize")),
                str(validation_config.get("metric", "accuracy")),
            )
            result = ExperimentResult(
                experiment_id=resolved_id,
                status="completed",
                started_at=started_at,
                finished_at=utc_now(),
                best_epoch=output["best_epoch"],
                validation_metric=float(output["validation_metric"]),
                metrics={key: float(value) for key, value in output["metrics"].items()},
                runtime_seconds=round(time.perf_counter() - started, 3),
                peak_gpu_memory_gb=output["peak_gpu_memory_gb"],
                diagnosis=diagnosis,
                conclusion=(
                    f"Baseline completed with validation metric "
                    f"{float(output['validation_metric']):.4f}."
                ),
                decision="keep_as_candidate",
                next_candidates=diagnosis["recommendations"],
                artifact_paths=output["artifact_paths"]
                + [str(artifact_dir / "history.json"), str(artifact_dir / "config_snapshot.yaml")],
            ).to_dict()
            result["tracker_backend"] = self.tracker.log_completed_run(
                manifest, result, artifact_dir
            )
        except Exception as exc:
            result = ExperimentResult(
                experiment_id=resolved_id,
                status="failed",
                started_at=started_at,
                finished_at=utc_now(),
                best_epoch=None,
                validation_metric=None,
                metrics={},
                runtime_seconds=round(time.perf_counter() - started, 3),
                peak_gpu_memory_gb=None,
                diagnosis={},
                conclusion="Experiment failed before producing validated results.",
                decision="reject",
                next_candidates=["Inspect the captured error before retrying."],
                artifact_paths=[],
                error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
            ).to_dict()

        result_path = self.workspace / "experiments" / "results" / f"{resolved_id}.json"
        write_json_atomic(result_path, result)
        self.ledger.save_result(result)
        return manifest, result
