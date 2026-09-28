"""研究循环接口的测试：路由接得上、内置界面能取到、同源请求不被 403 挡掉。

最后一条是修出来的真缺陷：内置界面由本服务自己 serve，它发来的 `Origin` 必然等于本机
地址，可桌面白名单里没有它 —— 于是界面一调敏感端点就是 403，整个应用功能全废，
而单看服务端代码完全看不出问题（白名单看起来"很正常"）。所以用真实 HTTP 请求钉住它。

这里刻意用 `backfill` 而不是 `step` 来验同源：它是敏感端点，但不会真调模型，
所以既走了完整门禁，又不必为了测试去 stub 一个执行器。
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

from app.api_server import CompetitionApiHandler, _RESEARCH_LOOP_CACHE
from app.research_loop_service import ResearchLoopService


def _workspace(root: Path) -> Path:
    workspace = root / "workspace"
    (workspace / "experiments" / "manifests").mkdir(parents=True)
    (workspace / "experiments" / "results").mkdir(parents=True)
    (workspace / "research" / "loop").mkdir(parents=True)
    return workspace


def _fake_executor(action: str, decision: object, state: object, workspace: Path) -> dict:
    return {"detail": f"fake handled {action}"}


class ResearchLoopApiTests(unittest.TestCase):
    def _serve(self, root: Path, workspace: Path):
        handler = type(
            "TestResearchLoopApiHandler",
            (CompetitionApiHandler,),
            {"project_root": root, "workspace": workspace},
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _stop(self, server, thread) -> None:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    def _get(self, base: str, path: str) -> dict:
        with urlopen(base + path, timeout=5) as response:  # nosec B310: local test server
            return json.loads(response.read())

    def _post(self, base: str, path: str, payload: dict, origin: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        request = Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:  # nosec B310: local test server
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return int(error.code), json.loads(error.read().decode("utf-8"))

    def test_the_loop_endpoint_answers_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                snapshot = self._get(base, "/api/research/loop")
            finally:
                self._stop(server, thread)

            self.assertIn("summary", snapshot)
            self.assertIn("next_action", snapshot)
            self.assertIn("hypotheses", snapshot)

    def test_the_built_in_ui_is_served_from_the_same_origin(self) -> None:
        """界面与接口同源：这是"同源即可信"那条规则成立的前提。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                for path, marker in (("/", "<!doctype html>"), ("/ui.js", "PageHeader"), ("/styles.css", "--primary")):
                    with urlopen(base + path, timeout=5) as response:  # nosec B310: local test server
                        body = response.read().decode("utf-8")
                    self.assertIn(marker, body, f"{path} 没取到界面内容")
            finally:
                self._stop(server, thread)

    def test_a_page_served_by_this_server_is_not_forbidden(self) -> None:
        """界面调敏感端点不能是 403。

        内置界面就是本服务 serve 出去的，浏览器发请求时带的 Origin 必然等于本机地址。
        不认这一条，应用一打开就处处失败。
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status, payload = self._post(base, "/api/research/loop/backfill", {}, origin=base)
            finally:
                self._stop(server, thread)

            self.assertEqual(status, 200, payload)
            self.assertIn("summary", payload)

    def test_another_site_is_still_forbidden(self) -> None:
        """放行同源不等于放行所有来源 —— 别的站点的页面仍然进不来。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status, _ = self._post(base, "/api/research/loop/backfill", {}, origin="https://evil.example")
            finally:
                self._stop(server, thread)

            self.assertEqual(status, 403)

    def test_a_port_mismatch_is_still_forbidden(self) -> None:
        """同源判定要连端口一起比：只比主机名会让另一个本地服务也拿到权限。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            other = f"http://127.0.0.1:{server.server_port + 1}"
            try:
                status, _ = self._post(base, "/api/research/loop/backfill", {}, origin=other)
            finally:
                self._stop(server, thread)

            self.assertEqual(status, 403)

    def test_a_step_is_accepted_as_a_job(self) -> None:
        """推进走作业模式：同步返回必然读超时，所以只能 202 加轮询。

        断言刻意**不**写死"接的这一刻状态还是 running"：假执行器快得能在响应被序列化之前
        就跑完，那个断言会变成偶发失败。作业模式真正承诺的是两件事 —— 给一个作业号，
        以及这个号查得到终态。这里就断言这两件。
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            # 预置一份带假执行器的服务，避免测试去调真实模型。
            _RESEARCH_LOOP_CACHE[str(workspace.resolve())] = ResearchLoopService(
                root, workspace, executor_factory=lambda: _fake_executor
            )
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status, job = self._post(base, "/api/research/loop/step", {"max_steps": 1}, origin=base)
                self.assertEqual(status, 202, job)
                self.assertTrue(job.get("job_id"), "202 必须给出作业号，否则界面没法轮询")
                self.assertIn(job["status"], ("running", "completed"), job)

                # 等作业结束再离开临时目录，否则 Windows 上删不掉。
                deadline = 10
                snapshot: dict = {}
                for _ in range(deadline * 20):
                    snapshot = self._get(base, "/api/research/loop")
                    if not snapshot["running"]:
                        break
                    threading.Event().wait(0.05)
                self.assertFalse(snapshot["running"], "作业没有在超时内结束")

                detail = self._get(base, f"/api/research/loop/jobs/{job['job_id']}")
                self.assertEqual(detail["status"], "completed", detail)
            finally:
                self._stop(server, thread)
                _RESEARCH_LOOP_CACHE.pop(str(workspace.resolve()), None)

    def test_a_second_step_while_one_runs_is_a_conflict(self) -> None:
        """同一工作区不能有两个循环同时改状态，接口层要把这件事答成 409 而不是 500。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace(root)
            released = threading.Event()

            def blocking_executor(action: str, decision: object, state: object, workspace_path: Path) -> dict:
                released.wait(timeout=10)
                return {"detail": "慢执行器"}

            _RESEARCH_LOOP_CACHE[str(workspace.resolve())] = ResearchLoopService(
                root, workspace, executor_factory=lambda: blocking_executor
            )
            server, thread = self._serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                first_status, first_body = self._post(base, "/api/research/loop/step", {"max_steps": 1}, origin=base)
                self.assertEqual(first_status, 202, first_body)

                second_status, second_body = self._post(base, "/api/research/loop/step", {"max_steps": 1}, origin=base)
                self.assertEqual(second_status, 409, second_body)
            finally:
                released.set()
                threading.Event().wait(0.5)
                self._stop(server, thread)
                _RESEARCH_LOOP_CACHE.pop(str(workspace.resolve()), None)


if __name__ == "__main__":
    unittest.main()
