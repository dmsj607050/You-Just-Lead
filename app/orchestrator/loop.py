"""Drive the research loop: pick an action, carry it out, update state, repeat.

三个时间尺度，边界划在文件顶部而不是靠约定：

* **行动循环**（最内层）—— "这个实验具体怎么写代码、装环境、跑命令"，由执行器
  （`llm_service.run_agent` 那套）负责，**编排层不进这一层**；
* **实验循环**（中间层）—— `step()`：决策 → 执行 → 收证据 → 更新状态；
* **发现循环**（最外层）—— `run()`：连跑若干步，直到 FINISH 或预算耗尽。

编排器**不自己触发执行**。`RUN_EXPERIMENT` / `REPLICATE_EXPERIMENT` 这类要动算力的动作
被记成 `awaiting_approval` 就停住 —— 这是项目原有的安全边界，EGRL 不碰它。
科研决策交给机器，烧机器的事留给人批准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.orchestrator.policy import decide_next_action
from app.orchestrator.state import ResearchState
from schemas.research import PENDING_ACTIONS, Decision


# 执行器：接到一个动作，去把这件事做完，并回填状态（加假设、加实验、写证据）。
# 注入它，是为了让 loop 本身不依赖网络与模型 —— 测试时塞一个假的就能全离线跑。
Executor = Callable[[str, Decision, ResearchState, Path], dict[str, Any]]


@dataclass
class StepOutcome:
    """一步的结果。`status` 说明这一步到底发生了什么。"""

    decision: Decision
    # applied（已落实）/ awaiting_approval（等人批）/ deferred（没执行器，记为待办）
    # / noop（动作找不到目标）/ failed（执行器抛错）/ finished（编排结束）
    status: str
    detail: str = ""
    state: ResearchState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "status": self.status,
            "detail": self.detail,
        }


def workspace_context(workspace: Path) -> dict[str, Any]:
    """状态之外、但决策需要知道的事实。

    目前只有一项：工作区里有没有文献记录。没有它，"先查文献再提假设"这条规则
    就无从判断。以后新增外部事实也挂在这里，而不是塞进 ResearchState。
    """
    return {"has_research": (Path(workspace) / "research" / "papers.json").exists()}


def step(
    state: ResearchState,
    workspace: Path,
    *,
    executor: Executor | None = None,
    context: dict[str, Any] | None = None,
    chooser: Callable[[ResearchState, tuple[str, ...]], str] | None = None,
) -> StepOutcome:
    """推进一个动作，并把状态落盘。

    无论成功失败都落盘：编排是一次一步、可中断、可恢复的，不是一口气跑完的黑盒。
    """
    workspace = Path(workspace)
    decision = decide_next_action(
        state,
        context=context if context is not None else workspace_context(workspace),
        chooser=chooser,
    )
    state.record_decision(decision)

    if decision.action == "FINISH":
        state.save(workspace)
        return StepOutcome(decision, "finished", decision.reason, state)

    # 终止一条路线是编排器自己能做的决定，不需要执行器：它只改状态，不碰机器。
    if decision.action == "KILL_HYPOTHESIS":
        branch = state.branch_of(decision.target_id or "")
        if branch is None:
            state.save(workspace)
            return StepOutcome(decision, "noop", f"找不到与 {decision.target_id} 对应的分支", state)
        state.kill_branch(branch.branch_id, decision.reason)
        state.save(workspace)
        return StepOutcome(decision, "applied", f"已终止分支 {branch.branch_id}", state)

    if decision.action in PENDING_ACTIONS:
        state.save(workspace)
        return StepOutcome(decision, "awaiting_approval", "要动算力的动作需要人工批准后再交给执行器", state)

    if executor is None:
        state.save(workspace)
        return StepOutcome(decision, "deferred", f"没有可用的执行器，{decision.action} 记为待办", state)

    try:
        result = executor(decision.action, decision, state, workspace) or {}
    except Exception as exc:  # 执行器是外部边界，任何异常都要变成一步失败而不是整个循环崩掉
        state.save(workspace)
        return StepOutcome(decision, "failed", f"{type(exc).__name__}: {exc}", state)

    state.save(workspace)
    return StepOutcome(decision, "applied", str(result.get("detail") or ""), state)


@dataclass
class LoopOutcome:
    """一次循环的完整轨迹。"""

    steps: list[StepOutcome] = field(default_factory=list)
    stopped_because: str = ""
    # 登记下来、等人批准的动作。它们不阻塞其他路线，只是还没被执行。
    pending_approvals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stopped_because": self.stopped_because,
            "steps": [item.to_dict() for item in self.steps],
            "pending_approvals": list(self.pending_approvals),
        }


def run(
    state: ResearchState,
    workspace: Path,
    *,
    executor: Executor | None = None,
    context: dict[str, Any] | None = None,
    chooser: Callable[[ResearchState, tuple[str, ...]], str] | None = None,
    max_steps: int = 12,
) -> LoopOutcome:
    """连推若干步，直到明确结束、被预算挡住、或人需要介入。

    停下来必须给出**理由**：`FINISH` 之外还可能是撞上预算、或执行器缺位。
    一个不说自己为什么停的循环，等于把"卡住了"伪装成"跑完了"。
    """
    outcomes: list[StepOutcome] = []
    current_context = context if context is not None else workspace_context(workspace)
    stopped = f"达到步数上限 {max_steps}"
    pending: list[str] = []

    for _ in range(max_steps):
        outcome = step(state, workspace, executor=executor, context=current_context, chooser=chooser)
        outcomes.append(outcome)
        if outcome.status == "finished":
            stopped = outcome.detail or "编排器决定结束"
            break
        if outcome.status == "awaiting_approval":
            # 待批准**不该卡住整条循环**：把它登记下来，继续推进别的路线。
            # 之前这里直接 break，于是一个等人批准的复现会让其他所有假设永远排不上队
            # —— 真实撞到过。停下来的判断交给步数上限与下面的收尾。
            if outcome.decision.action not in pending:
                pending.append(outcome.decision.action)
            continue
        if outcome.status == "deferred":
            stopped = f"缺少执行器，停在 {outcome.decision.action}"
            break
        if outcome.status == "failed":
            stopped = f"执行 {outcome.decision.action} 失败"
            break

    if pending:
        # 待批准的必须出现在停因里：否则"因为别的原因停下"会掩盖"还有事等人批"，
        # 而这两件事对读的人来说含义完全不同。
        stopped = f"{stopped}；{len(pending)} 个动作等待人工批准：{'、'.join(pending)}"

    return LoopOutcome(steps=outcomes, stopped_because=stopped, pending_approvals=pending)


__all__ = [
    "Executor",
    "LoopOutcome",
    "StepOutcome",
    "run",
    "step",
    "workspace_context",
]
