"""Tests for the evidence-guided research loop: research objects and state.

这些测试盯的是"类型层面的承诺"，不是实现细节：

* 不可证伪的假设、没有对照的实验，能不能被挡住；
* 状态落盘再读回来，对象是不是一个不少、边是不是还在；
* 状态文件被手改坏（多余字段、非法状态）时，加载是丢弃还是整体崩掉。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable

from app.agent_tools import agent_tools_schema, available_tool_names
from app.code_tools import _list_directory, _read_file, _run_command, _search_text, _within, _write_file
from app.orchestrator.executor import ResearchExecutor, _tri_state, extract_json
from app.orchestrator.loop import run, step
from app.orchestrator.policy import MAX_REPEATS, decide_next_action
from app.orchestrator.state import ResearchState
from app.orchestrator.validator import validate_evidence
from schemas.research import (
    CHECK_FIELDS,
    CHECK_LABELS,
    GRAPH_EDGE_KINDS,
    RESEARCH_ACTIONS,
    Decision,
    Evidence,
    Experiment,
    Hypothesis,
    ResearchBranch,
    is_valid_action,
)
from tools.files import write_json_atomic


def _hypothesis(root: Path, *, statement: str = "加入 X 机制能提升小目标召回", **overrides) -> Hypothesis:
    payload = {
        "hypothesis_id": root.name,
        "statement": statement,
        "rationale": ["arxiv:1"],
        "predictions": ["ball 的 AP50 提升 >= 0.005"],
        "falsifiers": ["ball 的 AP50 没有提升"],
    }
    payload.update(overrides)
    return Hypothesis(**payload)


def _falsifiable(hypothesis_id: str = "H0001") -> Hypothesis:
    """一条入场即合格的假设：有预测，也有反证条件。"""
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        statement="加入 X 机制能提升小目标召回",
        predictions=["ball 的 AP50 提升 >= 0.005"],
        falsifiers=["ball 的 AP50 没有提升"],
    )


def _evidence(**overrides) -> Evidence:
    """一份"九项核查全部合格"的基线；每个测试只动自己关心的那一项。"""
    payload: dict = {name: True for name in CHECK_FIELDS}
    payload.update({"evidence_id": "V0001", "experiment_id": "E0001"})
    payload.update(overrides)
    return Evidence(**payload)


def _chat_returning(payload: object) -> Callable[[str, str], dict]:
    """假的模型调用：把固定内容当回复返回，执行器测试因此完全离线。"""

    def chat(_system: str, _user: str) -> dict:
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return {"content": content}

    return chat


class HypothesisTests(unittest.TestCase):
    def test_predictions_alone_are_not_enough(self) -> None:
        """只写"我预测会变好"、不写"什么算我错了"，那不是假设，是愿望。"""
        item = Hypothesis(hypothesis_id="H0001", statement="x", predictions=["会更好"])
        self.assertFalse(item.is_falsifiable())

    def test_falsifiers_alone_are_not_enough(self) -> None:
        item = Hypothesis(hypothesis_id="H0001", statement="x", falsifiers=["不会更好"])
        self.assertFalse(item.is_falsifiable())

    def test_both_present_is_falsifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            item = _hypothesis(Path(temporary) / "H0001")
            self.assertTrue(item.is_falsifiable())


class ExperimentTests(unittest.TestCase):
    def test_without_baseline_it_is_not_a_comparison(self) -> None:
        item = Experiment(
            experiment_id="E0001",
            hypothesis_id="H0001",
            question="X 有没有用？",
            independent="mechanism_x",
            controlled=["dataset"],
        )
        self.assertFalse(item.is_controlled())

    def test_without_controls_it_is_not_a_comparison(self) -> None:
        """只动一个变量还不够，得把"其余都没动"写出来，否则无从判断是否公平。"""
        item = Experiment(
            experiment_id="E0001",
            hypothesis_id="H0001",
            question="X 有没有用？",
            baseline="baseline_v3",
            independent="mechanism_x",
        )
        self.assertFalse(item.is_controlled())

    def test_full_design_is_a_comparison(self) -> None:
        item = Experiment(
            experiment_id="E0001",
            hypothesis_id="H0001",
            question="X 有没有用？",
            baseline="baseline_v3",
            independent="mechanism_x",
            controlled=["parameter_count", "seed"],
        )
        self.assertTrue(item.is_controlled())


class ActionSpaceTests(unittest.TestCase):
    def test_action_space_is_the_documented_fourteen(self) -> None:
        self.assertEqual(len(RESEARCH_ACTIONS), 14)
        self.assertEqual(len(set(RESEARCH_ACTIONS)), 14)

    def test_kill_and_fork_exist_because_search_quality_depends_on_them(self) -> None:
        """能不能"换个方向"是区分科研 Agent 和调参脚本的分水岭。"""
        self.assertIn("KILL_HYPOTHESIS", RESEARCH_ACTIONS)
        self.assertIn("FORK_HYPOTHESIS", RESEARCH_ACTIONS)
        self.assertIn("MERGE_HYPOTHESES", RESEARCH_ACTIONS)

    def test_unknown_action_is_rejected(self) -> None:
        self.assertFalse(is_valid_action("RUN_TRAINING"))
        self.assertTrue(is_valid_action("RUN_EXPERIMENT"))

    def test_decision_with_unknown_action_is_invalid(self) -> None:
        self.assertFalse(Decision(decision_id="D0001", action="DO_MAGIC").is_valid())


class StateTests(unittest.TestCase):
    def test_ids_increment_per_kind(self) -> None:
        state = ResearchState()
        self.assertEqual(state.new_id("hypothesis"), "H0001")
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x"))
        self.assertEqual(state.new_id("hypothesis"), "H0002")
        self.assertEqual(state.new_id("experiment"), "E0001")

    def test_parent_hypothesis_creates_a_derived_from_edge(self) -> None:
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="母假设"))
        state.add_hypothesis(Hypothesis(hypothesis_id="H0002", statement="分叉", parent_id="H0001"))

        kinds = [item.kind for item in state.edges]
        self.assertIn("derived_from", kinds)
        self.assertTrue(any(item.source_id == "H0001" and item.target_id == "H0002" for item in state.edges))

    def test_experiment_links_to_its_hypothesis(self) -> None:
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x"))
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q"))

        self.assertTrue(any(item.kind == "tests" and item.source_id == "E0001" for item in state.edges))

    def test_evidence_without_outcome_claims_nothing(self) -> None:
        """没判定过的证据，不该在图上声称支持或否定任何假设。"""
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x"))
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q"))
        state.record_evidence(Evidence(evidence_id="V0001", experiment_id="E0001"))

        self.assertEqual([item.kind for item in state.edges if item.kind in ("supports", "refutes")], [])

    def test_evidence_outcome_links_to_the_hypothesis(self) -> None:
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x"))
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q"))
        state.record_evidence(Evidence(evidence_id="V0001", experiment_id="E0001"), outcome="refutes")

        self.assertTrue(
            any(
                item.kind == "refutes" and item.source_id == "V0001" and item.target_id == "H0001"
                for item in state.edges
            )
        )

    def test_awaiting_evidence_tracks_experiments_without_a_verdict(self) -> None:
        state = ResearchState()
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q"))
        self.assertEqual([item.experiment_id for item in state.experiments_without_evidence()], ["E0001"])

        state.record_evidence(Evidence(evidence_id="V0001", experiment_id="E0001"))
        self.assertEqual(state.experiments_without_evidence(), [])

    def test_killing_a_branch_also_kills_its_hypothesis(self) -> None:
        """终止一条路线是编排器最重要的动作：假设和分支不能只死一个。"""
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x"))
        state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001"))
        state.kill_branch("B0001", "核心预测已被反证")

        self.assertEqual(state.branches["B0001"].status, "killed")
        self.assertEqual(state.hypotheses["H0001"].status, "killed")
        self.assertEqual(state.branches["B0001"].conclusion, "核心预测已被反证")

    def test_forking_records_the_parent_child_link(self) -> None:
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="母"))
        state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001"))
        state.add_hypothesis(Hypothesis(hypothesis_id="H0002", statement="子", parent_id="H0001"))
        state.add_branch(ResearchBranch(branch_id="B0002", hypothesis_id="H0002", parent_id="B0001"))

        self.assertEqual(state.branches["B0001"].child_ids, ["B0002"])

    def test_only_the_latest_verdict_per_experiment_is_considered(self) -> None:
        """同一实验被反复核查时，"当前结论"只有一条。

        否则编排器每轮都会先撞上刚写的那条，在原地打转；而且证据列表会无限膨胀。
        """
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
        state.record_evidence(_evidence(ran_successfully=False))
        state.record_evidence(_evidence(evidence_id="V0002", ran_successfully=True, prediction_met=False))

        latest = state.latest_evidence()
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0].evidence_id, "V0002")
        # 完整历史仍然留在集合里：去重的是"现在怎么看",不是审计记录。
        self.assertEqual(len(state.evidence), 2)

    def test_cursor_points_at_the_first_branch_then_can_move(self) -> None:
        state = ResearchState()
        state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001"))
        self.assertEqual(state.cursor, "B0001")
        state.set_cursor("B0002")
        self.assertEqual(state.cursor, "B0002")


class PersistenceTests(unittest.TestCase):
    def test_state_round_trips_through_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = ResearchState(budget={"max_actions": 20})
            state.add_hypothesis(_hypothesis(workspace / "H0001"))
            state.add_experiment(
                Experiment(
                    experiment_id="E0001",
                    hypothesis_id="H0001",
                    question="X 有没有用？",
                    baseline="baseline_v3",
                    independent="mechanism_x",
                    controlled=["seed"],
                )
            )
            state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001", score_empirical=0.82))
            state.record_evidence(Evidence(evidence_id="V0001", experiment_id="E0001", verdict="pass"), outcome="supports")
            state.record_decision(Decision(decision_id="D0001", action="DESIGN_EXPERIMENT", target_id="H0001"))
            state.save(workspace)

            restored = ResearchState.load(workspace)

            self.assertEqual(list(restored.hypotheses), ["H0001"])
            self.assertEqual(list(restored.experiments), ["E0001"])
            self.assertEqual(list(restored.evidence), ["V0001"])
            self.assertEqual(restored.branches["B0001"].score_empirical, 0.82)
            self.assertEqual(restored.decisions[0].action, "DESIGN_EXPERIMENT")
            self.assertEqual(restored.budget, {"max_actions": 20})
            self.assertEqual(len(restored.edges), len(state.edges))
            self.assertEqual(restored.hypotheses["H0001"].predictions, ["ball 的 AP50 提升 >= 0.005"])

    def test_missing_state_file_is_an_empty_state_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState.load(Path(temporary))
            self.assertEqual(state.hypotheses, {})
            self.assertIsNone(state.cursor)

    def test_unknown_fields_are_dropped_instead_of_breaking_the_load(self) -> None:
        """状态文件会被手改、也会被旧版本写过：多一个陌生键不该让整份状态加载失败。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            write_json_atomic(
                workspace / "research" / "loop" / "state.json",
                {
                    "hypotheses": [{"hypothesis_id": "H0001", "statement": "x", "future_field": 1}],
                    "unknown_section": {"a": 1},
                },
            )
            state = ResearchState.load(workspace)
            self.assertEqual(state.hypotheses["H0001"].statement, "x")

    def test_illegal_branch_status_is_corrected_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            write_json_atomic(
                workspace / "research" / "loop" / "state.json",
                {"branches": [{"branch_id": "B0001", "hypothesis_id": "H0001", "status": "zombie"}]},
            )
            state = ResearchState.load(workspace)
            self.assertEqual(state.branches["B0001"].status, "active")

    def test_unknown_edge_kind_is_refused_on_write(self) -> None:
        state = ResearchState()
        with self.assertRaises(ValueError):
            state.link("E0001", "H0001", "vibes")

    def test_graph_edge_kinds_are_the_documented_seven(self) -> None:
        self.assertEqual(
            set(GRAPH_EDGE_KINDS),
            {"supports", "refutes", "tests", "derived_from", "contradicts", "improves", "supersedes"},
        )

    def test_summary_reports_what_the_ui_needs(self) -> None:
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x", predictions=["p"], falsifiers=["f"]))
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q"))
        summary = state.summary()

        self.assertEqual(summary["hypotheses"]["total"], 1)
        self.assertEqual(summary["hypotheses"]["falsifiable"], 1)
        self.assertEqual(summary["experiments"]["awaiting_evidence"], ["E0001"])
        self.assertIsNone(summary["last_decision"])


class ValidatorTests(unittest.TestCase):
    def test_a_clean_run_that_moved_the_metric_passes(self) -> None:
        outcome = validate_evidence(_evidence())
        self.assertEqual(outcome.verdict, "pass")
        self.assertEqual(outcome.follow_up, "SYNTHESIZE")
        self.assertEqual(outcome.unchecked, [])

    def test_unrun_experiment_is_an_implementation_bug(self) -> None:
        """跑都没跑成，是工程问题不是科学结论 —— 哪怕同时存在设计缺陷也先修代码。"""
        outcome = validate_evidence(_evidence(ran_successfully=False, baseline_comparable=False))
        self.assertEqual(outcome.verdict, "implementation_bug")
        self.assertEqual(outcome.follow_up, "REPAIR_EXPERIMENT")
        self.assertNotIn(CHECK_LABELS["baseline_comparable"], outcome.reasons)

    def test_implementation_problem_outranks_design_problem(self) -> None:
        outcome = validate_evidence(_evidence(matches_hypothesis=False, single_variable=False))
        self.assertEqual(outcome.verdict, "implementation_bug")

    def test_missing_control_is_an_experiment_flaw(self) -> None:
        outcome = validate_evidence(_evidence(baseline_comparable=False))
        self.assertEqual(outcome.verdict, "experiment_flaw")
        self.assertEqual(outcome.follow_up, "DESIGN_EXPERIMENT")

    def test_leakage_is_a_design_flaw_not_a_bug(self) -> None:
        outcome = validate_evidence(_evidence(leakage_free=False))
        self.assertEqual(outcome.verdict, "experiment_flaw")

    def test_a_clean_run_that_missed_its_prediction_falsifies_the_hypothesis(self) -> None:
        """实验干净、预测没被满足 —— 这是有价值的负结果，该杀掉这条路线，而不是继续修它。"""
        outcome = validate_evidence(_evidence(prediction_met=False))
        self.assertEqual(outcome.verdict, "hypothesis_falsified")
        self.assertEqual(outcome.follow_up, "KILL_HYPOTHESIS")

    def test_a_reproduction_that_moved_nothing_still_supports_its_hypothesis(self) -> None:
        """指标没变不等于假设被反证。

        真实的坑：EXP-0007 精确复现了 EXP-0006 的 0.00234，判决却是 hypothesis_falsified，
        整条路线被终止。原因是用"指标有没有涨"当判决依据 —— 可复现类假设的成功
        恰恰是"指标没变"。判据必须是"预测有没有被满足"。
        """
        outcome = validate_evidence(_evidence(metric_improved=False, prediction_met=True))

        self.assertNotEqual(outcome.verdict, "hypothesis_falsified")
        self.assertNotEqual(outcome.follow_up, "KILL_HYPOTHESIS")

    def test_an_unjudged_prediction_blocks_any_conclusion(self) -> None:
        """没人判断过预测是否满足时，连"通过"都不能给。"""
        outcome = validate_evidence(_evidence(prediction_met=None))

        self.assertEqual(outcome.verdict, "inconclusive")

    def test_single_seed_result_must_be_replicated_first(self) -> None:
        outcome = validate_evidence(_evidence(replicated_across_seeds=False))
        self.assertEqual(outcome.verdict, "inconclusive")
        self.assertEqual(outcome.follow_up, "REPLICATE_EXPERIMENT")

    def test_unchecked_items_block_a_pass_verdict(self) -> None:
        """"没查"不是"合格"：九项没查全就不许判通过。"""
        outcome = validate_evidence(_evidence(leakage_free=None))
        self.assertEqual(outcome.verdict, "inconclusive")
        self.assertIn("leakage_free", outcome.unchecked)

    def test_unknown_run_state_is_inconclusive_not_failure(self) -> None:
        outcome = validate_evidence(_evidence(ran_successfully=None))
        self.assertEqual(outcome.verdict, "inconclusive")
        self.assertEqual(outcome.follow_up, "ANALYZE_RESULT")

    def test_backfilled_evidence_is_inconclusive_not_failed(self) -> None:
        """真实回填出来的证据只有"跑没跑成"一项可读，其余八项没人查过。

        判它"不合格"就是把"没查"读成了"失败"，会凭空杀掉本来有希望的路线。
        """
        item = Evidence(evidence_id="V0001", experiment_id="E0001", ran_successfully=True)
        outcome = validate_evidence(item)
        self.assertEqual(outcome.verdict, "inconclusive")
        self.assertEqual(len(outcome.unchecked), 8)

    def test_every_follow_up_is_a_real_action(self) -> None:
        samples = (
            _evidence(),
            _evidence(ran_successfully=False),
            _evidence(matches_hypothesis=False),
            _evidence(baseline_comparable=False),
            _evidence(prediction_met=False),
            _evidence(replicated_across_seeds=False),
            _evidence(ran_successfully=None),
        )
        for item in samples:
            self.assertTrue(is_valid_action(validate_evidence(item).follow_up))


class PolicyTests(unittest.TestCase):
    def test_no_hypotheses_searches_literature_before_anything_else(self) -> None:
        state = ResearchState()
        decision = decide_next_action(state, context={"has_research": False})
        self.assertEqual(decision.action, "SEARCH_LITERATURE")

    def test_literature_on_hand_leads_to_hypothesis_generation(self) -> None:
        state = ResearchState()
        decision = decide_next_action(state, context={"has_research": True})
        self.assertEqual(decision.action, "GENERATE_HYPOTHESIS")

    def test_unfalsifiable_hypothesis_is_refined_before_any_experiment(self) -> None:
        """没有预测也没有反证条件的假设，不该直接上实验台。"""
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x"))
        decision = decide_next_action(state)
        self.assertEqual(decision.action, "REFINE_HYPOTHESIS")
        self.assertEqual(decision.target_id, "H0001")

    def test_endlessly_vague_hypothesis_is_killed_instead_of_refined_forever(self) -> None:
        state = ResearchState()
        state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="x"))
        for _ in range(MAX_REPEATS):
            state.record_decision(Decision(decision_id=state.new_id("decision"), action="REFINE_HYPOTHESIS", target_id="H0001"))

        decision = decide_next_action(state)
        self.assertEqual(decision.action, "KILL_HYPOTHESIS")

    def test_experiment_with_artifacts_but_no_evidence_is_analyzed_first(self) -> None:
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(
            Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["metrics.json"])
        )
        decision = decide_next_action(state)
        self.assertEqual(decision.action, "ANALYZE_RESULT")
        self.assertEqual(decision.target_id, "E0001")

    def test_implementation_bug_leads_to_repair_not_to_a_new_hypothesis(self) -> None:
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
        state.record_evidence(_evidence(matches_hypothesis=False))

        self.assertEqual(decide_next_action(state).action, "REPAIR_EXPERIMENT")

    def test_falsified_hypothesis_is_killed_not_repaired(self) -> None:
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
        state.record_evidence(_evidence(prediction_met=False))

        self.assertEqual(decide_next_action(state).action, "KILL_HYPOTHESIS")

    def test_a_repair_advice_is_not_repeated_for_the_same_experiment(self) -> None:
        """建议类动作做第二次不会带来新信息，只会把同一句话再说一遍。"""
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
        state.record_evidence(_evidence(matches_hypothesis=False))

        first = decide_next_action(state)
        self.assertEqual(first.action, "REPAIR_EXPERIMENT")
        state.record_decision(first)

        self.assertNotEqual(decide_next_action(state).action, "REPAIR_EXPERIMENT")

    def test_falsifiable_hypothesis_without_experiment_gets_one_designed(self) -> None:
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        decision = decide_next_action(state)
        self.assertEqual(decision.action, "DESIGN_EXPERIMENT")
        self.assertEqual(decision.target_id, "H0001")

    def test_exhausted_budget_finishes(self) -> None:
        state = ResearchState(budget={"max_actions": 1})
        state.record_decision(Decision(decision_id="D0001", action="SEARCH_LITERATURE"))
        self.assertEqual(decide_next_action(state).action, "FINISH")

    def test_chooser_is_confined_to_the_restricted_action_set(self) -> None:
        """兜底的模型也不许自己触发执行类动作。"""
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
        state.record_evidence(_evidence())

        seen: list[tuple[str, ...]] = []

        def chooser(_state: ResearchState, actions: tuple[str, ...]) -> str:
            seen.append(actions)
            return "RUN_EXPERIMENT"

        decision = decide_next_action(state, chooser=chooser)
        self.assertEqual(decision.action, "SYNTHESIZE")
        self.assertNotIn("RUN_EXPERIMENT", seen[0])

    def test_policy_does_not_mutate_the_state(self) -> None:
        """决策是纯函数：选什么都不该顺手改状态。"""
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        before = len(state.decisions)
        decide_next_action(state)
        self.assertEqual(len(state.decisions), before)


class LoopTests(unittest.TestCase):
    def test_killing_a_branch_is_applied_without_an_executor(self) -> None:
        """终止路线是编排器自己的决定：不需要模型，也不需要动机器。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = ResearchState()
            state.add_hypothesis(_falsifiable())
            state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001"))
            state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
            state.record_evidence(_evidence(prediction_met=False))

            outcome = step(state, workspace)

            self.assertEqual(outcome.decision.action, "KILL_HYPOTHESIS")
            self.assertEqual(outcome.status, "applied")
            self.assertEqual(state.branches["B0001"].status, "killed")

    def test_running_an_experiment_waits_for_human_approval(self) -> None:
        """要动算力的动作，编排器不自己触发。"""
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()
            state.add_hypothesis(_falsifiable())
            state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
            state.record_evidence(_evidence(replicated_across_seeds=False))

            outcome = step(state, Path(temporary))

            self.assertEqual(outcome.decision.action, "REPLICATE_EXPERIMENT")
            self.assertEqual(outcome.status, "awaiting_approval")

    def test_without_an_executor_the_action_is_deferred_not_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()
            outcome = step(state, Path(temporary), context={"has_research": True})
            self.assertEqual(outcome.status, "deferred")
            self.assertIn("GENERATE_HYPOTHESIS", outcome.detail)

    def test_executor_failure_becomes_one_failed_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()

            def broken(*_args: object) -> dict:
                raise RuntimeError("模型不可用")

            outcome = step(state, Path(temporary), executor=broken, context={"has_research": True})
            self.assertEqual(outcome.status, "failed")
            self.assertIn("模型不可用", outcome.detail)

    def test_executor_can_write_back_into_the_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()

            def executor(action: str, _decision: object, current: ResearchState, _workspace: Path) -> dict:
                current.add_hypothesis(_falsifiable())
                return {"detail": f"已按 {action} 写入一条假设"}

            outcome = step(state, Path(temporary), executor=executor, context={"has_research": True})
            self.assertEqual(outcome.status, "applied")
            self.assertEqual(len(state.hypotheses), 1)

    def test_every_step_is_persisted(self) -> None:
        """编排是一次一步、可中断、可恢复的，每一步都必须落盘。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = ResearchState()
            step(state, workspace, context={"has_research": True})

            restored = ResearchState.load(workspace)
            self.assertEqual(len(restored.decisions), 1)

    def test_a_pending_approval_is_recorded_without_blocking_other_work(self) -> None:
        """待批准不该卡住整条循环。

        真实的坑：一条需要批准的复现登记之后，循环每轮都重新选它并就地停下，
        于是其他假设永远排不上队 —— "连续跑通"变成了"反复撞同一堵墙"。
        """
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = ResearchState()
            state.add_hypothesis(_falsifiable())
            state.add_experiment(Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["a"]))
            state.record_evidence(_evidence(replicated_across_seeds=False))

            outcome = run(state, workspace, max_steps=5)

            self.assertIn("REPLICATE_EXPERIMENT", outcome.pending_approvals)
            self.assertEqual(outcome.steps[0].status, "awaiting_approval")
            # 登记之后继续往前走，而不是就地停住。
            self.assertGreater(len(outcome.steps), 1)
            self.assertIn("人工批准", outcome.stopped_because)

    def test_run_reports_the_step_cap_instead_of_pretending_it_finished(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()

            def executor(_action: str, _decision: object, _state: ResearchState, _workspace: Path) -> dict:
                return {"detail": "no-op"}

            outcome = run(state, Path(temporary), executor=executor, context={"has_research": True}, max_steps=2)
            self.assertEqual(len(outcome.steps), 2)
            self.assertIn("上限", outcome.stopped_because)


class ExecutorTests(unittest.TestCase):
    def _state(self) -> ResearchState:
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(
            Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["metrics.json"])
        )
        return state

    def test_extract_json_handles_fences_and_surrounding_prose(self) -> None:
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('好的，结果是 {"a": 1} 请查收'), {"a": 1})
        self.assertEqual(extract_json('{"a": {"b": 2}}'), {"a": {"b": 2}})

    def test_extract_json_refuses_to_repair_broken_output(self) -> None:
        """补出来的 JSON 等于替模型编内容，所以宁可不解析。"""
        self.assertIsNone(extract_json('{"a": 1'))
        self.assertIsNone(extract_json("没有 JSON"))
        self.assertIsNone(extract_json(""))

    def test_model_judgement_only_accepts_true_false_or_null(self) -> None:
        self.assertIs(_tri_state(True), True)
        self.assertIs(_tri_state(False), False)
        self.assertIsNone(_tri_state("yes"))
        self.assertIsNone(_tri_state("unknown"))
        self.assertIsNone(_tri_state(None))

    def test_unimplemented_action_reports_itself_instead_of_crashing(self) -> None:
        executor = ResearchExecutor(chat=_chat_returning({}))
        result = executor("RUN_EXPERIMENT", Decision(decision_id="D0001", action="RUN_EXPERIMENT"), ResearchState(), Path("."))
        self.assertIn("还没有接执行器", result["detail"])

    def test_refine_fills_predictions_and_falsifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()
            state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="把 X 接上去"))
            executor = ResearchExecutor(
                chat=_chat_returning({"predictions": ["AP50 +0.005"], "falsifiers": ["AP50 不涨"], "uncertainty": 0.4})
            )
            executor(
                "REFINE_HYPOTHESIS",
                Decision(decision_id="D0001", action="REFINE_HYPOTHESIS", target_id="H0001"),
                state,
                Path(temporary),
            )

            self.assertTrue(state.hypotheses["H0001"].is_falsifiable())
            self.assertEqual(state.hypotheses["H0001"].uncertainty, 0.4)

    def test_refine_that_cannot_produce_falsifiers_leaves_the_hypothesis_alone(self) -> None:
        """模型说不出反证条件时不许硬填：保持不可证伪，让编排器的重复计数把它推向终止。"""
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()
            state.add_hypothesis(Hypothesis(hypothesis_id="H0001", statement="让整条链路跑通"))
            executor = ResearchExecutor(
                chat=_chat_returning({"predictions": [], "falsifiers": [], "note": "这是工程目标，不可判决"})
            )
            result = executor(
                "REFINE_HYPOTHESIS",
                Decision(decision_id="D0001", action="REFINE_HYPOTHESIS", target_id="H0001"),
                state,
                Path(temporary),
            )

            self.assertFalse(state.hypotheses["H0001"].is_falsifiable())
            self.assertIn("仍不可证伪", result["detail"])

    def test_generate_hypothesis_creates_a_branch_for_each_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()
            executor = ResearchExecutor(
                chat=_chat_returning(
                    {
                        "hypotheses": [
                            {
                                "statement": "加大 P2 分辨率能提升 ball 召回",
                                "predictions": ["ball AP50 +0.004"],
                                "falsifiers": ["ball AP50 持平"],
                                "rationale": ["arxiv:1"],
                            }
                        ]
                    }
                )
            )
            executor("GENERATE_HYPOTHESIS", Decision(decision_id="D0001", action="GENERATE_HYPOTHESIS"), state, Path(temporary))

            self.assertEqual(len(state.hypotheses), 1)
            self.assertEqual(len(state.branches), 1)
            self.assertTrue(list(state.hypotheses.values())[0].is_falsifiable())

    def test_design_experiment_records_controls_and_warns_when_they_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()
            state.add_hypothesis(_falsifiable())
            executor = ResearchExecutor(
                chat=_chat_returning({"question": "X 有用吗", "baseline": "", "independent": "x", "controlled": []})
            )
            result = executor(
                "DESIGN_EXPERIMENT",
                Decision(decision_id="D0001", action="DESIGN_EXPERIMENT", target_id="H0001"),
                state,
                Path(temporary),
            )

            self.assertEqual(len(state.experiments), 1)
            self.assertIn("不会把它当成一次公平比较", result["detail"])

    def test_recorded_facts_override_the_model_opinion(self) -> None:
        """记录里写着 failed，模型说跑成功了 —— 以记录为准。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            write_json_atomic(
                workspace / "experiments" / "results" / "E0001.json",
                {"experiment_id": "E0001", "status": "failed", "error": "exit code 1"},
            )
            state = self._state()
            executor = ResearchExecutor(chat=_chat_returning({"ran_successfully": True, "notes": "看起来跑成了"}))

            executor("ANALYZE_RESULT", Decision(decision_id="D0001", action="ANALYZE_RESULT", target_id="E0001"), state, workspace)

            evidence = state.evidence["V0001"]
            self.assertIs(evidence.ran_successfully, False)
            self.assertEqual(evidence.verdict, "implementation_bug")

    def test_analysis_that_cannot_check_anything_is_inconclusive(self) -> None:
        """八项全返回 null 时不许判通过，也不许判失败。"""
        with tempfile.TemporaryDirectory() as temporary:
            state = self._state()
            executor = ResearchExecutor(chat=_chat_returning({}))
            executor("ANALYZE_RESULT", Decision(decision_id="D0001", action="ANALYZE_RESULT", target_id="E0001"), state, Path(temporary))

            self.assertEqual(state.evidence["V0001"].verdict, "inconclusive")

    def test_evidence_is_linked_to_the_hypothesis_only_when_it_judges_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = self._state()
            executor = ResearchExecutor(
                chat=_chat_returning({"metric_improved": False, "ran_successfully": True})
            )
            executor("ANALYZE_RESULT", Decision(decision_id="D0001", action="ANALYZE_RESULT", target_id="E0001"), state, Path(temporary))

            self.assertEqual(state.evidence["V0001"].verdict, "inconclusive")
            self.assertEqual([item.kind for item in state.edges if item.kind in ("supports", "refutes")], [])

    def test_synthesize_writes_a_note_and_opens_new_hypotheses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = self._state()
            executor = ResearchExecutor(
                chat=_chat_returning({"conclusion": "证据不足", "next_questions": ["P2 分辨率是不是瓶颈？"]})
            )
            executor("SYNTHESIZE", Decision(decision_id="D0001", action="SYNTHESIZE", target_id="B0001"), state, workspace)

            self.assertEqual(len(state.hypotheses), 2)
            notes = list((workspace / "research" / "loop" / "notes").glob("synthesis-*.md"))
            self.assertEqual(len(notes), 1)
            self.assertIn("证据不足", notes[0].read_text(encoding="utf-8"))

    def test_unparsable_output_raises_so_the_loop_records_a_failed_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = ResearchState()
            state.add_hypothesis(_falsifiable())
            executor = ResearchExecutor(chat=_chat_returning("我不知道该说什么"))
            with self.assertRaises(ValueError):
                executor("DESIGN_EXPERIMENT", Decision(decision_id="D0001", action="DESIGN_EXPERIMENT", target_id="H0001"), state, Path(temporary))

    def test_continue_advice_writes_a_note_without_touching_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = self._state()
            executor = ResearchExecutor(chat=_chat_returning({"advice": "把 IR 注入系数改成可学习", "verdict": "continue"}))
            before = len(state.experiments)
            executor("REPAIR_EXPERIMENT", Decision(decision_id="D0001", action="REPAIR_EXPERIMENT", target_id="E0001"), state, workspace)

            self.assertEqual(len(state.experiments), before)
            self.assertTrue(list((workspace / "research" / "loop" / "notes").glob("repair_experiment-*.md")))

    def test_abandon_verdict_kills_the_branch_automatically(self) -> None:
        """模型判了"这条路不值得继续"，循环就该真的把算力挪走。

        只写一句笔记、不终止分支的话，下一轮还会继续在它身上花钱 —— 等于白判。
        """
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = self._state()
            state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001"))
            executor = ResearchExecutor(
                chat=_chat_returning({"advice": "四次独立尝试都以同一方式失败，建议终止", "verdict": "abandon"})
            )
            result = executor(
                "REPAIR_EXPERIMENT",
                Decision(decision_id="D0001", action="REPAIR_EXPERIMENT", target_id="E0001"),
                state,
                workspace,
            )

            self.assertEqual(state.branches["B0001"].status, "killed")
            self.assertEqual(state.hypotheses["H0001"].status, "killed")
            self.assertIn("已终止分支 B0001", result["detail"])
            self.assertIn("建议终止", state.branches["B0001"].conclusion)

    def test_abandon_can_target_a_hypothesis_too(self) -> None:
        """target 的语义随动作而变：分叉指向假设，修实现指向实验，两种都要能找到分支。"""
        with tempfile.TemporaryDirectory() as temporary:
            state = self._state()
            state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001"))
            executor = ResearchExecutor(chat=_chat_returning({"advice": "换个方向", "verdict": "abandon"}))
            executor(
                "FORK_HYPOTHESIS",
                Decision(decision_id="D0001", action="FORK_HYPOTHESIS", target_id="H0001"),
                state,
                Path(temporary),
            )

            self.assertEqual(state.branches["B0001"].status, "killed")

    def test_abandon_without_a_branch_says_so_instead_of_pretending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = self._state()  # 没有建分支
            executor = ResearchExecutor(chat=_chat_returning({"advice": "放弃", "verdict": "abandon"}))
            result = executor(
                "REPAIR_EXPERIMENT",
                Decision(decision_id="D0001", action="REPAIR_EXPERIMENT", target_id="E0001"),
                state,
                Path(temporary),
            )

            self.assertIn("未终止任何路线", result["detail"])

    def test_an_already_killed_branch_is_not_killed_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = self._state()
            state.add_branch(ResearchBranch(branch_id="B0001", hypothesis_id="H0001"))
            state.kill_branch("B0001", "先前已终止")
            executor = ResearchExecutor(chat=_chat_returning({"advice": "放弃", "verdict": "abandon"}))
            result = executor(
                "REPAIR_EXPERIMENT",
                Decision(decision_id="D0001", action="REPAIR_EXPERIMENT", target_id="E0001"),
                state,
                Path(temporary),
            )

            self.assertIn("无需重复终止", result["detail"])


class CodeToolTests(unittest.TestCase):
    """代码工具是 Agent 唯一能动手的地方，边界必须钉死在代码里。"""

    def test_paths_cannot_escape_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with self.assertRaises(ValueError):
                _within(workspace, "../../etc/passwd")
            with self.assertRaises(ValueError):
                _within(workspace, "C:/Windows/system32")
            with self.assertRaises(ValueError):
                _within(workspace, "")

    def test_reading_and_listing_stay_inside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "configs").mkdir()
            (workspace / "configs" / "a.yaml").write_text("lr: 0.02\n", encoding="utf-8")

            listing = _list_directory(workspace, workspace, path="configs")
            self.assertEqual([item["name"] for item in listing["entries"]], ["a.yaml"])

            read = _read_file(workspace, workspace, path="configs/a.yaml")
            self.assertIn("lr: 0.02", read["content"])

            found = _search_text(workspace, workspace, query="lr")
            self.assertEqual(found["hits"][0]["path"], "configs/a.yaml")

    def test_the_official_rule_directory_is_write_protected(self) -> None:
        """官方规则原件是证据，Agent 不许改写它。"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            result = _write_file(workspace, workspace, path="input/rules.md", content="被改了")
            self.assertIn("error", result)
            self.assertFalse((workspace / "input" / "rules.md").exists())

    def test_writing_a_config_persists_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            result = _write_file(workspace, workspace, path="configs/new.yaml", content="a: 1\n")
            self.assertTrue(result["written"])
            self.assertEqual((workspace / "configs" / "new.yaml").read_text(encoding="utf-8"), "a: 1\n")

    def test_multiline_commands_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            result = _run_command(workspace, workspace, command="echo a\necho b")
            self.assertIn("error", result)

    def test_run_command_refuses_when_docker_is_unavailable(self) -> None:
        class Unavailable:
            def availability(self) -> dict:
                return {"available": False, "version": None, "reason": "no docker here"}

            def run(self, *_args: object, **_kwargs: object) -> object:
                raise AssertionError("Docker 不可用时不该真的去开容器")

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            result = _run_command(workspace, workspace, command="echo hi", runner=Unavailable())
            self.assertIn("Docker is not usable", result["error"])

    def test_run_command_never_runs_on_the_host(self) -> None:
        """命令必须走容器：宿主上不存在"直接执行"这条路径。"""
        seen: list[dict] = []

        class Recording:
            def availability(self) -> dict:
                return {"available": True, "version": "test", "reason": ""}

            def run(self, spec: object, *, log_path: Path) -> object:
                seen.append({"network": spec.network, "mounts": [(m.target, m.read_only) for m in spec.mounts]})
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("ok\n", encoding="utf-8")

                class Outcome:
                    returncode = 0
                    timed_out = False
                    duration_seconds = 0.01

                return Outcome()

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _run_command(workspace, workspace, command="echo hi", runner=Recording())

            self.assertEqual(seen[0]["network"], "none")
            self.assertIn(("/work", True), seen[0]["mounts"])
            self.assertIn(("/scratch", False), seen[0]["mounts"])

    def test_code_tools_are_registered_and_can_be_narrowed(self) -> None:
        names = set(available_tool_names())
        self.assertTrue({"list_directory", "read_file", "search_text", "write_file", "run_command"} <= names)

        only = ("read_file", "search_text")
        narrowed = {entry["function"]["name"] for entry in agent_tools_schema(only)}
        self.assertEqual(narrowed, set(only))


class ToolLoopTests(unittest.TestCase):
    """执行器接上工具后的角色边界：谁能改东西，谁只能看。"""

    def _state(self) -> ResearchState:
        state = ResearchState()
        state.add_hypothesis(_falsifiable())
        state.add_experiment(
            Experiment(experiment_id="E0001", hypothesis_id="H0001", question="q", artifacts=["metrics.json"])
        )
        return state

    def _recording_agent(self, calls: list[dict], content: str):
        def agent(prompt: str, stage: str, project_root: Path, workspace: Path, *, system_prompt=None, tools=None) -> dict:
            calls.append({"stage": stage, "tools": tools, "system": system_prompt})
            return {"content": content}

        return agent

    def test_repair_gets_write_and_run_tools(self) -> None:
        calls: list[dict] = []
        agent = self._recording_agent(calls, '{"advice": "把 IR 注入系数改成可学习", "verdict": "continue"}')
        with tempfile.TemporaryDirectory() as temporary:
            executor = ResearchExecutor(project_root=Path("."), agent=agent)
            executor(
                "REPAIR_EXPERIMENT",
                Decision(decision_id="D0001", action="REPAIR_EXPERIMENT", target_id="E0001"),
                self._state(),
                Path(temporary),
            )

            self.assertEqual(len(calls), 1)
            self.assertIn("write_file", calls[0]["tools"])
            self.assertIn("run_command", calls[0]["tools"])

    def test_reasoning_only_actions_never_get_write_tools(self) -> None:
        calls: list[dict] = []
        agent = self._recording_agent(calls, '{"conclusion": "证据不足"}')
        with tempfile.TemporaryDirectory() as temporary:
            executor = ResearchExecutor(project_root=Path("."), agent=agent)
            executor("SYNTHESIZE", Decision(decision_id="D0001", action="SYNTHESIZE"), self._state(), Path(temporary))

            self.assertNotIn("write_file", calls[0]["tools"])
            self.assertNotIn("run_command", calls[0]["tools"])
            self.assertIn("read_file", calls[0]["tools"])

    def test_the_executor_carries_its_own_discipline_into_the_loop(self) -> None:
        """行动循环可以自由探索，但纪律与输出契约仍由执行器给出。"""
        calls: list[dict] = []
        agent = self._recording_agent(calls, '{"conclusion": "x"}')
        with tempfile.TemporaryDirectory() as temporary:
            executor = ResearchExecutor(project_root=Path("."), agent=agent)
            executor("SYNTHESIZE", Decision(decision_id="D0001", action="SYNTHESIZE"), self._state(), Path(temporary))

            self.assertIn("只输出要求的 JSON", calls[0]["system"])

    def test_without_a_project_root_it_falls_back_to_single_turn(self) -> None:
        """没给 project_root 就只有单轮问答，测试因此完全离线。"""
        with tempfile.TemporaryDirectory() as temporary:
            executor = ResearchExecutor(chat=_chat_returning({"conclusion": "证据不足"}))
            executor("SYNTHESIZE", Decision(decision_id="D0001", action="SYNTHESIZE"), self._state(), Path(temporary))

            self.assertIsNone(executor._agent)

    def test_tool_loop_output_still_has_to_satisfy_the_contract(self) -> None:
        """摸清过程的自由度，不等于放宽输出契约。"""
        calls: list[dict] = []
        agent = self._recording_agent(calls, "我看了代码，觉得可以改一下")
        with tempfile.TemporaryDirectory() as temporary:
            executor = ResearchExecutor(project_root=Path("."), agent=agent)
            with self.assertRaises(ValueError):
                executor(
                    "REPAIR_EXPERIMENT",
                    Decision(decision_id="D0001", action="REPAIR_EXPERIMENT", target_id="E0001"),
                    self._state(),
                    Path(temporary),
                )


if __name__ == "__main__":
    unittest.main()
