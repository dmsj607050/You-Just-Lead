"""Deterministic, local-only analysis of persisted validation predictions."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tools.files import write_json_atomic


def _load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Prediction record {line_number} is not an object")
            for field in ("true_label", "predicted_label", "confidence"):
                if field not in payload:
                    raise ValueError(f"Prediction record {line_number} is missing '{field}'")
            records.append(payload)
    return records


def analyze_prediction_errors(predictions_path: Path, output_dir: Path) -> dict[str, Any]:
    """Summarize classification failures without sending samples off-device."""
    records = _load_records(predictions_path)
    total = len(records)
    correct = sum(record["true_label"] == record["predicted_label"] for record in records)
    labels = sorted({str(record["true_label"]) for record in records} | {str(record["predicted_label"]) for record in records})
    supports: Counter[str] = Counter(str(record["true_label"]) for record in records)
    hits: Counter[str] = Counter(
        str(record["true_label"])
        for record in records
        if record["true_label"] == record["predicted_label"]
    )
    confusion: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        confusion[str(record["true_label"])][str(record["predicted_label"])] += 1
    per_class = [
        {
            "label": label,
            "support": supports[label],
            "correct": hits[label],
            "recall": round(hits[label] / supports[label], 6) if supports[label] else None,
        }
        for label in labels
        if supports[label]
    ]
    failures = [record for record in records if record["true_label"] != record["predicted_label"]]
    high_confidence_failures = sorted(
        (record for record in failures if float(record.get("confidence", 0)) >= 0.8),
        key=lambda record: float(record["confidence"]),
        reverse=True,
    )
    failure_modes: list[dict[str, str]] = []
    recalls = [float(item["recall"]) for item in per_class if item["recall"] is not None]
    if len(recalls) >= 2 and max(recalls) - min(recalls) >= 0.3:
        worst = min(per_class, key=lambda item: float(item["recall"] or 0))
        failure_modes.append(
            {
                "kind": "class_recall_asymmetry",
                "detail": f"Class '{worst['label']}' recall is materially lower than the best observed class.",
            }
        )
    if high_confidence_failures:
        failure_modes.append(
            {
                "kind": "high_confidence_misclassification",
                "detail": f"{len(high_confidence_failures)} validation errors have confidence at or above 0.80.",
            }
        )
    summary = {
        "prediction_source": str(predictions_path),
        "samples": total,
        "correct": correct,
        "accuracy": round(correct / total, 6) if total else None,
        "per_class": per_class,
        "confusion": {label: dict(sorted(confusion[label].items())) for label in labels if confusion[label]},
        "failure_modes": failure_modes,
        "worst_examples": [
            {
                "path": record.get("path"),
                "true_label": record["true_label"],
                "predicted_label": record["predicted_label"],
                "confidence": round(float(record["confidence"]), 6),
            }
            for record in sorted(failures, key=lambda item: float(item["confidence"]), reverse=True)[:20]
        ],
        "high_confidence_error_count": len(high_confidence_failures),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_dir / "error_analysis.json", summary)
    markdown = ["# Validation error analysis", "", f"- Samples: **{total}**", f"- Accuracy: **{summary['accuracy']}**", f"- High-confidence errors: **{len(high_confidence_failures)}**", "", "## Per-class recall", "", "| Class | Support | Recall |", "| --- | ---: | ---: |"]
    markdown.extend(
        f"| {item['label']} | {item['support']} | {item['recall'] if item['recall'] is not None else 'n/a'} |"
        for item in per_class
    )
    markdown.extend(["", "## Failure modes", ""])
    if failure_modes:
        markdown.extend(
            f"- **{item['kind']}**: {item['detail']}" for item in failure_modes
        )
    else:
        markdown.append("- No deterministic failure mode crossed a threshold.")
    (output_dir / "error_analysis.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return summary
