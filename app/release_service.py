"""发布清单：把一个「版本」变成可审计的记录。

目标对 Release Engineering 的要求原话是「最终提交出去的不再是一个『文件包』，而是一个**可审计的
软件版本**」，并点名 `release_manifest.json` 要记录 version / git commit / schema version /
build time / HAP 或 APP 的 SHA256 / backend version / workspace schema / migration version。

为什么必须做成命令而不是靠人记：`docs/RELEASE_0.1.5.md` 记了安装包的 SHA-256，而 0.1.6~0.1.9
都没记 —— **靠人记的纪律一定会退化**。这里把它变成一条命令的产物。

## 什么算「可以发布」

三道一起过才算（`release_ready`）：

1. 版本号处于 `rc` 或正式版阶段（`dev` / `alpha` / `beta` 不算发布）；
2. 发布必需的产物**都在**（缺了就判为不可发布，而不是记一条空路径 —— 这正是
   「有 RELEASE_0.1.9.md 却没有对应安装包」这类不一致的根因）；
3. 两个仓库都**没有未提交改动**（发布必须从干净的提交切出来，否则 commit 号对不上实际内容）。

产物路径（HAP 在端侧仓库里，exe 在后端仓库里）是**事实**，不是配置：写在 `_default_artifacts`。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.experiment_service import WORKSPACE_DIRECTORIES
from database.ledger import SCHEMA_VERSION as DB_MIGRATION_VERSION
from app.project_registry import REGISTRY_VERSION
from app.training_scaffold_service import SCHEMA_VERSION as SCAFFOLD_SCHEMA_VERSION
from schemas.contracts import CONTRACT_VERSION
from tools.device_project import device_project_root
from tools.files import write_json_atomic
from tools.provenance import file_sha256, git_provenance, utc_now

#: 清单自身的格式版本；加字段不改含义时不动它。
MANIFEST_VERSION = 1

#: 版本号的唯一来源。
VERSION_FILE = "VERSION"

#: 版本流：dev → alpha → beta → rc → release。没有后缀即正式版。
STAGES: tuple[str, ...] = ("dev", "alpha", "beta", "rc", "release")

_VERSION_PATTERN = re.compile(
    r"^(?P<core>\d+\.\d+\.\d+)(?:-(?P<stage>dev|alpha|beta|rc)\.(?P<serial>\d+))?$"
)


@dataclass(frozen=True)
class ProjectVersion:
    """解析后的版本号。`stage == "release"` 表示正式版（版本号里没有后缀）。"""

    text: str
    core: str
    stage: str
    serial: int | None

    @property
    def is_release_stage(self) -> bool:
        return self.stage in ("rc", "release")


@dataclass(frozen=True)
class ArtifactSpec:
    """一个要记进清单的产物。`relative` 允许通配（取排序后第一个匹配）。"""

    name: str
    kind: str
    root: Path
    relative: str
    required_for_release: bool


def parse_version(text: str) -> ProjectVersion:
    """解析 `MAJOR.MINOR.PATCH[-stage.N]`，不合法就报错（不猜、不兜底）。"""
    cleaned = str(text).strip()
    match = _VERSION_PATTERN.match(cleaned)
    if match is None:
        raise ValueError(
            f"Unsupported version {cleaned!r}: expect MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-<stage>.<n> "
            f"with stage in {', '.join(STAGES[:-1])}"
        )
    stage = match.group("stage") or "release"
    serial = match.group("serial")
    return ProjectVersion(
        text=cleaned,
        core=match.group("core"),
        stage=stage,
        serial=int(serial) if serial is not None else None,
    )


def read_project_version(project_root: Path) -> ProjectVersion:
    path = Path(project_root) / VERSION_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{VERSION_FILE} is required to describe a release: {path}")
    return parse_version(path.read_text(encoding="utf-8"))


def _resolve(spec: ArtifactSpec) -> Path | None:
    """把产物定位到具体文件；没找到返回 None（由调用方记成 present=false）。"""
    if "*" in spec.relative:
        matches = sorted(spec.root.glob(spec.relative))
        return matches[0] if matches else None
    candidate = spec.root / spec.relative
    return candidate if candidate.is_file() else None


def _default_artifacts(project_root: Path, device_root: Path) -> list[ArtifactSpec]:
    return [
        ArtifactSpec(
            name="backend-executable",
            kind="windows-executable",
            root=Path(project_root),
            relative="dist/competition-agent-api.exe",
            # 无界面的本地服务：给没有 Python 环境的机器用，鸿蒙端在电脑上连的就是它。
            required_for_release=True,
        ),
        ArtifactSpec(
            name="desktop-app",
            kind="windows-desktop-app",
            root=Path(project_root),
            relative="dist/YouJustLead.exe",
            # 用户双击就能用的完整应用（自带界面）。它和服务那个 exe 是两个交付物：
            # 一个给端侧当执行器，一个给人当工具，混起来会让"少了哪个"说不清。
            required_for_release=True,
        ),
        # 端侧这两个**无条件列进来**。以前端侧在另一个仓库里，找不到那个仓库时这里
        # 直接不 append —— 于是清单少了一半、`release_ready` 却是 true。产物"该在哪"
        # 由位置决定，跟"这次找没找到"无关；找不到就记 present=false，让它变成阻塞项。
        ArtifactSpec(
            name="device-hap",
            kind="harmony-hap",
            root=device_root,
            relative="entry/build/default/outputs/default/entry-default-signed.hap",
            required_for_release=True,
        ),
        ArtifactSpec(
            name="device-app",
            kind="harmony-app",
            root=device_root,
            relative="build/outputs/default/*.app",
            # Release 上架交的是 `.app`（要在 DevEco 里 Build APP(s) 才产出），
            # 当前只有调试签名 HAP，所以这一条先记成"非发布必需"，缺了就如实记 present=false。
            required_for_release=False,
        ),
    ]


def _device_app_info(device_root: Path) -> dict[str, Any] | None:
    """端侧应用标识：bundleName / versionName / versionCode（读 `AppScope/app.json5`）。"""
    path = device_root / "AppScope" / "app.json5"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    app = payload.get("app") if isinstance(payload.get("app"), dict) else {}
    return {
        "bundle_name": app.get("bundleName"),
        "version_name": app.get("versionName"),
        "version_code": app.get("versionCode"),
    }


def _workspace_schema() -> dict[str, Any]:
    """工作区骨架的身份：目录清单 + 它的摘要（清单变了摘要就变）。"""
    listing = "\n".join(WORKSPACE_DIRECTORIES)
    return {
        "directories": list(WORKSPACE_DIRECTORIES),
        "digest": hashlib.sha256(listing.encode("utf-8")).hexdigest(),
    }


def build_release_manifest(
    project_root: Path,
    *,
    device_root: Path | None = None,
    version_text: str | None = None,
    artifacts: list[ArtifactSpec] | None = None,
    build_time: str | None = None,
) -> dict[str, Any]:
    """生成发布清单。

    `device_root` 默认是仓库里的 `device/`；测试可以注入一个临时目录来验版本一致性。
    `artifacts` 可注入，测试与将来换打包路径都用得上。
    """
    root = Path(project_root).resolve()
    device = Path(device_root).resolve() if device_root is not None else device_project_root(root)
    version = parse_version(version_text) if version_text is not None else read_project_version(root)

    specs = artifacts if artifacts is not None else _default_artifacts(root, device)
    entries: list[dict[str, Any]] = []
    for spec in specs:
        found = _resolve(spec)
        entries.append(
            {
                "name": spec.name,
                "kind": spec.kind,
                "path": str(found) if found is not None else str(spec.root / spec.relative),
                "present": found is not None,
                "bytes": found.stat().st_size if found is not None else None,
                "sha256": file_sha256(found) if found is not None else None,
                "required_for_release": spec.required_for_release,
            }
        )

    backend_git = git_provenance(root)

    missing = [entry["name"] for entry in entries if entry["required_for_release"] and not entry["present"]]
    dirty = ["backend"] if backend_git is not None and backend_git.get("dirty") else []
    blockers: list[str] = []
    if not version.is_release_stage:
        blockers.append(f"version stage is {version.stage!r}, not rc/release")
    if missing:
        blockers.append("required artifacts are missing: " + ", ".join(missing))
    if dirty:
        blockers.append("uncommitted changes in: " + ", ".join(dirty))

    app_info = _device_app_info(device)
    if app_info is not None and app_info.get("version_name") not in (None, version.core):
        # 应用版本与应用内声明不一致，是"文档里的版本 ≠ 实际构建的版本"那类问题的根。
        blockers.append(
            f"device app versionName {app_info['version_name']!r} does not match version core {version.core!r}"
        )

    return {
        "manifest_version": MANIFEST_VERSION,
        "version": version.text,
        "version_core": version.core,
        "stage": version.stage,
        "build_time": build_time or utc_now(),
        "git": {"backend": backend_git},
        "schema": {
            "data_contracts": CONTRACT_VERSION,
            "db_migration": DB_MIGRATION_VERSION,
            "experiment_registry": REGISTRY_VERSION,
            "training_scaffold": SCAFFOLD_SCHEMA_VERSION,
        },
        "workspace_schema": _workspace_schema(),
        "components": {
            "backend": {"python": sys.version.split()[0]},
            "device": app_info,
        },
        "artifacts": entries,
        "release_ready": not blockers,
        "release_blockers": blockers,
    }


def manifest_path(project_root: Path) -> Path:
    """发布清单的落点：与产物放在一起（`release/`，该目录不进版本库）。"""
    return Path(project_root) / "release" / "release_manifest.json"


def write_release_manifest(project_root: Path, manifest: dict[str, Any]) -> Path:
    target = manifest_path(project_root)
    write_json_atomic(target, manifest)
    return target


def release_manifest_for_project(project_root: Path, *, device_root: Path | None = None) -> dict[str, Any]:
    """便捷入口：按默认位置找端侧工程、自己写文件，返回清单。"""
    root = Path(project_root).resolve()
    manifest = build_release_manifest(root, device_root=device_root)
    write_release_manifest(root, manifest)
    return manifest


def stage_release_artifacts(project_root: Path, manifest: dict[str, Any]) -> Path:
    """把清单里**确实存在**的产物复制进 `release/`，并写出 `SHA256SUMS.txt`。

    产物本来分散在两处（Windows 两个 exe 在 `dist/`，HAP 在 `device/entry/build/`），而用户下载的是
    一个版本包 —— 这里把它们归到一处，并给出下载页要贴的那几行校验和。

    **复制而不是移动**：`dist/` 仍然是构建产物的原处，删掉 `release/` 不会毁掉构建结果。
    缺的产物直接跳过（清单里已经如实记成 `present: false`），不编一行假校验和。
    """
    directory = Path(project_root) / "release"
    directory.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for entry in manifest.get("artifacts", []):
        if not entry.get("present"):
            continue
        source = Path(str(entry["path"]))
        target = directory / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        lines.append(f"{entry['sha256']}  {source.name}")
    sums = directory / "SHA256SUMS.txt"
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sums
