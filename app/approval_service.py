"""Explicit, immutable human approvals for costly training configurations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.configuration import get_mapping, load_yaml
from tools.files import read_json, write_json_atomic
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


def verify_training_config_approval(workspace: Path, config_path: Path) -> dict[str, Any]:
    """Return a verified approval for exactly ``config_path`` or raise a clear error.

    The filename is derived from the config digest for convenient lookup, but it is
    not itself proof of approval.  Rechecking the record prevents a copied or
    manually altered approval file from authorizing a different GPU run.
    """
    config_path = config_path.resolve()
    digest = file_sha256(config_path)
    target = approval_path(workspace, digest)
    if not target.is_file():
        raise PermissionError(
            "GPU training requires a human approval for this exact configuration. "
            "Run approve-run after reviewing the budget."
        )
    try:
        record = read_json(target)
    except (OSError, ValueError) as exc:
        raise PermissionError(f"GPU approval record is unreadable: {target.name}") from exc

    expected = {
        "type": "training_config_approval",
        "config_sha256": digest,
        "config_path": str(config_path),
    }
    mismatched = [key for key, value in expected.items() if record.get(key) != value]
    if mismatched or not str(record.get("approved_at", "")).strip() or not str(record.get("note", "")).strip():
        details = ", ".join(mismatched) if mismatched else "approved_at or note"
        raise PermissionError(
            "GPU approval record does not match the current configuration "
            f"({details}). Re-run approve-run after reviewing the budget."
        )
    return record
