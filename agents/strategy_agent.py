"""Rule-aware next-action selection based only on persisted local evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.configuration import load_yaml
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


def _results(workspace: Path) -> list[dict[str, Any]]:
    return sorted(
        (read_json(path) for path in (workspace / "experiments" / "results").glob("EXP-*.json")),
        key=lambda item: item["experiment_id"],
    )


def recommend_next_actions(workspace: Path, *, persist: bool = True) -> dict[str, Any]:
    """Produce a bounded, human-reviewable action queue rather than auto-running work."""
    actions: list[dict[str, str]] = []
    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        actions.append({"priority": "blocker", "action": "Create and review competition_spec.yaml before any real-data training.", "evidence": "No specification found."})
    else:
        spec = load_yaml(spec_path)
        approval = spec.get("approval", {})
        if approval.get("requires_human_confirmation", True):
            questions = approval.get("unresolved_questions", [])
            actions.append({"priority": "blocker", "action": "Resolve official-rule questions and explicitly approve the specification.", "evidence": "; ".join(questions) or "Specification is not approved."})

    if not (workspace / "reports" / "data_statistics.json").exists():
        actions.append({"priority": "high", "action": "Run the deterministic data audit before creating a real baseline.", "evidence": "No data_statistics.json exists."})
    if not (workspace / "research" / "papers.json").exists():
        actions.append({"priority": "medium", "action": "Search research sources using the task and metric from the approved specification.", "evidence": "No persisted research radar exists."})

    results = _results(workspace)
    completed = [item for item in results if item.get("status") == "completed"]
    if not completed:
        actions.append({"priority": "high", "action": "After rules and audit are approved, run one reproducible baseline with a frozen configuration.", "evidence": "No completed experiments recorded."})
    else:
        latest = completed[-1]
        diagnosis = latest.get("diagnosis", {})
        for recommendation in diagnosis.get("recommendations", [])[:2]:
            actions.append({"priority": "medium", "action": str(recommendation), "evidence": f"{latest['experiment_id']} curve diagnosis."})
        actions.append({"priority": "low", "action": "Create one candidate experiment that changes a single variable and submit it for human approval.", "evidence": f"Latest completed run: {latest['experiment_id']}."})

    payload = {"generated_at": utc_now(), "actions": actions[:6], "completed_experiments": len(completed)}
    if persist:
        write_json_atomic(workspace / "experiments" / "next_actions.json", payload)
        report = ["# Decision memo", "", "This queue is evidence-led and does not execute actions automatically.", ""]
        for index, action in enumerate(payload["actions"], 1):
            report.extend([f"## {index}. {action['priority'].upper()}", action["action"], "", f"Evidence: {action['evidence']}", ""])
        (workspace / "reports" / "decision_memo.md").write_text("\n".join(report), encoding="utf-8")
    return payload
