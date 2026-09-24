"""Read-only projection of persisted workflow data for the local dashboard API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.rules_agent import rule_confirmation_readiness_for_workspace
from agents.strategy_agent import recommend_next_actions
from database.ledger import ExperimentLedger
from app.orchestrator.workflow import workflow_state
from training.catalog import supported_runners
from tools.configuration import load_yaml
from tools.experiment_scope import current_competition_results
from tools.files import read_json


def _json_if_exists(path: Path, default: Any) -> Any:
    return read_json(path) if path.exists() else default


def _records(directory: Path) -> list[dict[str, Any]]:
    return sorted(
        (read_json(path) for path in directory.glob("EXP-*.json")),
        key=lambda item: item["experiment_id"],
    ) if directory.exists() else []


def _history_for(result: dict[str, Any]) -> list[dict[str, float]]:
    for value in result.get("artifact_paths", []):
        path = Path(str(value))
        if path.name == "history.json" and path.exists():
            return _json_if_exists(path, {}).get("history", [])
    return []


def dashboard_snapshot(project_root: Path, workspace: Path) -> dict[str, Any]:
    """Build a JSON-safe dashboard state without treating Markdown as truth."""
    spec = load_yaml(workspace / "competition_spec.yaml") if (workspace / "competition_spec.yaml").exists() else {}
    manifests = {item["experiment_id"]: item for item in _records(workspace / "experiments" / "manifests")}
    all_results = _records(workspace / "experiments" / "results")
    results = current_competition_results(workspace)
    direction = spec.get("evaluation", {}).get("direction", "maximize")
    completed = [item for item in results if item.get("status") == "completed" and item.get("validation_metric") is not None]
    best = (max if direction == "maximize" else min)(completed, key=lambda item: float(item["validation_metric"])) if completed else None
    experiments = []
    for result in reversed(results):
        manifest = manifests.get(result["experiment_id"], {})
        approval = _json_if_exists(workspace / "experiments" / "approvals" / f"{result['experiment_id']}.json", {})
        experiments.append(
            {
                "id": result["experiment_id"],
                "status": result.get("status"),
                "metric": result.get("validation_metric"),
                "best_epoch": result.get("best_epoch"),
                "hypothesis": manifest.get("hypothesis"),
                "change_type": manifest.get("change_type"),
                "runtime_seconds": result.get("runtime_seconds"),
                "decision": result.get("decision"),
                "diagnosis": result.get("diagnosis", {}),
                "error_analysis": result.get("error_analysis", {}),
                "history": _history_for(result),
                # 人工批准记录（experiments/approvals/<id>.json）。界面据此把「记录批准」
                # 换成「已批准」，否则同一道关口会被重复点。
                "approved": bool(approval),
                "approved_at": approval.get("approved_at"),
                "approved_by": approval.get("approved_by"),
            }
        )
    data_audit = _json_if_exists(workspace / "reports" / "data_statistics.json", {})
    research = _json_if_exists(workspace / "research" / "papers.json", {})
    next_actions = recommend_next_actions(workspace, persist=False)
    rule_readiness = rule_confirmation_readiness_for_workspace(workspace)
    ledger = ExperimentLedger(project_root / "database" / "competition_agent.sqlite")
    return {
        "competition": {
            "name": spec.get("competition", {}).get("name"),
            "task_type": spec.get("competition", {}).get("task_type"),
            "preferred_runner": spec.get("competition", {}).get("preferred_runner"),
            "metric": spec.get("evaluation", {}).get("primary_metric"),
            "direction": direction,
            "requires_human_confirmation": spec.get("approval", {}).get("requires_human_confirmation", True) or not rule_readiness["ready"],
            "rule_readiness": rule_readiness,
        },
        "summary": {
            "completed_experiments": len(completed),
            "total_experiments": len(results),
            "best": {"experiment_id": best.get("experiment_id"), "metric": best.get("validation_metric"), "history": _history_for(best)} if best else None,
            "data_files": data_audit.get("file_count", 0),
            "data_issues": data_audit.get("issue_count", 0),
            "research_records": len(research.get("records", [])),
            "infrastructure_experiments": len(all_results) - len(results),
        },
        "experiments": experiments,
        "data_audit": data_audit,
        "next_actions": next_actions.get("actions", []),
        "proposals": next_actions.get("proposals", []),
        "workflow": workflow_state(workspace),
        "capabilities": {"runners": supported_runners()},
        "recent_events": ledger.recent_events(),
    }
