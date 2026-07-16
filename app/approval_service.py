"""Explicit, immutable human approvals for costly training configurations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.configuration import get_mapping, load_yaml
from tools.files import write_json_atomic
from tools.provenance import file_sha256, utc_now


def approval_path(workspace: Path, config_sha256: str) -> Path:
    return workspace / "experiments" / "approvals" / f"config-{config_sha256[:16]}.json"


def approve_training_config(workspace: Path, config_path: Path, note: str) -> dict[str, Any]:
    """Approve the exact frozen config that may request GPU resources."""
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration does not exist: {config_path}")
    if not note.strip():
        raise ValueError("A human approval note is required")
    config = load_yaml(config_path)
    experiment = get_mapping(config, "experiment")
    training = get_mapping(config, "training")
    digest = file_sha256(config_path)
    record: dict[str, Any] = {
        "type": "training_config_approval",
        "config_path": str(config_path),
        "config_sha256": digest,
        "approved_at": utc_now(),
        "note": note.strip(),
        "estimated_gpu_hours": experiment.get("estimated_gpu_hours"),
        "requested_device": training.get("device", "cpu"),
    }
    target = approval_path(workspace, digest)
    write_json_atomic(target, record)
    return {"approval_path": str(target), **record}
