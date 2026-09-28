"""科研契约的单一来源测试。

目标里「三端 schema 单一来源」这一条落在这里。它的对象是**词汇**，不是字段：
动作名、九项核查、判定值、假设/分支状态、图边类型，以及它们的中文名与色调。

规则只有一句：**只在 `schemas/research.py` 定义一次**。后端发在
`GET /api/research/contract`，Windows 端的 `web/` 与鸿蒙端的 ArkTS 都从那里取。

为什么值得单独测：抄一份到前端的代价不是"多写几行"，而是**静默漂移**。
后端删掉一个动作、改一个判定值，界面还在显示旧的中文名，谁都不会发现 ——
直到有人在演示时发现界面写着"跨种子复现"，而后端已经不认这个动作了。

两类断言：

1. 契约本身自洽（每个动作都有中文名、九项核查一个不漏、待批准集合与动作空间对得上）；
2. 两个前端的源码里**找不到**这些名字 —— 谁抄了一份，这里就红。
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from app.api_server import CompetitionApiHandler
from schemas.research import (
    ACTION_LABELS,
    BRANCH_STATUSES,
    CHECK_FIELDS,
    CHECK_LABELS,
    CHECK_TITLES,
    CHOOSABLE_ACTIONS,
    EVIDENCE_VERDICTS,
    EVIDENCE_VERDICT_LABELS,
    FALSIFICATION_PRECONDITIONS,
    GRAPH_EDGE_KINDS,
    GRAPH_NODE_KINDS,
    HYPOTHESIS_STATUSES,
    PENDING_ACTIONS,
    RESEARCH_ACTIONS,
    STEP_STATUSES,
    TERMINAL_ACTIONS,
    research_contract,
)
from tools.device_repo import DEVICE_REPO_ENV, device_repo_root


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


#: 前端不许自带副本的那些名字。
#:
#: 只挑**不会在别处出现**的标识符：动作名、核查项、判定值。假设状态与图边类型里有
#: `active`、`tests` 这种日常词，拿它们做文本扫描只会得到一堆假阳性，
#: 所以那两类靠契约自洽断言（动作与核查项对得上）来守，不靠 grep。
_FRONTEND_FORBIDDEN = tuple(RESEARCH_ACTIONS) + CHECK_FIELDS + EVIDENCE_VERDICTS


class VocabularyTests(unittest.TestCase):
    """契约自身：每个名字都要有可展示的说法，一个都不能漏。"""

    def test_every_action_has_a_label(self) -> None:
        self.assertEqual(set(ACTION_LABELS), set(RESEARCH_ACTIONS), "动作空间与中文名对不上")

    def test_action_labels_are_distinct_and_non_empty(self) -> None:
        labels = [ACTION_LABELS[name] for name in RESEARCH_ACTIONS]
        self.assertTrue(all(label.strip() for label in labels), "有空的动作中文名")
        self.assertEqual(len(set(labels)), len(labels), "两个动作用了同一个中文名")

    def test_the_action_space_has_no_duplicates(self) -> None:
        self.assertEqual(len(set(RESEARCH_ACTIONS)), len(RESEARCH_ACTIONS))

    def test_every_check_has_a_verdict_wording_and_a_question_wording(self) -> None:
        """同一个字段要说两种话：判词是"实验没有成功运行"，界面问的是"真的跑成了吗"。"""
        self.assertEqual(set(CHECK_LABELS), set(CHECK_FIELDS), "核查项与判词对不上")
        self.assertEqual(set(CHECK_TITLES), set(CHECK_FIELDS), "核查项与界面问法对不上")
        for name in CHECK_FIELDS:
            with self.subTest(check=name):
                self.assertTrue(CHECK_LABELS[name].strip())
                self.assertTrue(CHECK_TITLES[name].strip())
                self.assertNotEqual(CHECK_LABELS[name], CHECK_TITLES[name], "两种说法不该是同一句")

    def test_every_verdict_has_a_label_and_a_tone(self) -> None:
        self.assertEqual(set(EVIDENCE_VERDICT_LABELS), set(EVIDENCE_VERDICTS))

    def test_every_status_has_a_label_and_a_tone(self) -> None:
        """`active` / `killed` / `applied` 是内部取值，不该原样印在界面上 —— 中文名也属于契约。"""
        payload = research_contract()
        lists = (
            "hypothesis_statuses",
            "branch_statuses",
            "verdicts",
            "job_statuses",
            "step_statuses",
        )
        for key in lists:
            self.assertTrue(payload[key], f"{key} 是空的")
            for item in payload[key]:
                with self.subTest(list=key, name=item["name"]):
                    self.assertTrue(item["label"].strip(), f"{key}.{item['name']} 没有中文名")
                    self.assertIn(item["tone"], ("ok", "warn", "danger", "muted"))

    def test_falsification_preconditions_are_real_checks(self) -> None:
        """判"假设被反证"之前要先确认的那几项，必须是核查项里真的有名字的项。"""
        self.assertTrue(FALSIFICATION_PRECONDITIONS)
        self.assertLessEqual(set(FALSIFICATION_PRECONDITIONS), set(CHECK_FIELDS))

    def test_pending_actions_are_part_of_the_action_space(self) -> None:
        self.assertLessEqual(set(PENDING_ACTIONS), set(RESEARCH_ACTIONS))
        self.assertLessEqual(set(CHOOSABLE_ACTIONS), set(RESEARCH_ACTIONS))

    def test_a_pending_action_is_never_choosable(self) -> None:
        """要动算力的动作**不允许**被模型在自由选择里挑走。

        这条是"科研决策交给机器，烧机器的事留给人"的实现级约束：一旦某个待批准动作
        同时出现在 CHOOSABLE_ACTIONS 里，模型就能绕过人工批准自己开训练。
        """
        self.assertEqual(set(PENDING_ACTIONS) & set(CHOOSABLE_ACTIONS), set())


class ContractPayloadTests(unittest.TestCase):
    def test_the_payload_covers_the_whole_vocabulary_in_order(self) -> None:
        payload = research_contract()

        self.assertEqual([item["name"] for item in payload["actions"]], list(RESEARCH_ACTIONS))
        self.assertEqual([item["name"] for item in payload["checks"]], list(CHECK_FIELDS))
        self.assertEqual([item["name"] for item in payload["verdicts"]], list(EVIDENCE_VERDICTS))
        self.assertEqual(
            [item["name"] for item in payload["hypothesis_statuses"]], list(HYPOTHESIS_STATUSES)
        )
        self.assertEqual([item["name"] for item in payload["branch_statuses"]], list(BRANCH_STATUSES))
        self.assertEqual(payload["graph_edge_kinds"], list(GRAPH_EDGE_KINDS))
        self.assertEqual(payload["graph_node_kinds"], list(GRAPH_NODE_KINDS))
        self.assertEqual(payload["falsification_preconditions"], list(FALSIFICATION_PRECONDITIONS))

    def test_the_pending_and_choosable_flags_match_the_policy(self) -> None:
        payload = research_contract()
        pending = {item["name"] for item in payload["actions"] if item["pending_approval"]}
        choosable = {item["name"] for item in payload["actions"] if item["choosable"]}

        self.assertEqual(pending, set(PENDING_ACTIONS))
        self.assertEqual(choosable, set(CHOOSABLE_ACTIONS))

    def test_the_payload_is_json_serialisable(self) -> None:
        """它要经 HTTP 发出去，序列化不了就等于没有这份契约。"""
        encoded = json.dumps(research_contract(), ensure_ascii=False)
        self.assertIn("检索文献", encoded)

    def test_exactly_one_action_is_declared_terminal(self) -> None:
        """界面的「当前」那条靠这个标记决定颜色，所以它必须是准的。"""
        terminal = {item["name"] for item in research_contract()["actions"] if item["terminal"]}
        self.assertEqual(terminal, set(TERMINAL_ACTIONS))
        self.assertTrue(terminal, "没有任何动作被标成终止 —— 界面会一直显示「还有事要做」")

    def test_the_declared_step_statuses_are_the_ones_the_loop_uses(self) -> None:
        """端侧靠这份清单把 `applied` 翻译成中文，所以它必须与编排器实际用的取值一致。

        "编排器实际会返回哪些状态"由 `test_research_loop.py` 那条覆盖测试盯着。
        """
        declared = [item["name"] for item in research_contract()["step_statuses"]]

        self.assertEqual(declared, list(STEP_STATUSES))


class ContractEndpointTests(unittest.TestCase):
    """契约要从接口上真的取得到 —— 前端就靠它，取不到等于两端各写一份。"""

    def test_the_endpoint_serves_exactly_the_declared_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            handler = type(
                "ContractEndpointHandler",
                (CompetitionApiHandler,),
                {"project_root": root, "workspace": workspace},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(  # nosec B310: local test server
                    f"http://127.0.0.1:{server.server_port}/api/research/contract", timeout=20
                ) as response:
                    served = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(served, research_contract())


class NoPrivateCopyTests(unittest.TestCase):
    """前端源码里不许有这些名字的第二份定义。

    这是"单一来源"唯一能自动守住的方式：契约的对齐不是靠约定，而是靠"抄不了"。
    """

    def test_the_windows_ui_keeps_no_private_copy(self) -> None:
        for path in sorted((_repo_root() / "web").glob("*.js")):
            source = path.read_text(encoding="utf-8")
            found = [name for name in _FRONTEND_FORBIDDEN if name in source]
            with self.subTest(script=path.name):
                self.assertEqual(
                    found,
                    [],
                    f"{path.name} 里出现了契约词的第二份定义：{found}。"
                    "文案要从 GET /api/research/contract 取，不要在界面里再抄一份。",
                )

    def test_the_arkts_app_keeps_no_private_copy(self) -> None:
        root = device_repo_root(_repo_root())
        if root is None:
            self.skipTest(f"端侧仓库不在这台机器上；设 {DEVICE_REPO_ENV} 指向它即可一并检查")
        sources = sorted((root / "entry" / "src" / "main" / "ets").rglob("*.ets"))
        self.assertTrue(sources, "端侧工程里一个 .ets 都没有，路径可能不对")

        for path in sources:
            source = path.read_text(encoding="utf-8")
            found = [name for name in _FRONTEND_FORBIDDEN if name in source]
            with self.subTest(source=path.relative_to(root).as_posix()):
                self.assertEqual(
                    found,
                    [],
                    f"{path.name} 里出现了契约词的第二份定义：{found}。"
                    "文案要从 GET /api/research/contract 取，不要在端侧再抄一份。",
                )


if __name__ == "__main__":
    unittest.main()
