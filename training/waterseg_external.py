"""Approved bridge for the user's existing ``waterseg`` training project.

The bridge deliberately does not attempt to rewrite the specialised model.  It
freezes the external source inventory, invokes one fixed training entry point
without a shell, and converts the project's JSON history into the Competition
Agent experiment contract.  Execution still passes the rules, data-audit and
GPU-configuration gates enforced by :class:`ExperimentService`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


SOURCE_SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".txt", ".sh"}
EXCLUDED_SOURCE_PARTS = {".git", "__pycache__", "runs", "submission"}


def source_inventory(project_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    """Fingerprint relevant source/configuration files without hashing data or checkpoints."""
    root = project_dir.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"waterseg project directory does not exist: {root}")

    records: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if any(part.lower() in EXCLUDED_SOURCE_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": file_digest,
        }
        records.append(record)
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    if not records:
        raise ValueError(f"No waterseg source files found in {root}")
    return digest.hexdigest(), records


def _mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping for waterseg_external")
    return value


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must remain inside the waterseg project: {resolved}") from exc
    return resolved


def _optional_positive_integer(value: Any, key: str) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{key} must be a positive integer")
    return parsed


def _normalize_history(raw_history: list[dict[str, Any]]) -> list[dict[str, float]]:
    history: list[dict[str, float]] = []
    for item in raw_history:
        if not isinstance(item, dict) or not isinstance(item.get("train"), dict):
            continue
        train = item["train"]
        validation = item.get("val") if isinstance(item.get("val"), dict) else {}
        epoch = float(int(item.get("epoch", len(history))) + 1)
        point: dict[str, float] = {"epoch": epoch}
        for source, target in (
            ("loss", "train_loss"),
            ("iou", "train_iou"),
            ("dice", "train_dice"),
            ("lr", "learning_rate"),
            ("crop_water_ratio", "train_crop_water_ratio"),
        ):
            if source in train:
                point[target] = float(train[source])
        for source, target in (
            ("loss", "val_loss"),
            ("iou", "val_iou"),
            ("dice", "val_dice"),
            ("precision", "val_precision"),
            ("recall", "val_recall"),
            ("boundary_f1", "val_boundary_f1"),
            ("iou_image_p10", "val_image_iou_p10"),
            ("iou_image_median", "val_image_iou_median"),
        ):
            if source in validation:
                point[target] = float(validation[source])
        history.append(point)
    if not history or not any("val_iou" in point for point in history):
        raise ValueError("waterseg history.json contains no validated IoU measurements")
    return history


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
        timeout=60,
        check=False,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or len(lines) < 2 or lines[-1].lower() != "true":
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            "waterseg_external requires a CUDA-capable PyTorch runtime; "
            f"preflight failed: {detail or 'torch.cuda.is_available() was false'}"
        )
    return {"torch_version": lines[0], "cuda_available": lines[-1]}


def run_waterseg_external(config: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    """Execute the audited v16-style waterseg training entry point once approved."""
    external = _mapping(config, "external")
    project_dir = Path(str(external.get("project_dir", ""))).expanduser().resolve()
    expected_inventory = str(external.get("source_inventory_sha256", "")).strip().lower()
    if len(expected_inventory) != 64:
        raise ValueError("external.source_inventory_sha256 must be a SHA-256 digest")
    actual_inventory, records = source_inventory(project_dir)
    if actual_inventory != expected_inventory:
        raise PermissionError(
            "The external waterseg source changed after this configuration was reviewed. "
            "Refresh its source fingerprint, review the change, and obtain a new GPU approval."
        )

    config_path = Path(str(external.get("waterseg_config", ""))).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"external.waterseg_config does not exist: {config_path}")
    python_executable = Path(str(external.get("python_executable", sys.executable))).expanduser().resolve()
    if not python_executable.is_file():
        raise FileNotFoundError(f"external.python_executable does not exist: {python_executable}")

    script = _inside(project_dir / "scripts" / "01_train.py", project_dir, "training script")
    if not script.is_file():
        raise FileNotFoundError(f"Expected waterseg training entry point is absent: {script}")
    fold = int(external.get("fold", 0))
    if fold < 0:
        raise ValueError("external.fold must be non-negative")
    timeout_seconds = _optional_positive_integer(external.get("timeout_seconds", 172800), "external.timeout_seconds")
    if timeout_seconds is None or timeout_seconds > 172800:
        raise ValueError("external.timeout_seconds must be between 1 and 172800")

    if bool(external.get("require_cuda", True)):
        cuda_preflight = _run_cuda_preflight(python_executable, project_dir)
    else:
        cuda_preflight = {"cuda_available": "not-required"}

    run_root = artifact_dir / "waterseg_run"
    command = [
        str(python_executable),
        str(script),
        "--config",
        str(config_path),
        "--fold",
        str(fold),
        "--save_dir",
        str(run_root),
    ]
    for key in ("epochs", "batch_size", "num_workers"):
        value = _optional_positive_integer(external.get(key), f"external.{key}")
        if value is not None:
            command.extend([f"--{key}", str(value)])
    init_checkpoint = external.get("init_checkpoint")
    if init_checkpoint:
        checkpoint_path = Path(str(init_checkpoint)).expanduser().resolve()
        command.extend(["--init_checkpoint", str(checkpoint_path)])

    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / "waterseg_train.log"
    source_manifest_path = artifact_dir / "waterseg_source_manifest.json"
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
            "waterseg training command failed with exit code "
            f"{completed.returncode}; inspect {log_path} before retrying."
        )

    history_path = run_root / f"fold{fold}" / "history.json"
    if not history_path.is_file():
        raise RuntimeError(f"waterseg completed without history.json: {history_path}")
    raw_history = json.loads(history_path.read_text(encoding="utf-8"))
    if not isinstance(raw_history, list):
        raise ValueError("waterseg history.json must contain a JSON list")
    history = _normalize_history(raw_history)
    scored = [point for point in history if "val_iou" in point]
    best = max(scored, key=lambda point: point["val_iou"])
    checkpoint_path = run_root / f"fold{fold}" / "best.pth"
    artifact_paths = [str(log_path), str(source_manifest_path), str(history_path)]
    if checkpoint_path.is_file():
        artifact_paths.append(str(checkpoint_path))
    metrics = {
        "val_iou": float(best["val_iou"]),
        "val_loss_at_best_iou": float(best.get("val_loss", 0.0)),
        "val_dice_at_best_iou": float(best.get("val_dice", 0.0)),
        "val_precision_at_best_iou": float(best.get("val_precision", 0.0)),
        "val_recall_at_best_iou": float(best.get("val_recall", 0.0)),
        "val_boundary_f1_at_best_iou": float(best.get("val_boundary_f1", 0.0)),
    }
    if checkpoint_path.is_file():
        metrics["checkpoint_size_mb"] = round(checkpoint_path.stat().st_size / 1024**2, 3)
    return {
        "history": history,
        "best_epoch": int(best["epoch"]),
        "validation_metric": float(best["val_iou"]),
        "metrics": metrics,
        "peak_gpu_memory_gb": None,
        "artifact_paths": artifact_paths,
    }
