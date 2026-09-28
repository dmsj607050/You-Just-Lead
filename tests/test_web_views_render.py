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

PROBE = Path(__file__).resolve().parent / "js" / "render_probe.js"

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
                timeout=120,
            )
        self.assertEqual(result.returncode, 0, f"渲染探针失败：{result.stderr}")
        return json.loads(result.stdout)

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


if __name__ == "__main__":
    unittest.main()
