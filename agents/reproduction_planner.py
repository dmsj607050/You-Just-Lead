"""Turn a cloned third-party repository into an executable reproduction plan.

This module only *reads* the repository. It produces the plan a human then
approves:

* which dependency manifest the container should install from,
* which scripts look like training entrypoints,
* candidate commands, each carrying where it came from (a README line, or a
  bare entrypoint), so a person can judge them instead of trusting them,
* which audited local dataset directory to mount, and at which path,
* whether that dataset can actually feed the repository, given the input layout
  the repository documents,
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

# 仓库 README 描述输入数据时会写的子目录名。只认这两个：README 里的 `data/images/`
# 是数据契约，而 `train/`、`val/` 更像划分方式，把划分方式当成契约会误判。
CONTRACT_DIRECTORIES = ("images", "labels")

# 只比「输入图像」的格式，不把 `.txt` 这类标注格式算进去 —— 否则一个要求 5 通道 npy
# 的仓库会因为「数据集里也有 .txt」被判成兼容。
IMAGE_EXTENSIONS = (".npy", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


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
    contract = data_contract_fit(source, Path(str(dataset["host_path"])) if dataset else None)
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
        "data_contract": contract,
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


def declared_input_contract(source: Path) -> dict[str, Any]:
    """仓库自己声明的输入数据长什么样。

    只从 README 里明说的内容提取：它要求哪些子目录、哪种图像格式。没写到就返回
    `unknown` —— 猜出来的契约比没有契约更坏，人会以为已经核对过了。
    """
    readme = readme_name(source)
    if readme is None:
        return {"status": "unknown", "readme": None, "directories": [], "extensions": [], "reason": "no README to read a contract from"}
    lowered = _read_text(source / readme).lower()
    directories = [name for name in CONTRACT_DIRECTORIES if f"{name}/" in lowered]
    extensions = [ext for ext in IMAGE_EXTENSIONS if ext in lowered]
    if not directories and not extensions:
        return {
            "status": "unknown",
            "readme": readme,
            "directories": [],
            "extensions": [],
            "reason": f"{readme} does not describe its input layout",
        }
    return {"status": "declared", "readme": readme, "directories": directories, "extensions": extensions, "reason": ""}


def dataset_layout(data_dir: Path, scan_limit: int = 5000) -> dict[str, Any]:
    """本地已审计数据集实际提供什么：顶层目录名与见过的图像扩展名。"""
    directories: set[str] = set()
    extensions: set[str] = set()
    scanned = 0
    for path in data_dir.rglob("*"):
        scanned += 1
        if scanned > scan_limit:
            break
        relative = path.relative_to(data_dir)
        if len(relative.parts) > 1:
            directories.add(relative.parts[0])
        if path.is_file():
            suffix = path.suffix.lower()
            if suffix in IMAGE_EXTENSIONS:
                extensions.add(suffix)
    return {"directories": sorted(directories), "extensions": sorted(extensions), "scanned": scanned}


def data_contract_fit(source: Path, data_dir: Path | None) -> dict[str, Any]:
    """仓库要的数据 vs 本地已审计数据实际给的东西。

    对不上的时候必须明说 —— 数据喂不进去，跑出来的任何数字都不能算复现。

    返回 `compatible` / `incompatible` / `unknown`。第三种同样要讲清楚：对一条候选
    说「没核对出来」和「核对过、不兼容」是两件完全不同的事。
    """
    declared = declared_input_contract(source)
    if declared["status"] != "declared":
        return {"status": "unknown", "reason": declared["reason"], "declared": declared, "offered": None}
    if data_dir is None or not Path(data_dir).is_dir():
        return {
            "status": "unknown",
            "reason": "no audited dataset to compare the contract against",
            "declared": declared,
            "offered": None,
        }

    offered = dataset_layout(Path(data_dir))
    expected = declared["readme"] or "README"
    missing = [name for name in declared["directories"] if name not in offered["directories"]]
    if missing:
        return {
            "status": "incompatible",
            "reason": f"{expected} expects {'/'.join(missing)}/ but the audited dataset has no {missing[0]}/ directory",
            "declared": declared,
            "offered": offered,
        }
    shared = [ext for ext in declared["extensions"] if ext in offered["extensions"]]
    if declared["extensions"] and not shared:
        held = ", ".join(offered["extensions"]) or "no image files"
        return {
            "status": "incompatible",
            "reason": f"{expected} expects {'/'.join(declared['extensions'])} inputs but the audited dataset holds {held}",
            "declared": declared,
            "offered": offered,
        }
    return {"status": "compatible", "reason": "", "declared": declared, "offered": offered}


def local_repository(workspace: Path, clone_urls: list[str]) -> Path | None:
    """在这些地址里，找一个本地已经 clone 过的仓库。

    评判候选时仓库往往还没 clone —— 那就返回 None，让契约检查写成 `unknown`。
    绝不能用「还没 clone」冒充「不兼容」。
    """
    wanted = {url.rstrip("/").removesuffix(".git") for url in clone_urls if url}
    if not wanted:
        return None
    records = workspace / "reproductions"
    if not records.is_dir():
        return None
    for path in sorted(records.glob("*.json")):
        record = read_json(path)
        repository = str(record.get("repository") or "").rstrip("/").removesuffix(".git")
        if repository not in wanted:
            continue
        local_path = Path(str(record.get("local_path") or ""))
        if local_path.is_dir():
            return local_path
    return None


def plan_id(slug: str) -> str:
    """计划 id 直接带仓库名：人一眼能对上是哪个仓库的复现。"""
    return f"REPRO-{slug}"


def write_plan(workspace: Path, plan: dict[str, Any]) -> dict[str, Any]:
    slug = str(plan.get("slug") or "repository")
    stored = {"plan_id": plan_id(slug), **plan}
    write_json_atomic(workspace / "reproductions" / "plans" / f"{slug}.json", stored)
    return stored
