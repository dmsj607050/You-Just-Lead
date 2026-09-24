"""项目注册表与项目接口。

App 的入口改成「先选项目、再进工作台」之后，「有哪些项目、当前是哪个」就成了后端
必须负责的事：注册表要能自动登记历史工作区，新建项目要能造出可用骨架，切换项目要
真的把后续请求指到另一个工作区。
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.api_server import CompetitionApiHandler
from app.project_registry import (
    ProjectError,
    ProjectNotSelected,
    create_project,
    current_project,
    current_workspace,
    delete_project,
    find_project,
    list_projects,
    load_registry,
    registry_path,
    select_project,
    workspace_path,
)
from tools.configuration import load_yaml, write_yaml
from tools.files import read_json


def _legacy_workspace(root: Path, name: str) -> Path:
    workspace = root / "workspace" / "current_competition"
    write_yaml(workspace / "competition_spec.yaml", {"competition": {"name": name}})
    return workspace


class ProjectRegistryTests(unittest.TestCase):
    def test_first_read_registers_existing_workspace_and_keeps_it_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _legacy_workspace(root, "Legacy Cup")

            registry = load_registry(root)

            self.assertEqual(registry["current"], "current_competition")
            self.assertEqual([item["name"] for item in registry["projects"]], ["Legacy Cup"])
            self.assertEqual(current_workspace(root), workspace)
            # 补登记会落盘，之后读注册表不再改动文件。
            self.assertTrue(registry_path(root).exists())
            self.assertEqual(read_json(registry_path(root))["current"], "current_competition")

    def test_create_project_builds_usable_layout_and_selects_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy_workspace(root, "Legacy Cup")

            project = create_project(root, "  Water Seg v2  ")

            self.assertEqual(project["id"], "water-seg-v2")
            self.assertEqual(project["name"], "Water Seg v2")
            workspace = root / "workspace" / "water-seg-v2"
            self.assertTrue((workspace / "configs").is_dir())
            self.assertTrue((workspace / "experiments" / "drafts").is_dir())
            self.assertTrue((workspace / "data" / "raw").is_dir())
            self.assertEqual(load_yaml(workspace / "competition_spec.yaml")["competition"]["name"], "Water Seg v2")
            self.assertEqual(current_workspace(root), workspace)
            self.assertEqual(current_project(root)["id"], "water-seg-v2")

    def test_new_project_copies_the_spec_template_when_one_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _legacy_workspace(root, "Legacy Cup")
            template = {
                "competition": {"name": None, "task_type": None},
                "submission": {"format": None, "required_columns": []},
            }
            write_yaml(workspace / "competition_spec.template.yaml", template)

            project = create_project(root, "Fresh Cup")
            spec = load_yaml(workspace_path(root, project["id"]) / "competition_spec.yaml")

            # 模板里的骨架要留下来（人照着填），但名字必须换成新项目的。
            self.assertIn("submission", spec)
            self.assertEqual(spec["competition"]["name"], "Fresh Cup")
            self.assertIsNone(spec["competition"]["task_type"])

    def test_chinese_name_falls_back_to_a_stable_directory_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            project = create_project(root, "遥感水体分割")

            self.assertEqual(project["name"], "遥感水体分割")
            self.assertTrue(str(project["id"]).startswith("project-"))
            self.assertTrue(workspace_path(root, str(project["id"])).is_dir())

    def test_duplicate_names_get_distinct_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            first = create_project(root, "same name")
            second = create_project(root, "same name")

            self.assertEqual(first["id"], "same-name")
            self.assertEqual(second["id"], "same-name-2")
            self.assertEqual(len(list_projects(root)), 2)

    def test_create_project_rejects_missing_or_overlong_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            with self.assertRaises(ProjectError):
                create_project(root, "   ")
            with self.assertRaises(ProjectError):
                create_project(root, "x" * 61)
            # 名字不合法时不应该留下半个项目。
            self.assertEqual(list_projects(root), [])

    def test_select_project_rejects_unknown_ids_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy_workspace(root, "Legacy Cup")

            with self.assertRaises(ProjectError):
                select_project(root, "nope")
            with self.assertRaises(ProjectError):
                select_project(root, "../escape")
            with self.assertRaises(ProjectError):
                workspace_path(root, "../../etc")

    def test_workspace_requests_are_rejected_before_any_project_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            self.assertEqual(list_projects(root), [])
            self.assertIsNone(current_project(root))
            with self.assertRaises(ProjectNotSelected):
                current_workspace(root)

    def test_delete_project_removes_entry_and_workspace_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy_workspace(root, "Legacy Cup")
            project = create_project(root, "Throwaway")
            workspace = workspace_path(root, str(project["id"]))
            self.assertTrue(workspace.is_dir())

            deleted = delete_project(root, str(project["id"]))

            self.assertEqual(deleted["name"], "Throwaway")
            self.assertFalse(workspace.exists())
            self.assertEqual([item["id"] for item in list_projects(root)], ["current_competition"])
            # 删掉的是当前项目时不自动改选别的项目，让「没有当前项目」显式存在。
            self.assertIsNone(current_project(root))
            with self.assertRaises(ProjectNotSelected):
                current_workspace(root)

    def test_delete_project_leaves_the_other_projects_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = _legacy_workspace(root, "Legacy Cup")
            project = create_project(root, "Throwaway")
            select_project(root, "current_competition")

            delete_project(root, str(project["id"]))

            self.assertTrue(legacy.is_dir())
            self.assertEqual(current_project(root)["id"], "current_competition")
            self.assertEqual(current_workspace(root), legacy)

    def test_delete_project_rejects_unknown_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy_workspace(root, "Legacy Cup")

            with self.assertRaises(ProjectError):
                delete_project(root, "nope")
            with self.assertRaises(ProjectError):
                delete_project(root, "../escape")
            with self.assertRaises(ProjectError):
                find_project(root, "nope")
            self.assertEqual(find_project(root, "current_competition")["id"], "current_competition")
            self.assertEqual([item["id"] for item in list_projects(root)], ["current_competition"])


class ProjectEndpointTests(unittest.TestCase):
    """HTTP 层：项目接口 + 「切换后其他接口跟着换工作区」。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        _legacy_workspace(self.root, "Legacy Cup")
        write_yaml(
            self.root / "workspace" / "current_competition" / "competition_spec.yaml",
            {"competition": {"name": "Legacy Cup", "task_type": "classification"}, "evaluation": {"primary_metric": "accuracy"}},
        )
        # 只注入 project_root：工作区由注册表解析，这正是要测的路径。
        handler = type("TestProjectApiHandler", (CompetitionApiHandler,), {"project_root": self.root})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._temporary.cleanup()

    def _get(self, path: str) -> dict:
        with urlopen(self.base + path, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())

    def _post(self, path: str, payload: dict) -> dict:
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())

    def _post_status(self, path: str, payload: dict) -> int:
        try:
            self._post(path, payload)
        except HTTPError as error:
            return int(error.code)
        raise AssertionError(f"Expected {path} to fail")

    def _get_status(self, path: str) -> int:
        try:
            self._get(path)
        except HTTPError as error:
            return int(error.code)
        raise AssertionError(f"Expected {path} to fail")

    def _delete(self, path: str) -> dict:
        request = Request(self.base + path, method="DELETE")
        with urlopen(request, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())

    def _delete_status(self, path: str) -> int:
        try:
            self._delete(path)
        except HTTPError as error:
            return int(error.code)
        raise AssertionError(f"Expected DELETE {path} to fail")

    def test_projects_endpoint_lists_and_switches_the_active_workspace(self) -> None:
        listed = self._get("/api/projects")
        self.assertEqual(listed["current"], "current_competition")
        self.assertEqual([item["name"] for item in listed["projects"]], ["Legacy Cup"])

        created = self._post("/api/projects", {"name": "Draft Cup"})
        self.assertEqual(created["project"]["name"], "Draft Cup")
        self.assertEqual(created["current"], created["project"]["id"])
        self.assertEqual(sorted(item["name"] for item in created["projects"]), ["Draft Cup", "Legacy Cup"])

        # 新建项目后，仪表盘立刻读的是新工作区（规格里已经写进了项目名）。
        dashboard = self._get("/api/dashboard")
        self.assertEqual(dashboard["competition"]["name"], "Draft Cup")
        self.assertEqual(dashboard["summary"]["data_files"], 0)
        # 新建项目的规格几乎是空的，规则报告必须还能出结果（通用竞赛本来就没有固定字段契约）。
        report = self._get("/api/rules/report")
        self.assertIn("readiness", report)
        self.assertEqual(report["readiness"]["required_fields"], [])

        switched = self._post("/api/projects/select", {"id": "current_competition"})
        self.assertEqual(switched["current"], "current_competition")
        self.assertEqual(self._get("/api/dashboard")["competition"]["name"], "Legacy Cup")

    def test_projects_endpoint_rejects_bad_input(self) -> None:
        self.assertEqual(self._post_status("/api/projects", {"name": "  "}), 400)
        self.assertEqual(self._post_status("/api/projects/select", {"id": "../escape"}), 400)
        self.assertEqual(self._post_status("/api/projects/select", {"id": "missing"}), 400)

    def test_delete_endpoint_removes_a_created_project_and_clears_the_selection(self) -> None:
        created = self._post("/api/projects", {"name": "Disposable"})
        project_id = str(created["project"]["id"])
        workspace = self.root / "workspace" / project_id
        self.assertTrue(workspace.is_dir())

        deleted = self._delete(f"/api/projects/{project_id}")

        self.assertEqual(deleted["project"]["id"], project_id)
        self.assertEqual([item["name"] for item in deleted["projects"]], ["Legacy Cup"])
        self.assertFalse(workspace.exists())
        # 当前项目没了之后，依赖工作区的接口要明确报 409，而不是偷偷退回别的项目。
        self.assertIsNone(deleted["current"])
        self.assertEqual(self._get_status("/api/dashboard"), 409)
        # 重新选一个项目就恢复。
        self.assertEqual(self._post("/api/projects/select", {"id": "current_competition"})["current"], "current_competition")
        self.assertEqual(self._get("/api/dashboard")["competition"]["name"], "Legacy Cup")

    def test_delete_endpoint_rejects_unknown_ids_without_leaving_directories(self) -> None:
        self.assertEqual(self._delete_status("/api/projects/missing"), 400)
        self.assertEqual(self._delete_status("/api/projects/../escape"), 400)
        # 失败的删除不该在 workspace 下留下目录（projects.json 是注册表，不算项目）。
        self.assertEqual(
            sorted(entry.name for entry in (self.root / "workspace").iterdir() if entry.is_dir()),
            ["current_competition"],
        )
        self.assertEqual(self._get("/api/projects")["current"], "current_competition")

    def test_health_reports_the_active_workspace_path(self) -> None:
        health = self._get("/health")
        self.assertEqual(health["status"], "ok")
        self.assertTrue(str(health["workspace"]).endswith("current_competition"))


if __name__ == "__main__":
    unittest.main()
