"""本地设置与密钥。

**「来源」= 任意 OpenAI 兼容服务**（`POST {base_url}/chat/completions` + `Bearer` 密钥）。
DeepSeek 只是其中一个内置预设 —— 换供应商就是换一个 `base_url`，不需要改代码。
可以同时存多套配置，只有一套是「当前使用」。

两层存储，职责分开：

- `settings.json`（`%APPDATA%\\YouJustLead`）：名称、地址、模型名 —— **不含密钥**；
- Windows 凭据管理器：每套供应商一条记录（`provider:<id>`）—— **只有密钥**。

这样把 `settings.json` 发给别人看也不会泄露密钥。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.files import write_json_atomic


APP_NAME = "YouJustLead"
KEYRING_SERVICE = "YouJustLead.CompetitionAgent"

#: 旧的单供应商账户名。只用于**一次性迁移**，见 `_migrate_legacy_deepseek_key`。
LEGACY_KEYRING_ACCOUNT = "deepseek_api_key"

#: 每套供应商在凭据管理器里的账户名前缀。
KEYRING_ACCOUNT_PREFIX = "provider:"

#: settings.json 的结构版本。加字段不改含义时不动它。
SETTINGS_VERSION = 2

#: DeepSeek 在这个项目里默认用的模型（换供应商后这个值只是预设，可改）。
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"

#: 覆盖「当前使用」那套的密钥。给无头/CI 用，优先级最高。
API_KEY_ENV = "YJL_LLM_API_KEY"
#: 旧名字。只在当前这套的预设是 deepseek 时认它 —— 文档与用户 shell 里都可能还留着，
#: 突然不认会让人看到「未配置」却不知道为什么。
LEGACY_API_KEY_ENV = "DEEPSEEK_API_KEY"

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class ProviderPreset:
    """一个预填项。

    **地址只是预填，用户可以改。** 接任何 OpenAI 兼容服务都不需要改代码 ——
    有 `id` 是为了给界面一个稳定的选择项，不是为了白名单。
    """

    id: str
    name: str
    base_url: str
    key_required: bool
    docs_url: str


#: 内置预设。这几个地址是各家的 OpenAI 兼容端点，填错了在界面上可以直接改。
PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com", True,
                   "https://platform.deepseek.com"),
    ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", True,
                   "https://platform.openai.com/docs/api-reference"),
    ProviderPreset("moonshot", "月之暗面 Kimi", "https://api.moonshot.cn/v1", True,
                   "https://platform.moonshot.cn/docs"),
    ProviderPreset("dashscope", "阿里云百炼（通义）",
                   "https://dashscope.aliyuncs.com/compatible-mode/v1", True,
                   "https://help.aliyun.com/zh/model-studio"),
    # 本地模型不用密钥 —— 这也是 key_required 这个字段存在的理由。
    ProviderPreset("ollama", "本地 Ollama", "http://127.0.0.1:11434/v1", False,
                   "https://ollama.com"),
    ProviderPreset("custom", "自定义（OpenAI 兼容）", "", False, ""),
)


class SettingsError(ValueError):
    """Raised when an application setting cannot be safely applied."""


def _settings_dir() -> Path:
    root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return root / APP_NAME


def _settings_path() -> Path:
    return _settings_dir() / "settings.json"


def _keyring() -> Any | None:
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    return keyring


def _read_keyring(account: str) -> str | None:
    keyring = _keyring()
    if keyring is None:
        return None
    try:
        stored = keyring.get_password(KEYRING_SERVICE, account)
    except Exception:
        return None
    return stored.strip() if stored and stored.strip() else None


def _write_keyring(account: str, secret: str) -> None:
    keyring = _keyring()
    if keyring is None:
        raise SettingsError(
            "安全凭据组件不可用。请安装 keyring，或设置 " + API_KEY_ENV + " 环境变量。"
        )
    try:
        keyring.set_password(KEYRING_SERVICE, account, secret)
    except Exception as exc:
        raise SettingsError("无法写入 Windows 凭据管理器。") from exc


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


def _normalize_base_url(value: str) -> str:
    """去掉尾斜杠，并要求是个 http(s) 地址。

    允许 `http://`：本地模型（Ollama / vLLM / LM Studio）就是 http，这不是错误。
    """
    url = value.strip().rstrip("/")
    if not url:
        raise SettingsError("服务地址不能为空。")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise SettingsError("服务地址必须以 http:// 或 https:// 开头。")
    return url


def _normalize_models(models: Any, fallback: str) -> list[str]:
    """模型名列表：去空、去重、保序。至少留一个（当前使用的那个）。"""
    cleaned: list[str] = []
    for item in models if isinstance(models, (list, tuple)) else []:
        name = str(item).strip()
        if name and name not in cleaned:
            cleaned.append(name)
    current = fallback.strip()
    if current and current not in cleaned:
        cleaned.insert(0, current)
    return cleaned


def provider_presets() -> list[dict[str, Any]]:
    """内置预设。界面用它填下拉与预填，**不从界面自己写一份**。"""
    return [
        {
            "id": preset.id,
            "name": preset.name,
            "base_url": preset.base_url,
            "key_required": preset.key_required,
            "docs_url": preset.docs_url,
        }
        for preset in PROVIDER_PRESETS
    ]


def _preset_of(provider: dict[str, Any]) -> ProviderPreset | None:
    preset_id = str(provider.get("preset") or "")
    return next((item for item in PROVIDER_PRESETS if item.id == preset_id), None)


def _stored_providers() -> list[dict[str, Any]]:
    """settings.json 里那部分（不含密钥）。"""
    settings = _load_public_settings()
    raw = settings.get("providers")
    if not isinstance(raw, list):
        return []
    providers: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        base_url = str(item.get("base_url") or "").strip()
        if not provider_id or not name or not base_url:
            continue
        model = str(item.get("model") or "").strip()
        providers.append(
            {
                "id": provider_id,
                "name": name,
                "preset": str(item.get("preset") or "custom"),
                "base_url": base_url.rstrip("/"),
                "model": model,
                "models": _normalize_models(item.get("models"), model),
            }
        )
    return providers


def _save(providers: list[dict[str, Any]], active: str) -> None:
    write_json_atomic(
        _settings_path(),
        {"settings_version": SETTINGS_VERSION, "active_provider": active, "providers": providers},
    )


def _migrate_legacy_deepseek_key() -> bool:
    """把旧的单供应商配置搬成一套 provider。

    只做一次：settings.json 里没有 `providers`、而旧账户或旧的 `deepseek_model` 存在时。
    旧的凭据记录**不删** —— 那是用户存进去的东西，删掉不可逆，留着不占什么。
    返回是否真的迁移了。
    """
    settings = _load_public_settings()
    if settings.get("providers"):
        return False
    legacy_model = str(settings.get("deepseek_model") or DEFAULT_DEEPSEEK_MODEL).strip()
    legacy_key = _read_keyring(LEGACY_KEYRING_ACCOUNT)
    if legacy_key is None and "deepseek_model" not in settings:
        return False

    preset = next(item for item in PROVIDER_PRESETS if item.id == "deepseek")
    provider = {
        "id": "deepseek",
        "name": preset.name,
        "preset": preset.id,
        "base_url": preset.base_url,
        "model": legacy_model,
        "models": [legacy_model],
    }
    if legacy_key is not None:
        _write_keyring(KEYRING_ACCOUNT_PREFIX + "deepseek", legacy_key)
    _save([provider], "deepseek")
    return True


def _ensure_providers() -> tuple[list[dict[str, Any]], str]:
    """读配置；空的话先尝试迁移，再空就返回空表（由界面引导新建）。"""
    providers = _stored_providers()
    if not providers:
        _migrate_legacy_deepseek_key()
        providers = _stored_providers()
    if not providers:
        return [], ""
    active = str(_load_public_settings().get("active_provider") or "")
    if active not in {item["id"] for item in providers}:
        active = providers[0]["id"]
    return providers, active


def _env_key(provider: dict[str, Any], active: str) -> str:
    """环境变量给「当前使用」那套用的密钥；没有就返回空串。

    `YJL_LLM_API_KEY` 是一句**全局**设置，只覆盖当前那套。不这么切的话，「测试某一套」
    会拿当前这套的密钥去打另一个服务 —— 既测不准，也把密钥发给了第三方。
    旧的 `DEEPSEEK_API_KEY` 只在当前那套的预设确实是 DeepSeek 时认。
    """
    if provider["id"] != active:
        return ""
    override = os.environ.get(API_KEY_ENV, "").strip()
    if override:
        return override
    preset = _preset_of(provider)
    if preset is not None and preset.id == "deepseek":
        return os.environ.get(LEGACY_API_KEY_ENV, "").strip()
    return ""


def _public_view(provider: dict[str, Any], active: str) -> dict[str, Any]:
    """给界面看的：**永远不带密钥**。

    `has_key` 把环境变量也算进去：不装系统凭据库的机器（纯环境变量配起来的 Linux）
    否则会被界面说成「未配置」「缺密钥」，而它其实答得出来 —— 这是真发生过的一次部署。
    """
    preset = _preset_of(provider)
    account = KEYRING_ACCOUNT_PREFIX + provider["id"]
    has_key = bool(_env_key(provider, active)) or _read_keyring(account) is not None
    return {
        "id": provider["id"],
        "name": provider["name"],
        "preset": provider["preset"],
        "base_url": provider["base_url"],
        "model": provider["model"],
        "models": provider["models"],
        "key_required": preset.key_required if preset else False,
        "has_key": has_key,
        "docs_url": preset.docs_url if preset else "",
    }


def providers_status() -> dict[str, Any]:
    """现状：预设 + 已配置的几套 + 哪套在用。密钥只回「有没有」。"""
    providers, active = _ensure_providers()
    views = [_public_view(item, active) for item in providers]
    current = next((item for item in views if item["id"] == active), None)
    stored_current = next((item for item in providers if item["id"] == active), None)
    return {
        "presets": provider_presets(),
        "providers": views,
        "active": active,
        "configured": bool(current and (current["has_key"] or not current["key_required"])),
        "model": current["model"] if current else "",
        "key_source": _key_source_for(stored_current, active),
        "secure_storage_available": _keyring() is not None,
        "api_key_env": API_KEY_ENV,
    }


def _key_source_for(provider: dict[str, Any] | None, active: str) -> str | None:
    """密钥从哪来：环境变量还是凭据库。**不回具体的值**；一套都没有时是 None。"""
    if provider is None:
        return None
    if _env_key(provider, active):
        return "environment"
    if _read_keyring(KEYRING_ACCOUNT_PREFIX + provider["id"]):
        return "windows_credential_manager"
    return None


def resolve_credentials(provider_id: str | None = None) -> tuple[str | None, str, str]:
    """取一套的连接信息：`(api_key, base_url, model)`。

    `provider_id` 给了就取那一套（测试连接用），否则取当前的。
    环境变量**只覆盖当前那套**：显式指定别的来源时按它自己存的密钥算，而指定当前那套时
    环境变量照样生效 —— 否则靠环境变量配起来的环境根本没法自测。
    """
    providers, active = _ensure_providers()
    target = provider_id or active
    provider = next((item for item in providers if item["id"] == target), None)
    if provider is None:
        raise SettingsError("还没有配置任何模型来源。请先在「设置 → 模型」里添加一套。")
    key = _env_key(provider, active) or _read_keyring(KEYRING_ACCOUNT_PREFIX + provider["id"])
    return key, provider["base_url"], provider["model"]


def upsert_provider(
    *,
    provider_id: str | None = None,
    name: str,
    base_url: str,
    model: str,
    api_key: str = "",
    models: Any = None,
    preset: str = "custom",
) -> dict[str, Any]:
    """新增或更新一套。`api_key` 留空表示**不改动已存的密钥**。"""
    providers, active = _ensure_providers()
    clean_name = name.strip()
    if not clean_name:
        raise SettingsError("名称不能为空。")
    if len(clean_name) > 60:
        raise SettingsError("名称最多 60 个字符。")
    clean_url = _normalize_base_url(base_url)

    target = next((item for item in providers if item["id"] == provider_id), None)
    if target is None:
        if provider_id:
            raise SettingsError(f"没有这套来源：{provider_id}")
        new_id = preset if _ID_PATTERN.match(preset or "") and not any(
            item["id"] == preset for item in providers
        ) else "p-" + uuid.uuid4().hex[:8]
        target = {"id": new_id, "preset": preset if _ID_PATTERN.match(preset or "") else "custom"}
        providers.append(target)

    target["name"] = clean_name
    target["base_url"] = clean_url
    target["model"] = model.strip()
    target["models"] = _normalize_models(models, model)

    preset_spec = _preset_of(target)
    if preset_spec is not None and preset_spec.key_required and not target["model"]:
        raise SettingsError("模型名不能为空。")

    secret = api_key.strip()
    if secret:
        _write_keyring(KEYRING_ACCOUNT_PREFIX + target["id"], secret)

    _save(providers, active or target["id"])
    return providers_status()


def delete_provider(provider_id: str) -> dict[str, Any]:
    providers, active = _ensure_providers()
    remaining = [item for item in providers if item["id"] != provider_id]
    if len(remaining) == len(providers):
        raise SettingsError(f"没有这套来源：{provider_id}")
    next_active = active if active != provider_id else (remaining[0]["id"] if remaining else "")
    _save(remaining, next_active)
    return providers_status()


def set_active_provider(provider_id: str) -> dict[str, Any]:
    providers, _ = _ensure_providers()
    if not any(item["id"] == provider_id for item in providers):
        raise SettingsError(f"没有这套来源：{provider_id}")
    _save(providers, provider_id)
    return providers_status()


def settings_summary() -> dict[str, Any]:
    """给「设置」页的一段摘要。字段名保持向后兼容的一小部分（`configured` / `model` / `key_source`）。"""
    status = providers_status()
    return {
        "configured": status["configured"],
        "model": status["model"],
        "key_source": status["key_source"],
        "active": status["active"],
        "count": len(status["providers"]),
        "secure_storage_available": status["secure_storage_available"],
    }
