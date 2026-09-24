"""Tool layer exposed to the local DeepSeek Agent runtime.

Every tool here is either read-only or a low-risk draft creator. None of them
can start training, upload submissions, delete artefacts, or download third-party
code. High-risk operations still require an explicit human CLI action.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agents.rules_agent import rule_confirmation_readiness_for_workspace
from agents.strategy_agent import recommend_next_actions
from app.orchestrator.workflow import workflow_state
from database.ledger import ExperimentLedger
from tools.configuration import load_yaml
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now
from training.catalog import supported_runners


JSON_SCHEMA_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _records(directory: Path, pattern: str = "EXP-*.json") -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    return sorted(
        (read_json(path) for path in directory.glob(pattern)),
        key=lambda item: str(item.get("experiment_id", "")),
    )


def _history_for(result: dict[str, Any]) -> list[dict[str, float]]:
    for value in result.get("artifact_paths", []):
        path = Path(str(value))
        if path.name == "history.json" and path.exists():
            try:
                return read_json(path).get("history", [])
            except (ValueError, OSError):
                return []
    return []


def _list_experiments(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    results = _records(workspace / "experiments" / "results")
    manifests = {item["experiment_id"]: item for item in _records(workspace / "experiments" / "manifests")}
    experiments = []
    for result in reversed(results):
        manifest = manifests.get(result["experiment_id"], {})
        experiments.append({
            "experiment_id": result["experiment_id"],
            "status": result.get("status"),
            "validation_metric": result.get("validation_metric"),
            "hypothesis": manifest.get("hypothesis"),
            "change_type": manifest.get("change_type"),
            "decision": result.get("decision"),
        })
    return {"experiments": experiments, "total": len(experiments)}


def _get_experiment(project_root: Path, workspace: Path, *, experiment_id: str, **_: Any) -> dict[str, Any]:
    if not experiment_id or not isinstance(experiment_id, str):
        return {"error": "experiment_id is required"}
    results = _records(workspace / "experiments" / "results")
    manifests = {item["experiment_id"]: item for item in _records(workspace / "experiments" / "manifests")}
    for result in results:
        if result.get("experiment_id") == experiment_id:
            manifest = manifests.get(experiment_id, {})
            return {
                "experiment_id": experiment_id,
                "status": result.get("status"),
                "validation_metric": result.get("validation_metric"),
                "best_epoch": result.get("best_epoch"),
                "runtime_seconds": result.get("runtime_seconds"),
                "hypothesis": manifest.get("hypothesis"),
                "change_type": manifest.get("change_type"),
                "decision": result.get("decision"),
                "diagnosis": result.get("diagnosis", {}),
                "error_analysis": result.get("error_analysis", {}),
                "history": _history_for(result),
                "manifest": manifest,
            }
    return {"error": f"Experiment {experiment_id} not found"}


def _get_workflow_state(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    return workflow_state(workspace)


def _get_rule_readiness(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    return rule_confirmation_readiness_for_workspace(workspace)


def _get_data_audit(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    path = workspace / "reports" / "data_statistics.json"
    if not path.exists():
        return {"error": "Data audit has not been run. Execute `python main.py audit-data` first."}
    return read_json(path)


def _get_next_actions(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    outcome = recommend_next_actions(workspace, persist=False)
    return {"actions": outcome.get("actions", []), "proposals": outcome.get("proposals", [])}


def _get_capabilities(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    return {"runners": supported_runners()}


def _get_competition_spec(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    path = workspace / "competition_spec.yaml"
    if not path.exists():
        return {"error": "competition_spec.yaml is missing. Run `python main.py init` first."}
    return load_yaml(path)


def _get_best_run(project_root: Path, workspace: Path, **_: Any) -> dict[str, Any]:
    spec = load_yaml(workspace / "competition_spec.yaml") if (workspace / "competition_spec.yaml").exists() else {}
    direction = spec.get("evaluation", {}).get("direction", "maximize")
    results = _records(workspace / "experiments" / "results")
    completed = [item for item in results if item.get("status") == "completed" and item.get("validation_metric") is not None]
    if not completed:
        return {"error": "No completed experiment with a validation metric yet."}
    best = (max if direction == "maximize" else min)(completed, key=lambda item: float(item["validation_metric"]))
    return {
        "experiment_id": best.get("experiment_id"),
        "validation_metric": best.get("validation_metric"),
        "direction": direction,
        "best_epoch": best.get("best_epoch"),
        "history": _history_for(best),
    }


def _get_recent_events(project_root: Path, workspace: Path, *, limit: int = 10, **_: Any) -> dict[str, Any]:
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10
    ledger = ExperimentLedger(project_root / "database" / "competition_agent.sqlite")
    events = ledger.recent_events()
    return {"events": events[:limit], "total": len(events)}


def _create_experiment_draft(
    project_root: Path,
    workspace: Path,
    *,
    hypothesis: str,
    parent_experiment_id: str | None = None,
    config_path: str | None = None,
    estimated_gpu_hours: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    if not isinstance(hypothesis, str) or not (8 <= len(hypothesis.strip()) <= 1000):
        return {"error": "hypothesis must contain 8 to 1000 characters"}
    drafts_dir = workspace / "experiments" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    existing = [path.stem for path in drafts_dir.glob("DRAFT-*.json")]
    numbers = [int(item.split("-", 1)[1]) for item in existing if item.split("-", 1)[1].isdigit()]
    draft_id = f"DRAFT-{max(numbers, default=0) + 1:04d}"
    draft = {
        "draft_id": draft_id,
        "created_at": utc_now(),
        "status": "awaiting_human_approval",
        "hypothesis": hypothesis.strip(),
        "parent_experiment_id": parent_experiment_id,
        "config_path": config_path,
        "estimated_gpu_hours": estimated_gpu_hours,
        "safety_note": "Draft creation does not schedule training. Execute `python main.py approve-run` and `python main.py run` manually to start.",
    }
    write_json_atomic(drafts_dir / f"{draft_id}.json", draft)
    ledger = ExperimentLedger(project_root / "database" / "competition_agent.sqlite")
    ledger.record_event("experiment_draft_created", draft)
    return draft


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_experiments",
            "description": "List all experiments recorded in the current competition workspace, newest first. Returns experiment_id, status, validation_metric, hypothesis, change_type and decision for each.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_experiment",
            "description": "Get full details of a single experiment by its ID, including history curves, diagnosis, error analysis and the original manifest.",
            "parameters": {
                "type": "object",
                "properties": {"experiment_id": {"type": "string", "description": "Experiment identifier like EXP-0001"}},
                "required": ["experiment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_workflow_state",
            "description": "Return the current workflow stage (rules_capture, rules_review, data_audit, baseline_design, evidence_led_iteration), its blockers, component readiness and recommended next actions. This is the single source of truth for where the project stands.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rule_readiness",
            "description": "Return the rule confirmation checklist: which rule fields are filled, which gaps remain, and whether the competition spec is ready for human approval.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_data_audit",
            "description": "Return the most recent raw data audit report: file count, sizes, label distribution, duplicate risks and issues. Returns an error if audit-data has not been run yet.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_next_actions",
            "description": "Return the evidence-backed next action queue and at most three experiment proposals (with parent, evidence, cost/risk score and approval requirements). Priority is for sorting only; nothing is auto-started.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_capabilities",
            "description": "List built-in task adapters and their data contracts. Use this to confirm which task types the workspace can already run end-to-end.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_competition_spec",
            "description": "Return the current competition_spec.yaml content: competition name, task_type, evaluation metric, direction and approval flags.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_best_run",
            "description": "Return the best completed experiment so far, including its validation metric, best epoch and training history curve. Returns an error if no completed experiment exists yet.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_events",
            "description": "Return the most recent ledger events (training runs, approvals, rule reviews, research searches, etc.) for auditing what has happened in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Number of events to return, 1-50. Defaults to 10."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_experiment_draft",
            "description": "Create a new experiment draft capturing a hypothesis, optional parent experiment, config path and GPU budget estimate. The draft is persisted as awaiting_human_approval and does NOT start any training. A human must still run `python main.py approve-run` and `python main.py run` to execute it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hypothesis": {"type": "string", "description": "A clear, falsifiable hypothesis statement, 8-1000 characters."},
                    "parent_experiment_id": {"type": "string", "description": "Optional parent experiment ID, e.g. EXP-0001. Omit for a baseline."},
                    "config_path": {"type": "string", "description": "Optional config path relative to the workspace, e.g. configs/tabular_baseline.yaml."},
                    "estimated_gpu_hours": {"type": "number", "description": "Optional estimated GPU hours this experiment would consume if approved."},
                },
                "required": ["hypothesis"],
            },
        },
    },
]


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "list_experiments": _list_experiments,
    "get_experiment": _get_experiment,
    "get_workflow_state": _get_workflow_state,
    "get_rule_readiness": _get_rule_readiness,
    "get_data_audit": _get_data_audit,
    "get_next_actions": _get_next_actions,
    "get_capabilities": _get_capabilities,
    "get_competition_spec": _get_competition_spec,
    "get_best_run": _get_best_run,
    "get_recent_events": _get_recent_events,
    "create_experiment_draft": _create_experiment_draft,
}


def agent_tools_schema() -> list[dict[str, Any]]:
    """Return the OpenAI-compatible tool schema list sent to DeepSeek."""
    return TOOL_DEFINITIONS


def execute_tool(project_root: Path, workspace: Path, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a registered tool by name. Returns an error dict for unknown tools or handler failures."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return handler(project_root, workspace, **arguments)
    except TypeError as exc:
        return {"error": f"Invalid arguments for {name}: {exc}"}
    except (ValueError, OSError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def available_tool_names() -> list[str]:
    """Return the names of tools the Agent is allowed to call. Useful for safety assertions in tests."""
    return list(TOOL_HANDLERS.keys())
