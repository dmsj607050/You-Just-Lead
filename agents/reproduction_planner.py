"""Turn a cloned third-party repository into an executable reproduction plan.

This module only *reads* the repository. It produces the plan a human then
approves:

* which dependency manifest the container should install from,
* which scripts look like training entrypoints,
* candidate commands, each carrying where it came from (a README line, or a
  bare entrypoint), so a person can judge them instead of trusting them,
* which audited local dataset directory to mount, and at which path,
* whether the code appears to want a GPU.

Nothing here executes anything, and no command is invented: every candidate is
either copied out of the repository's own documentation with a line reference,
or is a plainly-labelled fallback (`--help` on an entrypoint, or running the
entrypoint with no arguments).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


# 读多大的文本就够了：README 动辄几百 KB，全读进来只为找命令行不值当。
TEXT_LIMIT = 200_000

# 入口文件名里的关键词 → 这一步是干什么的。顺序即优先级。
ENTRY_KINDS: list[tuple[str, list[str]]] = [
    ("train", ["train", "finetune", "fit"]),
    ("evaluate", ["eval", "validate", "test"]),
    ("infer", ["infer", "predict", "demo"]),
    ("export", ["export", "convert"]),
]

# 依赖清单的候选文件名，按优先级排。
DEPENDENCY_CANDIDATES = ["requirements.txt", "requirements-dev.txt", "environment.yml", "environment.yaml", "pyproject.toml", "setup.py"]

# 出现这些词就认为这个仓库要 GPU。只用来提示与选镜像，不参与任何自动决策。
GPU_HINTS = ["cuda", "cudnn", "nvidia", "nvidia-smi", "torch.cuda", ".cuda()", "gpu"]

# README 里看起来像训练命令的行：有 python 调用，且提到仓库里的某个脚本。
COMMAND_PATTERN = re.compile(r"^\s*(?:\$\s*)?(python[0-9.]*\s+\S+.*)$")

# 数据在容器里的挂载点：固定下来，供人写命令时引用。
DATASET_TARGET = "/data"
SOURCE_TARGET = "/src"
WORK_TARGET = "/work"
OUTPUT_TARGET = "/output"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:TEXT_LIMIT]
    except OSError:
        return ""


def _entry_kind(name: str) -> str:
    lowered = name.lower()
    for kind, keywords in ENTRY_KINDS:
        if any(keyword in lowered for keyword in keywords):
            return kind
    return "other"


def find_entrypoints(source: Path, limit: int = 12) -> list[dict[str, Any]]:
    """根目录与 scripts/ 下像训练入口的脚本。训练类排最前。"""
    candidates: list[Path] = []
    for pattern in ("*.py", "scripts/*.py", "src/*.py"):
        candidates.extend(sorted(source.glob(pattern)))
    found: list[dict[str, Any]] = []
    for path in candidates:
        if path.name.startswith("_") or path.name == "setup.py":
            continue
        kind = _entry_kind(path.stem)
        if kind == "other":
            continue
        found.append({"path": path.relative_to(source).as_posix(), "kind": kind})
    order = {"train": 0, "evaluate": 1, "infer": 2, "export": 3, "other": 4}
    found.sort(key=lambda item: (order[item["kind"]], item["path"]))
    return found[:limit]


def dependency_manifest(source: Path) -> str | None:
    """挑一个依赖清单。requirements.txt 优先，它是 `pip download` 最直接的目标。"""
    for name in DEPENDENCY_CANDIDATES:
        if (source / name).is_file():
            return name
    return None


def readme_name(source: Path) -> str | None:
    return next((path.name for path in sorted(source.glob("README*")) if path.is_file()), None)


def commands_from_readme(source: Path, readme: str | None, known_paths: list[str]) -> list[dict[str, Any]]:
    """把 README 里提到仓库脚本的命令行抄出来，带上文件:行号。

    只抄不猜：命令原文照搬，出处写到行，人看到的就是仓库自己写的用法。
    """
    if readme is None:
        return []
    text = _read_text(source / readme)
    found: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), 1):
        match = COMMAND_PATTERN.match(line)
        if match is None:
            continue
        command = match.group(1).strip()
        if not any(path in command for path in known_paths):
            continue
        if any(item["command"] == command for item in found):
            continue
        found.append({"command": command, "source": f"{readme}:{index}", "origin": "documented"})
    return found


def looks_like_gpu(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in GPU_HINTS)


def reproduce_plan(
    workspace: Path,
    record: dict[str, Any],
    *,
    image: str = "python:3.12-slim",
    cpus: str = "4",
    memory: str = "8g",
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """给一个已通过静态检查的仓库生成复现计划。"""
    source = Path(str(record.get("local_path") or ""))
    if record.get("status") != "static_inspection_complete" or not source.is_dir():
        raise ValueError("Repository must pass static inspection before a plan can be made.")

    entrypoints = find_entrypoints(source)
    manifest = dependency_manifest(source)
    readme = readme_name(source)
    known_paths = [item["path"] for item in entrypoints]
    documented = commands_from_readme(source, readme, known_paths)

    commands: list[dict[str, Any]] = []
    for index, item in enumerate(documented, 1):
        commands.append({"id": f"cmd-{index}", **item, "confidence": "documented"})
    # 文档里没有可用命令时，退回到「先看帮助、再裸跑」。两条都明确标成 fallback，
    # 因为它们不保证是仓库真正推荐的用法。
    if not commands:
        for item in entrypoints[:2]:
            commands.append(
                {
                    "id": f"cmd-{len(commands) + 1}",
                    "command": f"python {item['path']} --help",
                    "source": f"{item['path']} (entrypoint)",
                    "origin": "fallback",
                    "confidence": "probe",
                }
            )
        if entrypoints:
            commands.append(
                {
                    "id": f"cmd-{len(commands) + 1}",
                    "command": f"python {entrypoints[0]['path']}",
                    "source": f"{entrypoints[0]['path']} (entrypoint)",
                    "origin": "fallback",
                    "confidence": "unverified",
                }
            )

    probe_text = " ".join(
        [_read_text(source / name) for name in ([manifest] if manifest else []) + ([readme] if readme else [])]
    )
    dataset = audited_dataset(workspace)
    return {
        "created_at": utc_now(),
        "repository": record.get("repository"),
        "commit": record.get("commit"),
        "local_path": str(source),
        "slug": source.name,
        "image": image,
        "requires_gpu": looks_like_gpu(probe_text),
        "dependency_manifest": manifest,
        "readme": readme,
        "entrypoints": entrypoints,
        "commands": commands,
        "dataset": dataset,
        "mounts": {
            "source": {"target": SOURCE_TARGET, "read_only": True},
            "work": {"target": WORK_TARGET, "read_only": False},
            "output": {"target": OUTPUT_TARGET, "read_only": False},
            "dataset": {"target": DATASET_TARGET, "read_only": True, "present": dataset is not None},
        },
        "resources": {"cpus": cpus, "memory": memory, "timeout_seconds": timeout_seconds},
        "execution_policy": (
            "Two phases: a networked phase that only downloads wheels, then a network-isolated "
            "phase that installs them and runs the approved command. The repository is mounted "
            "read-only; the audited dataset is mounted read-only."
        ),
    }


def audited_dataset(workspace: Path) -> dict[str, Any] | None:
    """已审计的本地数据集：目录 + 指纹。没审计过就不给挂载点，不猜路径。"""
    statistics_path = workspace / "reports" / "data_statistics.json"
    if not statistics_path.exists():
        return None
    payload = read_json(statistics_path)
    data_dir = str(payload.get("data_dir") or "").strip()
    if not data_dir or not Path(data_dir).is_dir():
        return None
    return {
        "host_path": data_dir,
        "target": DATASET_TARGET,
        "inventory_sha256": payload.get("inventory_sha256"),
        "file_count": payload.get("file_count"),
    }


def plan_id(slug: str) -> str:
    """计划 id 直接带仓库名：人一眼能对上是哪个仓库的复现。"""
    return f"REPRO-{slug}"


def write_plan(workspace: Path, plan: dict[str, Any]) -> dict[str, Any]:
    slug = str(plan.get("slug") or "repository")
    stored = {"plan_id": plan_id(slug), **plan}
    write_json_atomic(workspace / "reproductions" / "plans" / f"{slug}.json", stored)
    return stored
