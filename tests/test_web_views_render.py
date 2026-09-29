"""Windows 端视图的渲染冒烟测试：真实脚本 + 真实快照。

`node --check` 只证明语法对，`test_web_assets.py` 只证明端点对得上。两者都拦不住
"视图里引用了一个不存在的变量"：那种错误语法完全合法，只在用户点开那一页时炸成白屏。

这里把真实的 `web/ui.js`、`web/views.js`、`web/app.js` 加载到 node 里（探针见
`tests/js/render_probe.js`），喂一份**真跑出来的**研究循环快照，把四段各渲染一遍，
再断言渲染结果里没有"漏接线"的痕迹。

快照与契约都是真的：契约来自 `research_contract()`，快照来自 `ResearchLoopService`
在临时工作区上的 `snapshot()`。手写 fixture 会掩盖真实的字段名改动。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.research_loop_service import ResearchLoopService
from app.trace_service import trace_snapshot
from schemas.research import (
    ACTION_LABELS,
    CHECK_FIELDS,
    CHECK_TITLES,
    EVIDENCE_VERDICT_LABELS,
    Decision,
    Evidence,
    Experiment,
    research_contract,
)
from tools.files import write_json_atomic

PROBE = Path(__file__).resolve().parent / "js" / "render_probe.js"

#: 空设计的理由。放在常量里，断言和 fixture 用的是同一句话。
BLOCKER_REASON = "要判决它得先实现三模态数据读取与模态计数，当前工作区没有这份代码。"

#: 渲染结果里不该出现的东西。它们是"某个字段名拼错了 / 某个变量不存在"的典型痕迹：
#: `undefined` 会原样印在页面上，`[object Object]` 是把对象塞进文本位。
FORBIDDEN_FRAGMENTS = ("undefined", "NaN", "[object Object]")


def _real_snapshot(workspace: Path) -> dict:
    """在临时工作区上真建一份研究状态，并取它的快照。

    刻意不用 `add_experiment` / `record_evidence` 的"外部写入"捷径：走
    `service.state()` 拿到的是编排层真正在用的那个对象，字段名改动会同步反映到快照里。
    """
    service = ResearchLoopService(workspace, workspace)
    added = service.add_hypothesis(
        statement="把早融合打开之后小目标召回会提升",
        predictions=["val_map50_95 高于单模态参考点"],
        falsifiers=["val_map50_95 不高于单模态参考点"],
        rationale=["规则九（一）要求读取三模态"],
    )
    state = service.state()
    experiment = Experiment(
        experiment_id=state.new_id("experiment"),
        hypothesis_id=added["hypothesis_id"],
        question="融合与单模态相比，指标会不会变",
        baseline="单模态基线 EXP-0006",
        independent="external.stage",
        controlled=["data_version=v1", "seed=20260713"],
        metrics=["val_map50_95"],
        success_condition="高于参考点 0.00234",
        config_path="configs/loop/probe.yaml",
    )
    state.add_experiment(experiment, branch_id=state.branch_of(added["hypothesis_id"]).branch_id)
    state.record_evidence(
        Evidence(
            evidence_id=state.new_id("evidence"),
            experiment_id=experiment.experiment_id,
            ran_successfully=True,
            baseline_comparable=True,
            metric_improved=False,
            prediction_met=False,
            replicated_across_seeds=False,
            leakage_free=None,
            matches_hypothesis=True,
            single_variable=True,
            logs_consistent=True,
            verdict="hypothesis_falsified",
            notes="指标没动，实验本身是干净的。",
        )
    )
    state.record_decision(
        Decision(
            decision_id=state.new_id("decision"),
            action="KILL_HYPOTHESIS",
            target_id=added["hypothesis_id"],
            reason="实验干净但指标没有改善 —— 这是负结果。",
        )
    )
    # 再放一个"跑不起来"的空设计：模型的这类判定必须能在界面上看见理由，
    # 否则它只留在作业日志里，下次打开页面就没人知道这条路线为什么停着。
    blank = service.add_hypothesis(
        statement="三模态读取与同口径可比能否在同一次实验里同时验证",
        predictions=["三模态读取样本数均大于 0"],
        falsifiers=["任一模态样本数为 0"],
    )
    state.add_experiment(
        Experiment(
            experiment_id=state.new_id("experiment"),
            hypothesis_id=blank["hypothesis_id"],
            question="",
            blocked=BLOCKER_REASON,
        ),
        branch_id=state.branch_of(blank["hypothesis_id"]).branch_id,
    )
    # 还有一类更早的空设计：状态里没有留下理由（那时还没记这个字段）。
    # 它同样要能在页面上解释自己，否则"有 N 个跑不起来"就成了没头没尾的一句话。
    older = service.add_hypothesis(
        statement="三模态检测数据读取、训练与落盘这条链是否可复跑",
        predictions=["重跑能落盘指标"],
        falsifiers=["重跑没有落盘指标"],
    )
    state.add_experiment(
        Experiment(experiment_id=state.new_id("experiment"), hypothesis_id=older["hypothesis_id"], question=""),
        branch_id=state.branch_of(older["hypothesis_id"]).branch_id,
    )
    # 再来一条还没补上预测与反证条件的：它必须被标成"不可证伪"。这一位的判据由后端给出
    # （`falsifiable`），所以这条断言同时在钉"界面用的是后端的判据，不是自己算的"。
    service.add_hypothesis(statement="早融合对红外与深度的利用效率如何", predictions=[], falsifiers=[])
    return service.snapshot()


@unittest.skipIf(shutil.which("node") is None, "本机没有 node，跳过渲染冒烟测试")
class LoopViewRenderTests(unittest.TestCase):
    def _render(self, snapshot: dict) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            contract_path = directory / "contract.json"
            snapshot_path = directory / "snapshot.json"
            contract_path.write_text(json.dumps(research_contract(), ensure_ascii=False), encoding="utf-8")
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                ["node", str(PROBE), str(contract_path), str(snapshot_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        self.assertEqual(result.returncode, 0, f"渲染探针失败：{result.stderr}")
        return json.loads(result.stdout)

    def _render_trace(self, snapshot: dict) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "trace.json"
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["node", str(PROBE), "--trace", str(snapshot_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        self.assertEqual(result.returncode, 0, f"溯源渲染探针失败：{result.stderr}")
        return json.loads(result.stdout)

    def test_theme_preference_cycles_and_persists_locally(self) -> None:
        result = subprocess.run(
            ["node", str(PROBE), "--theme"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, f"主题探针失败：{result.stderr}")
        cycle = json.loads(result.stdout)
        self.assertEqual(
            cycle,
            [
                {"theme": "light", "stored": "light"},
                {"theme": "dark", "stored": "dark"},
                {"theme": "system", "stored": "system"},
            ],
        )

    def test_every_section_renders_without_a_wiring_mistake(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _real_snapshot(Path(temporary))
        rendered = self._render(snapshot)

        self.assertEqual(sorted(rendered), ["evidence", "history", "hypotheses", "now"])
        for section, html in rendered.items():
            with self.subTest(section=section):
                self.assertTrue(html.strip(), f"{section} 段渲染成了空")
                for fragment in FORBIDDEN_FRAGMENTS:
                    self.assertNotIn(
                        fragment,
                        html,
                        f"{section} 段渲染出了 {fragment} —— 多半是某个变量没接上",
                    )

    def test_the_current_section_shows_the_orchestrator_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _real_snapshot(Path(temporary))
        rendered = self._render(snapshot)

        action = snapshot["next_action"]["action"]
        self.assertIn("研究循环", rendered["now"])
        self.assertIn(ACTION_LABELS[action], rendered["now"], "当前动作没有显示中文名")

    def test_the_hypothesis_section_shows_the_statement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _real_snapshot(Path(temporary))
        rendered = self._render(snapshot)

        statement = snapshot["hypotheses"][0]["statement"]
        self.assertIn(statement, rendered["hypotheses"])

    def test_a_design_that_cannot_run_explains_itself_on_the_page(self) -> None:
        """空设计的理由是模型认真写下的判断，不能只留在作业日志里。"""
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _real_snapshot(Path(temporary))
        rendered = self._render(snapshot)

        self.assertIn(BLOCKER_REASON, rendered["hypotheses"])
        self.assertIn("这次设计跑不起来", rendered["hypotheses"])
        # 没有留下理由的那些也要能解释自己，否则"有 N 个跑不起来"是没头没尾的一句话。
        self.assertIn("生成它时还没有记下原因", rendered["hypotheses"])
        self.assertIn("这次设计跑不起来：没有对照也没有配置", rendered["hypotheses"])
        # 空设计不算"欠着核查"，但要在界面上单独数出来。
        self.assertIn("设计跑不起来", rendered["now"])

    def test_a_hypothesis_without_predictions_is_marked_unfalsifiable(self) -> None:
        """可证伪的判据来自后端的 `falsifiable`，不是界面自己拿两个数组长度算的。"""
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _real_snapshot(Path(temporary))
        rendered = self._render(snapshot)

        unfalsifiable = [item for item in snapshot["hypotheses"] if item["falsifiable"] is not True]
        self.assertTrue(unfalsifiable, "fixture 里应当有一条不可证伪的假设")
        self.assertIn("不可证伪", rendered["hypotheses"])

    def test_the_evidence_section_uses_the_contract_wording(self) -> None:
        """九项核查的名称来自契约。界面自己抄一份的话，这里会因为名字对不上而红。"""
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _real_snapshot(Path(temporary))
        rendered = self._render(snapshot)
        html = rendered["evidence"]

        for field in CHECK_FIELDS:
            with self.subTest(check=field):
                self.assertIn(CHECK_TITLES[field], html, f"核查项 {field} 的界面问法没显示出来")
        self.assertIn(EVIDENCE_VERDICT_LABELS["hypothesis_falsified"], html)
        self.assertIn("未核查", html, "leakage_free 是 None，必须显示成「未核查」而不是「否」")

    def test_the_history_section_translates_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = _real_snapshot(Path(temporary))
        rendered = self._render(snapshot)

        self.assertIn(ACTION_LABELS["KILL_HYPOTHESIS"], rendered["history"])
        self.assertIn("负结果", rendered["history"])

    def test_trace_sections_render_nested_chains_and_verified_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            manifests = workspace / "experiments" / "manifests"
            results = workspace / "experiments" / "results"
            approvals = workspace / "experiments" / "approvals"
            research = workspace / "research"
            for directory in (manifests, results, approvals, research):
                directory.mkdir(parents=True, exist_ok=True)

            digest = "a" * 64
            write_json_atomic(
                manifests / "EXP-0001.json",
                {
                    "experiment_id": "EXP-0001",
                    "status": "planned",
                    "config_sha256": digest,
                    "config": {"training": {"runner": "synthetic_binary_classification"}},
                },
            )
            write_json_atomic(
                results / "EXP-0001.json",
                {"experiment_id": "EXP-0001", "status": "completed", "artifact_paths": []},
            )
            write_json_atomic(
                approvals / f"config-{digest[:16]}.json",
                {
                    "type": "training_config_approval",
                    "config_sha256": digest,
                    "approved_at": "2026-09-28T01:46:56+00:00",
                    "note": "测试用：预算已复核",
                },
            )
            write_json_atomic(
                research / "papers.json",
                {
                    "records": [
                        {"paper_id": "paper-1", "title": "示例研究", "source": "arXiv", "year": 2026}
                    ]
                },
            )
            snapshot = trace_snapshot(root, workspace)

        rendered = self._render_trace(snapshot)
        experiment_html = rendered["experiment"]
        research_html = rendered["research"]
        self.assertIn("EXP-0001", experiment_html)
        self.assertIn("结果 已完成 · 清单 计划中", experiment_html)
        self.assertIn("审批已核验", experiment_html)
        self.assertIn("测试用：预算已复核", experiment_html)
        self.assertIn("示例研究", research_html)
        for section, html in rendered.items():
            with self.subTest(section=section):
                for fragment in FORBIDDEN_FRAGMENTS:
                    self.assertNotIn(fragment, html)


if __name__ == "__main__":
    unittest.main()
