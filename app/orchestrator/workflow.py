"""Derive a safe workflow stage from persisted evidence, without auto-execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.rules_agent import rule_confirmation_readiness
from agents.strategy_agent import recommend_next_actions
from tools.experiment_scope import current_competition_results
from training.catalog import recommend_runner, supported_runners
from tools.configuration import load_yaml
from tools.files import read_json


def _runner_by_name(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    for capability in supported_runners():
        if capability.get("runner") == name:
            return capability
    return None


def workflow_state(workspace: Path) -> dict[str, Any]:
    """Return the central coordinator's evidence-backed state and gates."""
    spec_path = workspace / "competition_spec.yaml"
    audit_path = workspace / "reports" / "data_statistics.json"
    research_path = workspace / "research" / "papers.json"
    scoped_results = current_competition_results(workspace)
    approval_paths = sorted((workspace / "experiments" / "approvals").glob("*.json"))
    components = {
        "rules": "missing",
        "data_audit": "complete" if audit_path.exists() else "missing",
        "research": "complete" if research_path.exists() else "not_started",
        "baseline": "complete" if any(item.get("status") == "completed" for item in scoped_results) else "not_started",
        "approvals": "recorded" if approval_paths else "none",
    }
    blockers: list[str] = []
    if not spec_path.exists():
        stage = "rules_capture"
        blockers.append("No competition_spec.yaml exists.")
    else:
        spec = load_yaml(spec_path)
        competition = spec.get("competition", {})
        readiness = rule_confirmation_readiness(spec)
        suggested_runner = _runner_by_name(competition.get("preferred_runner")) or recommend_runner(
            competition.get("task_type")
        )
        if spec.get("approval", {}).get("requires_human_confirmation", True) or not readiness["ready"]:
            stage = "rules_review"
            components["rules"] = "awaiting_human_confirmation"
            blockers.extend(spec.get("approval", {}).get("unresolved_questions", []) or ["Official rules require human confirmation."])
            blockers.extend(
                f"Rule evidence missing: {item['field']}" for item in readiness["gaps"][:5]
            )
        elif not audit_path.exists():
            stage = "data_audit"
            components["rules"] = "approved"
            blockers.append("Raw data has not been audited.")
        elif not any(item.get("status") == "completed" for item in scoped_results):
            stage = "baseline_design"
            components["rules"] = "approved"
            blockers.append("No completed baseline experiment exists.")
        else:
            stage = "evidence_led_iteration"
            components["rules"] = "approved"

        if suggested_runner is None and competition.get("task_type"):
            blockers.append("No built-in adapter matches the confirmed task type; add or select a task-specific adapter.")

    completed_results = [item for item in scoped_results if item.get("status") == "completed"]
    return {
        "stage": stage,
        "automatic_execution": False,
        "components": components,
        "blockers": blockers,
        "completed_experiments": len(completed_results),
        "recommended_runner": suggested_runner if spec_path.exists() else None,
        "available_runners": supported_runners(),
        "recommended_actions": recommend_next_actions(workspace, persist=False).get("actions", []),
    }
