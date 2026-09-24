"""Approved bridge for the user's own object-detection training project.

Same shape as :mod:`training.waterseg_external`: the bridge never rewrites the
project's model, loss or trainer.  It freezes the project's source inventory,
invokes one fixed entry point without a shell, and reads the run's own
``results.csv`` back into the Competition Agent experiment contract.  Execution
still passes the rules, data-audit and GPU-configuration gates enforced by
:class:`ExperimentService`.

The metric is read from the standard Ultralytics CSV the project already
writes, not from a new file this bridge would have to invent: an experiment the
user cannot reproduce by running the project themselves is not evidence.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from training.source_inventory import fingerprint_source


#: 只对源码与配置取指纹。`datasets/`、`pretrained_weights/`、`runs*/` 这些是数据与产物；
#: `reference_code/` 是第三方参考仓库（体量比本工程代码大一个数量级，且不参与训练）。
#: 把它们算进来，任何一次训练都会让上一份人工复核失效，而失效的理由是错的。
SOURCE_SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".sh"}
EXCLUDED_SOURCE_PARTS = {
    ".git",
    "__pycache__",
    "runs",
    "runs_before920",
    "artifacts",
    "datasets",
    "pretrained_weights",
    "reference_code",
    "submission",
    "tmp",
    ".server_docs_tmp",
    "outputs",
}
SOURCE_LABEL = "detection"

DEFAULT_ENTRY_SCRIPT = "train.py"
RESULTS_FILENAME = "results.csv"
PRIMARY_METRIC_COLUMN = "metrics/mAP50-95(B)"
PRIMARY_METRIC_NAME = "map50_95"

#: results.csv 的列 -> 实验契约里的指标名。缺失的列只是不记，不当成错误：
#: 上游改列名时应当在这里显式对齐，而不是让整次运行的证据丢掉。
METRIC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("metrics/mAP50-95(B)", PRIMARY_METRIC_NAME),
    ("metrics/mAP50(B)", "map50"),
    ("metrics/precision(B)", "precision"),
    ("metrics/recall(B)", "recall"),
    ("train/box_loss", "train_box_loss"),
    ("train/cls_loss", "train_cls_loss"),
    ("train/dfl_loss", "train_dfl_loss"),
    ("val/box_loss", "val_box_loss"),
    ("val/cls_loss", "val_cls_loss"),
    ("val/dfl_loss", "val_dfl_loss"),
    ("lr/pg0", "learning_rate"),
)


def source_inventory(project_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    """Fingerprint the detection project's source and configuration files."""
    return fingerprint_source(
        project_dir,
        suffixes=SOURCE_SUFFIXES,
        excluded_parts=EXCLUDED_SOURCE_PARTS,
        label=SOURCE_LABEL,
    )


def _mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping for external_detection")
    return value


def _positive_integer(value: Any, key: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{key} must be a positive integer")
    return parsed


def _non_negative_integer(value: Any, key: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return parsed


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must remain inside the detection project: {resolved}") from exc
    return resolved


def _run_cuda_preflight(python_executable: Path, project_dir: Path) -> dict[str, str]:
    command = [
        str(python_executable),
        "-c",
        "import torch; print(torch.__version__); print(torch.cuda.is_available())",
    ]
    completed = subprocess.run(
        command,
        cwd=project_dir,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or len(lines) < 2 or lines[-1].lower() != "true":
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            "external_detection requires a CUDA-capable PyTorch runtime; "
            f"preflight failed: {detail or 'torch.cuda.is_available() was false'}"
        )
    return {"torch_version": lines[0], "cuda_available": lines[-1]}


def _number(text: Any) -> float | None:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def read_results_csv(path: Path) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    """把 Ultralytics 的 results.csv 读成逐轮指标 + 原始行。

    返回 (history, rows)。history 只保留能解析成数字的列，行序即 epoch 序。
    主指标列必须存在，否则这次运行证明不了任何与竞赛指标有关的事。
    """
    if not path.is_file():
        raise FileNotFoundError(f"The detection run wrote no {RESULTS_FILENAME}: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = [field.strip() for field in (reader.fieldnames or [])]
        header = {field.strip(): field for field in (reader.fieldnames or [])}
        if PRIMARY_METRIC_COLUMN not in header:
            raise ValueError(
                f"{RESULTS_FILENAME} has no {PRIMARY_METRIC_COLUMN} column; "
                "this run cannot be reported as a mAP@50-95 measurement"
            )
        history: list[dict[str, float]] = []
        rows: list[dict[str, Any]] = []
        for index, raw in enumerate(reader, 1):
            row: dict[str, Any] = {}
            for field in fields:
                row[field] = raw.get(header[field], "")
            rows.append(row)
            point: dict[str, float] = {"epoch": _number(row.get("epoch")) or float(index)}
            for column, name in METRIC_COLUMNS:
                parsed = _number(row.get(column))
                if parsed is not None:
                    point[name] = parsed
            if PRIMARY_METRIC_NAME in point:
                history.append(point)
    if not history:
        raise ValueError(f"{RESULTS_FILENAME} contains no scored epoch for {PRIMARY_METRIC_COLUMN}")
    return history, rows


def run_external_detection(config: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    """Run the audited detection training entry point exactly once."""
    external = _mapping(config, "external")
    project_dir = Path(str(external.get("project_dir", ""))).expanduser().resolve()
    expected_inventory = str(external.get("source_inventory_sha256", "")).strip().lower()
    if len(expected_inventory) != 64:
        raise ValueError("external.source_inventory_sha256 must be a SHA-256 digest")
    actual_inventory, records = source_inventory(project_dir)
    if actual_inventory != expected_inventory:
        raise PermissionError(
            "The detection project source changed after this configuration was reviewed. "
            "Refresh its source fingerprint, review the change, and obtain a new GPU approval."
        )

    entry_script = _inside(project_dir / str(external.get("entry_script") or DEFAULT_ENTRY_SCRIPT), project_dir, "entry script")
    if not entry_script.is_file():
        raise FileNotFoundError(f"Expected detection training entry point is absent: {entry_script}")
    python_executable = Path(str(external.get("python_executable", sys.executable))).expanduser().resolve()
    if not python_executable.is_file():
        raise FileNotFoundError(f"external.python_executable does not exist: {python_executable}")

    # 训练只允许吃审计范围内的原始数据：这里读的是配置里声明的同一份路径，
    # 所以 AuditedInputScopePolicy 验的就是这次真正会被读的数据。
    source_root = Path(str((config.get("data") or {}).get("train_images_dir", ""))).expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"data.train_images_dir does not exist: {source_root}")

    timeout_seconds = _positive_integer(external.get("timeout_seconds", 172800), "external.timeout_seconds")
    if timeout_seconds > 172800:
        raise ValueError("external.timeout_seconds must be at most 172800")

    run_root = artifact_dir / "detection_run"
    command = [
        str(python_executable),
        str(entry_script),
        "--output-dir",
        str(run_root),
        "--source-root",
        str(source_root),
    ]
    for key, flag in (
        ("stage", "--stage"),
        ("model_config", "--model-config"),
        ("train_list", "--train-list"),
        ("val_list", "--val-list"),
        ("dataset_root", "--dataset-root"),
        ("device", "--device"),
    ):
        value = external.get(key)
        if value:
            command.extend([flag, str(value)])
    # 预训练权重只从 model.pretrained_model 读。PretrainedModelPolicy 审的就是这个键，
    # 如果这里再读一处 external.weights，就可能出现「审的是 A、跑的是 B」。
    pretrained_model = str((config.get("model") or {}).get("pretrained_model") or "").strip()
    if pretrained_model:
        command.extend(["--weights", pretrained_model])
    for key, flag in (
        ("epochs", "--epochs"),
        ("batch_size", "--batch-size"),
        ("image_size", "--image-size"),
        ("seed", "--seed"),
    ):
        command.extend([flag, str(_positive_integer(external.get(key), f"external.{key}"))])
    # workers=0 是合法取值（Ultralytics 用它跑单进程加载），所以这里不能按正整数卡。
    command.extend(["--workers", str(_non_negative_integer(external.get("workers"), "external.workers"))])
    fraction = float(external.get("fraction", 1.0))
    if not 0 < fraction <= 1:
        raise ValueError("external.fraction must be within (0, 1]")
    command.extend(["--fraction", str(fraction)])

    if bool(external.get("require_cuda", True)):
        cuda_preflight = _run_cuda_preflight(python_executable, project_dir)
    else:
        cuda_preflight = {"cuda_available": "not-required"}

    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / "detection_train.log"
    source_manifest_path = artifact_dir / "detection_source_manifest.json"
    source_manifest_path.write_text(
        json.dumps(
            {
                "project_dir": str(project_dir),
                "inventory_sha256": actual_inventory,
                "files": records,
                "python_executable": str(python_executable),
                "cuda_preflight": cuda_preflight,
                "command": command,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with log_path.open("w", encoding="utf-8", newline="") as log_handle:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            "Detection training command failed with exit code "
            f"{completed.returncode}; inspect {log_path} before retrying."
        )

    results_path = run_root / RESULTS_FILENAME
    history, rows = read_results_csv(results_path)
    best = max(history, key=lambda point: point[PRIMARY_METRIC_NAME])
    run_log = run_root / "console.log"
    artifact_paths = [str(log_path), str(source_manifest_path), str(results_path)]
    if run_log.is_file():
        artifact_paths.append(str(run_log))
    metrics = {name: float(best[name]) for _, name in METRIC_COLUMNS if name in best}
    metrics["epochs_scored"] = float(len(history))
    return {
        "history": history,
        "best_epoch": int(best["epoch"]),
        "validation_metric": float(best[PRIMARY_METRIC_NAME]),
        "metrics": metrics,
        "peak_gpu_memory_gb": None,
        "artifact_paths": artifact_paths,
    }
