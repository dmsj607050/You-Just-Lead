"""The executor: carry out the action the orchestrator chose.

编排器决定"做什么"（`policy.py`），这里负责"把它做成"，并把结果写回研究状态。
边界依旧守着：**执行类动作（跑真训练、复现）不在这里**，它们要人批准后交给训练执行器。

两层防幻觉：

1. **结构化输出**：解析不出 JSON 就什么都不改 —— 宁可这一步白做，也不要半截状态；
2. **事实优先**：从记录里能直接读出的事实（例如"实验到底跑完了没有"），
   不允许被模型的判断覆盖。模型说"跑成功了"而记录里是 `failed`，以记录为准。

给了 `project_root` 就走**行动循环**（`run_agent` 的多轮工具调用）：执行器可以自己
列目录、读代码、搜参数、在隔离容器里跑 smoke test、看报错再改 —— 编排层不规定这些步骤。
只注入 `chat` 时退化为单轮问答，测试因此完全离线。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from agents.research_agent import build_research_query, search_research
from app.orchestrator.prompts import (
    SYSTEM,
    advisory,
    analyze_result,
    design_experiment,
    generate_hypotheses,
    refine_hypothesis,
    synthesize,
)
from app.orchestrator.state import ResearchState
from app.orchestrator.validator import validate_evidence
from schemas.research import Decision, Evidence, Experiment, Hypothesis, ResearchBranch
from tools.configuration import load_yaml
from tools.files import read_json
from tools.provenance import utc_now


# 一次动作最多生成几条假设：一轮提出一打假设等于没提。
MAX_NEW_HYPOTHESES = 3

# 失败归档只读前这么多行。它是给人看的台账，不是数据集。
FAILED_NOTES_LIMIT = 40

# 工具白名单。只做推理判断的动作（补全假设、设计方案、核查结果、综合）不该同时
# 握着写文件和跑命令的手；只有"去修"那类动作才拿全副工具。
READ_ONLY_TOOLS: tuple[str, ...] = (
    "list_experiments",
    "get_experiment",
    "get_best_run",
    "get_recent_events",
    "get_competition_spec",
    "list_directory",
    "read_file",
    "search_text",
)

WRITE_TOOLS: tuple[str, ...] = READ_ONLY_TOOLS + ("write_file", "run_command")

# 设计实验要真的把配置写出来，所以它需要写文件的手；但它不该能跑命令 ——
# "设计"和"执行"是两件事，执行要人批准后才交给训练调度器。
DESIGN_TOOLS: tuple[str, ...] = READ_ONLY_TOOLS + ("write_file",)


def extract_json(text: str) -> Any:
    """从模型回复里抽出第一个 JSON 对象。

    模型经常会加前后说明或 ```json 围栏。这里只做"找第一个括号平衡的 `{}` 块"，
    不做宽松修补 —— 补出来的 JSON 等于替模型编内容。
    （该扫描不处理字符串字面量里的花括号；对本项目用到的扁平结构足够。）
    """
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(candidate)):
        char = candidate[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _strings(value: Any) -> list[str]:
    """只收非空的字符串项。模型偶尔会把列表写成字符串或塞进 null。"""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]


def _tri_state(value: Any) -> bool | None:
    """模型的判断只允许三个值：true / false / null。

    返回 "yes"、"unknown"、"可能吧" 的一律记成 null —— 那表示"没判断"，
    而不是"合格"或"不合格"。
    """
    if value is True or value is False:
        return value
    return None


def _facts_from_records(workspace: Path, experiment_id: str) -> dict[str, Any]:
    """从实验记录里能直接读出来的事实。

    只读不猜：记录里没有的键就不出现在结果里，交给模型或留成 None。
    """
    path = Path(workspace) / "experiments" / "results" / f"{experiment_id}.json"
    if not path.exists():
        return {}
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {}
    facts: dict[str, Any] = {}
    status = str(payload.get("status") or "").strip()
    if status:
        facts["status"] = status
        facts["ran_successfully"] = status == "completed"
    if payload.get("validation_metric") is not None:
        facts["validation_metric"] = payload["validation_metric"]
    if payload.get("error"):
        facts["error"] = str(payload["error"])[:300]
    return facts


def _research_titles(workspace: Path, limit: int = 12) -> list[str]:
    path = Path(workspace) / "research" / "papers.json"
    if not path.exists():
        return []
    payload = read_json(path)
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    titles: list[str] = []
    for item in records:
        if isinstance(item, dict) and item.get("title"):
            titles.append(f"{item.get('paper_id') or '?'} — {item['title']}")
    return titles[:limit]


def _failure_notes(workspace: Path) -> list[str]:
    path = Path(workspace) / "experiments" / "FAILED_IDEAS.md"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines[:FAILED_NOTES_LIMIT] if line.strip()]


def _write_note(workspace: Path, name: str, text: str) -> Path:
    """把建议类产出落成可审计的笔记。带时间戳，不覆盖旧笔记。"""
    directory = Path(workspace) / "research" / "loop" / "notes"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = utc_now()[:19].replace(":", "").replace("-", "")
    path = directory / f"{name}-{stamp}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _workspace_hint(workspace: Path) -> str:
    """告诉模型它现在站在哪儿。

    不写这段，模型会一路试 `configs/x.yaml`、`aic2026/configs/x.yaml`、
    `workspace/aic2026/configs/x.yaml` —— 真实跑过一轮，16 次工具调用里有 6 次
    花在猜路径上。工具本来就是相对工作区的，那就把根说清楚。
    """
    return (
        f"当前工作区根目录：{Path(workspace)}\n"
        "所有工具的相对路径都相对这个目录（写 'configs/a.yaml' 指的是它下面的 configs/a.yaml）。"
        "不要加 workspace/<项目名>/ 前缀，也不要试绝对路径。\n"
        "run_command 打开的容器里，同一个工作区以只读方式挂在 /work，唯一可写的是 /scratch。"
    )


def _branch_for_target(state: ResearchState, target_id: str) -> ResearchBranch | None:
    """从动作的 target 找到它所属的分支。

    target 的语义随动作而变：修实现 / 质疑指向**实验**，分叉指向**假设**。
    两种都要能找到分支，否则"建议放弃这条路"就落不了地 —— 模型判了该放弃，
    循环却不知道该把哪条路线停下来。
    """
    if target_id in state.hypotheses:
        return state.branch_of(target_id)
    experiment = state.experiments.get(target_id)
    if experiment is not None:
        return state.branch_of(experiment.hypothesis_id)
    return None


class ResearchExecutor:
    """把一个动作做成，并回填研究状态。"""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        chat: Callable[[str, str], dict[str, Any]] | None = None,
        agent: Callable[..., dict[str, Any]] | None = None,
    ):
        """给了 `project_root` 就走带工具的行动循环；只给 `chat` 时是单轮问答。

        `agent` 可显式注入，测试用它替换掉真实的多轮循环。
        """
        self._project_root = Path(project_root) if project_root is not None else None
        if agent is not None:
            self._agent = agent
        elif self._project_root is not None:
            from app.llm_service import run_agent  # 延迟导入：单轮路径不需要它

            self._agent = run_agent
        else:
            self._agent = None
        if chat is None:
            from app.llm_service import chat_completion

            chat = chat_completion
        self._chat = chat

    def __call__(self, action: str, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        method = getattr(self, f"_do_{action.lower()}", None)
        if method is None:
            return {"detail": f"动作 {action} 还没有接执行器"}
        return method(decision, state, workspace)

    # ------------------------------------------------------------------ 内部

    def _ask(
        self,
        user_prompt: str,
        workspace: Path,
        *,
        tools: tuple[str, ...] = READ_ONLY_TOOLS,
        required: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """问一次模型，并要求结构化输出。

        走行动循环时，模型可以先用工具把情况摸清，最后再给出契约要求的 JSON；
        最终答复仍要过 `extract_json` —— 摸清过程的自由度，不等于放宽输出契约。
        """
        framed = f"{_workspace_hint(workspace)}\n\n{user_prompt}"
        if self._agent is not None and self._project_root is not None:
            response = self._agent(
                framed,
                "research_loop",
                self._project_root,
                Path(workspace),
                system_prompt=SYSTEM,
                tools=tools,
            )
        else:
            response = self._chat(SYSTEM, framed)

        payload = extract_json(str((response or {}).get("content") or ""))
        if not isinstance(payload, dict):
            raise ValueError("模型没有返回可解析的 JSON")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"模型输出缺少必需字段：{', '.join(missing)}")
        return payload

    def _advisory(
        self,
        action: str,
        decision: Decision,
        state: ResearchState,
        workspace: Path,
        *,
        tools: tuple[str, ...] = READ_ONLY_TOOLS,
    ) -> dict[str, Any]:
        """修实现 / 质疑 / 分叉 这类"给建议"的动作：写一份笔记；判了放弃就终止分支。

        建议本身不改状态 —— 那是给人和下一轮看的，不是替人下结论。但**"放弃"是个例外**：
        模型说这条路不值得继续，却不把算力挪走，下一轮就会继续在它身上花钱，等于白判。
        终止一条路线不烧算力、不可逆性也低（假设与分支都还在，结论写明理由），
        所以让它自动生效。
        """
        target = decision.target_id or ""
        facts = _facts_from_records(workspace, target)
        payload = self._ask(advisory(action, target, state, facts), workspace, tools=tools, required=("advice",))
        verdict = str(payload.get("verdict") or "continue")
        advice = str(payload["advice"])
        path = _write_note(workspace, f"{action.lower()}-{target or 'none'}", f"# {action} {target}\n\n{advice}\n")
        detail = f"已写出建议（{verdict}）：{path.name}"

        if verdict == "abandon":
            branch = _branch_for_target(state, target)
            if branch is None:
                detail += "；但找不到对应的分支，未终止任何路线"
            elif branch.status != "active":
                detail += f"；分支 {branch.branch_id} 已是 {branch.status}，无需重复终止"
            else:
                state.kill_branch(branch.branch_id, f"{action} 判定建议放弃：{advice[:240]}")
                detail += f"；已终止分支 {branch.branch_id}"
        return {"detail": detail}

    # ------------------------------------------------------------------ 动作

    def _do_search_literature(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        spec_path = Path(workspace) / "competition_spec.yaml"
        spec = load_yaml(spec_path) if spec_path.exists() else {}
        query = build_research_query(spec).strip()
        if not query:
            return {"detail": "拼不出检索式：competition_spec.yaml 里缺任务类型或模态"}
        outcome = search_research(workspace, query, limit=8)
        return {"detail": f"按「{query}」检索到 {len(outcome.get('records') or [])} 条记录"}

    def _do_generate_hypothesis(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        payload = self._ask(
            generate_hypotheses(state, _research_titles(workspace), _failure_notes(workspace)),
            workspace,
            required=("hypotheses",),
        )
        items = payload.get("hypotheses")
        if not isinstance(items, list) or not items:
            return {"detail": "模型没有给出候选假设"}

        created: list[str] = []
        for item in items[:MAX_NEW_HYPOTHESES]:
            if not isinstance(item, dict):
                continue
            statement = str(item.get("statement") or "").strip()
            if not statement:
                continue
            hypothesis = Hypothesis(
                hypothesis_id=state.new_id("hypothesis"),
                statement=statement,
                rationale=_strings(item.get("rationale")),
                predictions=_strings(item.get("predictions")),
                falsifiers=_strings(item.get("falsifiers")),
                uncertainty=item.get("uncertainty") if isinstance(item.get("uncertainty"), (int, float)) else None,
            )
            state.add_hypothesis(hypothesis)
            state.add_branch(
                ResearchBranch(branch_id=state.new_id("branch"), hypothesis_id=hypothesis.hypothesis_id)
            )
            created.append(hypothesis.hypothesis_id)

        if not created:
            return {"detail": "模型的候选假设缺少可用的 statement"}
        # 不可证伪的那些不用在这里纠：编排器的规则会先把它们抓去补全。
        return {"detail": f"新增假设 {'、'.join(created)}"}

    def _do_refine_hypothesis(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        hypothesis = state.hypotheses.get(decision.target_id or "")
        if hypothesis is None:
            return {"detail": f"找不到假设 {decision.target_id}"}
        payload = self._ask(
            refine_hypothesis(hypothesis, state), workspace, required=("predictions", "falsifiers")
        )

        predictions = _strings(payload.get("predictions"))
        falsifiers = _strings(payload.get("falsifiers"))
        if not predictions or not falsifiers:
            # 模型说不出可判决的预测/反证 —— 保持原样，让编排器的重复计数把它推向终止。
            note = str(payload.get("note") or "").strip()
            return {"detail": f"{hypothesis.hypothesis_id} 仍不可证伪" + (f"：{note}" if note else "")}

        hypothesis.predictions = predictions
        hypothesis.falsifiers = falsifiers
        if isinstance(payload.get("uncertainty"), (int, float)):
            hypothesis.uncertainty = float(payload["uncertainty"])
        state.touch()
        return {
            "detail": f"{hypothesis.hypothesis_id} 补上 {len(predictions)} 条预测、{len(falsifiers)} 条反证条件"
        }

    def _do_design_experiment(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        hypothesis = state.hypotheses.get(decision.target_id or "")
        if hypothesis is None:
            return {"detail": f"找不到假设 {decision.target_id}"}
        payload = self._ask(
            design_experiment(hypothesis, state),
            workspace,
            tools=DESIGN_TOOLS,
            required=("question", "baseline", "independent", "controlled"),
        )
        experiment = Experiment(
            experiment_id=state.new_id("experiment"),
            hypothesis_id=hypothesis.hypothesis_id,
            question=str(payload.get("question") or "").strip(),
            baseline=str(payload.get("baseline") or "").strip(),
            independent=str(payload.get("independent") or "").strip(),
            controlled=_strings(payload.get("controlled")),
            metrics=_strings(payload.get("metrics")),
            success_condition=str(payload.get("success_condition") or "").strip(),
            config_path=str(payload.get("config_path") or "").strip(),
            blocked=str(payload.get("blocker") or "").strip(),
        )
        branch = state.branch_of(hypothesis.hypothesis_id)
        state.add_experiment(experiment, branch_id=branch.branch_id if branch else None)

        blocker = experiment.blocked
        detail = f"已设计实验 {experiment.experiment_id}"
        if blocker:
            # 这一类设计是"空"的：没有对照、没有配置，跑不起来。如实说清楚，
            # 否则界面上它和一次真能跑的实验长得一模一样。
            detail += f"（这次设计是空的，跑不起来）；模型给出的阻碍：{blocker}"
        elif not experiment.is_controlled():
            detail += "（缺对照或控制变量，编排器不会把它当成一次公平比较）"
        # 配置在不在，决定这次设计能不能被执行。检查一次是因为"写进 JSON 的路径"
        # 和"真的写了那个文件"是两件事，而只有后者能跑。
        if experiment.config_path:
            if (Path(workspace) / experiment.config_path).is_file():
                detail += f"；配置已就位：{experiment.config_path}"
            else:
                detail += f"；但配置 {experiment.config_path} 并不存在，这次设计跑不了"
        elif not blocker:
            detail += "；没有给出配置，无法执行"
        return {"detail": detail}

    def _do_analyze_result(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        experiment_id = decision.target_id or ""
        experiment = state.experiments.get(experiment_id)
        if experiment is None:
            return {"detail": f"找不到实验 {experiment_id}"}
        hypothesis = state.hypotheses.get(experiment.hypothesis_id)
        facts = _facts_from_records(workspace, experiment_id)

        payload = self._ask(
            analyze_result(experiment_id, hypothesis.statement if hypothesis else "（未知）", facts),
            workspace,
        )
        evidence = Evidence(
            evidence_id=state.new_id("evidence"),
            experiment_id=experiment_id,
            ran_successfully=_tri_state(payload.get("ran_successfully")),
            baseline_comparable=_tri_state(payload.get("baseline_comparable")),
            metric_improved=_tri_state(payload.get("metric_improved")),
            prediction_met=_tri_state(payload.get("prediction_met")),
            replicated_across_seeds=_tri_state(payload.get("replicated_across_seeds")),
            leakage_free=_tri_state(payload.get("leakage_free")),
            matches_hypothesis=_tri_state(payload.get("matches_hypothesis")),
            single_variable=_tri_state(payload.get("single_variable")),
            logs_consistent=_tri_state(payload.get("logs_consistent")),
            notes=str(payload.get("notes") or "").strip(),
        )
        # 事实优先：记录里读得出的项，不允许被模型的判断覆盖。
        for key, value in facts.items():
            if key in ("ran_successfully", "metric_improved") and isinstance(value, bool):
                setattr(evidence, key, value)

        outcome = validate_evidence(evidence)
        evidence.verdict = outcome.verdict
        link = "supports" if outcome.verdict == "pass" else "refutes" if outcome.verdict == "hypothesis_falsified" else None
        state.record_evidence(evidence, outcome=link)
        return {"detail": f"{experiment_id} 判定为 {outcome.verdict}，下一步 {outcome.follow_up}"}

    def _do_synthesize(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        summary = [f"{item.experiment_id}: {item.verdict}" for item in state.evidence.values()]
        payload = self._ask(synthesize(state, summary), workspace, required=("conclusion",))

        lines = [f"# 综合 {utc_now()}", "", str(payload["conclusion"]), ""]
        for label, key in (("支持", "supported"), ("否定", "refuted")):
            entries = payload.get(key)
            if isinstance(entries, list) and entries:
                lines.append(f"## {label}")
                for entry in entries:
                    if isinstance(entry, dict):
                        sources = ", ".join(_strings(entry.get("evidence"))) or "未注明"
                        lines.append(f"- {entry.get('claim')}（依据 {sources}）")
                lines.append("")
        questions = _strings(payload.get("next_questions"))
        if questions:
            lines.append("## 未解决的问题")
            lines.extend(f"- {item}" for item in questions)
        path = _write_note(workspace, "synthesis", "\n".join(lines) + "\n")

        # 把"还没解决的问题"变成下一条待补全的假设，循环才有下一步可走。
        opened: list[str] = []
        for question in questions[:MAX_NEW_HYPOTHESES]:
            hypothesis = Hypothesis(hypothesis_id=state.new_id("hypothesis"), statement=question)
            state.add_hypothesis(hypothesis)
            state.add_branch(ResearchBranch(branch_id=state.new_id("branch"), hypothesis_id=hypothesis.hypothesis_id))
            opened.append(hypothesis.hypothesis_id)

        detail = f"已写出综合结论：{path.name}"
        if opened:
            detail += f"；由未解决问题开出 {len(opened)} 条假设（待补全预测与反证）"
        return {"detail": detail}

    # 建议类动作。只有"去修"这一类拿写工具：它能读代码、改文件、在隔离容器里
    # 跑 smoke test 看报错；其余只读，用来质疑和分叉。
    def _do_repair_experiment(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        return self._advisory("REPAIR_EXPERIMENT", decision, state, workspace, tools=WRITE_TOOLS)

    def _do_challenge_claim(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        return self._advisory("CHALLENGE_CLAIM", decision, state, workspace)

    def _do_fork_hypothesis(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        return self._advisory("FORK_HYPOTHESIS", decision, state, workspace)

    def _do_merge_hypotheses(self, decision: Decision, state: ResearchState, workspace: Path) -> dict[str, Any]:
        return self._advisory("MERGE_HYPOTHESES", decision, state, workspace)


__all__ = [
    "MAX_NEW_HYPOTHESES",
    "READ_ONLY_TOOLS",
    "WRITE_TOOLS",
    "ResearchExecutor",
    "extract_json",
]
