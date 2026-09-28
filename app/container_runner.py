"""Run approved commands inside network-isolated Docker containers.

The runner is deliberately thin: it builds one `docker run` argument vector,
runs it, and reports what happened. It decides nothing about whether a run
*should* happen — that gate lives in the API layer, and the plan it executes
comes from ``reproduction_planner``.

Two properties matter and are enforced here rather than promised by callers:

* **No shell interpolation on the host.** Arguments are passed as a list to
  ``subprocess``; the only shell is the one inside the container.
* **Timeouts still stop the container.** Killing the ``docker run`` client
  leaves the container running, so a timed-out run is followed by an explicit
  ``docker rm -f``.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ContainerError(RuntimeError):
    """Raised when a container cannot be started or cleaned up."""


# docker 装完不一定立刻在 PATH 里（Windows 上要开新终端才有），而 Docker Desktop
# 的安装目录里除了 docker.exe 还有凭据助手 docker-credential-desktop.exe —— 后者
# 找不到时，连拉公开镜像都会报 "error getting credentials"。
DOCKER_FALLBACK_PATHS = (
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    "/usr/bin/docker",
    "/usr/local/bin/docker",
)


@dataclass(frozen=True)
class BindMount:
    """一个宿主目录到容器路径的绑定挂载。"""

    host: Path
    target: str
    read_only: bool = True


@dataclass(frozen=True)
class ContainerSpec:
    """一次 `docker run` 的完整描述。"""

    name: str
    image: str
    command: str
    mounts: tuple[BindMount, ...]
    # none 表示容器内没有网络；bridge 只在下载依赖那一阶段用。
    network: str = "none"
    cpus: str = "4"
    memory: str = "8g"
    pids_limit: int = 512
    workdir: str = "/work/src"
    timeout_seconds: int = 3600
    gpus: bool = False
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class RunOutcome:
    """一次运行的结局：退出码、是否超时、日志在哪、命令行原文。"""

    returncode: int
    timed_out: bool
    duration_seconds: float
    log_path: str
    command_line: list[str]

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def build_arguments(spec: ContainerSpec, executable: str = "docker") -> list[str]:
    """把规格翻成 `docker run` 参数表。

    挂载用 `--mount` 而不是 `-v`：Windows 上宿主路径形如 `B:\\data`，
    `-v B:\\data:/data` 里的冒号会让人一眼读不出哪段是路径哪段是容器目录。
    """
    arguments: list[str] = [
        executable,
        "run",
        "--rm",
        "--name",
        spec.name,
        "--network",
        spec.network,
        "--pids-limit",
        str(spec.pids_limit),
        "--cpus",
        spec.cpus,
        "--memory",
        spec.memory,
        "-w",
        spec.workdir,
    ]
    if spec.gpus:
        arguments.extend(["--gpus", "all"])
    for mount in spec.mounts:
        options = f"type=bind,source={mount.host},target={mount.target}"
        if mount.read_only:
            options += ",readonly"
        arguments.extend(["--mount", options])
    for key, value in sorted(spec.environment.items()):
        arguments.extend(["-e", f"{key}={value}"])
    arguments.extend([spec.image, "sh", "-lc", spec.command])
    return arguments


class DockerRunner:
    """薄薄一层 subprocess 包装；测试里可以换成假的 runner。"""

    def __init__(self, executable: str | None = None):
        self.executable = executable or self.locate()

    @staticmethod
    def locate() -> str:
        """找 docker 可执行文件：先看 PATH，再退回各平台的默认安装位置。

        退回一步查找是必要的：刚装完 Docker Desktop 时 `docker` 还不在当前进程的
        PATH 里（要开新终端才有），而此时后端已经在跑了。
        """
        found = shutil.which("docker")
        if found:
            return found
        for candidate in DOCKER_FALLBACK_PATHS:
            if Path(candidate).is_file():
                return candidate
        return "docker"

    def environment(self) -> dict[str, str]:
        """给子进程的 PATH 里补上 docker 所在目录。

        补 PATH 不只是为了找到 docker 本身：模块里还有 docker-credential-desktop，
        docker CLI 会把它当子进程调用，找不到就连公开镜像都拉不下来。
        """
        env = dict(os.environ)
        directory = str(Path(self.executable).parent)
        current = env.get("PATH", "")
        if directory and Path(directory).is_dir() and directory not in current.split(os.pathsep):
            env["PATH"] = f"{directory}{os.pathsep}{current}" if current else directory
        return env

    def availability(self) -> dict[str, Any]:
        """docker 客户端与守护进程是否都在。"""
        try:
            completed = subprocess.run(
                [self.executable, "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=30,
                env=self.environment(),
            )
        except FileNotFoundError:
            return {"available": False, "version": None, "reason": f"docker executable not found ({self.executable})"}
        except subprocess.TimeoutExpired:
            return {"available": False, "version": None, "reason": "docker daemon did not answer within 30s"}
        if completed.returncode != 0:
            # 客户端在、守护进程没起来，是最常见的一种「装了但没启动」。
            detail = (completed.stderr or completed.stdout).strip().splitlines()
            return {"available": False, "version": None, "reason": detail[-1] if detail else "docker daemon unreachable"}
        return {"available": True, "version": completed.stdout.strip(), "reason": ""}

    def run(self, spec: ContainerSpec, *, log_path: Path) -> RunOutcome:
        """跑一次容器，输出写进日志文件（长训练的输出不适合全留在内存里）。"""
        arguments = build_arguments(spec, self.executable)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        timed_out = False
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write("$ " + " ".join(shlex.quote(item) for item in arguments) + "\n\n")
            handle.flush()
            try:
                completed = subprocess.run(
                    arguments,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=spec.timeout_seconds,
                    env=self.environment(),
                )
                returncode = completed.returncode
            except subprocess.TimeoutExpired:
                # docker run 客户端被杀不等于容器停了，必须显式删掉，否则它一直占着资源。
                handle.write(f"\n[timeout] no result within {spec.timeout_seconds}s; removing the container\n")
                self.remove(spec.name)
                returncode = -1
                timed_out = True
        return RunOutcome(
            returncode=returncode,
            timed_out=timed_out,
            duration_seconds=round(time.monotonic() - started, 3),
            log_path=str(log_path),
            command_line=arguments,
        )

    def remove(self, name: str) -> None:
        """强制删掉一个可能还在跑的容器。删不掉也不该盖住原本的错误。"""
        try:
            subprocess.run(
                [self.executable, "rm", "-f", name],
                capture_output=True,
                text=True,
                timeout=60,
                env=self.environment(),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def log_tail(path: Path, characters: int = 4000) -> str:
    """日志末尾若干字符：给人看的就是这一段，全量留在文件里。"""
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-characters:]
