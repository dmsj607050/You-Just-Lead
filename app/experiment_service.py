"""Application service for a complete config-to-ledger experiment run."""

from __future__ import annotations

from copy import deepcopy
import re
import time
import traceback
from pathlib import Path
from typing import Any

from agents.analysis_agent import analyze_history
from agents.error_analysis_agent import analyze_prediction_errors
from agents.optimization_ledger import render_optimization_ledger
from app.authorization import authorise, training_run_request
from database.ledger import ledger_for_workspace
from schemas.experiment import ExperimentManifest, ExperimentResult
from tools.configuration import (
    DATA_PATH_KEYS,
    get_mapping,
    load_yaml,
    require_experiment_config,
    write_yaml,
)
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


DATA_PATH_KEYS = (
    "train_csv",
    "test_csv",
    "train_images_dir",
    "train_masks_dir",
    "test_images_dir",
)


class ExperimentService:
    """Runs one approved experiment and persists every observable outcome."""

    def __init__(self, project_root: Path, workspace: Path):
        self.project_root = project_root.resolve()
        self.workspace = workspace.resolve()
        ensure_workspace_layout(self.workspace)
        self.ledger = ledger_for_workspace(self.project_root, self.workspace)
        self.tracker = ExperimentTracker(self.workspace / "experiments" / "tracking")

    def _require_real_training_preflight(self, config: dict[str, Any], config_path: Path) -> None:
        """Block real-data runs until the authorization gateway allows this exact run."""
        authorise(training_run_request(config, config_path), self.workspace)

    def _resolve_runtime_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Resolve known data inputs relative to the current competition workspace.

        Stored configurations remain portable; only the immutable runtime snapshot
        contains absolute paths.  This prevents behavior from changing with the
        shell's current working directory.
        """
        runtime_config = deepcopy(config)
        data = get_mapping(runtime_config, "data")
        for key in DATA_PATH_KEYS:
            value = data.get(key)
            if not value:
                continue
            candidate = Path(str(value)).expanduser()
            if not candidate.is_absolute():
                candidate = self.workspace / candidate
            data[key] = str(candidate.resolve())
        return runtime_config

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
        runtime_config = self._resolve_runtime_config(config)
        self._require_real_training_preflight(runtime_config, config_path)
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
        write_yaml(artifact_dir / "runtime_config.yaml", runtime_config)

        try:
            output = execute_training(runtime_config, artifact_dir)
            history = output["history"]
            write_json_atomic(artifact_dir / "history.json", {"history": history})
            prediction_records = next(
                (
                    Path(path)
                    for path in output["artifact_paths"]
                    if Path(path).name == "validation_predictions.jsonl"
                ),
                None,
            )
            error_analysis = (
                analyze_prediction_errors(prediction_records, artifact_dir)
                if prediction_records is not None
                else {}
            )
            if error_analysis:
                output["artifact_paths"].extend(
                    [str(artifact_dir / "error_analysis.json"), str(artifact_dir / "error_analysis.md")]
                )
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
                + [
                    str(artifact_dir / "history.json"),
                    str(artifact_dir / "config_snapshot.yaml"),
                    str(artifact_dir / "runtime_config.yaml"),
                ],
            ).to_dict()
            result["error_analysis"] = error_analysis
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
        render_optimization_ledger(self.workspace)
        return manifest, result
