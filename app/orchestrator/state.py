"""The research state: the single source of truth the orchestrator reasons over.

编排器不推理"对话历史"，它推理一份持续更新的**科研状态**：已知什么、还没解决什么、
哪条路线有希望、哪条已经被反证、还剩多少预算。

这份状态整个落盘（`research/loop/state.json`）。所以后端重启、进程被杀、人隔一天回来，
都能从断点接着走 —— 编排不是一个常驻的 `while True`，而是
"推进一个动作 → 落盘 → 退出 → 等人或等下一次触发"。

图谱的**节点**由对象集合自身承担（假设/实验/证据/分支/决策都是节点），
这里只额外维护**边**：`supports` / `refutes` / `tests` / `derived_from` /
`contradicts` / `improves` / `supersedes`。有了边，才能回答
"为什么我们现在正在跑这个实验"。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

from schemas.research import (
    BRANCH_STATUSES,
    Decision,
    Evidence,
    Experiment,
    GraphEdge,
    Hypothesis,
    ResearchBranch,
)
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


# 相对工作区的落盘位置。与 `research/papers.json` 同处一层：都是科研状态。
STATE_FILE = Path("research") / "loop" / "state.json"

# 各类对象的 id 前缀。前缀只用于人眼识别，排序与去重按数字。
ID_PREFIXES = {
    "hypothesis": "H",
    "experiment": "E",
    "evidence": "V",
    "branch": "B",
    "decision": "D",
}

_Object = TypeVar("_Object")


def _payload_for(cls: type[_Object], payload: dict[str, Any]) -> dict[str, Any]:
    """只保留 dataclass 认得的字段。

    状态文件是会被手改、也会被旧版本写过的：多出来的键直接丢掉，而不是让整个
    状态因为一个陌生字段而加载失败。
    """
    known = {item.name for item in fields(cls)}
    return {key: value for key, value in payload.items() if key in known}


def _next_id(prefix: str, existing: list[str]) -> str:
    numbers: list[int] = []
    for item in existing:
        tail = item[len(prefix):] if item.startswith(prefix) else ""
        if tail.isdigit():
            numbers.append(int(tail))
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


@dataclass
class ResearchState:
    """一份可落盘、可恢复的科研状态。"""

    hypotheses: dict[str, Hypothesis] = field(default_factory=dict)
    experiments: dict[str, Experiment] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    branches: dict[str, ResearchBranch] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    # 预算由调用方填写（最大动作数、剩余 GPU 小时等），编排层只读不算。
    budget: dict[str, Any] = field(default_factory=dict)
    # 当前关注的分支。发现循环决定要不要把算力挪到别处。
    cursor: str | None = None
    updated_at: str = field(default_factory=utc_now)

    # ------------------------------------------------------------------ 查询

    def active_hypotheses(self) -> list[Hypothesis]:
        return [item for item in self.hypotheses.values() if item.status == "active"]

    def falsifiable_hypotheses(self) -> list[Hypothesis]:
        """可以被送上实验台的假设：活跃，且写了预测与反证条件。"""
        return [item for item in self.active_hypotheses() if item.is_falsifiable()]

    def experiments_without_evidence(self) -> list[Experiment]:
        """已经设计、但还没有证据核查过的实验。

        验证器卡在这里：证据没过关之前，结果不允许进入下一轮。
        """
        return [item for item in self.experiments.values() if self.evidence_for(item.experiment_id) is None]

    def evidence_for(self, experiment_id: str) -> Evidence | None:
        for item in self.evidence.values():
            if item.experiment_id == experiment_id:
                return item
        return None

    def latest_evidence(self) -> list[Evidence]:
        """每个实验只保留最新的一条判定，最新的排在最前。

        同一个实验会被反复核查，每核查一次就写一条新证据。但"当前结论"只有一个：
        不按实验去重的话，编排器每一轮都会先撞上刚写的那条，在原地打转
        （真实跑过一轮，4 步里有 2 步耗在这上面），而证据列表会无限膨胀。
        完整历史留在证据集合里与账本中，这里只回答"现在怎么看"。
        """
        latest: dict[str, Evidence] = {}
        for item in self.evidence.values():
            latest[item.experiment_id] = item
        return sorted(latest.values(), key=lambda item: item.recorded_at, reverse=True)

    def branch_of(self, hypothesis_id: str) -> ResearchBranch | None:
        for branch in self.branches.values():
            if branch.hypothesis_id == hypothesis_id:
                return branch
        return None

    def active_branches(self) -> list[ResearchBranch]:
        return [item for item in self.branches.values() if item.status == "active"]

    def experiments_of(self, branch_id: str) -> list[Experiment]:
        branch = self.branches.get(branch_id)
        if branch is None:
            return []
        return [self.experiments[item] for item in branch.experiments if item in self.experiments]

    def latest_decision(self) -> Decision | None:
        return self.decisions[-1] if self.decisions else None

    def edges_of(self, node_id: str) -> list[GraphEdge]:
        return [item for item in self.edges if node_id in (item.source_id, item.target_id)]

    # ------------------------------------------------------------------ 变更

    def new_id(self, kind: str) -> str:
        prefix = ID_PREFIXES[kind]
        if kind == "hypothesis":
            return _next_id(prefix, list(self.hypotheses))
        if kind == "experiment":
            return _next_id(prefix, list(self.experiments))
        if kind == "evidence":
            return _next_id(prefix, list(self.evidence))
        if kind == "branch":
            return _next_id(prefix, list(self.branches))
        return _next_id(prefix, [item.decision_id for item in self.decisions])

    def add_hypothesis(self, item: Hypothesis) -> Hypothesis:
        self.hypotheses[item.hypothesis_id] = item
        if item.parent_id:
            # 分叉关系本身就是图上的边：新假设由旧假设派生而来。
            self.link(item.parent_id, item.hypothesis_id, "derived_from")
        self.touch()
        return item

    def add_experiment(self, item: Experiment, *, branch_id: str | None = None) -> Experiment:
        self.experiments[item.experiment_id] = item
        self.link(item.experiment_id, item.hypothesis_id, "tests")
        if branch_id and branch_id in self.branches:
            branch = self.branches[branch_id]
            if item.experiment_id not in branch.experiments:
                branch.experiments.append(item.experiment_id)
        self.touch()
        return item

    def record_evidence(self, item: Evidence, *, outcome: str | None = None) -> Evidence:
        """落一条证据，并按判定结果在图上连边。

        `outcome` 由验证器给出：`supports` 或 `refutes`。传 None 时不连边 ——
        没判定过的证据不该在图上声称支持或否定任何东西。
        """
        self.evidence[item.evidence_id] = item
        if outcome in ("supports", "refutes"):
            experiment = self.experiments.get(item.experiment_id)
            if experiment is not None:
                self.link(item.evidence_id, experiment.hypothesis_id, outcome)
        self.touch()
        return item

    def add_branch(self, item: ResearchBranch) -> ResearchBranch:
        self.branches[item.branch_id] = item
        if item.parent_id and item.parent_id in self.branches:
            parent = self.branches[item.parent_id]
            if item.branch_id not in parent.child_ids:
                parent.child_ids.append(item.branch_id)
            self.link(item.parent_id, item.branch_id, "derived_from")
        if self.cursor is None:
            self.cursor = item.branch_id
        self.touch()
        return item

    def record_decision(self, item: Decision) -> Decision:
        self.decisions.append(item)
        self.touch()
        return item

    def link(self, source_id: str, target_id: str, kind: str, note: str = "") -> GraphEdge:
        edge = GraphEdge(source_id=source_id, target_id=target_id, kind=kind, note=note)
        if not edge.is_valid():
            raise ValueError(f"unknown graph edge kind: {kind}")
        self.edges.append(edge)
        return edge

    def kill_branch(self, branch_id: str, conclusion: str) -> None:
        """显式终止一条分支。这是编排器最重要的动作之一：不把算力继续投在死路上。"""
        branch = self.branches.get(branch_id)
        if branch is None:
            return
        branch.status = "killed"
        branch.conclusion = conclusion
        hypothesis = self.hypotheses.get(branch.hypothesis_id)
        if hypothesis is not None:
            hypothesis.status = "killed"
        self.touch()

    def set_cursor(self, branch_id: str | None) -> None:
        self.cursor = branch_id
        self.touch()

    def touch(self) -> None:
        self.updated_at = utc_now()

    # ------------------------------------------------------------------ 摘要

    def summary(self) -> dict[str, Any]:
        """给决策层和界面看的状态摘要。

        界面只该显示四件事：当前在研究什么、最可能是哪个假设、刚做了什么实验和结果、
        为什么决定下一步这么做 —— 这个摘要是那四件事的数据来源。
        """
        active = self.active_branches()
        latest = self.latest_decision()
        return {
            "hypotheses": {
                "total": len(self.hypotheses),
                "active": len(self.active_hypotheses()),
                "falsifiable": len(self.falsifiable_hypotheses()),
            },
            "experiments": {
                "total": len(self.experiments),
                "awaiting_evidence": [item.experiment_id for item in self.experiments_without_evidence()],
            },
            "branches": {"total": len(self.branches), "active": [item.branch_id for item in active]},
            "cursor": self.cursor,
            "budget": self.budget,
            "last_decision": latest.to_dict() if latest else None,
            "updated_at": self.updated_at,
        }

    # ------------------------------------------------------------------ 落盘

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "cursor": self.cursor,
            "budget": self.budget,
            "hypotheses": [item.to_dict() for item in self.hypotheses.values()],
            "experiments": [item.to_dict() for item in self.experiments.values()],
            "evidence": [item.to_dict() for item in self.evidence.values()],
            "branches": [item.to_dict() for item in self.branches.values()],
            "decisions": [item.to_dict() for item in self.decisions],
            "edges": [item.to_dict() for item in self.edges],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchState":
        state = cls(
            cursor=payload.get("cursor"),
            budget=payload.get("budget") if isinstance(payload.get("budget"), dict) else {},
            updated_at=str(payload.get("updated_at") or utc_now()),
        )
        for item in payload.get("hypotheses") or []:
            if isinstance(item, dict) and item.get("hypothesis_id"):
                state.hypotheses[str(item["hypothesis_id"])] = Hypothesis(**_payload_for(Hypothesis, item))
        for item in payload.get("experiments") or []:
            if isinstance(item, dict) and item.get("experiment_id"):
                state.experiments[str(item["experiment_id"])] = Experiment(**_payload_for(Experiment, item))
        for item in payload.get("evidence") or []:
            if isinstance(item, dict) and item.get("evidence_id"):
                state.evidence[str(item["evidence_id"])] = Evidence(**_payload_for(Evidence, item))
        for item in payload.get("branches") or []:
            if isinstance(item, dict) and item.get("branch_id"):
                branch = ResearchBranch(**_payload_for(ResearchBranch, item))
                if branch.status not in BRANCH_STATUSES:
                    branch.status = "active"
                state.branches[branch.branch_id] = branch
        for item in payload.get("decisions") or []:
            if isinstance(item, dict) and item.get("decision_id"):
                state.decisions.append(Decision(**_payload_for(Decision, item)))
        for item in payload.get("edges") or []:
            if isinstance(item, dict) and item.get("source_id") and item.get("target_id"):
                state.edges.append(GraphEdge(**_payload_for(GraphEdge, item)))
        return state

    def save(self, workspace: Path) -> Path:
        self.touch()
        path = Path(workspace) / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, self.to_dict())
        return path

    @classmethod
    def load(cls, workspace: Path) -> "ResearchState":
        """读取状态；还没开始过研究就返回一份空状态，而不是抛错。"""
        path = Path(workspace) / STATE_FILE
        if not path.exists():
            return cls()
        payload = read_json(path)
        if not isinstance(payload, dict):
            return cls()
        return cls.from_dict(payload)


__all__ = ["ID_PREFIXES", "ResearchState", "STATE_FILE"]
