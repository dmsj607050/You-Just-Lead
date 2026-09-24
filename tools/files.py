"""Small safe file helpers used by the local workflow."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Windows 上 `os.replace` 只要目标文件正被任何读者打开，就直接报 ERROR_ACCESS_DENIED（WinError 5）；
# 读者持句柄的时间是微秒级，所以这里重试一小会儿就过去了。超时后仍然把原始错误抛出去 ——
# 真正的句柄泄漏或 ACL 问题不该被"过一会儿就好了"掩盖掉。
_RETRY_BUDGET_SECONDS = 1.0
_RETRY_FIRST_DELAY = 0.001
_RETRY_MAX_DELAY = 0.05


def _is_transient_sharing_error(exc: OSError) -> bool:
    """判断是不是"文件正被占用"这类值得重试的错误。

    Windows 上 PermissionError 同时覆盖「被别的句柄占着」和「ACL 不允许」，异常本身分不出来；
    这里一律按可重试处理，代价是真正的权限问题会多等一个重试预算才报错。
    """
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32, 33}


def _retry_transient(operation: Callable[[], Any]) -> Any:
    """跑一个会被"文件被占用"打断的 IO 动作，短暂重试后如实抛出原错误。"""
    deadline = time.monotonic() + _RETRY_BUDGET_SECONDS
    delay = _RETRY_FIRST_DELAY
    while True:
        try:
            return operation()
        except OSError as exc:
            if not _is_transient_sharing_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, _RETRY_MAX_DELAY)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomic JSON write: fill a unique temporary file, then replace the target with it.

    The temporary name carries the process and thread id: when two writers target the same
    path, each one keeps its own scratch file, so whatever lands in the target is always one
    complete document. The replace is retried briefly because Windows refuses to overwrite a
    file that a reader currently has open -- which happens constantly here, since the API
    server reads job records while the worker writes the next revision. A failed replace
    (retry budget exhausted) removes the scratch file, so an aborted write no longer leaves
    `.tmp` litter inside the workspace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        _retry_transient(lambda: os.replace(temporary, path))
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object, tolerating a replace that is happening at this very moment.

    Readers need the same tolerance as writers: on Windows an open that lands in the instant
    a writer swaps the file in can come back as "access denied". Without the retry a
    momentary conflict would be reported as a corrupt or missing record.
    """

    def _load() -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    payload = _retry_transient(_load)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
