"""Read-only local runtime discovery for the desktop Agent."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from typing import Any


def _run(command: list[str], timeout: int = 12) -> tuple[int | None, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def _find_conda() -> str | None:
    """Prefer the native executable: invoking conda.bat with subprocess is unreliable."""
    executable = shutil.which("conda.exe") or shutil.which("conda")
    if executable and executable.lower().endswith(".bat"):
        return None
    return executable


def _conda_snapshot() -> dict[str, Any]:
    executable = _find_conda()
    if not executable:
        return {"available": False, "executable": None, "environments": []}
    code, stdout, stderr = _run([executable, "env", "list", "--json"])
    if code != 0:
        return {"available": True, "executable": executable, "environments": [], "error": stderr.strip() or "Conda 查询失败"}
    try:
        payload = json.loads(stdout)
        environments = [str(item) for item in payload.get("envs", [])]
    except (json.JSONDecodeError, AttributeError):
        environments = []
    return {"available": True, "executable": executable, "environments": environments}


def _gpu_snapshot() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"available": False, "gpus": []}
    query = "name,memory.total,memory.free,driver_version"
    code, stdout, stderr = _run([executable, f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    if code != 0:
        return {"available": False, "gpus": [], "error": stderr.strip() or "nvidia-smi 查询失败"}
    gpus: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 4:
            continue
        try:
            total_mb, free_mb = int(values[1]), int(values[2])
        except ValueError:
            continue
        gpus.append({"name": values[0], "memory_total_mb": total_mb, "memory_free_mb": free_mb, "driver_version": values[3]})
    return {"available": bool(gpus), "gpus": gpus}


def local_runtime_snapshot() -> dict[str, Any]:
    """Return machine capability data without changing conda, GPU, or training state."""
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "conda": _conda_snapshot(),
        "gpu": _gpu_snapshot(),
    }
