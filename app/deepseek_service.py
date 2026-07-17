"""Small DeepSeek client used by the local competition Agent.

The client only talks to DeepSeek after an explicit user action. It never starts
training, uploads competition data, or sends local files without a separate
reviewed tool call.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.settings_service import DEFAULT_DEEPSEEK_MODEL, SettingsError, deepseek_settings_status, get_deepseek_api_key


DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekError(RuntimeError):
    """Raised when DeepSeek cannot complete a local Agent request."""


def _request(payload: dict[str, Any]) -> dict[str, Any]:
    api_key, _ = get_deepseek_api_key()
    if not api_key:
        raise DeepSeekError("尚未配置 DeepSeek API Key。请在桌面端模型设置中配置，或设置 DEEPSEEK_API_KEY。")
    request = Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:  # noqa: S310 - fixed official API origin
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise DeepSeekError(f"DeepSeek 请求失败（HTTP {exc.code}）：{detail}") from exc
    except URLError as exc:
        raise DeepSeekError("无法连接 DeepSeek API，请检查网络、代理或 API Key。") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DeepSeekError("DeepSeek 返回了无法解析的内容。") from exc
    if not isinstance(parsed, dict):
        raise DeepSeekError("DeepSeek 返回格式无效。")
    return parsed


def chat_completion(system_prompt: str, user_prompt: str, *, model: str | None = None, thinking: bool = True) -> dict[str, Any]:
    status = deepseek_settings_status()
    selected_model = model or str(status["model"])
    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    if thinking:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "high"
    result = _request(payload)
    try:
        message = result["choices"][0]["message"]
        content = str(message.get("content") or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError("DeepSeek 响应中没有可用答案。") from exc
    if not content:
        raise DeepSeekError("DeepSeek 未返回最终答案。")
    reasoning = str(message.get("reasoning_content") or "").strip()
    return {"model": selected_model, "content": content, "reasoning": reasoning}


def verify_connection() -> dict[str, Any]:
    try:
        response = chat_completion(
            "You are a connection check for a local competition-training Agent. Reply in Chinese with exactly: 连接正常。",
            "验证当前 DeepSeek 配置。",
            thinking=False,
        )
    except (DeepSeekError, SettingsError) as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "DeepSeek 连接正常。", "model": response["model"]}

