"""Local-only settings and secret access for the desktop application."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tools.files import write_json_atomic


APP_NAME = "YouJustLead"
KEYRING_SERVICE = "YouJustLead.CompetitionAgent"
KEYRING_ACCOUNT = "deepseek_api_key"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
SUPPORTED_DEEPSEEK_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}


class SettingsError(ValueError):
    """Raised when an application setting cannot be safely applied."""


def _settings_dir() -> Path:
    root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return root / APP_NAME


def _settings_path() -> Path:
    return _settings_dir() / "settings.json"


def _load_public_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsError("本地设置文件已损坏，请删除后重新配置。") from exc
    if not isinstance(payload, dict):
        raise SettingsError("本地设置文件格式无效。")
    return payload


def _keyring() -> Any | None:
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    return keyring


def get_deepseek_api_key() -> tuple[str | None, str | None]:
    """Return a key and origin without ever exposing it in API responses."""
    environment_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if environment_key:
        return environment_key, "environment"
    keyring = _keyring()
    if keyring is None:
        return None, None
    try:
        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        return None, None
    return (stored.strip(), "windows_credential_manager") if stored and stored.strip() else (None, None)


def deepseek_settings_status() -> dict[str, Any]:
    settings = _load_public_settings()
    _, key_source = get_deepseek_api_key()
    model = str(settings.get("deepseek_model") or DEFAULT_DEEPSEEK_MODEL)
    if model not in SUPPORTED_DEEPSEEK_MODELS:
        model = DEFAULT_DEEPSEEK_MODEL
    return {
        "configured": key_source is not None,
        "key_source": key_source,
        "model": model,
        "supported_models": sorted(SUPPORTED_DEEPSEEK_MODELS),
        "secure_storage_available": _keyring() is not None,
    }


def configure_deepseek(api_key: str, model: str) -> dict[str, Any]:
    normalized_key = api_key.strip()
    if len(normalized_key) < 16:
        raise SettingsError("DeepSeek API Key 格式无效。")
    if model not in SUPPORTED_DEEPSEEK_MODELS:
        raise SettingsError("不支持的 DeepSeek 模型。")
    keyring = _keyring()
    if keyring is None:
        raise SettingsError("安全凭据组件不可用。请先在桌面环境安装 keyring，或设置 DEEPSEEK_API_KEY 环境变量。")
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, normalized_key)
    except Exception as exc:
        raise SettingsError("无法写入 Windows 凭据管理器。") from exc
    write_json_atomic(_settings_path(), {"deepseek_model": model})
    return deepseek_settings_status()

