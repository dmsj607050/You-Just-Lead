"""Prompts for the research-loop executor.

每个提示词只做两件事：把当前状态讲清楚，把输出契约讲死。

结构化输出是防幻觉的第一道闸（解析失败就什么都不改），提示词是第二道：
每个动作都明确要求"每条判断必须能指回具体来源，指不回去就填 null"。
**不许出现"模型觉得大概是这样"的字段** —— 空缺会被如实记成 `None`，
而猜出来的东西会污染整条证据链，比空缺坏得多。
"""

from __future__ import annotations

from typing import Any

from schemas.research import Hypothesis


SYSTEM = """你是科研编排器的一个执行器。编排器已经决定了这一轮要做什么，你只负责把这一件事做成。

三条纪律：
1. 只输出要求的 JSON，不要解释、不要寒暄、不要加契约以外的字段。
2. 每一条判断都要能指回具体来源（哪次实验、哪篇论文、哪条记录）。指不回去的，
   宁可填 null，也不要猜 —— 空缺会被如实记录，猜出来的会污染整条证据链。
3. 把"没查到"和"不存在"分开写，不要合并。"""


def refine_hypothesis(hypothesis: Hypothesis, state: Any) -> str:
    """补全一条不可证伪的假设。"""
    return f"""这条假设目前**不可证伪**，所以编排器拒绝为它设计实验。你的任务是把它变成一条可被实验判决的命题。

假设原文：
{hypothesis.statement}

现有依据：{hypothesis.rationale or "（无）"}
当前不确定性：{hypothesis.uncertainty}

要求：
- `predictions`：至少 2 条**可测量**的预测（写清指标名与方向，例如"ball 的 AP50 提升 >= 0.005"）。
- `falsifiers`：至少 2 条**会否定它**的结果（例如"ball 的 AP50 没有提升"）。
- 预测与反证必须来自假设本身，不要换成另一条更容易验证的假设。
- 如果这条假设本身就无法被实验判决（例如它只是"这条链路能跑通"这种工程目标），
  `predictions` 与 `falsifiers` 都返回空数组，并在 `note` 里说明为什么 —— 这是合法答案。

只输出：
{{"predictions": ["..."], "falsifiers": ["..."], "uncertainty": 0.0, "note": ""}}"""


def generate_hypotheses(state: Any, research_titles: list[str], failure_notes: list[str]) -> str:
    """从文献与失败史里提出候选假设。"""
    titles = "\n".join(f"- {item}" for item in research_titles) or "（工作区里还没有文献记录）"
    failures = "\n".join(f"- {item}" for item in failure_notes) or "（还没有失败记录）"
    return f"""提出 2 到 3 条**互相不同**的研究假设，用于改进当前基线。

可引用的文献：
{titles}

已知失败的方向（不要重复它们）：
{failures}

当前状态：{state.summary()}

每条假设必须：
- `statement`：一句话说清"改动什么、期望什么"；
- `predictions`：至少 1 条可测量的预测；
- `falsifiers`：至少 1 条会否定它的结果；
- `rationale`：依据的来源 id（论文 id 或实验 id），至少 1 条。**没有来源的想法不要提**，
  宁可少提一条。

只输出：
{{"hypotheses": [{{"statement": "...", "predictions": ["..."], "falsifiers": ["..."], "rationale": ["..."], "uncertainty": 0.0}}]}}"""


def design_experiment(hypothesis: Hypothesis, state: Any) -> str:
    """把假设变成一次公平比较，并且落成一份真的能跑的配置。"""
    return f"""为下面这条假设设计**一次**实验。要求是"能判决它"，不是"能跑起来"。

假设：{hypothesis.statement}
预测：{hypothesis.predictions}
反证条件：{hypothesis.falsifiers}

已有实验：{sorted(state.experiments)}

要求：
- `question`：这次实验在区分什么（一句话）；
- `baseline`：跟谁比。**必须写具体的对照物**，例如父实验 id 或某个已完成的配置；
- `independent`：唯一被改变的自变量；
- `controlled`：至少 3 项被固定的东西（数据版本、随机种子、训练步数、参数量、评测脚本……）；
- `metrics`：用来判决预测的指标名；
- `success_condition`：什么结果算支持这条假设；
- `config_path`：这次实验要跑的配置，相对工作区。**你要真的把这份配置写出来**：
  先用 `read_file` 读 `configs/` 下最接近的一份现有配置，只改你指定的那一个自变量，
  写到 `configs/loop/<短名>.yaml`，再把相对路径填在这里。
  配置要能直接跑 —— 路径不对、键名不对的配置只会让这次实验白等一轮。

如果这条假设**无法在一次有对照的实验里被判决**（例如需要先造数据、需要新硬件），
`baseline` 与 `config_path` 都返回空字符串，并在 `blocker` 里说明原因 ——
不要为了凑出一个实验而编造对照，也不要写一份跑不起来的配置。

只输出：
{{"question": "...", "baseline": "...", "independent": "...", "controlled": ["..."], "metrics": ["..."], "success_condition": "...", "config_path": "...", "blocker": ""}}"""


def analyze_result(experiment_id: str, hypothesis_statement: str, facts: dict[str, Any]) -> str:
    """核查一次实验的结果。九项里能判断的判断，判断不了的留 null。"""
    return f"""核查下面这次实验的结果。你的产出会直接决定"这条证据算不算数"，所以**拿不准就填 null**。

实验：{experiment_id}
它要检验的假设：{hypothesis_statement}
从记录里能直接读出来的事实：{facts}

九项核查（true = 合格，false = 不合格，null = 你无法判断）：
- `ran_successfully`：实验真的跑完了吗
- `baseline_comparable`：对照可比吗（同数据、同口径、同评测脚本）
- `metric_improved`：指标有没有实际变化。这是**事实记录**，它本身不决定假设成立与否
- `prediction_met`：**假设写下的预测有没有被这次结果满足**。判"假设被反证"看的是这一项，
  不是 `metric_improved` —— 如果预测是"能复现到 ±0.001"或"不再 OOM"，那指标不变恰恰是满足。
  预测看不出方向、或记录不足以判断时填 null
- `replicated_across_seeds`：跨随机种子复现过吗
- `leakage_free`：确认没有数据泄漏吗
- `matches_hypothesis`：改动真的对应这条假设吗（还是改了个参数就宣称验证了 X）
- `single_variable`：只动了一个变量吗
- `logs_consistent`：日志与结论一致吗

注意：**记录里没写的东西就是 null，不是 false**。把"没人查过"写成"不合格"，
会凭空否定一条可能有希望的路线。

只输出：
{{"ran_successfully": null, "baseline_comparable": null, "metric_improved": null,
 "prediction_met": null, "replicated_across_seeds": null, "leakage_free": null,
 "matches_hypothesis": null, "single_variable": null, "logs_consistent": null, "notes": ""}}"""


def synthesize(state: Any, evidence_summary: list[str]) -> str:
    """综合已有证据，得出可以写进报告的结论，并提出下一步问题。"""
    lines = "\n".join(f"- {item}" for item in evidence_summary) or "（还没有合格的证据）"
    return f"""综合目前的证据，给出**能站得住的**结论。

已核查的证据：
{lines}

要求：
- `conclusion`：一段话。**只能写证据支持的**；证据不足就直说"目前不足以支持任何结论"。
- `supported`：被证据支持的判断，每条注明依据的实验 id。
- `refuted`：被证据否定的判断，每条注明依据。
- `next_questions`：还没解决的问题（这些会成为下一轮的假设来源）。

只输出：
{{"conclusion": "...", "supported": [{{"claim": "...", "evidence": ["E0001"]}}],
 "refuted": [{{"claim": "...", "evidence": ["E0002"]}}], "next_questions": ["..."]}}"""


def advisory(action: str, target: str, state: Any, facts: dict[str, Any]) -> str:
    """给"建议类"动作（修实现 / 质疑 / 分叉）产出可执行的下一步。"""
    return f"""编排器当前的动作是 `{action}`，目标 `{target}`。

已知事实：{facts}
当前状态：{state.summary()}

请给出可执行的下一步，写在 `advice` 里，要求：
- 具体到"改哪个文件/哪个配置项/哪段逻辑"，不要写"进一步优化"这种空话；
- 说明**为什么这样改**，依据要能指回上面的已知事实；
- 如果判断这条路已经不值得继续，直接说"建议终止"，并给出依据。

只输出：{{"advice": "...", "verdict": "continue|abandon"}}"""


__all__ = [
    "SYSTEM",
    "advisory",
    "analyze_result",
    "design_experiment",
    "generate_hypotheses",
    "refine_hypothesis",
    "synthesize",
]
