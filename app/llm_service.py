"""模型客户端与工具调用循环。

**只讲 OpenAI 兼容协议**（`POST {base_url}/chat/completions`，`Authorization: Bearer`），
地址与密钥来自「当前使用」的那套来源（`app/settings_service.py`）。所以它对供应商是无感的：
DeepSeek、OpenAI、Kimi、百炼、本地 Ollama 走的是同一段代码。

只在用户显式动作之后才发请求。它不会自己启动训练、上传比赛数据，也不会在没有一次单独
工具调用的情况下把本地文件发出去。

`chat_completion` 是单轮入口。`run_agent` 是多轮工具调用循环 —— 它让这个客户端成为
真正的 Agent：能读工作区里已落盘的状态、建实验草稿、跨多轮推理；但**仍然**不能启动训练、
提交预测或删除产物。
"""

from __future__ import annotations

import json
import time
from http.client import IncompleteRead
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agent_tools import agent_tools_schema, execute_tool
from app.settings_service import SettingsError, resolve_credentials


AGENT_MAX_TURNS = 10
# 单轮问答 45 秒够用；行动循环的一轮会带上整套工具 schema 和深度推理，真实网络下
# 用同一个口径会偶发读超时（实测撞过一次）。给循环单独放宽，但仍设上界 ——
# 一次请求挂死不能把整条循环拖住。
CHAT_REQUEST_TIMEOUT = 45
AGENT_REQUEST_TIMEOUT = 180

# 网络层重试次数。模型 API 会偶发返回不完整响应（实测撞到过 `IncompleteRead(0 bytes read)`），
# 那是链路抖动、不是请求有问题，退避重试一次就能过去。但**状态码类错误不重试** ——
# 那说明请求本身或额度/权限有问题，重试只是把同一个错误再犯一遍。
REQUEST_ATTEMPTS = 3
AGENT_SYSTEM_PROMPT = (
    "你是竞赛模型训练 Agent。你可以调用工具读取当前比赛工作区的真实状态（实验记录、工作流阶段、规则就绪度、"
    "数据审计、下一步建议、最佳实验等），也可以创建实验草稿。"
    "重要边界：你不能启动训练、提交结果、下载数据或删除文件——这些高风险操作必须由人通过命令行显式执行。"
    "当用户要求执行高风险操作时，明确告知需要的命令并提醒审批。"
    "回答必须基于工具返回的真实数据，不得虚构实验编号、指标或结论。"
    "如果工具返回错误或数据缺失，如实说明并建议用户运行相应命令补齐数据。"
)


class LLMError(RuntimeError):
    """Raised when the configured model source cannot complete a local Agent request."""


def _request(
    payload: dict[str, Any], *, timeout: int = CHAT_REQUEST_TIMEOUT, provider_id: str | None = None
) -> dict[str, Any]:
    api_key, base_url, _ = resolve_credentials(provider_id)
    if not api_key:
        raise LLMError("当前模型来源还没有密钥。请在「设置 → 模型」里填，或设置 YJL_LLM_API_KEY 环境变量。")
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official API origin
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # 状态码类错误不重试：那是请求本身或额度/权限的问题，重试只是再犯一遍。
            body = exc.read()
            detail = (
                body.decode("utf-8", errors="replace")
                if isinstance(body, bytes)
                else str(body or "")
            )[:600]
            raise LLMError(f"模型服务返回 HTTP {exc.code}：{detail}") from exc
        except (IncompleteRead, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < REQUEST_ATTEMPTS:
                time.sleep(1.5 * (attempt + 1))
                continue
        else:
            if not isinstance(parsed, dict):
                raise LLMError("模型服务返回格式无效。")
            return parsed

    if isinstance(last_error, TimeoutError):
        # "这一轮慢"和"连不上"要分开说 —— 处置方式不一样。
        raise LLMError(
            f"模型服务在 {timeout} 秒内没有返回，重试 {REQUEST_ATTEMPTS} 次仍未成功，可稍后重试。"
        ) from last_error
    raise LLMError(f"与模型服务的连接不稳定（重试 {REQUEST_ATTEMPTS} 次仍失败）：{last_error}") from last_error


def chat_completion(system_prompt: str, user_prompt: str, *, model: str | None = None, thinking: bool = True) -> dict[str, Any]:
    _, _, configured_model = resolve_credentials()
    selected_model = model or configured_model
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
        raise LLMError("模型响应中没有可用答案。") from exc
    if not content:
        raise LLMError("模型没有返回最终答案。")
    reasoning = str(message.get("reasoning_content") or "").strip()
    return {"model": selected_model, "content": content, "reasoning": reasoning}


def verify_connection(provider_id: str | None = None) -> dict[str, Any]:
    """发一次最小请求验证配置。`provider_id` 给了就验那一套（还没切过去也能先试）。"""
    try:
        if provider_id is None:
            response = chat_completion(
                "You are a connection check for a local competition-training Agent. Reply in Chinese with exactly: 连接正常。",
                "验证当前模型配置。",
                thinking=False,
            )
        else:
            # 显式指定那一套：绕开「当前使用」，直接用它的地址与密钥发一次最小请求。
            # 这里只看它**有没有抛错** —— 抛了就说明这套配不通，返回内容不重要。
            _, _, configured_model = resolve_credentials(provider_id)
            _request(
                {
                    "model": configured_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a connection check for a local competition-training Agent. Reply in Chinese with exactly: 连接正常。",
                        },
                        {"role": "user", "content": "验证这套模型配置。"},
                    ],
                    "stream": False,
                },
                timeout=CHAT_REQUEST_TIMEOUT,
                provider_id=provider_id,
            )
            response = {"model": configured_model}
    except (LLMError, SettingsError) as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "连接正常。", "model": response["model"]}


def _extract_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        return response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("模型响应中没有可用消息。") from exc


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
    system_prompt: str | None = None,
    tools: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run a multi-turn tool-calling Agent loop grounded in the local workspace.

    `system_prompt` 与 `tools` 让调用方按角色收窄权限：只做推理判断的动作不必
    同时握着写文件和跑命令的手。默认仍是通用纪律与全部工具。

    Returns a dict with: model, content (final answer), reasoning (if any),
    trace (per-turn record of tool calls and results), and turns (count).
    """
    if not 1 <= len(user_prompt) <= 8_000:
        raise LLMError("prompt must contain 1 to 8000 characters")
    if max_turns < 1 or max_turns > 20:
        max_turns = AGENT_MAX_TURNS

    _, _, configured_model = resolve_credentials()
    selected_model = model or configured_model
    tools_schema = agent_tools_schema(tools)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or AGENT_SYSTEM_PROMPT},
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

        response = _request(payload, timeout=AGENT_REQUEST_TIMEOUT)
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
                raise LLMError("模型没有返回最终答案。")
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
    }, timeout=AGENT_REQUEST_TIMEOUT)
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
        raise LLMError(f"Agent 在 {max_turns} 轮工具调用后仍未给出最终答案。")
    return {
        "model": selected_model,
        "content": final_content,
        "reasoning": final_reasoning,
        "trace": trace,
        "turns": max_turns,
        "truncated": True,
    }
