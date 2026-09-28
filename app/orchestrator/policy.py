"""The orchestrator's decision function: ``next_action = policy(research_state)``.

整个系统最核心的代码不是提示词，而是这个函数。

V1 采用**硬规则优先 + LLM 兜底**，不训练打分器。规则负责那些"必须做"的事
（没有可证伪的假设就不该设计实验、跑过没核查的结果不许进下一轮），LLM 只负责
规则覆盖不到的自由选择。文档里的优先级公式 `αN+βE+γI+δP−λC−μR` 先不实现，
但**两类评分从第一天就分开存**（`score_empirical` 来自真实实验，`score_reasoning`
来自模型判断），免得以后合并成"模型说 8.7 分所以继续"。

这里刻意做成**纯函数**：只读状态、返回一条 `Decision`，不修改状态、不执行任何动作。
要不要采纳、采纳后状态怎么变，由 `loop.py` 决定 —— 决策与执行分离，测试才能不碰网络。
"""

from __future__ import annotations

from typing import Any, Callable

from app.orchestrator.validator import validate_evidence
from schemas.research import CHOOSABLE_ACTIONS, Decision, Hypothesis


# 同一个动作在同一个目标上连续重复这么多次之后，就不再死磕。
# 这是"失败后能不能换方向"（对应验收维度里的 Search quality）的技术实现。
MAX_REPEATS = 3


def _repeat_count(state: Any, action: str, target: str | None) -> int:
    """最近连续多少次是同一个动作打在同一个目标上。"""
    count = 0
    for item in reversed(state.decisions):
        if item.action != action or item.target_id != target:
            break
        count += 1
    return count


def _already_done(state: Any, action: str, target: str | None) -> bool:
    """这个动作是否已经对同一个目标做过一次。

    建议类动作（出修复建议、重设计）不改状态，所以不记这一笔的话，下一轮会再选一次、
    把同一句话再说一遍 —— 真实跑过一轮，4 步里有 3 步耗在这上面。执行类动作不同，
    它们可以重试，那由 `MAX_REPEATS` 管。
    """
    return any(item.action == action and item.target_id == target for item in state.decisions)


def _decision(state: Any, action: str, target: str | None, reason: str, based_on: list[str] | None = None) -> Decision:
    return Decision(
        decision_id=state.new_id("decision"),
        action=action,
        target_id=target,
        reason=reason,
        based_on=list(based_on or []),
    )


def _vague_hypothesis(state: Any) -> Hypothesis | None:
    for item in state.active_hypotheses():
        if not item.is_falsifiable():
            return item
    return None


def _ran_without_evidence(state: Any) -> list[Any]:
    """跑出过产物、但还没有证据核查过的实验。

    是否"跑过"以 `artifacts` 是否为空来判断 —— 这是现有记录里唯一能反映
    "这次实验真的产生了东西"的证据。
    """
    return [
        item
        for item in state.experiments.values()
        if item.artifacts and state.evidence_for(item.experiment_id) is None
    ]


def _hypotheses_without_experiment(state: Any) -> list[Hypothesis]:
    designed = {item.hypothesis_id for item in state.experiments.values()}
    return [item for item in state.falsifiable_hypotheses() if item.hypothesis_id not in designed]


def decide_next_action(
    state: Any,
    *,
    context: dict[str, Any] | None = None,
    chooser: Callable[[Any, tuple[str, ...]], str] | None = None,
) -> Decision:
    """在当前状态下挑出**一个**动作。

    `context` 提供状态之外的事实（例如工作区里有没有文献记录）。
    `chooser` 是可注入的 LLM 兜底；不注入时走确定性默认值，所以测试完全离线。
    """
    context = context or {}
    budget = state.budget if isinstance(state.budget, dict) else {}
    limit = budget.get("max_actions")
    if isinstance(limit, int) and len(state.decisions) >= limit:
        return _decision(state, "FINISH", None, f"动作预算已用满（{len(state.decisions)}/{limit}）")

    # 一、还没有任何假设：先有文献，再有想法。
    if not state.hypotheses:
        if not context.get("has_research"):
            return _decision(state, "SEARCH_LITERATURE", None, "工作区里还没有文献记录，先检索相关工作")
        return _decision(state, "GENERATE_HYPOTHESIS", None, "已有文献但还没有任何假设")

    # 二、不可证伪的假设：先补预测与反证条件；补不动就终止，不占着算力。
    vague = _vague_hypothesis(state)
    if vague is not None:
        if _repeat_count(state, "REFINE_HYPOTHESIS", vague.hypothesis_id) < MAX_REPEATS:
            return _decision(
                state,
                "REFINE_HYPOTHESIS",
                vague.hypothesis_id,
                "这条假设没有可被实验判决的预测或反证条件",
            )
        return _decision(
            state,
            "KILL_HYPOTHESIS",
            vague.hypothesis_id,
            f"补了 {MAX_REPEATS} 次仍然不可证伪，终止这条路线",
        )

    # 三、跑过但没核查的实验：结果不许直接进入下一轮。
    pending = _ran_without_evidence(state)
    if pending:
        target = pending[0].experiment_id
        if _repeat_count(state, "ANALYZE_RESULT", target) < MAX_REPEATS:
            return _decision(state, "ANALYZE_RESULT", target, "实验已有产物，但还没有经过证据核查")
        return _decision(
            state,
            "CHALLENGE_CLAIM",
            target,
            f"核查了 {MAX_REPEATS} 次仍无法给出可核查的结论，转为质疑这条路线",
        )

    # 四、已有判定的证据：按判定分派 —— 修实现 / 重设计 / 终止 / 复现。
    # 每个实验只看最新那条判定：核查会反复写证据，但"当前结论"只有一个。
    # 每个判定对应的动作只做一次：做过就跳过这条证据往下看，不把同一份建议再说一遍。
    for item in state.latest_evidence():
        outcome = validate_evidence(item)
        target = item.experiment_id
        if outcome.verdict == "implementation_bug":
            if not _already_done(state, "REPAIR_EXPERIMENT", target):
                return _decision(state, "REPAIR_EXPERIMENT", target, "证据判定为实现缺陷：" + "；".join(outcome.reasons))
            continue
        if outcome.verdict == "experiment_flaw":
            if not _already_done(state, "DESIGN_EXPERIMENT", target):
                return _decision(state, "DESIGN_EXPERIMENT", target, "证据判定为实验设计缺陷：" + "；".join(outcome.reasons))
            continue
        if outcome.verdict == "hypothesis_falsified":
            # 注意 target 的语义：`KILL_HYPOTHESIS` 指向**假设**，不是指向实验。
            # 动作名里的宾语就是它的 target —— 否则调用方得靠猜才能找到该终止谁。
            experiment = state.experiments.get(item.experiment_id)
            hypothesis_id = experiment.hypothesis_id if experiment is not None else item.experiment_id
            if not _already_done(state, "KILL_HYPOTHESIS", hypothesis_id):
                return _decision(
                    state,
                    "KILL_HYPOTHESIS",
                    hypothesis_id,
                    "实验干净但指标没有改善 —— 这是负结果，该终止这条路线而不是继续修它",
                )
            continue
        if outcome.follow_up == "REPLICATE_EXPERIMENT":
            if not _already_done(state, "REPLICATE_EXPERIMENT", target):
                return _decision(state, "REPLICATE_EXPERIMENT", target, "结论依赖单个随机种子，先跨种子复现")
            # 复现已登记过（无论是否已批准）：不要再排一次，去看别的路线。
            # 没有这一条时，一个等人批准的复现会把整条循环卡死。
            continue
        if outcome.verdict == "inconclusive" and outcome.unchecked:
            if _repeat_count(state, "ANALYZE_RESULT", target) < MAX_REPEATS:
                return _decision(
                    state,
                    "ANALYZE_RESULT",
                    target,
                    "九项核查还有没查过的：" + "、".join(outcome.unchecked),
                )

    # 五、有可证伪的假设但还没为它设计过实验。
    waiting = _hypotheses_without_experiment(state)
    if waiting:
        return _decision(
            state,
            "DESIGN_EXPERIMENT",
            waiting[0].hypothesis_id,
            "这条假设可证伪，但还没有对应的实验",
        )

    # 六、规则覆盖不到时，交给 LLM 在受限动作集里挑一个。
    if chooser is not None:
        chosen = chooser(state, CHOOSABLE_ACTIONS)
        if chosen in CHOOSABLE_ACTIONS:
            return _decision(state, chosen, state.cursor, "规则未覆盖当前局面，由模型在受限动作集内选择")

    # 七、默认：先综合当前证据，再谈开新方向。
    return _decision(state, "SYNTHESIZE", state.cursor, "当前假设都已有实验，先综合已有证据")


__all__ = ["MAX_REPEATS", "decide_next_action"]
