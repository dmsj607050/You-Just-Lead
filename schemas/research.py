"""Structured research objects for the evidence-guided research loop.

这些对象是编排层推理的对象，不是训练记录（训练记录在 `schemas/experiment.py`）。
两者刻意分开：一次训练可以对应科研上的多个问题，而一个科研实验也可能要跑多次训练。

三条硬约束写进类型里，而不是写在提示词里：

1. **假设必须可证伪** —— 没有 `predictions` 与 `falsifiers` 的假设不配上实验台；
2. **实验必须有对照** —— 没有 baseline、没写自变量、没列控制变量的比较不算证据；
3. **"没查" 与 "查了不合格" 是两件事** —— `Evidence` 的每一项都可以是 `None`，
   它表示当时没人去查。把 `None` 当成 `False` 会把"未知"误报成"失败"。

因此 `Evidence.verdict` 只由 `app/orchestrator/validator.py` 计算，不允许调用方直接写死。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.provenance import utc_now


# 假设的生命周期。`killed` 是编排器的显式动作，不是"很久没动"。
HYPOTHESIS_STATUSES = ("active", "supported", "refuted", "killed", "merged")

# 分支状态。一条分支承载"一个假设 + 它的实现 + 它的实验 + 它的批判 + 它的结论"。
BRANCH_STATUSES = ("active", "killed", "merged", "concluded")

# 证据判定。前四种对应验证器的三条失败路径，`inconclusive` 专门留给"查不动"。
EVIDENCE_VERDICTS = ("pass", "implementation_bug", "experiment_flaw", "hypothesis_falsified", "inconclusive")

# 编排器的固定动作空间。**固定动作，开放实现**：
# 编排层只在这些动作里选一个，至于"这个实验具体怎么写代码、装环境、跑命令"，
# 由执行模型在行动循环里自己决定，编排层不规定步骤。
RESEARCH_ACTIONS = (
    "SEARCH_LITERATURE",
    "GENERATE_HYPOTHESIS",
    "DESIGN_EXPERIMENT",
    "RUN_EXPERIMENT",
    "REPAIR_EXPERIMENT",
    "REPLICATE_EXPERIMENT",
    "ANALYZE_RESULT",
    "CHALLENGE_CLAIM",
    "REFINE_HYPOTHESIS",
    "FORK_HYPOTHESIS",
    "MERGE_HYPOTHESES",
    "KILL_HYPOTHESIS",
    "SYNTHESIZE",
    "FINISH",
)

# 研究图的节点与边。长期大脑是这张图，不是聊天记录。
GRAPH_NODE_KINDS = ("paper", "claim", "hypothesis", "experiment", "result", "artifact", "critique", "decision")

GRAPH_EDGE_KINDS = ("supports", "refutes", "tests", "derived_from", "contradicts", "improves", "supersedes")

# 要动算力的动作。编排器**不自己跑它们**，只登记成待批准 —— 科研决策交给机器，
# 烧机器的事留给人。放在这里是因为它同时是编排行为与界面提示语的依据。
PENDING_ACTIONS = ("RUN_EXPERIMENT", "REPLICATE_EXPERIMENT")

# 规则覆盖不到时，允许模型在这几个动作里挑一个。执行类动作不在其中：
# 编排器只决定"做什么"，不决定"怎么做"，更不允许自己触发执行。
CHOOSABLE_ACTIONS = (
    "SEARCH_LITERATURE",
    "GENERATE_HYPOTHESIS",
    "REFINE_HYPOTHESIS",
    "FORK_HYPOTHESIS",
    "MERGE_HYPOTHESES",
    "CHALLENGE_CLAIM",
    "SYNTHESIZE",
    "FINISH",
)

#: 会让循环停下来的动作。只有它一个，但它是**语义**不是样式：
#: "编排器认为没有下一步该做了" 与 "还有事要做" 在界面上必须看得出区别。
TERMINAL_ACTIONS = ("FINISH",)

# 九项核查。顺序即界面顺序，也是"还有哪些没查"的报告顺序。
CHECK_FIELDS = (
    "ran_successfully",
    "baseline_comparable",
    "metric_improved",
    "prediction_met",
    "replicated_across_seeds",
    "leakage_free",
    "matches_hypothesis",
    "single_variable",
    "logs_consistent",
)

# 判"假设被反证"之前必须先确认的四项。预测没被满足可能只是实现有 bug 或对照不可比，
# 那属于另外两条路 —— 只有"实现正确 + 实验公平"都被核实过，负结果才成立。
FALSIFICATION_PRECONDITIONS = (
    "matches_hypothesis",
    "baseline_comparable",
    "single_variable",
    "logs_consistent",
)


# ------------------------------------------------------------------ 契约
#
# 下面这些「名字 ↔ 中文 ↔ 色调」只在这里定义**一次**。后端把它当契约发出去
# （`GET /api/research/contract`），Windows 端与鸿蒙端都从那里取。
#
# 之前 Windows 界面自己抄了一份动作名与核查项。抄的代价不是"多写几行"，而是
# **静默漂移**：后端删掉一个动作，界面还在显示它的中文名，谁都不会发现。
# 界面渲染的是契约，不是自己的副本。

#: 动作的中文名。缺少某个动作会直接让契约自检失败，不允许漏。
ACTION_LABELS = {
    "SEARCH_LITERATURE": "检索文献",
    "GENERATE_HYPOTHESIS": "提出假设",
    "DESIGN_EXPERIMENT": "设计实验",
    "RUN_EXPERIMENT": "执行实验",
    "REPAIR_EXPERIMENT": "修复实现",
    "REPLICATE_EXPERIMENT": "跨种子复现",
    "ANALYZE_RESULT": "核查结果",
    "CHALLENGE_CLAIM": "质疑结论",
    "REFINE_HYPOTHESIS": "补全假设",
    "FORK_HYPOTHESIS": "分叉方向",
    "MERGE_HYPOTHESES": "合并假设",
    "KILL_HYPOTHESIS": "终止路线",
    "SYNTHESIZE": "综合结论",
    "FINISH": "结束",
}

#: 核查不合格时的判词（验证器写给决策层与人的）。
CHECK_LABELS = {
    "ran_successfully": "实验没有成功运行",
    "baseline_comparable": "baseline 不可比较",
    "metric_improved": "指标没有提升",
    "prediction_met": "假设的预测没有被满足",
    "replicated_across_seeds": "没有跨随机种子复现",
    "leakage_free": "存在数据泄漏",
    "matches_hypothesis": "实现与假设不一致",
    "single_variable": "同时改变了多个变量",
    "logs_consistent": "日志与结论不一致",
}

#: 界面上的正向问法。同一个字段在不同场合要说不同的话：判词是"实验没有成功运行"，
#: 界面要问的是"真的跑成了吗"。两句都在这一份契约里，不各写一份。
CHECK_TITLES = {
    "ran_successfully": "真的跑成了",
    "baseline_comparable": "有可比对照",
    "metric_improved": "指标确实动了",
    "prediction_met": "预测被满足",
    "replicated_across_seeds": "跨种子复现过",
    "leakage_free": "没有数据泄漏",
    "matches_hypothesis": "实现对得上假设",
    "single_variable": "只动了一个变量",
    "logs_consistent": "日志与结论一致",
}

#: 判定值的中文名与色调。色调也属于契约：让界面自己按字符串猜颜色，
#: 加一个新判定时界面就会显示成灰色而没人察觉。
EVIDENCE_VERDICT_LABELS = {
    "pass": "通过",
    "implementation_bug": "实现缺陷",
    "experiment_flaw": "实验设计缺陷",
    "hypothesis_falsified": "假设被反证",
    "inconclusive": "查不动",
}

VERDICT_TONES = {
    "pass": "ok",
    "implementation_bug": "danger",
    "experiment_flaw": "warn",
    "hypothesis_falsified": "danger",
    "inconclusive": "warn",
}

HYPOTHESIS_STATUS_TONES = {
    "active": "ok",
    "supported": "ok",
    "refuted": "danger",
    "killed": "danger",
    "merged": "muted",
}

BRANCH_STATUS_TONES = {
    "active": "ok",
    "killed": "danger",
    "merged": "muted",
    "concluded": "ok",
}

#: 契约格式自身的版本。改字段含义（不是加字段）时递增。
RESEARCH_CONTRACT_VERSION = 1


def research_contract() -> dict[str, Any]:
    """给所有端用的那一份科研契约。

    这是**唯一**的定义处：后端的策略、验证器、界面文案全部从上面这些常量取，
    两个前端从 `GET /api/research/contract` 取。任何一端想要一份自己的副本，
    都会在 `tests/test_research_contract.py` 里撞墙。
    """
    return {
        "contract_version": RESEARCH_CONTRACT_VERSION,
        "actions": [
            {
                "name": name,
                "label": ACTION_LABELS.get(name, name),
                "choosable": name in CHOOSABLE_ACTIONS,
                "pending_approval": name in PENDING_ACTIONS,
                "terminal": name in TERMINAL_ACTIONS,
            }
            for name in RESEARCH_ACTIONS
        ],
        "checks": [
            {"name": name, "label": CHECK_LABELS[name], "title": CHECK_TITLES[name]} for name in CHECK_FIELDS
        ],
        "falsification_preconditions": list(FALSIFICATION_PRECONDITIONS),
        "hypothesis_statuses": [
            {"name": name, "tone": HYPOTHESIS_STATUS_TONES.get(name, "muted")} for name in HYPOTHESIS_STATUSES
        ],
        "branch_statuses": [
            {"name": name, "tone": BRANCH_STATUS_TONES.get(name, "muted")} for name in BRANCH_STATUSES
        ],
        "verdicts": [
            {"name": name, "label": EVIDENCE_VERDICT_LABELS[name], "tone": VERDICT_TONES[name]}
            for name in EVIDENCE_VERDICTS
        ],
        "graph_node_kinds": list(GRAPH_NODE_KINDS),
        "graph_edge_kinds": list(GRAPH_EDGE_KINDS),
    }


def is_valid_action(name: str) -> bool:
    return name in RESEARCH_ACTIONS


@dataclass
class Hypothesis:
    """一条可判决的命题，不是一段自然语言。"""

    hypothesis_id: str
    statement: str
    # 依据：证据 id、论文 id 或实验 id。编排器要能沿它回溯"为什么会有这个想法"。
    rationale: list[str] = field(default_factory=list)
    # 可被实验验证的预测。空列表 = 这条假设还不配上实验台。
    predictions: list[str] = field(default_factory=list)
    # 什么结果会否定它。没有反证条件的假设永远"对"，那是废话不是假设。
    falsifiers: list[str] = field(default_factory=list)
    uncertainty: float | None = None
    status: str = "active"
    # 从哪条假设分叉而来。分叉是发现循环的主要产物。
    parent_id: str | None = None
    created_at: str = field(default_factory=utc_now)

    def is_falsifiable(self) -> bool:
        """可证伪性是入场券。缺预测或缺反证，就不该被送去设计实验。"""
        return bool(self.predictions) and bool(self.falsifiers)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Experiment:
    """一次科研实验的设计，不是一次训练运行。

    训练运行（`schemas/experiment.py` 的 manifest/result）是实现细节；
    这里记录的是"这次实验在区分什么、跟谁比、只动了哪个变量"。
    """

    experiment_id: str
    hypothesis_id: str
    # 这次实验在回答什么问题。它必须能把假设的某个预测或反证区分开。
    question: str
    # 对照。空字符串表示没对照——验证器会据此判 `experiment_flaw`。
    baseline: str = ""
    # 自变量。一次只允许动一个，否则结果无法归因。
    independent: str = ""
    # 控制变量：参数量、训练步数、数据、种子等，必须显式写出来。
    controlled: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    success_condition: str = ""
    # 要跑的配置（相对工作区）。设计阶段就把它定下来，"设计"才不是一句空话 ——
    # 没有它，批准之后没人知道该跑什么。留空表示这次设计还不能执行，
    # 循环会停在"待批准"而不是排一个注定失败的任务。
    config_path: str = ""
    # 批准之后填上训练作业号，用来把"这次设计"和"那次运行"对上。
    run_id: str = ""
    artifacts: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def is_controlled(self) -> bool:
        """公平比较的前提：有对照、指明自变量、控制变量列清楚。"""
        return bool(self.baseline.strip()) and bool(self.independent.strip()) and bool(self.controlled)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    """实验产出的事实核查结果。

    每一项都是"经过核查的事实"，不是"模型的印象"。取值三态：
    `True` 合格、`False` 不合格、`None` 没人查过。

    字段名统一取正向含义（True = 好），避免 `single_seed` 这类"True 反而更差"的字段
    在后续判断里被读反。
    """

    evidence_id: str
    experiment_id: str
    # 实验真正成功运行了吗（进程退出码、产物是否落盘）。
    ran_successfully: bool | None = None
    # baseline 是否可比较（同数据、同口径、同评测脚本）。
    baseline_comparable: bool | None = None
    # 指标有没有实际提升。**这是事实记录，不是判决依据** —— 复现类假设的成功
    # 恰恰是"指标没变"，拿指标方向去判会把成功的复现读成假设被反证（真实撞到过）。
    metric_improved: bool | None = None
    # 假设写下的预测有没有被这次结果满足。这才是判"假设被反证"的依据：
    # 预测可能根本不是"指标提升"（例如"能复现到 ±0.001"、"不再 OOM"）。
    prediction_met: bool | None = None
    # 是否跨多个随机种子复现过。只有单个种子时结论不牢。
    replicated_across_seeds: bool | None = None
    # 是否确认没有数据泄漏。`None` = 没人查过 —— 这与"查了发现有泄漏"必须分开。
    leakage_free: bool | None = None
    # 实现是否真的对应假设（不是"改了个参数就说验证了 X"）。
    matches_hypothesis: bool | None = None
    # 是否只改变了一个变量。
    single_variable: bool | None = None
    # 日志与结论是否一致（没出现"日志显示崩了但结论说成功"）。
    logs_consistent: bool | None = None
    # 由 validator 计算，调用方不得自行指定。
    verdict: str = "inconclusive"
    notes: str = ""
    recorded_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchBranch:
    """一条研究分支 = 假设 + 证据 + 实现 + 实验 + 批判 + 结论。

    这是"树搜索"在科研场景下的单元：搜索的对象不是代码版本，而是完整分支。
    """

    branch_id: str
    hypothesis_id: str
    experiments: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    critiques: list[str] = field(default_factory=list)
    conclusion: str = ""
    # 两类评分必须分开存，永远不合并成一个总分：
    # `score_empirical` 来自真实实验，`score_reasoning` 来自模型判断。
    score_empirical: float | None = None
    score_reasoning: float | None = None
    status: str = "active"
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    """编排器的一次决策。它要能回答"为什么现在做这件事"。"""

    decision_id: str
    action: str
    target_id: str | None = None
    reason: str = ""
    # 这次决策依据了哪些节点/证据。有了它，才能沿研究图回溯整条推理链。
    based_on: list[str] = field(default_factory=list)
    decided_at: str = field(default_factory=utc_now)

    def is_valid(self) -> bool:
        return is_valid_action(self.action)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    """研究图上的一条边。

    图才是长期大脑：跑到第 40 次实验时，要能回答的不是"第 637 条消息说了什么"，
    而是"什么已经被证明、什么已经被否定、哪个假设来自哪篇论文"。
    节点由对象集合自身承担（假设/实验/证据/分支/决策都是节点），所以这里只存边。
    """

    source_id: str
    target_id: str
    kind: str
    note: str = ""
    created_at: str = field(default_factory=utc_now)

    def is_valid(self) -> bool:
        return self.kind in GRAPH_EDGE_KINDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ACTION_LABELS",
    "BRANCH_STATUSES",
    "CHECK_FIELDS",
    "CHECK_LABELS",
    "CHECK_TITLES",
    "CHOOSABLE_ACTIONS",
    "Decision",
    "EVIDENCE_VERDICTS",
    "EVIDENCE_VERDICT_LABELS",
    "Evidence",
    "Experiment",
    "FALSIFICATION_PRECONDITIONS",
    "GRAPH_EDGE_KINDS",
    "GRAPH_NODE_KINDS",
    "GraphEdge",
    "HYPOTHESIS_STATUSES",
    "Hypothesis",
    "PENDING_ACTIONS",
    "RESEARCH_ACTIONS",
    "RESEARCH_CONTRACT_VERSION",
    "ResearchBranch",
    "TERMINAL_ACTIONS",
    "is_valid_action",
    "research_contract",
]
