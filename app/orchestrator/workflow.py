"""Derive a safe workflow stage from persisted evidence, without auto-execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.strategy_agent import recommend_next_actions
from tools.configuration import load_yaml
from tools.files import read_json


def workflow_state(workspace: Path) -> dict[str, Any]:
    """Return the central coordinator's evidence-backed state and gates."""
    spec_path = workspace / "competition_spec.yaml"
    audit_path = workspace / "reports" / "data_statistics.json"
    research_path = workspace / "research" / "papers.json"
    result_paths = sorted((workspace / "experiments" / "results").glob("EXP-*.json"))
    approval_paths = sorted((workspace / "experiments" / "approvals").glob("*.json"))
    components = {
        "rules": "missing",
        "data_audit": "complete" if audit_path.exists() else "missing",
        "research": "complete" if research_path.exists() else "not_started",
        "baseline": "complete" if result_paths else "not_started",
        "approvals": "recorded" if approval_paths else "none",
    }
    blockers: list[str] = []
    if not spec_path.exists():
        stage = "rules_capture"
        blockers.append("No competition_spec.yaml exists.")
    else:
        spec = load_yaml(spec_path)
        if spec.get("approval", {}).get("requires_human_confirmation", True):
            stage = "rules_review"
            components["rules"] = "awaiting_human_confirmation"
            blockers.extend(spec.get("approval", {}).get("unresolved_questions", []) or ["Official rules require human confirmation."])
        elif not audit_path.exists():
            stage = "data_audit"
            components["rules"] = "approved"
            blockers.append("Raw data has not been audited.")
        elif not result_paths:
            stage = "baseline_design"
            components["rules"] = "approved"
            blockers.append("No completed baseline experiment exists.")
        else:
            stage = "evidence_led_iteration"
            components["rules"] = "approved"

    completed_results = [read_json(path) for path in result_paths if read_json(path).get("status") == "completed"]
    return {
        "stage": stage,
        "automatic_execution": False,
        "components": components,
        "blockers": blockers,
        "completed_experiments": len(completed_results),
        "recommended_actions": recommend_next_actions(workspace, persist=False).get("actions", []),
    }
