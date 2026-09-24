"""Explicit, auditable runtime probes for local and SSH training targets.

The service performs only read-only discovery.  It never creates a Conda
environment, installs a package, starts a job, or stores a password/private
key.  Remote probes require the user to select SSH-key authentication and a
previously verified host key.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.runtime_service import local_runtime_snapshot
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


class RuntimeProbeError(ValueError):
    """Raised for invalid, unsafe, or unsuccessful explicit runtime probes."""


_HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,252}\Z")
_USER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z")


def _bounded_text(value: str, *, field: str, minimum: int = 0, maximum: int = 160) -> str:
    clean = value.strip()
    if not minimum <= len(clean) <= maximum or any(ord(char) < 32 for char in clean):
        raise RuntimeProbeError(f"{field} is invalid")
    return clean


def _run(command: list[str], timeout: int = 20) -> tuple[int | None, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "", str(exc)
    return completed.returncode, completed.stdout[-24_000:], completed.stderr[-24_000:]


def _parse_conda_environments(text: str) -> list[str]:
    try:
        payload = json.loads(text)
        environments = payload.get("envs", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return [str(item) for item in environments if isinstance(item, str)]


def _parse_gpus(text: str) -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    for line in text.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 4:
            continue
        try:
            total_mb, free_mb = int(values[1]), int(values[2])
        except ValueError:
            continue
        gpus.append({
            "name": values[0],
            "memory_total_mb": total_mb,
            "memory_free_mb": free_mb,
            "driver_version": values[3],
        })
    return gpus


def _server_target(server: dict[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    if not isinstance(server, dict):
        raise RuntimeProbeError("server settings are required for a remote probe")
    host = _bounded_text(str(server.get("host", "")), field="server host", minimum=1, maximum=253)
    user = _bounded_text(str(server.get("user", "")), field="server user", minimum=1, maximum=64)
    if not _HOST_RE.fullmatch(host) or not _USER_RE.fullmatch(user):
        raise RuntimeProbeError("server host or user contains unsupported characters")
    try:
        port = int(server.get("port", 22))
    except (TypeError, ValueError) as exc:
        raise RuntimeProbeError("server port must be a number") from exc
    if not 1 <= port <= 65535:
        raise RuntimeProbeError("server port must be between 1 and 65535")
    auth = str(server.get("auth", "key"))
    if auth != "key":
        raise RuntimeProbeError("Remote probing currently supports SSH-key authentication only; passwords are not sent or stored.")
    key_value = _bounded_text(str(server.get("credential", "")), field="SSH key path", minimum=1, maximum=1024)
    key_path = Path(os.path.expanduser(key_value)).resolve()
    if not key_path.is_file():
        raise RuntimeProbeError("SSH private-key file was not found on this computer")
    executable = shutil.which("ssh.exe") or shutil.which("ssh")
    if not executable:
        raise RuntimeProbeError("OpenSSH client was not found; install the Windows OpenSSH client first")
    arguments = [
        executable,
        "-F", "NUL",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=12",
        "-o", "StrictHostKeyChecking=yes",
        "-p", str(port),
        "-i", str(key_path),
        f"{user}@{host}",
    ]
    safe_server = {"host": host, "user": user, "port": port, "auth": "key", "credential_provided": True}
    return arguments, safe_server


def _ssh_read_only(arguments: list[str], command: str) -> str:
    code, stdout, stderr = _run([*arguments, command])
    if code != 0:
        detail = (stderr or stdout or "SSH command failed").strip().replace("\n", " ")[:800]
        raise RuntimeProbeError(f"Remote SSH probe failed: {detail}")
    return stdout


def _remote_runtime_snapshot(server: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    arguments, safe_server = _server_target(server)
    platform = _ssh_read_only(arguments, "uname -srm")
    python = _ssh_read_only(arguments, "python3 --version 2>&1 || python --version 2>&1 || true")
    conda_path = _ssh_read_only(arguments, "command -v conda || true").strip()
    conda_raw = _ssh_read_only(arguments, "conda env list --json 2>/dev/null || true") if conda_path else ""
    gpu_raw = _ssh_read_only(
        arguments,
        "nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader,nounits 2>/dev/null || true",
    )
    environments = _parse_conda_environments(conda_raw)
    gpus = _parse_gpus(gpu_raw)
    return {
        "platform": platform.strip() or "remote platform unavailable",
        "python": python.strip() or "python unavailable",
        "conda": {"available": bool(conda_path), "executable": conda_path or None, "environments": environments},
        "gpu": {"available": bool(gpus), "gpus": gpus},
    }, safe_server


def _environment_plan(runtime: dict[str, Any], strategy: str, name: str) -> dict[str, Any]:
    if strategy not in {"existing", "new"}:
        raise RuntimeProbeError("conda strategy must be existing or new")
    requested = _bounded_text(name, field="Conda environment name", maximum=160) if name.strip() else ""
    conda = runtime.get("conda", {})
    if strategy == "new":
        return {
            "strategy": "new",
            "requested": requested or None,
            "status": "creation_not_started",
            "note": "The probe did not create an environment. Create and review it in a separate approved step.",
        }
    environments = [str(item) for item in conda.get("environments", [])]
    available = bool(conda.get("available"))
    found = bool(requested) and any(item == requested or Path(item).name == requested for item in environments)
    return {
        "strategy": "existing",
        "requested": requested or None,
        "status": "available" if found else "not_found" if requested and available else "not_checked" if not requested else "conda_unavailable",
        "known_environments": environments,
        "note": "Environment presence was checked only; no package or interpreter was changed.",
    }


def _assessment(target: str, runtime: dict[str, Any], required_vram_gb: float) -> dict[str, Any]:
    if not 0 < required_vram_gb <= 1_024:
        raise RuntimeProbeError("required_vram_gb must be between 0 and 1024")
    gpus = runtime.get("gpu", {}).get("gpus", [])
    best = max(gpus, key=lambda item: int(item.get("memory_free_mb", 0)), default=None)
    available = round(int(best.get("memory_free_mb", 0)) / 1024, 1) if best else 0.0
    total = round(int(best.get("memory_total_mb", 0)) / 1024, 1) if best else 0.0
    recommended = math.ceil(required_vram_gb * 12) / 10
    batch_size = 8 if available >= 48 else 4 if available >= 24 else 2 if available >= 12 else 1
    target_name = "本机" if target == "local" else "该服务器"
    if not best:
        status = "server_needed" if target == "local" else "server_insufficient"
        return {
            "status": status,
            "title": "未检测到可用 NVIDIA GPU" if target == "local" else "服务器未检测到可用 NVIDIA GPU",
            "reason": f"{target_name}的真实探测没有返回 nvidia-smi GPU 记录，无法为当前至少 {required_vram_gb:g} GB 的方案安全启动训练。",
            "recommendation": "使用具有 NVIDIA GPU 且可用显存满足建议容量的服务器，或先降低模型/输入规模。",
            "available_vram_gb": available,
            "total_vram_gb": total,
            "recommended_vram_gb": recommended,
            "recommended_batch_size": batch_size,
            "gpu_name": None,
        }
    has_capacity = available >= recommended
    if target == "local" and not has_capacity:
        status = "server_needed"
        title = "建议切换到服务器训练"
        reason = f"本机实际可用显存为 {available:g} GB（{best.get('name')}），低于当前方案建议的 {recommended:g} GB。继续本机训练可能在前向、验证或保存检查点时显存不足。"
        recommendation = f"选择可用显存至少 {recommended:g} GB 的服务器；首轮使用混合精度、梯度累积与 batch size {batch_size}。"
    elif target == "server" and not has_capacity:
        status = "server_insufficient"
        title = "当前服务器显存仍不足"
        reason = f"服务器实际可用显存为 {available:g} GB（{best.get('name')}），低于当前方案建议的 {recommended:g} GB。"
        recommendation = "改用更高显存 GPU，或回到模型配置阶段降低输入尺寸、模型规模和 batch size。"
    else:
        status = "local_ready" if target == "local" else "server_ready"
        title = "本机资源可以承载当前方案" if target == "local" else "服务器资源可以承载当前方案"
        reason = f"{target_name}实际可用显存为 {available:g} GB（{best.get('name')}），达到当前方案建议的 {recommended:g} GB。"
        recommendation = f"建议先以 batch size {batch_size}、混合精度和梯度累积运行一个小规模验证，再批准完整训练。"
    return {
        "status": status,
        "title": title,
        "reason": reason,
        "recommendation": recommendation,
        "available_vram_gb": available,
        "total_vram_gb": total,
        "recommended_vram_gb": recommended,
        "recommended_batch_size": batch_size,
        "gpu_name": best.get("name"),
    }


def _next_probe_id(directory: Path) -> str:
    values = [
        int(path.stem.split("-", 1)[1])
        for path in directory.glob("PROBE-*.json")
        if path.stem.split("-", 1)[1].isdigit()
    ]
    return f"PROBE-{max(values, default=0) + 1:04d}"


def probe_runtime(
    workspace: Path,
    *,
    target: str,
    required_vram_gb: float,
    conda_strategy: str,
    conda_environment: str = "",
    server: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform an explicit read-only runtime probe and persist a safe report."""
    if target not in {"local", "server"}:
        raise RuntimeProbeError("target must be local or server")
    if target == "local":
        runtime = local_runtime_snapshot()
        safe_server = None
    else:
        runtime, safe_server = _remote_runtime_snapshot(server)
    environment = _environment_plan(runtime, conda_strategy, conda_environment)
    assessment = _assessment(target, runtime, float(required_vram_gb))
    directory = workspace / "reports" / "runtime_probes"
    directory.mkdir(parents=True, exist_ok=True)
    probe = {
        "probe_id": _next_probe_id(directory),
        "probed_at": utc_now(),
        "target": target,
        "server": safe_server,
        "runtime": runtime,
        "environment": environment,
        "assessment": assessment,
        "safety_note": "Read-only runtime discovery. No environment was created, package installed, code executed, or credential stored.",
    }
    write_json_atomic(directory / f"{probe['probe_id']}.json", probe)
    write_json_atomic(workspace / "reports" / "runtime_latest.json", probe)
    return probe


def latest_runtime_probe(workspace: Path) -> dict[str, Any] | None:
    path = workspace / "reports" / "runtime_latest.json"
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None
