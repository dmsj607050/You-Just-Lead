"""项目（竞赛工作区）注册表。

App 现在的入口是「先选项目、再进工作台」，所以「有哪些项目、当前是哪一个」必须
落盘，并且 App 与命令行认同一份：`workspace/projects.json`。

一个项目就是一个工作区目录 `workspace/<id>/`，里面放这场竞赛的规则、数据、实验与
提交候选。历史遗留的 `workspace/current_competition` 会被当作第一个项目自动登记，
所以升级不会搬动任何已有文件，`competition_spec.yaml` 的位置也不变。

新建项目时按既有约定从 `competition_spec.template.yaml` 复制一份骨架并把项目名写进
`competition.name`，这样新项目一建出来就是一个规格齐备（字段为空）的工作区，
而不是一个空目录；界面上的「尚未配置竞赛」也因此变成「已命名但还没填规则」。
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.experiment_service import ensure_workspace_layout
from database.ledger import LEGACY_PROJECT_ID
from tools.configuration import load_yaml, write_yaml
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now

REGISTRY_FILENAME = "projects.json"
REGISTRY_VERSION = 1
SPEC_FILENAME = "competition_spec.yaml"
TEMPLATE_FILENAME = "competition_spec.template.yaml"
MAX_NAME_LENGTH = 60
MIN_SLUG_LENGTH = 3

_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class ProjectError(ValueError):
    """项目注册表的用法错误，调用方应转成 4xx 而不是 5xx。"""


class ProjectNotSelected(ProjectError):
    """还没有选定项目。只有项目列表类接口能在这种状态下工作。"""


def projects_root(project_root: Path) -> Path:
    return project_root / "workspace"


def registry_path(project_root: Path) -> Path:
    return projects_root(project_root) / REGISTRY_FILENAME


def workspace_path(project_root: Path, project_id: str) -> Path:
    """由项目 id 定位工作区目录。

    id 可能来自 HTTP 请求体，所以先卡死字符集，避免 `../` 这类路径穿越。
    """
    if not _ID_PATTERN.fullmatch(project_id):
        raise ProjectError(f"Invalid project id: {project_id!r}")
    return projects_root(project_root) / project_id


def load_registry(project_root: Path) -> dict[str, Any]:
    """读取注册表；文件不存在时先扫描现存工作区补一份出来。

    首次补登记会写文件，这是升级必需的一次性动作，之后读注册表都是纯读。
    """
    path = registry_path(project_root)
    if path.exists():
        payload = read_json(path)
        projects = payload.get("projects")
        if not isinstance(projects, list):
            raise ProjectError(f"Registry is malformed: {path}")
        current = payload.get("current")
        return {
            "version": REGISTRY_VERSION,
            "current": current if isinstance(current, str) and current else None,
            "projects": [item for item in projects if isinstance(item, dict) and item.get("id")],
        }
    registry = _bootstrap(project_root)
    save_registry(project_root, registry)
    return registry


def save_registry(project_root: Path, registry: dict[str, Any]) -> None:
    write_json_atomic(registry_path(project_root), registry)


def list_projects(project_root: Path) -> list[dict[str, Any]]:
    """按注册顺序返回项目，并标出当前项目。"""
    registry = load_registry(project_root)
    current = registry["current"]
    return [dict(project, current=project["id"] == current) for project in registry["projects"]]


def current_project(project_root: Path) -> dict[str, Any] | None:
    registry = load_registry(project_root)
    current = registry["current"]
    for project in registry["projects"]:
        if project["id"] == current:
            return dict(project)
    return None


def current_workspace(project_root: Path) -> Path:
    """当前项目的工作区目录。没选项目就抛 ProjectNotSelected。"""
    project = current_project(project_root)
    if project is None:
        raise ProjectNotSelected("No project is selected; create or select one first")
    return workspace_path(project_root, str(project["id"]))


def find_project(project_root: Path, project_id: str) -> dict[str, Any]:
    """按 id 取项目；id 不在注册表里就抛 ProjectError。"""
    return dict(_find(load_registry(project_root), project_id))


def select_project(project_root: Path, project_id: str) -> dict[str, Any]:
    """把某个项目设为当前项目。"""
    registry = load_registry(project_root)
    project = _find(registry, project_id)
    registry["current"] = project["id"]
    save_registry(project_root, registry)
    return dict(project)


def delete_project(project_root: Path, project_id: str) -> dict[str, Any]:
    """删除一个项目：从注册表移除，并把工作区目录真的删掉。

    删掉的如果是当前项目，`current` 置空而不是自动改选别的项目——让「没有当前项目」
    这个状态显式存在，客户端会回到项目选择页，命令行也会明确报「先选一个项目」。

    先写注册表再删目录：目录删不掉（文件被占用）时注册表已经是干净的，抛出的错误
    会把原因说清楚，不会留下一个指向已删项目的条目。
    """
    registry = load_registry(project_root)
    project = _find(registry, project_id)
    workspace = workspace_path(project_root, project_id)
    registry["projects"] = [item for item in registry["projects"] if item["id"] != project_id]
    if registry["current"] == project_id:
        registry["current"] = None
    save_registry(project_root, registry)
    if workspace.is_dir():
        try:
            shutil.rmtree(workspace)
        except OSError as error:
            raise ProjectError(f"Removed {project_id} from the registry but failed to delete {workspace}: {error}") from error
    return dict(project)


def create_project(project_root: Path, name: str) -> dict[str, Any]:
    """新建一个项目并设为当前项目。

    只建目录骨架与一份带名字的规格，不写任何实验或规则内容：规则要靠读取官方文档
    后人工确认，这条链路不变。同名项目允许并存，id 会自动让开。
    """
    cleaned = " ".join(str(name).split())
    if not cleaned:
        raise ProjectError("Project name must not be empty")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ProjectError(f"Project name must be at most {MAX_NAME_LENGTH} characters")

    registry = load_registry(project_root)
    taken = {str(project["id"]) for project in registry["projects"]}
    project_id = _unique_id(_slug(cleaned), taken)
    workspace = workspace_path(project_root, project_id)
    ensure_workspace_layout(workspace)
    write_yaml(workspace / SPEC_FILENAME, _spec_skeleton(project_root, cleaned))

    project = {"id": project_id, "name": cleaned, "created_at": utc_now()}
    registry["projects"].append(project)
    registry["current"] = project_id
    save_registry(project_root, registry)
    return project


def _find(registry: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in registry["projects"]:
        if project["id"] == project_id:
            return project
    raise ProjectError(f"Unknown project: {project_id!r}")


def _bootstrap(project_root: Path) -> dict[str, Any]:
    """扫描现存工作区，生成初始注册表。"""
    root = projects_root(project_root)
    projects: list[dict[str, Any]] = []
    if root.exists():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not (entry / SPEC_FILENAME).exists():
                continue
            projects.append({
                "id": entry.name,
                "name": _spec_name(entry) or entry.name,
                "created_at": _directory_created_at(entry),
            })
    ids = [str(project["id"]) for project in projects]
    if LEGACY_PROJECT_ID in ids:
        current = LEGACY_PROJECT_ID
    else:
        current = ids[0] if ids else None
    return {"version": REGISTRY_VERSION, "current": current, "projects": projects}


def _spec_name(workspace: Path) -> str | None:
    """从规格里取竞赛名，取不到就返回 None，由调用方退回目录名。"""
    path = workspace / SPEC_FILENAME
    try:
        name = load_yaml(path).get("competition", {}).get("name")
    except (OSError, ValueError):
        return None
    text = str(name).strip() if name is not None else ""
    return text or None


def _directory_created_at(workspace: Path) -> str:
    """用规格文件的修改时间当项目建立时间，比「首次登记时间」更接近事实。"""
    spec = workspace / SPEC_FILENAME
    try:
        stamp = spec.stat().st_mtime
    except OSError:
        stamp = workspace.stat().st_mtime
    return datetime.fromtimestamp(stamp, timezone.utc).replace(microsecond=0).isoformat()


def _slug(name: str) -> str:
    """把项目名压成目录名用的 id；纯中文名压不出东西，退回 project-<时间戳>。"""
    slug = _SLUG_STRIP.sub("-", name.lower()).strip("-")
    if len(slug) < MIN_SLUG_LENGTH:
        slug = "project-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return slug[:MAX_NAME_LENGTH]


def _unique_id(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def _spec_skeleton(project_root: Path, name: str) -> dict[str, Any]:
    """按模板生成新项目的规格骨架，模板找不到就用一份最小可用结构。"""
    template = _template_source(project_root)
    if template is not None:
        spec = load_yaml(template)
    else:
        spec = {
            "evaluation": {"direction": "maximize"},
            "approval": {"requires_human_confirmation": True, "unresolved_questions": []},
        }
    competition = spec.get("competition")
    if not isinstance(competition, dict):
        competition = {}
    competition["name"] = name
    spec["competition"] = competition
    return spec


def _template_source(project_root: Path) -> Path | None:
    """模板跟着项目走（README 就是让人从它复制），取排序最靠前的那份。"""
    root = projects_root(project_root)
    if not root.exists():
        return None
    for entry in sorted(root.iterdir()):
        candidate = entry / TEMPLATE_FILENAME
        if entry.is_dir() and candidate.exists():
            return candidate
    return None
