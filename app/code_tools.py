"""Code-facing tools for the research executor's action loop.

文档里的"行动循环"（最内层）在这里落地：执行器自己决定"这个实验具体怎么做" ——
看代码、读配置、改文件、跑 smoke test、看报错、再改。编排层不规定这些步骤。

**这是 Agent 唯一能动手的地方，所以边界全部落在本文件里**，而不是靠提示词叮嘱：

* 读类（`list_directory` / `read_file` / `search_text`）：范围钉在工作区与项目根之内，
  `..` 逃逸一律拒绝；
* `write_file`：只准写工作区，且官方规则原件（`input/`）与 `.git/` 是禁区；
* `run_command`：**不在宿主上跑**。它开一个无网、限资源、限时间的容器，工作区只读挂载，
  唯一可写的是一个空的 `/scratch`。要改东西就在 scratch 里复制再改。

真正烧算力的训练仍然走人工批准那条路（`loop.PENDING_ACTIONS`），这里是"试一下"用的。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.container_runner import BindMount, ContainerSpec, DockerRunner


# 一次返回给模型的内容上限：模型读的是"够看懂"的量，不是整份文件。
READ_LIMIT_BYTES = 200_000
SEARCH_HIT_LIMIT = 60
LIST_LIMIT = 300

# 写文件时的禁区：官方规则原件不能被改写，版本库内部文件也不该由 Agent 碰。
WRITE_DENYLIST = ("input/", ".git/")

# 沙箱命令的默认规格。比训练容器更紧：目的只是"试一下"。
COMMAND_IMAGE = "python:3.12-slim"
COMMAND_TIMEOUT_SECONDS = 300
COMMAND_MAX_TIMEOUT_SECONDS = 900
COMMAND_CPUS = "2"
COMMAND_MEMORY = "2g"


def _roots(project_root: Path, workspace: Path) -> tuple[Path, Path]:
    return Path(project_root).resolve(), Path(workspace).resolve()


def _within(root: Path, relative: str) -> Path:
    """把相对路径钉在 root 之内。

    `..` 逃逸在这里直接拒绝，而不是"解析完再看在不在里面" —— 后者容易被符号链接绕过。
    """
    if not relative or not str(relative).strip():
        raise ValueError("path is required")
    text = str(relative).strip().replace("\\", "/")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise ValueError("only workspace-relative paths are allowed")
    candidate = (root / text).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes the workspace: {relative}")
    return candidate


def _display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return path.as_posix()


def _list_directory(project_root: Path, workspace: Path, *, path: str = ".", **_extra: Any) -> dict[str, Any]:
    target = _within(workspace, path)
    if not target.is_dir():
        return {"error": f"not a directory: {path}"}
    entries: list[dict[str, Any]] = []
    for item in sorted(target.iterdir(), key=lambda entry: (entry.is_file(), entry.name)):
        if len(entries) >= LIST_LIMIT:
            break
        entries.append(
            {
                "name": item.name,
                "kind": "file" if item.is_file() else "directory",
                "bytes": item.stat().st_size if item.is_file() else None,
            }
        )
    return {"path": _display(target, workspace), "entries": entries, "truncated": len(entries) >= LIST_LIMIT}


def _read_file(project_root: Path, workspace: Path, *, path: str, max_bytes: int = READ_LIMIT_BYTES, **_extra: Any) -> dict[str, Any]:
    target = _within(workspace, path)
    if not target.is_file():
        return {"error": f"not a file: {path}"}
    try:
        limit = max(1, min(int(max_bytes), READ_LIMIT_BYTES))
    except (TypeError, ValueError):
        limit = READ_LIMIT_BYTES
    raw = target.read_bytes()[:limit]
    return {
        "path": _display(target, workspace),
        "bytes": target.stat().st_size,
        "truncated": target.stat().st_size > len(raw),
        "content": raw.decode("utf-8", errors="replace"),
    }


def _search_text(project_root: Path, workspace: Path, *, query: str, path: str = ".", limit: int = SEARCH_HIT_LIMIT, **_extra: Any) -> dict[str, Any]:
    """在工作区里做纯文本搜索。用于回答"这个参数在哪儿定义的"。"""
    needle = str(query or "").strip()
    if not needle:
        return {"error": "query is required"}
    target = _within(workspace, path)
    try:
        maximum = max(1, min(int(limit), SEARCH_HIT_LIMIT))
    except (TypeError, ValueError):
        maximum = SEARCH_HIT_LIMIT

    hits: list[dict[str, Any]] = []
    candidates = [target] if target.is_file() else sorted(target.rglob("*"))
    for item in candidates:
        if len(hits) >= maximum:
            break
        if not item.is_file() or item.stat().st_size > READ_LIMIT_BYTES:
            continue
        try:
            text = item.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if needle in line:
                hits.append({"path": _display(item, workspace), "line": number, "text": line.strip()[:240]})
                if len(hits) >= maximum:
                    break
    return {"query": needle, "hits": hits, "truncated": len(hits) >= maximum}


def _write_file(project_root: Path, workspace: Path, *, path: str, content: str, **_extra: Any) -> dict[str, Any]:
    """把内容写进工作区。禁区之外的路径不拦，但写入内容不经过任何"智能"加工。"""
    text = str(path or "").strip().replace("\\", "/")
    for forbidden in WRITE_DENYLIST:
        if text.startswith(forbidden) or f"/{forbidden}" in f"/{text}":
            return {"error": f"refusing to write under {forbidden} — that directory holds source evidence"}

    target = _within(workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = content if isinstance(content, str) else str(content)
    target.write_text(body, encoding="utf-8")
    return {"path": _display(target, workspace), "bytes": len(body.encode("utf-8")), "written": True}


def _run_command(
    project_root: Path,
    workspace: Path,
    *,
    command: str,
    timeout_seconds: int = COMMAND_TIMEOUT_SECONDS,
    runner: DockerRunner | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """在隔离容器里跑一条命令。

    容器是本工具唯一允许的执行方式：无网、限 CPU 与内存、限时间，工作区**只读**挂载，
    可写的只有一个空的 `/scratch`。超时由 `DockerRunner` 负责删容器，不留残留。
    """
    text = str(command or "").strip()
    if not text:
        return {"error": "command is required"}
    if "\n" in text or "\r" in text:
        # 多行会让"到底批准了哪一条命令"说不清；要串联就用 && 写在一行里。
        return {"error": "command must be a single line"}

    active = runner or DockerRunner()
    status = active.availability()
    if not status["available"]:
        return {"error": f"Docker is not usable: {status['reason']}"}

    try:
        timeout = max(5, min(int(timeout_seconds), COMMAND_MAX_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = COMMAND_TIMEOUT_SECONDS

    workspace = Path(workspace)
    scratch = workspace / "research" / "loop" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    log_dir = workspace / "research" / "loop" / "sandbox"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{time.strftime('%Y%m%dT%H%M%S')}-{abs(hash(text)) % 100000:05d}.log"

    spec = ContainerSpec(
        name=f"yjl-sandbox-{int(time.time() * 1000)}",
        image=COMMAND_IMAGE,
        command=text,
        mounts=(BindMount(workspace, "/work", True), BindMount(scratch, "/scratch", False)),
        network="none",
        cpus=COMMAND_CPUS,
        memory=COMMAND_MEMORY,
        workdir="/scratch",
        timeout_seconds=timeout,
    )
    outcome = active.run(spec, log_path=log_path)
    return {
        "command": text,
        "exit_code": outcome.returncode,
        "timed_out": outcome.timed_out,
        "duration_seconds": outcome.duration_seconds,
        "log_path": str(log_path),
        "output_tail": log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.exists() else "",
    }


CODE_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories inside the competition workspace. Paths are workspace-relative; escaping the workspace is refused.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Workspace-relative directory, e.g. 'configs'. Default '.'"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the competition workspace. Use this to inspect configs, training scripts and result records before proposing changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "max_bytes": {"type": "integer", "description": f"Byte limit, at most {READ_LIMIT_BYTES}. Default {READ_LIMIT_BYTES}."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Plain-text search inside the workspace. Use it to find where a parameter, flag or metric name is defined.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Literal text to look for."},
                    "path": {"type": "string", "description": "Workspace-relative file or directory. Default '.'"},
                    "limit": {"type": "integer", "description": f"Maximum hits, at most {SEARCH_HIT_LIMIT}."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write a text file inside the competition workspace. Writing under input/ or .git/ is refused. "
                "This is the only way changes persist; content is written verbatim."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run ONE command inside an isolated, network-less container. The workspace is mounted read-only at /work; "
                "the only writable place is an empty /scratch, so copy what you need there first. "
                "Use this for smoke tests and small checks. Real training still requires a human approval step and is NOT allowed here."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "A single-line shell command."},
                    "timeout_seconds": {"type": "integer", "description": f"At most {COMMAND_MAX_TIMEOUT_SECONDS}. Default {COMMAND_TIMEOUT_SECONDS}."},
                },
                "required": ["command"],
            },
        },
    },
]


CODE_TOOL_HANDLERS: dict[str, Any] = {
    "list_directory": _list_directory,
    "read_file": _read_file,
    "search_text": _search_text,
    "write_file": _write_file,
    "run_command": _run_command,
}


__all__ = [
    "CODE_TOOL_DEFINITIONS",
    "CODE_TOOL_HANDLERS",
    "COMMAND_MAX_TIMEOUT_SECONDS",
    "READ_LIMIT_BYTES",
    "WRITE_DENYLIST",
]
