"""Deterministic training-curve diagnosis used before LLM-level interpretation."""

from __future__ import annotations

import statistics
from typing import Any


def analyze_history(history: list[dict[str, float]], direction: str) -> dict[str, Any]:
    if not history:
        return {
            "overfitting_detected": False,
            "instability_detected": False,
            "recommendations": ["Training produced no history; inspect runner logs."],
        }

    metric_name = "val_accuracy" if direction == "maximize" else "val_loss"
    values = [point[metric_name] for point in history]
    selector = max if direction == "maximize" else min
    best_index = values.index(selector(values))
    final = history[-1]
    gap = final.get("train_accuracy", 0.0) - final.get("val_accuracy", 0.0)
    post_best = values[best_index + 1 :]
    degraded = bool(post_best) and (
        final[metric_name] < values[best_index] - 0.02
        if direction == "maximize"
        else final[metric_name] > values[best_index] + 0.02
    )
    overfitting = gap > 0.08 and degraded
    recent = values[-min(4, len(values)) :]
    instability = len(recent) >= 3 and statistics.pstdev(recent) > 0.05

    recommendations: list[str] = []
    if overfitting:
        recommendations.extend(
            [
                "尝试更强的数据增强或正则化。",
                "比较早停与较小模型容量。",
            ]
        )
    if instability:
        recommendations.append("检查学习率，并以较小学习率复现实验。")
    if not recommendations:
        recommendations.append("在保持当前基线的前提下，只验证一个低成本改动。")

    return {
        "metric_name": metric_name,
        "best_epoch": int(history[best_index]["epoch"]),
        "final_train_val_gap": round(gap, 6),
        "overfitting_detected": overfitting,
        "instability_detected": instability,
        "recommendations": recommendations,
    }
