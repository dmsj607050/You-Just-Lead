"""Command-line interface for the first-phase experiment workflow."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from app.experiment_service import ExperimentService, ensure_workspace_layout
from app.reporting import generate_reports
from database.ledger import ExperimentLedger
from tools.configuration import load_yaml


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = PROJECT_ROOT / "workspace" / "current_competition"


def _workspace(value: str | None) -> Path:
    return Path(value).resolve() if value else DEFAULT_WORKSPACE


def _config_path(workspace: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else workspace / path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Competition Agent first-phase workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create required runtime directories")
    init_parser.add_argument("--workspace", help="Workspace path")

    run_parser = subparsers.add_parser("run", help="Run a configuration and record it")
    run_parser.add_argument(
        "--config",
        default="configs/baseline_synthetic.yaml",
        help="Configuration path relative to the workspace",
    )
    run_parser.add_argument("--workspace", help="Workspace path")
    run_parser.add_argument("--experiment-id", help="Explicit EXP-xxxx identifier")
    run_parser.add_argument("--hypothesis", help="Override the config hypothesis")
    run_parser.add_argument("--parent-id", help="Parent experiment identifier")

    report_parser = subparsers.add_parser("report", help="Regenerate Markdown summaries")
    report_parser.add_argument("--workspace", help="Workspace path")

    status_parser = subparsers.add_parser("status", help="Print SQLite experiment summaries")
    status_parser.add_argument("--workspace", help="Workspace path")
    return parser


def main() -> int:
    args = _parser().parse_args()
    workspace = _workspace(getattr(args, "workspace", None))
    ensure_workspace_layout(workspace)

    if args.command == "init":
        target_spec = workspace / "competition_spec.yaml"
        template = workspace / "competition_spec.template.yaml"
        if template.exists() and not target_spec.exists():
            shutil.copy2(template, target_spec)
        print(f"Workspace ready: {workspace}")
        return 0

    if args.command == "run":
        config_path = _config_path(workspace, args.config)
        service = ExperimentService(PROJECT_ROOT, workspace)
        command = " ".join(["python", "main.py", "run", "--config", args.config])
        _, result = service.run(
            config_path,
            experiment_id=args.experiment_id,
            hypothesis=args.hypothesis,
            parent_id=args.parent_id,
            command=command,
        )
        direction = load_yaml(config_path).get("validation", {}).get("direction", "maximize")
        generate_reports(workspace, str(direction))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 1

    if args.command == "report":
        config_path = workspace / "configs" / "baseline_synthetic.yaml"
        direction = (
            load_yaml(config_path).get("validation", {}).get("direction", "maximize")
            if config_path.exists()
            else "maximize"
        )
        print(json.dumps(generate_reports(workspace, str(direction)), ensure_ascii=False))
        return 0

    ledger = ExperimentLedger(PROJECT_ROOT / "database" / "competition_agent.sqlite")
    print(json.dumps(ledger.summaries(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
