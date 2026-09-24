"""YAML configuration loading and immutable snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


# Configuration keys whose values point at real competition data inputs.
DATA_PATH_KEYS = (
    "train_csv",
    "test_csv",
    "train_images_dir",
    "train_masks_dir",
    "test_images_dir",
)


class ConfigError(ValueError):
    """Raised when an experiment configuration is invalid."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a mapping-only YAML file."""
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ConfigError(f"Configuration must be a mapping: {path}")
    return payload


def get_nested(payload: dict[str, Any], dotted_name: str) -> Any:
    """按点号路径取值，中间不是映射就返回 None。"""
    value: Any = payload
    for key in dotted_name.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def display_value(value: Any) -> str | None:
    """把配置里的标量折成一行可显示文本，空值统一为 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) if value else None
    text = str(value).strip()
    return text or None


def get_mapping(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{name}' must be a mapping")
    return value


def require_experiment_config(config: dict[str, Any]) -> None:
    training = get_mapping(config, "training")
    validation = get_mapping(config, "validation")
    if not training.get("runner"):
        raise ConfigError("training.runner is required")
    if not validation.get("metric"):
        raise ConfigError("validation.metric is required")
    direction = validation.get("direction", "maximize")
    if direction not in {"maximize", "minimize"}:
        raise ConfigError("validation.direction must be maximize or minimize")


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
