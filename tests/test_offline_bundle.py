"""离线包的测试：Windows 端「后端不在时核心状态仍可读」这条能力的证据。

鸿蒙端的界面装在设备上，后端不在也打得开（端侧直接读工作区文件）；Windows 端的界面是
后端 serve 出来的，所以同样的能力要靠一份**静态包**实现：页面资源 + 最后一次成功响应，
由桌面外壳在后端不可达时用浏览器直接打开。

三件事必须被钉住，否则这份能力只是看起来有：

1. 离线页跑的是**线上那份脚本的原样副本**（另写一个简化版 = 两个界面慢慢变成不同的东西）；
2. 快照里只放**真实取到过**的响应（编一个空对象出来会让人以为后端还活着）；
3. 离线页**一次网络都不打**也能把状态读出来 —— 这是这条能力唯一有意义的判据。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.api_server import WEB_ROOT
from app.offline_bundle import (
    ASSET_NAMES,
    SNAPSHOT_NAME,
    build_offline_bundle,
    frontend_read_endpoints,
    offline_page,
    render_offline_page,
)
from app.research_loop_service import ResearchLoopService
from schemas.research import RESEARCH_ACTIONS, research_contract

PROBE = Path(__file__).resolve().parent / "js" / "render_probe.js"


class _FakeResponse:
    """够用的假响应：`fetch_responses` 只用 `with` + `read()`。"""

    def __init__(self, payload: Any):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _opener(payloads: dict[str, Any], failing: tuple[str, ...] = ()):
    def open_url(url: str) -> _FakeResponse:
        for path, payload in payloads.items():
            if not url.endswith(path):
                continue
            if path in failing:
                raise OSError("stub opener failed on purpose")
            return _FakeResponse(payload)
        raise OSError(f"stub opener got an endpoint it was not prepared for: {url}")

    return open_url


def _loop_snapshot(workspace: Path) -> dict:
    service = ResearchLoopService(workspace, workspace)
    service.add_hypothesis(
        statement="离线包探针：这条假设要出现在离线页上",
        predictions=["某个指标提升"],
        falsifiers=["某个指标没有提升"],
    )
    return service.snapshot()


def _payloads(workspace: Path) -> dict[str, Any]:
    endpoints = frontend_read_endpoints((WEB_ROOT / "app.js").read_text(encoding="utf-8"))
    payloads: dict[str, Any] = {path: {"probe": path} for path in endpoints}
    payloads["/api/research/contract"] = research_contract()
    payloads["/api/research/loop"] = _loop_snapshot(workspace)
    return payloads


class EndpointExtractionTests(unittest.TestCase):
    def test_the_endpoint_list_comes_from_the_frontend_itself(self) -> None:
        """清单不在 Python 里另抄一份：界面会问什么，就预先取什么。"""
        endpoints = frontend_read_endpoints((WEB_ROOT / "app.js").read_text(encoding="utf-8"))

        self.assertGreaterEqual(len(endpoints), 10, f"只解析出 {len(endpoints)} 个端点，正则可能失效了")
        self.assertIn("/api/research/loop", endpoints)
        self.assertIn("/api/research/contract", endpoints)
        self.assertEqual(len(set(endpoints)), len(endpoints), "解析结果里有重复")


class BundleLayoutTests(unittest.TestCase):
    def test_the_bundle_reuses_the_real_scripts_byte_for_byte(self) -> None:
        """离线页跑的就是线上那份脚本。另写一份简化版，两个界面迟早会变成不同的东西。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_offline_bundle(
                WEB_ROOT, root, "http://127.0.0.1:1/", opener=_opener(_payloads(root))
            )

            for name in ASSET_NAMES:
                if name == "index.html":
                    continue
                with self.subTest(asset=name):
                    self.assertEqual(
                        (root / "offline" / name).read_bytes(),
                        (WEB_ROOT / name).read_bytes(),
                        f"{name} 在离线包里被改写了",
                    )

    def test_the_offline_page_switches_to_relative_paths_and_loads_the_snapshot_first(self) -> None:
        """`file://` 下 `/styles.css` 指的是盘根；而且快照必须在 app.js 之前。"""
        live = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        rendered = render_offline_page(live)

        # index.html 不引用自己，其余每个资源都要变成相对路径。
        for name in ASSET_NAMES:
            if name == "index.html":
                continue
            self.assertIn(f'"{name}"', rendered)
        self.assertNotIn('="/', rendered, "还有指向站点根的绝对路径")
        self.assertLess(
            rendered.index(SNAPSHOT_NAME),
            rendered.index('src="app.js"'),
            "快照脚本排在 app.js 之后 —— 界面会先去过网络",
        )

    def test_the_insertion_point_must_exist(self) -> None:
        """找不到插入点就报错，而不是产出一个静默离不了线的页面。"""
        with self.assertRaises(ValueError):
            render_offline_page("<html><body>no scripts here</body></html>")

    def test_only_responses_that_were_really_fetched_go_in_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broken = "/api/trace"
            payloads = _payloads(root)
            record = build_offline_bundle(
                WEB_ROOT,
                root,
                "http://127.0.0.1:1/",
                opener=_opener(payloads, failing=(broken,)),
            )

            self.assertIn(broken, record["missing"])
            self.assertNotIn(broken, record["captured"])
            self.assertIn("/api/research/loop", record["captured"])

            snapshot = (root / "offline" / SNAPSHOT_NAME).read_text(encoding="utf-8")
            # 端点清单里当然会有它（那是"界面会问什么"的记录），但它的**响应**不该在。
            self.assertNotIn(
                f'"probe": "{broken}"',
                snapshot,
                "没取到的端点的响应不该出现在快照里",
            )

    def test_a_missing_asset_is_a_hard_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty_web = root / "web"
            empty_web.mkdir()
            with self.assertRaises(FileNotFoundError):
                build_offline_bundle(empty_web, root / "cache", "http://127.0.0.1:1/", opener=_opener({}))

    def test_offline_page_is_none_until_a_bundle_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(offline_page(root))

            build_offline_bundle(WEB_ROOT, root, "http://127.0.0.1:1/", opener=_opener(_payloads(root)))

            self.assertEqual(offline_page(root), root / "offline" / "index.html")


@unittest.skipIf(shutil.which("node") is None, "本机没有 node，跳过离线渲染测试")
class OfflineRenderTests(unittest.TestCase):
    """离线页必须**一次网络都不打**就把状态读出来。这是这条能力唯一有意义的判据。"""

    def _render_offline(self, root: Path) -> dict:
        result = subprocess.run(
            ["node", str(PROBE), "--offline", str(root / "offline")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, f"离线渲染失败：{result.stderr}")
        return json.loads(result.stdout)

    def _bundle(self, root: Path, *, generated_at: str) -> dict:
        return build_offline_bundle(
            WEB_ROOT,
            root,
            "http://127.0.0.1:1/",
            opener=_opener(_payloads(root)),
            generated_at=generated_at,
        )

    def test_the_offline_page_renders_the_state_without_touching_the_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._bundle(root, generated_at="2026-01-01T00:00:00+00:00")
            report = self._render_offline(root)

        self.assertEqual(report["network_calls"], 0, "离线页碰了网络 —— 后端不在时它就是白屏")
        self.assertTrue(report["offline_flag"])
        self.assertEqual(report["offline_generated_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(report["contract_actions"], len(RESEARCH_ACTIONS))
        self.assertTrue(report["contract_offline"], "离线时契约应当来自快照")
        # 从 `#loop` 进来，所以 boot() 只取这一页的数据 —— 一屏只渲染一段。
        self.assertEqual(report["pages_loaded"], ["loop"])
        self.assertEqual(report["loop_offline_at"], "2026-01-01T00:00:00+00:00")

    def test_the_offline_page_says_it_is_offline(self) -> None:
        """离线页不能看起来跟在线一样：要写清这是快照、是什么时候的。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._bundle(root, generated_at="2026-01-01T00:00:00+00:00")
            report = self._render_offline(root)

        self.assertIn("离线模式", report["banner"])
        self.assertIn("2026-01-01T00:00:00+00:00", report["banner"])
        self.assertIn("静态快照", report["banner"])

    def test_the_loop_page_still_renders_from_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._bundle(root, generated_at="2026-01-01T00:00:00+00:00")
            report = self._render_offline(root)

        sections = report["loop_sections"]
        self.assertEqual(sorted(sections), ["evidence", "history", "hypotheses", "now"])
        for name, html in sections.items():
            with self.subTest(section=name):
                self.assertTrue(html.strip(), f"{name} 段在离线页上是空的")
                self.assertNotIn("undefined", html, f"{name} 段渲染出了 undefined")
        self.assertIn("离线包探针", sections["hypotheses"])


if __name__ == "__main__":
    unittest.main()
