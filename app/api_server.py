"""Minimal local REST API for the competition workspace.

The API binds to loopback by default and checks the desktop Origin allowlist.
When it is deliberately bound to a local-network address, mobile clients such
as a HarmonyOS app authenticate sensitive endpoints with a shared token instead.
The API exposes persisted state and creates drafts. Explicitly selected public
research materials may be downloaded for static inspection; third-party code is
never executed by that workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents.rules_agent import (
    RuleImportError,
    apply_official_rule_evidence,
    approve_rule_specification,
    build_rule_evidence_record,
    import_rule_source,
    rule_confirmation_readiness_for_workspace,
    rule_evidence_form_for_workspace,
)
from agents.research_agent import search_research
from agents.materials_agent import MaterialIntakeError
from app.data_audit_scheduler import DataAuditScheduler, DataAuditSchedulerError
from app.dashboard_service import dashboard_snapshot
from app.deepseek_service import DeepSeekError, run_agent, verify_connection
from app.runtime_service import local_runtime_snapshot
from app.runtime_probe_service import RuntimeProbeError, latest_runtime_probe, probe_runtime
from app.settings_service import SettingsError, configure_deepseek, deepseek_settings_status
from app.trace_service import paper_package_report, trace_snapshot
from app.training_scaffold_service import TrainingScaffoldError, build_training_scaffold, latest_training_scaffold
from app.material_scheduler import MaterialScheduler, MaterialSchedulerError
from app.project_registry import (
    ProjectError,
    ProjectNotSelected,
    create_project,
    current_project,
    current_workspace,
    delete_project,
    find_project,
    list_projects,
    select_project,
    workspace_path,
)
from app.training_scheduler import SchedulerError, TrainingScheduler
from database.ledger import ledger_for_workspace
from tools.files import read_json, write_json_atomic
from tools.configuration import load_yaml, write_yaml
from tools.provenance import utc_now
from training.catalog import supported_runners


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "http://127.0.0.1:1420", "http://localhost:1420"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ACCESS_TOKEN_HEADER = "X-YJL-Token"
MAX_REQUEST_BODY_BYTES = 17 * 1024 * 1024
SENSITIVE_LOCAL_ENDPOINTS = {
    "/api/settings/deepseek",
    "/api/rules/import",
    "/api/rules/approve",
    "/api/rules/evidence",
    "/api/research/search",
    "/api/materials/intake",
    "/api/data-audit/run",
    "/api/build/scaffold",
    "/api/runtime/probe",
    "/api/settings/deepseek/test",
    "/api/agent/deepseek",
    "/api/experiments/execute",
    "/api/decisions/approve",
}


def allowed_origins() -> set[str]:
    """Return the desktop allowlist plus any additionally configured clients.

    A HarmonyOS Web component or another local front end is admitted by listing
    its exact Origin in the comma-separated ``YJL_ALLOWED_ORIGINS`` variable.
    """
    configured = os.environ.get("YJL_ALLOWED_ORIGINS", "")
    return DESKTOP_ORIGINS | {item.strip() for item in configured.split(",") if item.strip()}


def reachable_addresses(port: int) -> list[str]:
    """Best-effort list of URLs other devices can use for a non-loopback bind."""
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            addresses.add(str(info[4][0]))
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            addresses.add(str(probe.getsockname()[0]))
        finally:
            probe.close()
    except OSError:
        pass
    return [f"http://{address}:{port}" for address in sorted(addresses) if not address.startswith("127.")]


def _draft_id(workspace: Path) -> str:
    existing = [path.stem for path in (workspace / "experiments" / "drafts").glob("DRAFT-*.json")]
    numbers = [int(item.split("-", 1)[1]) for item in existing if item.split("-", 1)[1].isdigit()]
    return f"DRAFT-{max(numbers, default=0) + 1:04d}"


def _draft_list(workspace: Path) -> list[dict[str, Any]]:
    """List experiment drafts, newest first.

    A draft is only a recorded hypothesis: it never schedules training, so this
    endpoint stays read-only.
    """
    drafts_dir = workspace / "experiments" / "drafts"
    if not drafts_dir.exists():
        return []
    records = [read_json(path) for path in drafts_dir.glob("DRAFT-*.json")]
    return sorted(
        (item for item in records if isinstance(item, dict)),
        key=lambda item: str(item.get("draft_id", "")),
        reverse=True,
    )


def _rule_report(workspace: Path) -> dict[str, Any]:
    spec_path = workspace / "competition_spec.yaml"
    report_path = workspace / "docs" / "competition_rules.md"
    extraction_path = workspace / "reports" / "rule_extraction.json"
    return {
        "spec": load_yaml(spec_path) if spec_path.exists() else {},
        "readiness": rule_confirmation_readiness_for_workspace(workspace),
        "report_markdown": report_path.read_text(encoding="utf-8") if report_path.exists() else "",
        "analysis": read_json(extraction_path) if extraction_path.exists() else None,
    }
def _research_report(workspace: Path) -> dict[str, Any]:
    research_dir = workspace / "research"
    papers_path = research_dir / "papers.json"
    radar_path = research_dir / "research_radar.md"
    payload = read_json(papers_path) if papers_path.exists() else {
        "query": None,
        "searched_at": None,
        "sources": [],
        "records": [],
        "provider_failures": {},
    }
    if not isinstance(payload, dict):
        payload = {"query": None, "records": [], "provider_failures": {}}
    payload["report_markdown"] = radar_path.read_text(encoding="utf-8") if radar_path.exists() else ""
    return payload


def _apply_rule_evidence(workspace: Path, body: dict[str, Any]) -> dict[str, Any]:
    """把界面提交的官方证据落成一份记录文件，再交给 rules_agent 应用。

    先写文件再应用：apply 会把文件路径与 sha256 写进规格，证据链才落到具体的文件上。
    应用失败（值类型或取值域不对）时删掉刚写的文件，不留半成品。
    """
    fields = body.get("fields")
    if not isinstance(fields, list):
        raise ValueError("fields must be a list of {field, anchor} objects")
    overrides: dict[str, Any] = {}
    for item in fields:
        if not isinstance(item, dict) or not str(item.get("field") or "").strip():
            raise ValueError("each field entry needs a field name")
        overrides[str(item["field"]).strip()] = item

    spec_path = workspace / "competition_spec.yaml"
    if not spec_path.exists():
        raise FileNotFoundError("competition_spec.yaml is required before applying rule evidence")
    record = build_rule_evidence_record(
        spec=load_yaml(spec_path),
        source={
            "source_type": str(body.get("source_type") or "").strip(),
            "source_locator": str(body.get("source_locator") or "").strip(),
            "reviewed_at": str(body.get("reviewed_at") or "").strip(),
        },
        overrides=overrides,
    )

    stamp = utc_now().replace("-", "").replace(":", "").replace("+00:00", "Z")
    evidence_path = workspace / "docs" / f"rule_evidence_{stamp}_{secrets.token_hex(2)}.yaml"
    write_yaml(evidence_path, record)
    try:
        return apply_official_rule_evidence(workspace, evidence_path)
    except Exception:
        evidence_path.unlink(missing_ok=True)
        raise


def _workspace_display(project_root: Path) -> str:
    """当前项目的工作区路径。一个项目都没选时返回空串：健康检查仍应是 ok。"""
    project = current_project(project_root)
    if project is None:
        return ""
    return str(workspace_path(project_root, str(project["id"])))


_SCHEDULER_CACHE: dict[str, tuple[TrainingScheduler, MaterialScheduler, DataAuditScheduler]] = {}
_SCHEDULER_LOCK = threading.Lock()


def schedulers_for(
    project_root: Path, workspace: Path
) -> tuple[TrainingScheduler, MaterialScheduler, DataAuditScheduler]:
    """按工作区取一份调度器。

    三个调度器的队列都落在各自的工作区里，所以换项目就必须换实例；同一进程内同一个
    工作区复用同一份，避免每次请求重建（重建会丢掉内存里的活动任务句柄）。
    """
    key = str(workspace.resolve())
    with _SCHEDULER_LOCK:
        cached = _SCHEDULER_CACHE.get(key)
        if cached is None:
            root = project_root.resolve()
            cached = (
                TrainingScheduler(root, workspace.resolve()),
                MaterialScheduler(root, workspace.resolve()),
                DataAuditScheduler(root, workspace.resolve()),
            )
            _SCHEDULER_CACHE[key] = cached
        return cached


def forget_schedulers(workspace: Path) -> None:
    """工作区被删掉后丢弃它的调度器缓存。"""
    with _SCHEDULER_LOCK:
        _SCHEDULER_CACHE.pop(str(workspace.resolve()), None)


class CompetitionApiHandler(BaseHTTPRequestHandler):
    """本地 REST 接口。

    工作区与调度器都按「当前项目」在请求内解析，因此 App 切完项目，之后的请求就作用在
    新工作区上，不必重启后端。把 `workspace`/`scheduler` 这些名字显式塞进子类即固定住
    它们（命令行 `--workspace` 与测试都走这条注入路径）。
    """

    project_root: Path
    access_token: str = ""
    require_token: bool = False

    @property
    def workspace(self) -> Path:
        return current_workspace(self.project_root)

    @property
    def scheduler(self) -> TrainingScheduler:
        return schedulers_for(self.project_root, self.workspace)[0]

    @property
    def material_scheduler(self) -> MaterialScheduler:
        return schedulers_for(self.project_root, self.workspace)[1]

    @property
    def data_audit_scheduler(self) -> DataAuditScheduler:
        return schedulers_for(self.project_root, self.workspace)[2]

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {ACCESS_TOKEN_HEADER}")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._send(status, {"error": message})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_REQUEST_BODY_BYTES:
            raise ValueError("Request body is too large")
        value = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _project_state(self) -> dict[str, Any]:
        """项目列表 + 当前项目 id。App 的启动页就读这一个接口。"""
        projects = list_projects(self.project_root)
        current = next((str(project["id"]) for project in projects if project.get("current")), None)
        return {"projects": projects, "current": current}

    def _authorised_local_client(self) -> bool:
        """Gate endpoints that can spend a local API key or start real work.

        A loopback-only server trusts the desktop Origin allowlist. Once the
        server is reachable from the local network it requires a shared token
        instead, because native mobile HTTP clients send no ``Origin`` header
        and would otherwise pass the allowlist check.
        """
        if self.require_token:
            supplied = self.headers.get(ACCESS_TOKEN_HEADER, "")
            return bool(self.access_token) and secrets.compare_digest(supplied, self.access_token)
        origin = self.headers.get("Origin")
        return origin is None or origin in allowed_origins()

    def do_OPTIONS(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if path in SENSITIVE_LOCAL_ENDPOINTS and not self._authorised_local_client():
            self._error(HTTPStatus.FORBIDDEN, "This endpoint requires a trusted local client")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {ACCESS_TOKEN_HEADER}")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path == "/health":
                self._send(HTTPStatus.OK, {"status": "ok", "workspace": _workspace_display(self.project_root)})
            elif path == "/api/projects":
                self._send(HTTPStatus.OK, self._project_state())
            elif path == "/api/experiments/jobs":
                self._send(HTTPStatus.OK, {"jobs": self.scheduler.list_jobs(), "active": self.scheduler.active_job()})
            elif path == "/api/experiments/jobs/active":
                self._send(HTTPStatus.OK, self.scheduler.active_job() or {"status": "idle"})
            elif path == "/api/experiments/drafts":
                self._send(HTTPStatus.OK, {"drafts": _draft_list(self.workspace)})
            elif path.startswith("/api/experiments/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                job = self.scheduler.job_status(job_id)
                self._send(HTTPStatus.OK, job) if job else self._error(HTTPStatus.NOT_FOUND, "Job not found")
            elif path == "/api/data-audit/jobs":
                self._send(HTTPStatus.OK, {"jobs": self.data_audit_scheduler.list_jobs(), "active": self.data_audit_scheduler.active_job()})
            elif path == "/api/data-audit/jobs/active":
                self._send(HTTPStatus.OK, self.data_audit_scheduler.active_job() or {"status": "idle"})
            elif path.startswith("/api/data-audit/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                job = self.data_audit_scheduler.job_status(job_id)
                self._send(HTTPStatus.OK, job) if job else self._error(HTTPStatus.NOT_FOUND, "Data audit job not found")
            elif path == "/api/runtime/local":
                self._send(HTTPStatus.OK, local_runtime_snapshot())
            elif path == "/api/runtime/latest":
                self._send(HTTPStatus.OK, latest_runtime_probe(self.workspace) or {"status": "not_probed"})
            elif path == "/api/build/scaffold":
                self._send(HTTPStatus.OK, latest_training_scaffold(self.workspace) or {"status": "not_built"})
            elif path == "/api/settings/deepseek":
                self._send(HTTPStatus.OK, deepseek_settings_status())
            elif path == "/api/rules/report":
                self._send(HTTPStatus.OK, _rule_report(self.workspace))
            elif path == "/api/rules/evidence":
                self._send(HTTPStatus.OK, rule_evidence_form_for_workspace(self.workspace))
            elif path == "/api/paper":
                self._send(HTTPStatus.OK, paper_package_report(self.project_root, self.workspace))
            elif path == "/api/trace":
                self._send(HTTPStatus.OK, trace_snapshot(self.project_root, self.workspace))
            elif path == "/api/research":
                self._send(HTTPStatus.OK, _research_report(self.workspace))
            elif path == "/api/capabilities":
                self._send(HTTPStatus.OK, {"runners": supported_runners()})
            elif path == "/api/materials/jobs":
                self._send(
                    HTTPStatus.OK,
                    {"jobs": self.material_scheduler.list_jobs(), "active": self.material_scheduler.active_job()},
                )
            elif path == "/api/materials/jobs/active":
                self._send(HTTPStatus.OK, self.material_scheduler.active_job() or {"status": "idle"})
            elif path.startswith("/api/materials/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                job = self.material_scheduler.job_status(job_id)
                self._send(HTTPStatus.OK, job) if job else self._error(HTTPStatus.NOT_FOUND, "Material job not found")
            else:
                snapshot = dashboard_snapshot(self.project_root, self.workspace)
                if path == "/api/dashboard":
                    self._send(HTTPStatus.OK, snapshot)
                elif path == "/api/experiments":
                    self._send(HTTPStatus.OK, {"experiments": snapshot["experiments"]})
                elif path.startswith("/api/experiments/"):
                    experiment_id = path.rsplit("/", 1)[-1]
                    experiment = next((item for item in snapshot["experiments"] if item["id"] == experiment_id), None)
                    self._send(HTTPStatus.OK, experiment) if experiment else self._error(HTTPStatus.NOT_FOUND, "Experiment not found")
                elif path == "/api/rules":
                    self._send(HTTPStatus.OK, snapshot["competition"])
                elif path == "/api/rule-readiness":
                    self._send(HTTPStatus.OK, snapshot["competition"]["rule_readiness"])
                elif path == "/api/data-audit":
                    self._send(HTTPStatus.OK, snapshot["data_audit"])
                elif path == "/api/next-actions":
                    self._send(HTTPStatus.OK, {"actions": snapshot["next_actions"]})
                elif path == "/api/workflow":
                    self._send(HTTPStatus.OK, snapshot["workflow"])
                else:
                    self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except ProjectNotSelected as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except ProjectError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        try:
            if path in SENSITIVE_LOCAL_ENDPOINTS and not self._authorised_local_client():
                self._error(HTTPStatus.FORBIDDEN, "This endpoint requires a trusted local client")
                return
            body = self._body()
            if path == "/api/projects":
                # 登记在注册表里（含建立时间），并记一条属于**这个新项目自己**的事件：
                # 账本现在有 project_id 了，不会再落到别的项目的「最近更新」里。
                project = create_project(self.project_root, str(body.get("name", "")))
                ledger_for_workspace(self.project_root, self.workspace).record_event(
                    "project_created", {"project_id": project["id"], "name": project["name"]}
                )
                self._send(HTTPStatus.CREATED, dict(self._project_state(), project=project))
                return
            if path == "/api/projects/select":
                project = select_project(self.project_root, str(body.get("id", "")))
                self._send(HTTPStatus.OK, dict(self._project_state(), project=project))
                return
            ledger = ledger_for_workspace(self.project_root, self.workspace)
            if path == "/api/data-audit/run":
                requested_data_dir = body.get("data_dir")
                if requested_data_dir is not None and not isinstance(requested_data_dir, str):
                    raise ValueError("data_dir must be a local directory path")
                self._send(HTTPStatus.ACCEPTED, self.data_audit_scheduler.submit(requested_data_dir))
            elif path == "/api/build/scaffold":
                scaffold = build_training_scaffold(self.workspace)
                ledger.record_event(
                    "training_scaffold_created",
                    {
                        "build_id": scaffold["build_id"],
                        "runner": scaffold["runner"],
                        "status": scaffold["status"],
                        "config_path": scaffold["config_path"],
                    },
                )
                self._send(HTTPStatus.CREATED, scaffold)
            elif path == "/api/runtime/probe":
                probe = probe_runtime(
                    self.workspace,
                    target=str(body.get("target", "")),
                    required_vram_gb=float(body.get("required_vram_gb", 0)),
                    conda_strategy=str(body.get("conda_strategy", "")),
                    conda_environment=str(body.get("conda_environment", "")),
                    server=body.get("server") if isinstance(body.get("server"), dict) else None,
                )
                ledger.record_event(
                    "runtime_probed",
                    {
                        "probe_id": probe["probe_id"],
                        "target": probe["target"],
                        "assessment": probe["assessment"],
                    },
                )
                self._send(HTTPStatus.OK, probe)
            elif path == "/api/materials/intake":
                paper_ids = body.get("paper_ids")
                if not isinstance(paper_ids, list) or not all(isinstance(item, str) for item in paper_ids):
                    raise ValueError("paper_ids must be a list of selected research record IDs")
                self._send(HTTPStatus.ACCEPTED, self.material_scheduler.submit(paper_ids))
            elif path == "/api/research/search":
                query = str(body.get("query", "")).strip()
                if not 2 <= len(query) <= 400:
                    raise ValueError("research query must contain 2 to 400 characters")
                raw_sources = body.get("sources")
                if raw_sources is not None and (
                    not isinstance(raw_sources, list) or not all(isinstance(item, str) for item in raw_sources)
                ):
                    raise ValueError("sources must be a list of provider names")
                limit = int(body.get("limit") or 6)
                outcome = search_research(
                    self.workspace,
                    query,
                    limit=limit,
                    sources=[item.strip() for item in raw_sources if item.strip()] if raw_sources else None,
                )
                report = _research_report(self.workspace)
                ledger.record_event(
                    "research_searched",
                    {
                        "query": query,
                        "records": outcome["records"],
                        "provider_failures": outcome["provider_failures"],
                    },
                )
                self._send(HTTPStatus.OK, report)
            elif path == "/api/rules/import":
                outcome = import_rule_source(
                    self.workspace,
                    filename=str(body.get("filename", "")),
                    content_base64=str(body.get("content_base64", "")),
                    source_url=str(body.get("source_url", "")),
                )
                ledger.record_event(
                    "rules_imported",
                    {
                        "source": outcome["source"],
                        "evidence_count": outcome["analysis"]["evidence_count"],
                    },
                )
                self._send(HTTPStatus.CREATED, outcome)
            elif path == "/api/rules/approve":
                outcome = approve_rule_specification(self.workspace, str(body.get("note", "")))
                ledger.record_event("rules_approved", outcome)
                self._send(HTTPStatus.OK, outcome)
            elif path == "/api/rules/evidence":
                # 录入证据不等于批准规则：apply 之后仍需走 /api/rules/approve 这道关口。
                outcome = _apply_rule_evidence(self.workspace, body)
                ledger.record_event(
                    "rules_evidence_applied",
                    {
                        "evidence_path": outcome["evidence_path"],
                        "source_type": body.get("source_type"),
                        "source_locator": body.get("source_locator"),
                        "field_count": len(outcome["applied_fields"]),
                    },
                )
                self._send(HTTPStatus.CREATED, outcome)
            elif path == "/api/experiments/drafts":
                hypothesis = str(body.get("hypothesis", "")).strip()
                if not 8 <= len(hypothesis) <= 1000:
                    raise ValueError("hypothesis must contain 8 to 1000 characters")
                draft = {
                    "draft_id": _draft_id(self.workspace),
                    "created_at": utc_now(),
                    "status": "awaiting_human_approval",
                    "hypothesis": hypothesis,
                    "parent_experiment_id": body.get("parent_experiment_id"),
                    "config_path": body.get("config_path"),
                    "estimated_gpu_hours": body.get("estimated_gpu_hours"),
                    "safety_note": "Draft creation does not schedule training.",
                }
                write_json_atomic(self.workspace / "experiments" / "drafts" / f"{draft['draft_id']}.json", draft)
                ledger.record_event("experiment_draft_created", draft)
                self._send(HTTPStatus.CREATED, draft)
            elif path == "/api/decisions/approve":
                experiment_id = str(body.get("experiment_id", "")).strip()
                if not experiment_id:
                    raise ValueError("experiment_id is required")
                approval = {"experiment_id": experiment_id, "approved_at": utc_now(), "approved_by": str(body.get("approved_by") or "local-owner"), "scope": "approval recorded only; execution remains manual"}
                write_json_atomic(self.workspace / "experiments" / "approvals" / f"{experiment_id}.json", approval)
                ledger.record_event("experiment_approval_recorded", approval)
                self._send(HTTPStatus.CREATED, approval)
            elif path == "/api/settings/deepseek":
                status = configure_deepseek(str(body.get("api_key", "")), str(body.get("model", "")))
                ledger.record_event("deepseek_configured", {"model": status["model"], "key_source": status["key_source"]})
                self._send(HTTPStatus.OK, status)
            elif path == "/api/settings/deepseek/test":
                outcome = verify_connection()
                self._send(HTTPStatus.OK if outcome["ok"] else HTTPStatus.BAD_GATEWAY, outcome)
            elif path == "/api/agent/deepseek":
                prompt = str(body.get("prompt", "")).strip()
                stage = str(body.get("stage", "当前项目阶段")).strip()[:120]
                if not 1 <= len(prompt) <= 8_000:
                    raise ValueError("prompt must contain 1 to 8000 characters")
                max_turns = int(body.get("max_turns") or 10)
                response = run_agent(
                    prompt,
                    stage,
                    self.project_root,
                    self.workspace,
                    max_turns=max_turns,
                )
                ledger.record_event("deepseek_agent_response", {
                    "stage": stage,
                    "model": response["model"],
                    "turns": response["turns"],
                    "tool_calls": sum(
                        len(step.get("tool_calls", []))
                        for step in response.get("trace", [])
                        if step.get("type") == "tool_calls"
                    ),
                    "truncated": response.get("truncated", False),
                })
                self._send(HTTPStatus.OK, response)
            elif path == "/api/experiments/execute":
                config_value = str(body.get("config_path", "")).strip()
                if not config_value:
                    raise ValueError("config_path is required")
                config_path = Path(config_value)
                if not config_path.is_absolute():
                    config_path = self.workspace / config_path
                hypothesis = str(body.get("hypothesis", "")).strip() or None
                parent_id = str(body.get("parent_id", "")).strip() or None
                job = self.scheduler.submit(
                    config_path,
                    hypothesis=hypothesis,
                    parent_id=parent_id,
                    command=str(body.get("command", "")).strip(),
                )
                self._send(HTTPStatus.ACCEPTED, job)
            else:
                self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except ProjectNotSelected as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except ProjectError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (ValueError, RuleImportError, MaterialIntakeError, RuntimeProbeError, TrainingScaffoldError, SettingsError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (SchedulerError, MaterialSchedulerError, DataAuditSchedulerError) as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except DeepSeekError as exc:
            self._error(HTTPStatus.BAD_GATEWAY, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def do_DELETE(self) -> None:  # noqa: N802
        """删除项目：`DELETE /api/projects/<id>`。"""
        path = urlparse(self.path).path.rstrip("/")
        try:
            if not self._authorised_local_client():
                self._error(HTTPStatus.FORBIDDEN, "This endpoint requires a trusted local client")
                return
            if not path.startswith("/api/projects/"):
                self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
                return
            project_id = path.rsplit("/", 1)[-1]
            # 先确认项目存在，再去碰调度器：否则会给一个不存在的 id 建出工作区目录。
            find_project(self.project_root, project_id)
            workspace = workspace_path(self.project_root, project_id)
            active = schedulers_for(self.project_root, workspace)[0].active_job()
            if active is not None:
                self._error(
                    HTTPStatus.CONFLICT,
                    f"Project {project_id} has a running job ({active.get('job_id')}); stop it before deleting",
                )
                return
            project = delete_project(self.project_root, project_id)
            forget_schedulers(workspace)
            self._send(HTTPStatus.OK, dict(self._project_state(), project=project))
        except ProjectNotSelected as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except ProjectError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace: Path | None = None,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """启动本地接口。

    `workspace` 只用于「固定到某个工作区」的场合（命令行 `--workspace`）。默认不传，
    此时工作区跟着注册表里的当前项目走，App 切换项目后无需重启后端。
    """
    loopback_only = host in LOOPBACK_HOSTS
    access_token = "" if loopback_only else (os.environ.get("YJL_API_TOKEN") or secrets.token_urlsafe(24))
    overrides: dict[str, Any] = {
        "project_root": project_root.resolve(),
        "access_token": access_token,
        "require_token": not loopback_only,
    }
    if workspace is not None:
        pinned = workspace.resolve()
        training, material, data_audit = schedulers_for(project_root, pinned)
        overrides.update({
            "workspace": pinned,
            "scheduler": training,
            "material_scheduler": material,
            "data_audit_scheduler": data_audit,
        })
    handler = type("WorkspaceApiHandler", (CompetitionApiHandler,), overrides)
    with ThreadingHTTPServer((host, port), handler) as server:
        print(f"Competition Agent API listening on http://{host}:{port}")
        if loopback_only:
            print("Loopback only; requests are checked against the desktop Origin allowlist.")
        else:
            for address in reachable_addresses(port):
                print(f"Reachable from the local network: {address}")
            print(f"Send {ACCESS_TOKEN_HEADER} on sensitive endpoints. Current token:")
            print(f"  {access_token}")
            print("Set YJL_API_TOKEN to keep the same token across restarts.")
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local Competition Agent API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--workspace", help="Pin the server to one workspace instead of the current project")
    args = parser.parse_args()
    serve(args.host, args.port, Path(args.workspace).resolve() if args.workspace else None)


if __name__ == "__main__":
    main()
