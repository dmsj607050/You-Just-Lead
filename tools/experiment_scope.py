"""Identify evidence that belongs to the currently audited competition data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.files import read_json


DATA_PATH_KEYS = (
    "train_csv",
    "test_csv",
    "train_images_dir",
    "train_masks_dir",
    "test_images_dir",
)


def _audit_context(workspace: Path) -> tuple[Path, str] | None:
    path = workspace / "reports" / "data_statistics.json"
    if not path.exists():
        return None
    audit = read_json(path)
    data_dir = audit.get("data_dir")
    fingerprint = str(audit.get("inventory_sha256") or "")
    if not data_dir or len(fingerprint) != 64:
        return None
    return Path(str(data_dir)).resolve(), fingerprint


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def is_current_competition_manifest(workspace: Path, manifest: dict[str, Any]) -> bool:
    """Exclude synthetic and stale experiments from the current leaderboard view."""
    context = _audit_context(workspace)
    if context is None:
        return False
    audited_root, fingerprint = context
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    training = config.get("training") if isinstance(config.get("training"), dict) else {}
    if training.get("runner") == "synthetic_binary_classification":
        return False
    data = config.get("data") if isinstance(config.get("data"), dict) else {}
    if fingerprint in str(data.get("version") or ""):
        return True
    for key in DATA_PATH_KEYS:
        value = data.get(key)
        if not value:
            continue
        candidate = Path(str(value)).expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        if _is_within(candidate, audited_root):
            return True
    return False


def manifests_by_id(workspace: Path) -> dict[str, dict[str, Any]]:
    directory = workspace / "experiments" / "manifests"
    return {
        str(record.get("experiment_id")): record
        for record in (read_json(path) for path in directory.glob("EXP-*.json"))
    } if directory.exists() else {}


def current_competition_results(workspace: Path) -> list[dict[str, Any]]:
    manifests = manifests_by_id(workspace)
    directory = workspace / "experiments" / "results"
    records = (read_json(path) for path in directory.glob("EXP-*.json")) if directory.exists() else []
    return sorted(
        (
            record
            for record in records
            if is_current_competition_manifest(
                workspace, manifests.get(str(record.get("experiment_id")), {})
            )
        ),
        key=lambda item: str(item.get("experiment_id", "")),
    )
