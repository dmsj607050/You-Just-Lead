"""Command-line interface for the first-phase experiment workflow."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from agents.data_agent import audit_dataset
from agents.reproduction_agent import intake_repository, run_isolated_smoke_test
from agents.research_agent import build_research_query, search_research
from agents.rules_agent import (
    analyze_rules,
    apply_official_rule_evidence,
    approve_rule_specification,
    rule_confirmation_readiness_for_workspace,
)
from agents.strategy_agent import recommend_next_actions
from app.api_server import serve as serve_api
from app.approval_service import approve_training_config
from app.orchestrator.workflow import workflow_state
from app.experiment_service import ExperimentService, ensure_workspace_layout
from app.project_registry import current_workspace
from app.release_service import build_release_manifest, write_release_manifest
from app.reporting import generate_reports
from database.ledger import ledger_for_workspace
from paper.generator import generate_paper_package
from tools.configuration import load_yaml
from tools.device_repo import device_repo_root
from tools.submission import validate_submission
from training.catalog import supported_runners


PROJECT_ROOT = Path(__file__).resolve().parent


def _workspace(value: str | None) -> Path:
    """--workspace 优先；没给就用注册表里的当前项目，与 App 进的是同一个工作区。"""
    return Path(value).resolve() if value else current_workspace(PROJECT_ROOT)


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

    approve_run_parser = subparsers.add_parser(
        "approve-run", help="Record human approval for one exact GPU training configuration"
    )
    approve_run_parser.add_argument(
        "--config",
        required=True,
        help="Configuration path relative to the workspace",
    )
    approve_run_parser.add_argument("--note", required=True, help="Human budget and scope review note")
    approve_run_parser.add_argument("--workspace", help="Workspace path")

    report_parser = subparsers.add_parser("report", help="Regenerate Markdown summaries")
    report_parser.add_argument("--workspace", help="Workspace path")

    status_parser = subparsers.add_parser("status", help="Print SQLite experiment summaries")
    status_parser.add_argument("--workspace", help="Workspace path")

    rules_parser = subparsers.add_parser(
        "rules", help="Extract an auditable draft specification from local official rules"
    )
    rules_parser.add_argument(
        "--source",
        required=True,
        help="Rule document path, relative to the workspace unless absolute",
    )
    rules_parser.add_argument("--workspace", help="Workspace path")

    approve_rules_parser = subparsers.add_parser(
        "approve-rules", help="Record a human review after all rule questions are resolved"
    )
    approve_rules_parser.add_argument("--note", required=True, help="Short human review note")
    approve_rules_parser.add_argument("--workspace", help="Workspace path")

    readiness_parser = subparsers.add_parser(
        "rules-readiness", help="List the evidence and rule fields required before approval"
    )
    readiness_parser.add_argument("--workspace", help="Workspace path")

    evidence_parser = subparsers.add_parser(
        "record-rule-evidence", help="Apply a complete, reviewed Xunfei official-rule evidence record"
    )
    evidence_parser.add_argument(
        "--file", required=True, help="YAML evidence record relative to the workspace unless absolute"
    )
    evidence_parser.add_argument("--workspace", help="Workspace path")

    audit_parser = subparsers.add_parser(
        "audit-data", help="Profile raw competition data without modifying it"
    )
    audit_parser.add_argument(
        "--data-dir",
        default="data/raw",
        help="Data directory relative to the workspace",
    )
    audit_parser.add_argument("--workspace", help="Workspace path")

    research_parser = subparsers.add_parser(
        "research", help="Search public paper and code providers and persist a research radar"
    )
    research_parser.add_argument(
        "--query", help="Task or method query; omit it to build the query from the competition spec"
    )
    research_parser.add_argument("--limit", default=5, type=int, help="Results per provider (1-25)")
    research_parser.add_argument(
        "--sources",
        default="arxiv,openalex,semantic_scholar,github",
        help="Comma-separated providers: arxiv,openalex,semantic_scholar,github",
    )
    research_parser.add_argument("--workspace", help="Workspace path")

    reproduce_parser = subparsers.add_parser(
        "reproduce", help="Create a safe third-party repository intake record"
    )
    reproduce_parser.add_argument("--repository", required=True, help="Explicit HTTPS .git or git@github.com URL")
    reproduce_parser.add_argument("--commit", help="Optional commit hash to pin")
    reproduce_parser.add_argument(
        "--approved",
        action="store_true",
        help="Confirms human approval to clone for static inspection only",
    )
    reproduce_parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run one explicit command in an approved network-isolated Docker container",
    )
    reproduce_parser.add_argument("--image", help="Container image required with --smoke-test")
    reproduce_parser.add_argument(
        "--command", dest="smoke_command", help="Explicit command required with --smoke-test"
    )
    reproduce_parser.add_argument("--cpu-limit", default="2", help="Docker CPU limit for smoke test")
    reproduce_parser.add_argument("--memory-limit", default="8g", help="Docker memory limit for smoke test")
    reproduce_parser.add_argument("--workspace", help="Workspace path")

    plan_parser = subparsers.add_parser(
        "plan", help="Generate a rule-aware, evidence-backed next-action queue"
    )
    plan_parser.add_argument("--workspace", help="Workspace path")

    paper_parser = subparsers.add_parser(
        "paper", help="Generate a TeX report and evidence map from persisted records"
    )
    paper_parser.add_argument("--workspace", help="Workspace path")
    paper_parser.add_argument("--output-dir", help="Optional destination for generated TeX artefacts")

    serve_parser = subparsers.add_parser("serve", help="Serve the local dashboard API on loopback")
    serve_parser.add_argument("--workspace", help="Workspace path")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host; loopback is recommended")
    serve_parser.add_argument("--port", default=8765, type=int, help="Bind port")

    workflow_parser = subparsers.add_parser(
        "workflow", help="Show the central evidence-derived workflow stage and gates"
    )
    workflow_parser.add_argument("--workspace", help="Workspace path")

    submission_parser = subparsers.add_parser(
        "validate-submission", help="Validate a local candidate without uploading it"
    )
    submission_parser.add_argument("--path", required=True, help="Candidate path relative to the workspace unless absolute")
    submission_parser.add_argument("--workspace", help="Workspace path")

    capability_parser = subparsers.add_parser(
        "capabilities", help="List built-in task adapters and their data contracts"
    )
    capability_parser.add_argument("--workspace", help="Workspace path")

    release_parser = subparsers.add_parser(
        "release-manifest", help="Write release/release_manifest.json describing this version"
    )
    release_parser.add_argument("--device-repo", help="Path to the HarmonyOS repository (auto-detected by default)")
    release_parser.add_argument(
        "--print", dest="print_only", action="store_true", help="Print the manifest without writing it"
    )
    return parser


def main() -> int:
    args = _parser().parse_args()

    if args.command == "serve":
        # 起服务不需要先有工作区：项目由注册表决定，一个项目都没选时也能启动，
        # App 会停在项目选择页。传了 --workspace 才固定到那一个工作区。
        serve_api(args.host, args.port, Path(args.workspace).resolve() if args.workspace else None)
        return 0

    if args.command == "release-manifest":
        # 描述的是"这次构建/这个版本"，不是某个项目，所以也不需要先有工作区。
        device_root = Path(args.device_repo).resolve() if args.device_repo else device_repo_root(PROJECT_ROOT)
        manifest = build_release_manifest(PROJECT_ROOT, device_root=device_root)
        if not args.print_only:
            write_release_manifest(PROJECT_ROOT, manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0 if manifest["release_ready"] else 1

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

    if args.command == "approve-run":
        config_path = _config_path(workspace, args.config)
        outcome = approve_training_config(workspace, config_path, args.note)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "training_config_approved", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "report":
        config_path = workspace / "configs" / "baseline_synthetic.yaml"
        direction = (
            load_yaml(config_path).get("validation", {}).get("direction", "maximize")
            if config_path.exists()
            else "maximize"
        )
        print(json.dumps(generate_reports(workspace, str(direction)), ensure_ascii=False))
        return 0

    if args.command == "rules":
        source_path = _config_path(workspace, args.source)
        outcome = analyze_rules(source_path, workspace)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "rules_analyzed", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "audit-data":
        data_dir = _config_path(workspace, args.data_dir)
        outcome = audit_dataset(workspace, data_dir)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "data_audited", {"data_dir": str(data_dir), "file_count": outcome["file_count"], "issue_count": outcome["issue_count"]}
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "approve-rules":
        outcome = approve_rule_specification(workspace, args.note)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "rules_approved", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rules-readiness":
        outcome = rule_confirmation_readiness_for_workspace(workspace)
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0 if outcome["ready"] else 1

    if args.command == "record-rule-evidence":
        evidence_path = _config_path(workspace, args.file)
        outcome = apply_official_rule_evidence(workspace, evidence_path)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "official_rule_evidence_recorded", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "research":
        sources = [item.strip() for item in args.sources.split(",") if item.strip()]
        # 不给 --query 就按规则规格拼一条：这是「按规则自动检索」的命令行入口。
        spec_path = workspace / "competition_spec.yaml"
        spec = load_yaml(spec_path) if spec_path.exists() else {}
        query = (args.query or "").strip() or build_research_query(spec)
        if not query:
            print("error: pass --query, or import a competition spec that names a task type and modalities")
            return 2
        outcome = search_research(workspace, query, limit=args.limit, sources=sources, spec=spec)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "research_searched", {**outcome, "from_spec": not (args.query or "").strip()}
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "reproduce":
        outcome = (
            run_isolated_smoke_test(
                workspace,
                args.repository,
                approved=args.approved,
                image=args.image or "",
                command=args.smoke_command or "",
                cpu_limit=args.cpu_limit,
                memory_limit=args.memory_limit,
            )
            if args.smoke_test
            else intake_repository(
                workspace,
                args.repository,
                approved=args.approved,
                commit=args.commit,
            )
        )
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "repository_intake", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "plan":
        outcome = recommend_next_actions(workspace)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "decision_plan_generated", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "paper":
        output_dir = Path(args.output_dir).resolve() if args.output_dir else None
        outcome = generate_paper_package(workspace, output_dir)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "paper_package_generated", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "workflow":
        print(json.dumps(workflow_state(workspace), ensure_ascii=False, indent=2))
        return 0

    if args.command == "validate-submission":
        candidate = _config_path(workspace, args.path)
        outcome = validate_submission(workspace, candidate)
        ledger_for_workspace(PROJECT_ROOT, workspace).record_event(
            "submission_validated", outcome
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        return 0

    if args.command == "capabilities":
        print(json.dumps({"runners": supported_runners()}, ensure_ascii=False, indent=2))
        return 0

    ledger = ledger_for_workspace(PROJECT_ROOT, workspace)
    print(json.dumps(ledger.summaries(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
