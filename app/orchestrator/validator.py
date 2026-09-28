"""The evidence validator: machine gating instead of form filling.

这是 EGRL 最关键的一道门：**结果不能直接进入下一轮，中间必须过这里**。

它检查的不是"模型觉得这次实验怎么样"，而是九项可以查证的事实，判定由机器做、可复算 ——
人填表会退化成走过场，模型自评会退化成自我表扬。

判定分四路，区别就是"该修什么"：

* `implementation_bug` —— 实现问题（没跑成、代码与假设不符、日志与结论矛盾）：
  修代码再来，**不要动假设**；
* `experiment_flaw` —— 设计问题（没有对照、同时动了多个变量、有数据泄漏）：
  重新设计实验，**也不要动假设**；
* `hypothesis_falsified` —— 实验是干净的、指标确实没动：这是**有价值的负结果**，
  该杀掉这条路线而不是继续修它；
* `inconclusive` —— 查不动（还有项目没人查过，或只跑了一个种子）。这一档必须与
  "不合格"严格分开：把"未知"读成"失败"，会凭空杀掉本来有希望的路线。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemas.research import CHECK_FIELDS, CHECK_LABELS, FALSIFICATION_PRECONDITIONS, Evidence


@dataclass(frozen=True)
class ValidationOutcome:
    """判定结果。`follow_up` 直接就是动作空间里的一个动作名。"""

    verdict: str
    follow_up: str
    # 哪几项查了、不合格。
    reasons: list[str]
    # 哪几项没人查过。空列表 = 八项都查过。
    unchecked: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "follow_up": self.follow_up,
            "reasons": list(self.reasons),
            "unchecked": list(self.unchecked),
        }


def _unchecked(evidence: Evidence) -> list[str]:
    return [name for name in CHECK_FIELDS if getattr(evidence, name) is None]


def validate_evidence(evidence: Evidence) -> ValidationOutcome:
    """九项核查 → 一个判定 + 下一步该做什么。

    判定顺序即优先级：先看"跑没跑成"，再看"实现对不对"，然后才是"实验设计公不公"，
    最后才谈结论。顺序反了会出现"实验根本没跑成却判假设被反证"这种笑话。
    """
    unchecked = _unchecked(evidence)

    # 一、跑都没跑成，这不是科学问题。
    if evidence.ran_successfully is False:
        return ValidationOutcome("implementation_bug", "REPAIR_EXPERIMENT", [CHECK_LABELS["ran_successfully"]], unchecked)
    if evidence.ran_successfully is None:
        return ValidationOutcome("inconclusive", "ANALYZE_RESULT", [], unchecked)

    # 二、实现层面：代码与假设不符、日志与结论矛盾 —— 先修代码，别急着下结论。
    for name in ("matches_hypothesis", "logs_consistent"):
        if getattr(evidence, name) is False:
            return ValidationOutcome("implementation_bug", "REPAIR_EXPERIMENT", [CHECK_LABELS[name]], unchecked)

    # 三、实验设计层面：没有对照、动了多个变量、有泄漏 —— 结论无法归因，重做实验。
    for name in ("baseline_comparable", "single_variable", "leakage_free"):
        if getattr(evidence, name) is False:
            return ValidationOutcome("experiment_flaw", "DESIGN_EXPERIMENT", [CHECK_LABELS[name]], unchecked)

    # 四、到这里实现与设计都没查出问题，结果才真正具有解释力。
    # **判"假设被反证"看的是"预测有没有被满足"，不是"指标有没有涨"。**
    # 复现类假设的成功恰恰是"指标没变"，拿指标方向去判会把成功的复现读成失败
    # —— 真实撞到过：EXP-0007 精确复现了 0.00234，却被判成 hypothesis_falsified。
    if evidence.prediction_met is False:
        # 判"被反证"是个重结论，必须先确认实现正确、实验公平。这四项只要有一项
        # 没查过，就只能是"查不动" —— 预测没满足完全可能是隐藏的实现缺陷造成的。
        unverified = [name for name in FALSIFICATION_PRECONDITIONS if getattr(evidence, name) is not True]
        if unverified:
            return ValidationOutcome("inconclusive", "ANALYZE_RESULT", [], sorted(set(unchecked) | set(unverified)))
        return ValidationOutcome(
            "hypothesis_falsified", "KILL_HYPOTHESIS", [CHECK_LABELS["prediction_met"]], unchecked
        )
    if evidence.prediction_met is None:
        # 没人判过预测是否满足，就不能下任何结论 —— 包括"通过"。
        return ValidationOutcome("inconclusive", "ANALYZE_RESULT", [], unchecked)

    # 五、预测满足了，但只有单个种子时结论不牢 —— 先复现，再当结论用。
    if evidence.replicated_across_seeds is not True:
        return ValidationOutcome(
            "inconclusive", "REPLICATE_EXPERIMENT", [CHECK_LABELS["replicated_across_seeds"]], unchecked
        )

    # 六、还有没查过的项目时不下"通过"的判定：通过必须是全查过且全合格。
    if unchecked:
        return ValidationOutcome("inconclusive", "ANALYZE_RESULT", [], unchecked)

    return ValidationOutcome("pass", "SYNTHESIZE", [], [])


__all__ = ["ValidationOutcome", "validate_evidence"]
