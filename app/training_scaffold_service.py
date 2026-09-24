"""Generate a reviewable training scaffold from persisted competition evidence.

This service intentionally creates configuration and evidence only.  It never
starts a training process, installs packages, contacts a remote host, or
executes third-party source code.  Actual execution remains guarded by
``ExperimentService`` and the training scheduler.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agents.rules_agent import rule_confirmation_readiness
from app.experiment_service import ensure_workspace_layout
from tools.configuration import load_yaml, write_yaml
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now
from training.catalog import recommend_runner, supported_runners


class TrainingScaffoldError(ValueError):
    """Raised when persisted evidence cannot safely support a scaffold."""


SCHEMA_VERSION = 1


def latest_training_scaffold(workspace: Path) -> dict[str, Any] | None:
    """Return the last persisted scaffold record, if one exists."""
    path = workspace / "reports" / "training_scaffold.json"
    if not path.exists():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def build_training_scaffold(workspace: Path) -> dict[str, Any]:
    """Create a baseline configuration grounded in approved local evidence.

    The generated configuration is a *draft for review*, not a queued job.
    Missing data mapping is represented openly in the record and prevents a
    ``ready_for_environment_review`` status rather than being filled with
    imaginary paths.
    """
    workspace = workspace.resolve()
    ensure_workspace_layout(workspace)
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        raise TrainingScaffoldError("Analyze and confirm official competition rules before generating a training scaffold.")

    spec = load_yaml(spec_path)
    readiness = rule_confirmation_readiness(spec)
    approval = spec.get("approval") if isinstance(spec.get("approval"), dict) else {}
    if approval.get("requires_human_confirmation", True) or not readiness["ready"]:
        missing = ", ".join(str(item.get("field")) for item in readiness.get("gaps", [])[:4])
        raise TrainingScaffoldError(
            "Training scaffold is blocked until official-rule confirmation is complete"
            + (f" (missing: {missing})." if missing else ".")
        )

    audit_path = workspace / "reports" / "data_statistics.json"
    if not audit_path.exists():
        raise TrainingScaffoldError("Run the deterministic data audit before generating a real baseline configuration.")
    audit = read_json(audit_path)
    if not isinstance(audit, dict):
        raise TrainingScaffoldError("data_statistics.json must contain a JSON object; rerun the data audit.")
    data_root_value = str(audit.get("data_dir") or "").strip()
    inventory_sha = str(audit.get("inventory_sha256") or "").strip()
    if not data_root_value or len(inventory_sha) != 64:
        raise TrainingScaffoldError("The data audit lacks a usable data_dir or inventory fingerprint; rerun the data audit.")
    data_root = Path(data_root_value).expanduser().resolve()
    if not data_root.is_dir():
        raise TrainingScaffoldError("The audited data directory is no longer readable; rerun the data audit.")

    competition = spec.get("competition") if isinstance(spec.get("competition"), dict) else {}
    evaluation = spec.get("evaluation") if isinstance(spec.get("evaluation"), dict) else {}
    preferred_runner = str(competition.get("preferred_runner") or "").strip()
    runner_capability = _runner_by_name(preferred_runner) or recommend_runner(str(competition.get("task_type") or ""))
    if runner_capability is None:
        task = str(competition.get("task_type") or "未填写任务类型")
        raise TrainingScaffoldError(
            f"No implemented training adapter matches confirmed task type '{task}'. "
            "Select a supported adapter or add a task-specific adapter before building."
        )

    runner = str(runner_capability["runner"])
    config_path = workspace / "configs" / "agent_baseline.yaml"
    data_config, data_blockers = _data_config_for_runner(runner, data_root, inventory_sha)
    config, source_template = _config_for_runner(
        workspace,
        runner,
        data_config,
        competition_name=str(competition.get("name") or "Current competition"),
        metric=str(evaluation.get("primary_metric") or _default_metric(runner)),
        direction=str(evaluation.get("direction") or "maximize"),
    )
    if runner == "waterseg_external":
        external = config.get("external")
        if isinstance(external, dict):
            external["waterseg_config"] = str(config_path)
    write_yaml(config_path, config)

    material_path = workspace / "research" / "materials" / "material_analysis.json"
    material_summary: dict[str, Any] = {"available": False, "item_count": 0, "path": None}
    if material_path.exists():
        materials = read_json(material_path)
        material_summary = {
            "available": isinstance(materials, dict),
            "item_count": len(materials.get("items", [])) if isinstance(materials, dict) and isinstance(materials.get("items"), list) else 0,
            "path": _portable_path(workspace, material_path),
        }

    blockers = list(data_blockers)
    advisories: list[str] = [
        "This action generated files only; no package installation, remote connection, or training process was started.",
        "Confirm local/server runtime and the Conda environment before submitting an approved training job.",
    ]
    if not material_summary["available"]:
        advisories.append("No material_analysis.json is available yet; review research materials before changing the baseline.")
    status = "ready_for_environment_review" if not blockers else "needs_data_mapping"
    record = {
        "schema_version": SCHEMA_VERSION,
        "build_id": _next_build_id(workspace),
        "status": status,
        "created_at": utc_now(),
        "config_path": _portable_path(workspace, config_path),
        "runner": runner,
        "runner_capability": runner_capability,
        "source_template": source_template,
        "competition": {
            "name": competition.get("name"),
            "task_type": competition.get("task_type"),
            "metric": evaluation.get("primary_metric"),
            "direction": evaluation.get("direction"),
        },
        "data_audit": {
            "path": _portable_path(workspace, audit_path),
            "data_dir": str(data_root),
            "inventory_sha256": inventory_sha,
            "file_count": audit.get("file_count"),
            "issue_count": audit.get("issue_count"),
        },
        "materials": material_summary,
        "blockers": blockers,
        "advisories": advisories,
        "execution": {
            "started": False,
            "queued": False,
            "automatic_execution": False,
            "next_gate": "environment_review",
        },
    }
    report_path = workspace / "reports" / "training_scaffold.json"
    markdown_path = workspace / "reports" / "training_scaffold.md"
    write_json_atomic(report_path, record)
    markdown_path.write_text(_render_markdown(record), encoding="utf-8")
    return {**record, "report_path": _portable_path(workspace, report_path), "markdown_path": _portable_path(workspace, markdown_path)}


def _runner_by_name(name: str) -> dict[str, Any] | None:
    if not name:
        return None
    return next((item for item in supported_runners() if item.get("runner") == name), None)


def _next_build_id(workspace: Path) -> str:
    current = latest_training_scaffold(workspace)
    previous = str(current.get("build_id", "")) if current else ""
    try:
        number = int(previous.rsplit("-", 1)[-1])
    except ValueError:
        number = 0
    return f"BUILD-{number + 1:04d}"


def _portable_path(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _first_child(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return None


def _first_csv(root: Path, preferred_names: tuple[str, ...]) -> Path | None:
    for name in preferred_names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    csvs = sorted(root.glob("*.csv"))
    return csvs[0] if len(csvs) == 1 else None


def _data_config_for_runner(runner: str, data_root: Path, inventory_sha: str) -> tuple[dict[str, Any], list[str]]:
    base: dict[str, Any] = {"version": inventory_sha}
    blockers: list[str] = []
    if runner == "image_segmentation":
        images = _first_child(data_root, ("images", "image", "train_images", "train/image"))
        masks = _first_child(data_root, ("masks", "mask", "train_masks", "train/mask"))
        if images is None or masks is None:
            blockers.append("Could not infer both train image and mask directories from the audited dataset; map them in configs/agent_baseline.yaml before training.")
        base.update({
            "train_images_dir": str(images or data_root / "images"),
            "train_masks_dir": str(masks or data_root / "masks"),
            "test_images_dir": str(_first_child(data_root, ("test", "test_images", "test/image")) or ""),
            "mask_filename_suffix": "_mask" if masks and any(path.stem.endswith("_mask") for path in masks.glob("*")) else "",
            "submission_filename_suffix": "_mask",
            "image_size": [512, 512],
            "validation_fraction": 0.2,
            "mask_foreground_threshold": 0,
            "prediction_threshold": 0.5,
        })
    elif runner == "image_classification":
        train_images = _first_child(data_root, ("train", "images", "train_images"))
        if train_images is None:
            blockers.append("Could not infer the class-directory training image root from the audited dataset; map it in configs/agent_baseline.yaml before training.")
        base.update({
            "train_images_dir": str(train_images or data_root / "train"),
            "test_images_dir": str(_first_child(data_root, ("test", "test_images")) or ""),
            "image_size": [224, 224],
            "validation_fraction": 0.2,
        })
    elif runner in {"tabular_classification", "tabular_regression"}:
        train_csv = _first_csv(data_root, ("train.csv", "training.csv"))
        test_csv = _first_csv(data_root, ("test.csv", "testing.csv"))
        if train_csv is None:
            blockers.append("Could not infer train.csv from the audited dataset; set train_csv, target_column and ID columns manually before training.")
        base.update({
            "train_csv": str(train_csv or data_root / "train.csv"),
            "test_csv": str(test_csv or ""),
            "target_column": "target",
            "id_column": "id",
            "prediction_column": "target",
            "validation_fraction": 0.2,
        })
    elif runner == "waterseg_external":
        images = _first_child(data_root, ("images", "image"))
        masks = _first_child(data_root, ("masks", "mask"))
        if images is None or masks is None:
            blockers.append("The approved external water-segmentation adapter needs image and mask directories; map them in the generated configuration before training.")
        base.update({
            "version": inventory_sha,
            "root": str(data_root),
            "train_images_dir": str(images or data_root / "image"),
            "train_masks_dir": str(masks or data_root / "mask"),
        })
    elif runner == "external_detection":
        # 检测项目自己声明数据根（--source-root）；这里把审计目录原样写进去，
        # 于是 AuditedInputScopePolicy 验的就是训练真正会读的那份路径。
        base.update({
            "version": inventory_sha,
            "train_images_dir": str(data_root),
        })
    else:
        blockers.append(f"Runner '{runner}' does not have an automatic data mapper.")
    return base, blockers


def _config_for_runner(
    workspace: Path,
    runner: str,
    data_config: dict[str, Any],
    *,
    competition_name: str,
    metric: str,
    direction: str,
) -> tuple[dict[str, Any], str | None]:
    if runner in {"waterseg_external", "external_detection"}:
        reviewed = (
            "xunfei_waterseg_v16_stage1.yaml"
            if runner == "waterseg_external"
            else "aic_detection_external.yaml"
        )
        source_path = workspace / "configs" / reviewed
        if not source_path.exists():
            raise TrainingScaffoldError(
                f"The {runner} adapter requires an already reviewed external-project configuration; "
                f"no {reviewed} was found."
            )
        config = deepcopy(load_yaml(source_path))
        config["data"] = {**(config.get("data") if isinstance(config.get("data"), dict) else {}), **data_config}
        config["experiment"] = {
            **(config.get("experiment") if isinstance(config.get("experiment"), dict) else {}),
            "hypothesis": f"Create a traceable baseline for {competition_name} from the reviewed external training recipe.",
            "change_type": "baseline",
            "rollback_plan": "Do not replace the current baseline unless a later approved experiment improves the validated official metric.",
        }
        config["validation"] = {"metric": metric, "direction": direction if direction in {"maximize", "minimize"} else "maximize"}
        config["training"] = {**(config.get("training") if isinstance(config.get("training"), dict) else {}), "runner": runner}
        return config, _portable_path(workspace, source_path)

    config: dict[str, Any] = {
        "experiment": {
            "hypothesis": f"Establish a reproducible {runner} baseline for {competition_name}.",
            "change_type": "baseline",
            "expected_improvement": "Establish a valid held-out reference before targeted optimization.",
            "estimated_gpu_hours": _estimated_gpu_hours(runner),
            "rollback_plan": "Retain the frozen baseline if a later approved change underperforms.",
        },
        "data": data_config,
        "training": {"runner": runner, "seed": 42, "epochs": 20, "batch_size": _default_batch_size(runner), "device": "cpu"},
        "optimizer": {"name": "adamw", "learning_rate": 0.001, "weight_decay": 0.0},
        "validation": {"metric": metric, "direction": direction if direction in {"maximize", "minimize"} else "maximize"},
    }
    if runner == "image_segmentation":
        config["model"] = {"base_channels": 16, "dice_loss_weight": 0.5}
        config["training"]["num_workers"] = 0
    elif runner == "image_classification":
        config["model"] = {"base_channels": 16, "dropout": 0.1}
        config["training"]["num_workers"] = 0
    elif runner in {"tabular_classification", "tabular_regression"}:
        config["model"] = {"hidden_dim": 64, "dropout": 0.1}
    else:
        raise TrainingScaffoldError(f"No config builder is implemented for runner '{runner}'.")
    return config, None


def _default_metric(runner: str) -> str:
    if runner in {"image_segmentation", "waterseg_external"}:
        return "global_iou"
    if runner == "external_detection":
        return "map50_95"
    if runner == "tabular_regression":
        return "rmse"
    return "accuracy"


def _default_batch_size(runner: str) -> int:
    return 4 if runner.startswith("image_") else 64


def _estimated_gpu_hours(runner: str) -> float:
    return {"image_segmentation": 4.0, "image_classification": 2.0, "tabular_classification": 0.2, "tabular_regression": 0.2}.get(runner, 1.0)


def _render_markdown(record: dict[str, Any]) -> str:
    blockers = record.get("blockers") or []
    advisories = record.get("advisories") or []
    lines = [
        "# Training scaffold",
        "",
        f"- Build: `{record['build_id']}`",
        f"- Status: `{record['status']}`",
        f"- Runner: `{record['runner']}`",
        f"- Generated configuration: `{record['config_path']}`",
        f"- Data inventory SHA-256: `{record['data_audit']['inventory_sha256']}`",
        "",
        "## Blocking items",
        "",
    ]
    lines.extend([f"- {item}" for item in blockers] or ["- None. Continue with environment review."])
    lines.extend(["", "## Notes", ""])
    lines.extend([f"- {item}" for item in advisories])
    lines.extend(["", "## Safety boundary", "", "This record does not execute training, download dependencies, connect to a server, or run third-party code.", ""])
    return "\n".join(lines)
