"""Render immutable experiment evidence into a compact optimization log.

The JSON manifest/result files remain the source of truth.  This renderer gives
humans and subsequent agents one Markdown/JSON view of every tested change,
its metric, rollback parent and next decision without inventing outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.files import read_json, write_json_atomic
from tools.experiment_scope import is_current_competition_manifest
from tools.provenance import utc_now


def _records(directory: Path) -> list[dict[str, Any]]:
    return sorted(
        (read_json(path) for path in directory.glob("EXP-*.json")),
        key=lambda item: str(item.get("experiment_id", "")),
    ) if directory.exists() else []


def render_optimization_ledger(workspace: Path) -> dict[str, Any]:
    manifests = {
        str(record.get("experiment_id")): record
        for record in _records(workspace / "experiments" / "manifests")
    }
    results = _records(workspace / "experiments" / "results")
    entries: list[dict[str, Any]] = []
    for result in results:
        experiment_id = str(result.get("experiment_id"))
        manifest = manifests.get(experiment_id, {})
        entries.append(
            {
                "experiment_id": experiment_id,
                "status": result.get("status"),
                "parent_id": manifest.get("parent_id"),
                "change_type": manifest.get("change_type"),
                "hypothesis": manifest.get("hypothesis"),
                "data_version": manifest.get("data_version"),
                "config_path": manifest.get("config_path"),
                "validation_metric": result.get("validation_metric"),
                "best_epoch": result.get("best_epoch"),
                "metrics": result.get("metrics", {}),
                "decision": result.get("decision"),
                "conclusion": result.get("conclusion"),
                "next_candidates": result.get("next_candidates", []),
                "error": result.get("error"),
                "current_competition": is_current_competition_manifest(workspace, manifest),
            }
        )
    payload = {
        "generated_at": utc_now(),
        "source_of_truth": "experiments/manifests/EXP-*.json and experiments/results/EXP-*.json",
        "entries": entries,
        "current_competition_entries": [entry for entry in entries if entry["current_competition"]],
    }
    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    write_json_atomic(reports / "optimization_ledger.json", payload)

    lines = [
        "# Optimization ledger",
        "",
        "This document is generated from frozen experiment manifests and results.",
        "Use it to select one controlled next change; do not treat a missing entry as a negative result.",
        "",
    ]
    current_entries = [entry for entry in entries if entry["current_competition"]]
    if not current_entries:
        lines.extend(
            [
                "No approved real-data experiment has completed.",
                "",
                "Current next step: resolve the official-rule questions, then approve exactly one frozen baseline configuration.",
            ]
        )
    for entry in current_entries:
        lines.extend(
            [
                f"## {entry['experiment_id']} — {entry['status']}",
                "",
                f"- Change type: `{entry.get('change_type') or 'unspecified'}`",
                f"- Parent / rollback: `{entry.get('parent_id') or 'none'}`",
                f"- Data version: `{entry.get('data_version') or 'unversioned'}`",
                f"- Config: `{entry.get('config_path') or 'unrecorded'}`",
                f"- Hypothesis: {entry.get('hypothesis') or 'not recorded'}",
                f"- Validation metric: {entry.get('validation_metric') if entry.get('validation_metric') is not None else 'not produced'}",
                f"- Best epoch: {entry.get('best_epoch') if entry.get('best_epoch') is not None else 'not produced'}",
                f"- Decision: `{entry.get('decision') or 'unreviewed'}`",
                f"- Conclusion: {entry.get('conclusion') or 'not recorded'}",
            ]
        )
        metrics = entry.get("metrics") if isinstance(entry.get("metrics"), dict) else {}
        if metrics:
            lines.extend(["", "### Metrics", ""])
            lines.extend(f"- `{name}`: {value}" for name, value in sorted(metrics.items()))
        if entry.get("error"):
            lines.extend(["", f"- Failure: {entry['error']}"])
        candidates = entry.get("next_candidates") if isinstance(entry.get("next_candidates"), list) else []
        if candidates:
            lines.extend(["", "### Evidence-led next candidates", ""])
            lines.extend(f"- {candidate}" for candidate in candidates)
        lines.append("")
    infrastructure_entries = [entry for entry in entries if not entry["current_competition"]]
    if infrastructure_entries:
        lines.extend(["## Infrastructure-only history (excluded from competition decisions)", ""])
        lines.extend(
            f"- `{entry['experiment_id']}` — {entry['status']}; runner/data are not bound to the current audited competition."
            for entry in infrastructure_entries
        )
    (reports / "optimization_ledger.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload
