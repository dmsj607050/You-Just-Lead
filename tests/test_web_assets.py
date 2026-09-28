"""Windows 端界面资产的测试。

`web/` 之前是零覆盖：界面由后端 serve，代码改动没有任何自动化保护，
而它最容易出的错恰好是"静默"的 —— 引用了不存在的端点、白名单漏了某个文件、
JS 里一个笔误让整页空白。这些都不会让后端测试变红，只会在用户打开界面时才现形。

这里只测**能确定对错**的东西：文件在不在、白名单全不全、语法通不通、
界面调用的每个端点后端是不是真的有。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from app.api_server import STATIC_ASSETS, WEB_ROOT, CompetitionApiHandler


def _serve(root: Path, workspace: Path):
    handler = type("TestWebAssetHandler", (CompetitionApiHandler,), {"project_root": root, "workspace": workspace})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class AssetTests(unittest.TestCase):
    def test_every_whitelisted_asset_exists_and_is_not_empty(self) -> None:
        """白名单与磁盘必须对得上。

        少一个文件、或多一个没人能取到的条目，都是"界面在某个时刻突然坏掉"的成因。
        """
        for route, (name, _content_type) in STATIC_ASSETS.items():
            path = WEB_ROOT / name
            with self.subTest(route=route):
                self.assertTrue(path.is_file(), f"{route} -> {name} 不存在")
                self.assertGreater(path.stat().st_size, 0, f"{name} 是空文件")

    def test_no_asset_is_left_out_of_the_whitelist(self) -> None:
        """`web/` 里不该有白名单之外的文件 —— 那意味着有人加了个取不到的资产。"""
        declared = {name for name, _ in STATIC_ASSETS.values()}
        on_disk = {item.name for item in WEB_ROOT.iterdir() if item.is_file()}

        self.assertEqual(on_disk - declared, set(), "有文件没登记进 STATIC_ASSETS")

    def test_the_index_loads_the_scripts_that_exist(self) -> None:
        """index.html 引的每个脚本/样式都要在白名单里，否则页面会静默地少一半。"""
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        referenced = re.findall(r'(?:src|href)="/([^"]+)"', index)

        self.assertTrue(referenced, "index.html 没有引用任何本地资源")
        for name in referenced:
            with self.subTest(asset=name):
                self.assertTrue((WEB_ROOT / name).is_file(), f"index.html 引用了不存在的 {name}")

    @unittest.skipIf(shutil.which("node") is None, "本机没有 node，跳过语法检查")
    def test_the_scripts_parse(self) -> None:
        """一个笔误就能让整页空白，而浏览器只在控制台里说一声。"""
        for name in ("ui.js", "views.js", "app.js"):
            with self.subTest(script=name):
                result = subprocess.run(
                    ["node", "--check", str(WEB_ROOT / name)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


class EndpointContractTests(unittest.TestCase):
    """界面调用的每个端点，后端必须真的有 —— 否则那一页打开就是"取数据失败"。"""

    def _endpoints(self, method: str) -> set[str]:
        source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        return set(re.findall(rf"API\.{method}\('(/[^']+)'", source))

    def _loader_endpoints(self) -> set[str]:
        return self._endpoints("get") | self._endpoints("post")

    def test_the_endpoint_extraction_actually_finds_the_calls(self) -> None:
        """自检：正则真能提取到端点。

        提取失败时，"每个端点都被服务"那条会**空着通过** —— 一条永远绿的保护等于没有。
        所以这里对提取结果本身下断言。
        """
        endpoints = self._loader_endpoints()

        self.assertGreaterEqual(len(endpoints), 10, f"只提取到 {len(endpoints)} 个端点，正则可能失效了")
        self.assertIn("/api/research/loop", endpoints)
        self.assertIn("/api/dashboard", endpoints)

    def test_the_frontend_calls_something(self) -> None:
        self.assertTrue(self._loader_endpoints(), "没能从 app.js 里解析出任何端点（正则失效了？）")

    def test_every_endpoint_the_ui_calls_is_served(self) -> None:
        endpoints = self._loader_endpoints()
        source = (Path(__file__).resolve().parents[1] / "app" / "api_server.py").read_text(encoding="utf-8")

        for path in sorted(endpoints):
            with self.subTest(endpoint=path):
                self.assertIn(f'"{path}"', source, f"界面调了 {path}，但 api_server 里找不到这个路由")

    def test_the_read_only_endpoints_actually_answer(self) -> None:
        """读接口真发一次请求。写接口不在这里打 —— 那会有副作用。"""
        readable = sorted(self._endpoints("get"))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            server, thread = _serve(root, workspace)
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                for path in readable:
                    with self.subTest(endpoint=path):
                        try:
                            with urlopen(base + path, timeout=20) as response:  # nosec B310: local test server
                                status = response.status
                                json.loads(response.read())
                        except HTTPError as error:
                            # 工作区是空的，有些端点会合理地报 4xx；404 才是"路由不存在"。
                            status = error.code
                        self.assertNotEqual(status, 404, f"{path} 没被路由接住")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
