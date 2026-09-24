"""Small DeepSeek client used by the local competition Agent.

The client only talks to DeepSeek after an explicit user action. It never starts
training, uploads competition data, or sends local files without a separate
reviewed tool call.

`chat_completion` is the original single-turn entry point kept for backward
compatibility. `run_agent` is the multi-turn tool-calling loop that turns the
DeepSeek client into an actual Agent: it can read persisted workspace state,
create experiment drafts, and reason across multiple turns — but it still
cannot start training, submit predictions, or delete artefacts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agent_tools import agent_tools_schema, execute_tool
from app.settings_service import DEFAULT_DEEPSEEK_MODEL, SettingsError, deepseek_settings_status, get_deepseek_api_key


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
AGENT_MAX_TURNS = 10
AGENT_SYSTEM_PROMPT = (
    "你是竞赛模型训练 Agent。你可以调用工具读取当前比赛工作区的真实状态（实验记录、工作流阶段、规则就绪度、"
    "数据审计、下一步建议、最佳实验等），也可以创建实验草稿。"
    "重要边界：你不能启动训练、提交结果、下载数据或删除文件——这些高风险操作必须由人通过命令行显式执行。"
    "当用户要求执行高风险操作时，明确告知需要的命令并提醒审批。"
    "回答必须基于工具返回的真实数据，不得虚构实验编号、指标或结论。"
    "如果工具返回错误或数据缺失，如实说明并建议用户运行相应命令补齐数据。"
)


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


def _extract_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        return response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError("DeepSeek 响应中没有可用消息。") from exc


def _parse_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw_calls = message.get("tool_calls") or []
    parsed: list[dict[str, Any]] = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        call_id = str(call.get("id") or "")
        function = call.get("function") or {}
        name = str(function.get("name") or "").strip()
        raw_args = function.get("arguments")
        if not name:
            continue
        if isinstance(raw_args, dict):
            arguments = raw_args
        elif isinstance(raw_args, str):
            try:
                arguments = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                arguments = {"_raw_arguments": raw_args}
        else:
            arguments = {}
        parsed.append({"id": call_id, "name": name, "arguments": arguments})
    return parsed


def run_agent(
    user_prompt: str,
    stage: str,
    project_root: Path,
    workspace: Path,
    *,
    model: str | None = None,
    max_turns: int = AGENT_MAX_TURNS,
    thinking: bool = True,
) -> dict[str, Any]:
    """Run a multi-turn tool-calling Agent loop grounded in the local workspace.

    Returns a dict with: model, content (final answer), reasoning (if any),
    trace (per-turn record of tool calls and results), and turns (count).
    """
    if not 1 <= len(user_prompt) <= 8_000:
        raise DeepSeekError("prompt must contain 1 to 8000 characters")
    if max_turns < 1 or max_turns > 20:
        max_turns = AGENT_MAX_TURNS

    status = deepseek_settings_status()
    selected_model = model or str(status["model"])
    tools_schema = agent_tools_schema()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"当前阶段：{stage}\n\n用户请求：{user_prompt}"},
    ]
    trace: list[dict[str, Any]] = []

    for turn in range(1, max_turns + 1):
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "tools": tools_schema,
            "tool_choice": "auto",
            "stream": False,
        }
        if thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "high"

        response = _request(payload)
        message = _extract_message(response)
        tool_calls = _parse_tool_calls(message)
        reasoning = str(message.get("reasoning_content") or "").strip()
        content = str(message.get("content") or "").strip()

        if not tool_calls:
            trace.append({
                "turn": turn,
                "type": "final",
                "content": content,
                "reasoning": reasoning,
            })
            if not content:
                raise DeepSeekError("DeepSeek 未返回最终答案。")
            return {
                "model": selected_model,
                "content": content,
                "reasoning": reasoning,
                "trace": trace,
                "turns": turn,
            }

        assistant_record: dict[str, Any] = {"role": "assistant"}
        if content:
            assistant_record["content"] = content
        assistant_record["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                },
            }
            for call in tool_calls
        ]
        messages.append(assistant_record)

        step_record: dict[str, Any] = {
            "turn": turn,
            "type": "tool_calls",
            "assistant_content": content,
            "reasoning": reasoning,
            "tool_calls": [],
        }

        for call in tool_calls:
            tool_result = execute_tool(project_root, workspace, call["name"], call["arguments"])
            result_json = json.dumps(tool_result, ensure_ascii=False, default=str)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": result_json,
            })
            step_record["tool_calls"].append({
                "name": call["name"],
                "arguments": call["arguments"],
                "result": tool_result,
            })

        trace.append(step_record)

    final_attempt = _request({
        "model": selected_model,
        "messages": messages + [{"role": "user", "content": "已达到工具调用轮数上限。请基于已收集的信息直接给出最终回答，不要再调用工具。"}],
        "stream": False,
    })
    final_message = _extract_message(final_attempt)
    final_content = str(final_message.get("content") or "").strip()
    final_reasoning = str(final_message.get("reasoning_content") or "").strip()
    trace.append({
        "turn": max_turns + 1,
        "type": "max_turns_summary",
        "content": final_content,
        "reasoning": final_reasoning,
    })
    if not final_content:
        raise DeepSeekError(f"Agent 在 {max_turns} 轮工具调用后仍未给出最终答案。")
    return {
        "model": selected_model,
        "content": final_content,
        "reasoning": final_reasoning,
        "trace": trace,
        "turns": max_turns,
        "truncated": True,
    }

