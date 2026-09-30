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
import sys
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
from agents.research_agent import build_research_query, search_research
from agents.candidate_agent import (
    assess_investigated,
    candidates_for_workspace,
    record_decision,
)
from agents.materials_agent import MaterialIntakeError
from app.account_service import (
    AccountError,
    AccountService,
    AuthenticationError,
    InsufficientCredits,
    RateLimitError,
    UsageMeter,
)
from app.approval_service import approve_training_config
from app.data_audit_scheduler import DataAuditScheduler, DataAuditSchedulerError
from app.dashboard_service import dashboard_snapshot
from app.llm_service import LLMError, run_agent, verify_connection
from app.runtime_service import local_runtime_snapshot
from app.runtime_probe_service import RuntimeProbeError, latest_runtime_probe, probe_runtime
from app.settings_service import (
    SettingsError,
    delete_provider,
    providers_status,
    set_active_provider,
    upsert_provider,
)
from app.trace_service import paper_package_report, trace_snapshot
from app.training_scaffold_service import TrainingScaffoldError, build_training_scaffold, latest_training_scaffold
from app.material_scheduler import MaterialScheduler, MaterialSchedulerError
from app.reproduction_service import (
    ReproductionError,
    ReproductionService,
    recover_interrupted_runs,
)
from app.research_loop_service import ResearchLoopError, ResearchLoopService
from app.project_registry import (
    ProjectError,
    ProjectNotSelected,
    create_project,
    current_workspace,
    delete_project,
    find_project,
    list_projects,
    select_project,
    workspace_path,
)
from app.training_scheduler import SchedulerError, TrainingScheduler
from database.ledger import ledger_for_workspace
from schemas.research import research_contract
from tools.files import read_json, write_json_atomic
from tools.configuration import load_yaml, write_yaml
from tools.provenance import utc_now
from training.catalog import supported_runners


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def web_root() -> Path:
    """内置界面的位置。

    PyInstaller 打成单文件后，源码路径不再存在，数据文件被解到 `sys._MEIPASS`。
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "web"
    return PROJECT_ROOT / "web"


WEB_ROOT = web_root()
DESKTOP_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "http://127.0.0.1:1420", "http://localhost:1420"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ACCESS_TOKEN_HEADER = "X-YJL-Token"
MAX_REQUEST_BODY_BYTES = 17 * 1024 * 1024

# 内置的 Windows 端界面就放在这些路径上。白名单而不是动态解析，
# 是为了让"能不能读这个文件"变成一个可以一眼看完的清单，不给路径穿越留口子。
STATIC_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/ui.js": ("ui.js", "application/javascript; charset=utf-8"),
    "/views.js": ("views.js", "application/javascript; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
SENSITIVE_LOCAL_ENDPOINTS = {
    "/api/settings/providers",
    "/api/settings/providers/active",
    "/api/settings/providers/delete",
    "/api/rules/import",
    "/api/rules/approve",
    "/api/rules/evidence",
    "/api/research/search",
    "/api/research/decide",
    "/api/research/assess",
    "/api/reproductions/plan",
    "/api/reproductions/run",
    "/api/materials/intake",
    "/api/data-audit/run",
    "/api/build/scaffold",
    "/api/runtime/probe",
    "/api/settings/providers/test",
    "/api/agent/ask",
    "/api/experiments/execute",
    "/api/decisions/approve",
    "/api/research/loop/step",
    "/api/research/loop/backfill",
    "/api/research/loop/run",
    "/api/research/loop/hypotheses",
}


def allowed_origins() -> set[str]:
    """Return the desktop allowlist plus any additionally configured clients.

    A HarmonyOS Web component or another local front end is admitted by listing
    its exact Origin in the comma-separated ``YJL_ALLOWED_ORIGINS`` variable.
    """
    configured = os.environ.get("YJL_ALLOWED_ORIGINS", "")
    return DESKTOP_ORIGINS | {item.strip() for item in configured.split(",") if item.strip()}


def same_local_origin(origin: str, host_header: str) -> bool:
    """浏览器发来的 Origin 是不是本服务自己。

    内置界面就是本服务 serve 出去的静态文件，它发请求时带的 Origin 必然等于本机地址。
    不认这一条，界面一调敏感端点就是 403（同源却不在桌面白名单里）。
    放行它不额外开放任何能力：能拿到这个来源的人，本来就已经能访问回环端口。
    """
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.hostname not in LOOPBACK_HOSTS:
        return False
    return parsed.netloc == host_header


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
    """检索结果 + 取舍 + 评判合成一份：界面只读这一个接口。

    取舍与评判各自落盘（`candidate_decisions.json` / `candidate_assessments.json`），
    所以重跑检索不会覆盖人的决定。这里只是把它们按 `paper_id` 合到记录上。
    """
    report = candidates_for_workspace(workspace)
    radar_path = workspace / "research" / "research_radar.md"
    report["report_markdown"] = radar_path.read_text(encoding="utf-8") if radar_path.exists() else ""
    return report


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
        # 工作区还没认领档案时，界面可以用 profile 声明这一次录的是哪份档案。
        profile=str(body.get("profile") or "").strip(),
    )

    stamp = utc_now().replace("-", "").replace(":", "").replace("+00:00", "Z")
    evidence_path = workspace / "docs" / f"rule_evidence_{stamp}_{secrets.token_hex(2)}.yaml"
    write_yaml(evidence_path, record)
    try:
        return apply_official_rule_evidence(workspace, evidence_path)
    except Exception:
        evidence_path.unlink(missing_ok=True)
        raise


_SCHEDULER_CACHE: dict[str, tuple[TrainingScheduler, MaterialScheduler, DataAuditScheduler]] = {}
_SCHEDULER_LOCK = threading.Lock()
_REPRODUCTION_CACHE: dict[str, ReproductionService] = {}
_RESEARCH_LOOP_CACHE: dict[str, ResearchLoopService] = {}


def research_loop_for(
    project_root: Path, workspace: Path, *, usage_meter: UsageMeter | None = None
) -> ResearchLoopService:
    """按工作区取一份研究循环服务。

    它持有内存里的研究状态，重建就等于把模型刚推出来的假设与证据丢掉，所以必须缓存。
    缓存与调度器共用同一把锁，`forget_schedulers` 一次就能全部清掉。
    """
    key = str(workspace.resolve())
    with _SCHEDULER_LOCK:
        cached = _RESEARCH_LOOP_CACHE.get(key)
        if cached is None:
            cached = ResearchLoopService(project_root.resolve(), workspace.resolve(), usage_meter=usage_meter)
            _RESEARCH_LOOP_CACHE[key] = cached
        elif usage_meter is not None:
            cached.bind_usage_meter(usage_meter)
        return cached


def reproduction_service_for(project_root: Path, workspace: Path) -> ReproductionService:
    """按工作区取一份复现服务。

    它持有正在运行的作业句柄，和调度器一样不能每次请求重建；缓存与调度器共用同一把锁，
    这样 `forget_schedulers` 一次就能把两者都清掉。
    """
    key = str(workspace.resolve())
    with _SCHEDULER_LOCK:
        cached = _REPRODUCTION_CACHE.get(key)
        if cached is None:
            cached = ReproductionService(project_root.resolve(), workspace.resolve())
            _REPRODUCTION_CACHE[key] = cached
            recover_interrupted_runs(cached)
        return cached


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
        _REPRODUCTION_CACHE.pop(str(workspace.resolve()), None)
        _RESEARCH_LOOP_CACHE.pop(str(workspace.resolve()), None)


class CompetitionApiHandler(BaseHTTPRequestHandler):
    """本地 REST 接口。

    工作区与调度器都按「当前项目」在请求内解析，因此 App 切完项目，之后的请求就作用在
    新工作区上，不必重启后端。把 `workspace`/`scheduler` 这些名字显式塞进子类即固定住
    它们（命令行 `--workspace` 与测试都走这条注入路径）。
    """

    project_root: Path
    access_token: str = ""
    require_token: bool = False
    cloud_mode: bool = False
    account_service: AccountService | None = None
    cloud_users_root: Path | None = None
    cloud_allowed_origins: set[str] = set()
    authenticated_account: Any = None
    auth_token: str = ""
    usage_meter: UsageMeter | None = None

    def _cloud_client_key(self) -> str:
        """获取注册限流键；云端只信任回环反向代理转发的末尾客户端地址。"""
        peer = str(self.client_address[0]) if self.client_address else "unknown"
        if peer in LOOPBACK_HOSTS:
            forwarded = self.headers.get("X-Forwarded-For", "")
            real_ip = self.headers.get("X-Real-IP", "")
            candidate = forwarded.split(",")[-1].strip() if forwarded.strip() else real_ip.strip()
            if candidate:
                try:
                    import ipaddress

                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    pass
        return peer

    def _prepare_cloud_request(self, path: str) -> bool:
        """云模式下强制 HTTPS 与用户会话，并把本次请求切到独立用户数据根。"""
        if not self.cloud_mode or not path.startswith("/api/") or path == "/api/health":
            return True
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").strip().lower()
        if forwarded_proto != "https":
            self._error(HTTPStatus.UPGRADE_REQUIRED, "云端 API 只接受 HTTPS 反向代理请求。")
            return False
        if path in {"/api/auth/register", "/api/auth/login"}:
            return True
        if self.account_service is None or self.cloud_users_root is None:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "账号服务尚未配置。")
            return False
        authorization = self.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            self._error(HTTPStatus.UNAUTHORIZED, "请先登录。")
            return False
        try:
            account = self.account_service.authenticate(token.strip())
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
            return False
        # ID 是数据库生成的十六进制 UUID，不从请求参数拼路径。
        user_root = (self.cloud_users_root / account.user_id).resolve()
        if user_root.parent != self.cloud_users_root.resolve():
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "账号数据路径无效。")
            return False
        user_root.mkdir(parents=True, exist_ok=True)
        self.project_root = user_root
        self.authenticated_account = account
        self.auth_token = token.strip()
        self.usage_meter = UsageMeter(self.account_service, account.user_id)
        return True

    def _send_cors(self) -> None:
        origin = self.headers.get("Origin")
        if not self.cloud_mode:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin and origin in self.cloud_allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {ACCESS_TOKEN_HEADER}, Authorization")

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

    @property
    def reproduction_service(self) -> ReproductionService:
        return reproduction_service_for(self.project_root, self.workspace)

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
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
        if self.cloud_mode:
            return bool(getattr(self, "authenticated_account", None))
        if self.require_token:
            supplied = self.headers.get(ACCESS_TOKEN_HEADER, "")
            return bool(self.access_token) and secrets.compare_digest(supplied, self.access_token)
        origin = self.headers.get("Origin")
        if origin is None or origin in allowed_origins():
            return True
        return same_local_origin(origin, self.headers.get("Host", ""))

    def _send_static(self, name: str, content_type: str) -> None:
        """把内置界面里的一个文件发出去。

        文件名来自 `STATIC_ASSETS` 白名单，不是从请求路径拼出来的，所以这里不做路径检查。
        `no-store` 是因为界面就在本机：缓存住旧 CSS 会让人以为改动没生效。
        """
        path = WEB_ROOT / name
        if not path.is_file():
            self._error(HTTPStatus.NOT_FOUND, f"Missing built-in asset: {name}")
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if self.cloud_mode:
            origin = self.headers.get("Origin")
            if origin and origin not in self.cloud_allowed_origins:
                self._error(HTTPStatus.FORBIDDEN, "该网页来源未获允许。")
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()
            return
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
            if not self._prepare_cloud_request(path):
                return
            if path in STATIC_ASSETS:
                # 内置界面：同源的静态文件，不经 API 校验，也不做任何目录解析。
                name, content_type = STATIC_ASSETS[path]
                self._send_static(name, content_type)
                return
            if path in {"/health", "/api/health"}:
                # 固定工作区模式也要报告真正服务的路径，避免健康探针把请求导向错误项目。
                if self.cloud_mode:
                    self._send(HTTPStatus.OK, {"status": "ok", "mode": "cloud"})
                    return
                try:
                    workspace = str(self.workspace)
                except ProjectNotSelected:
                    workspace = ""
                self._send(HTTPStatus.OK, {"status": "ok", "workspace": workspace})
            elif path == "/api/account" and self.cloud_mode:
                assert self.account_service is not None
                account = self.account_service.account(self.authenticated_account.user_id)
                account["credit_ledger"] = self.account_service.ledger(self.authenticated_account.user_id)
                self._send(HTTPStatus.OK, account)
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
            elif path == "/api/settings/providers":
                if self.cloud_mode:
                    from app.settings_service import DEFAULT_DEEPSEEK_MODEL, PROVIDER_PRESETS

                    preset = next(item for item in PROVIDER_PRESETS if item.id == "deepseek")
                    model = os.environ.get("YJL_LLM_MODEL", DEFAULT_DEEPSEEK_MODEL).strip() or DEFAULT_DEEPSEEK_MODEL
                    self._send(
                        HTTPStatus.OK,
                        {
                            "managed": True,
                            "presets": [
                                {
                                    "id": preset.id,
                                    "name": preset.name,
                                    "base_url": preset.base_url,
                                    "key_required": False,
                                    "docs_url": "",
                                }
                            ],
                            "providers": [
                                {
                                    "id": "platform-deepseek",
                                    "name": "DeepSeek（平台托管）",
                                    "preset": preset.id,
                                    "base_url": preset.base_url,
                                    "model": model,
                                    "models": [model],
                                    "key_required": False,
                                    "has_key": True,
                                    "docs_url": "",
                                }
                            ],
                            "active": "platform-deepseek",
                            "key_source": "platform",
                            "secure_storage_available": False,
                            "api_key_env": "",
                            "model": model,
                            "configured": True,
                        },
                    )
                else:
                    self._send(HTTPStatus.OK, providers_status())
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
            elif path == "/api/reproductions":
                service = self.reproduction_service
                self._send(
                    HTTPStatus.OK,
                    {
                        "docker": service.docker_status(),
                        "plans": service.plans(),
                        "runs": service.runs(),
                    },
                )
            elif path.startswith("/api/reproductions/runs/"):
                run_id = path.rsplit("/", 1)[-1]
                run = self.reproduction_service.run_detail(run_id)
                self._send(HTTPStatus.OK, run) if run else self._error(HTTPStatus.NOT_FOUND, "Reproduction run not found")
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
            elif path == "/api/data-audit":
                # 这个页面只需要一份审计文件。不要为了一个小响应构建整张仪表盘快照：
                # 快照还会读取实验、规则、运行器与账本，在云端新工作区首次打开时可能超过端侧超时。
                audit_path = self.workspace / "reports" / "data_statistics.json"
                report = read_json(audit_path) if audit_path.is_file() else {}
                self._send(HTTPStatus.OK, report)
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
                elif path == "/api/next-actions":
                    self._send(HTTPStatus.OK, {"actions": snapshot["next_actions"]})
                elif path == "/api/workflow":
                    self._send(HTTPStatus.OK, snapshot["workflow"])
                elif path == "/api/research/loop":
                    self._send(HTTPStatus.OK, research_loop_for(self.project_root, self.workspace).snapshot())
                elif path == "/api/research/contract":
                    # 动作名、核查项、判定值的中文与色调：定义只有 `schemas/research.py` 一份，
                    # 界面（Windows 端与鸿蒙端）都从这里取。抄一份到前端就是静默漂移的开始。
                    self._send(HTTPStatus.OK, research_contract())
                elif path == "/api/research/loop/jobs":
                    self._send(HTTPStatus.OK, {"jobs": research_loop_for(self.project_root, self.workspace).jobs()})
                elif path.startswith("/api/research/loop/jobs/"):
                    job_id = path.rsplit("/", 1)[-1]
                    job = research_loop_for(self.project_root, self.workspace).job(job_id)
                    self._send(HTTPStatus.OK, job) if job else self._error(HTTPStatus.NOT_FOUND, "Loop job not found")
                else:
                    self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except ProjectNotSelected as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except ProjectError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except AccountError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        try:
            if not self._prepare_cloud_request(path):
                return
            if self.cloud_mode and path in {"/api/auth/register", "/api/auth/login"}:
                if self.account_service is None:
                    self._error(HTTPStatus.SERVICE_UNAVAILABLE, "账号服务尚未配置。")
                    return
                body = self._body()
                username = str(body.get("username", ""))
                password = str(body.get("password", ""))
                client_key = self._cloud_client_key()
                if path.endswith("/register"):
                    result = self.account_service.register(username, password, client_key=client_key)
                    self._send(HTTPStatus.CREATED, result)
                else:
                    result = self.account_service.login(username, password, client_key=client_key)
                    self._send(HTTPStatus.OK, result)
                return
            if self.cloud_mode and path == "/api/auth/logout":
                assert self.account_service is not None
                self.account_service.logout(self.auth_token)
                self._send(HTTPStatus.OK, {"logged_out": True})
                return
            if self.cloud_mode and path == "/api/auth/refresh":
                assert self.account_service is not None
                self._send(HTTPStatus.OK, self.account_service.refresh(self.auth_token))
                return
            if self.cloud_mode and path in {
                "/api/settings/providers",
                "/api/settings/providers/active",
                "/api/settings/providers/delete",
                "/api/settings/providers/test",
            }:
                self._error(HTTPStatus.FORBIDDEN, "模型来源由平台管理，客户端不能修改服务器密钥。")
                return
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
                spec_path = self.workspace / "competition_spec.yaml"
                spec = load_yaml(spec_path) if spec_path.exists() else {}
                raw_query = str(body.get("query", "")).strip()
                # 不填检索式就按规则规格拼一条：这是「按规则自动检索」的入口，
                # 界面上不该逼着人自己编检索词。
                from_spec = len(raw_query) == 0
                query = build_research_query(spec) if from_spec else raw_query
                if not query:
                    raise ValueError("research query is empty and the competition spec has no usable task or modality terms")
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
                    spec=spec,
                )
                report = _research_report(self.workspace)
                ledger.record_event(
                    "research_searched",
                    {
                        "query": query,
                        "from_spec": from_spec,
                        "records": outcome["records"],
                        "provider_failures": outcome["provider_failures"],
                    },
                )
                self._send(HTTPStatus.OK, report)
            elif path == "/api/research/decide":
                paper_id = str(body.get("paper_id", "")).strip()
                if not paper_id:
                    raise ValueError("paper_id is required")
                outcome = record_decision(
                    self.workspace,
                    paper_id,
                    str(body.get("decision", "")).strip(),
                    str(body.get("note", "")),
                )
                ledger.record_event(
                    "research_candidate_decided",
                    {"paper_id": paper_id, "decision": outcome["decision"], "has_note": bool(body.get("note"))},
                )
                self._send(HTTPStatus.OK, _research_report(self.workspace))
            elif path == "/api/research/assess":
                raw_ids = body.get("paper_ids")
                if raw_ids is not None and (
                    not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids)
                ):
                    raise ValueError("paper_ids must be a list of research record IDs")
                # 不传就评判所有已标记「调研」的候选；已舍弃的不花这次查询。
                outcome = assess_investigated(
                    self.workspace,
                    paper_ids=[item for item in raw_ids if item] if raw_ids is not None else None,
                )
                ledger.record_event(
                    "research_candidates_assessed",
                    {
                        "assessed": outcome["assessed"],
                        "verdicts": outcome["verdicts"],
                        "skipped": outcome["skipped"],
                    },
                )
                self._send(HTTPStatus.OK, _research_report(self.workspace))
            elif path == "/api/reproductions/plan":
                # 生成计划会 clone 仓库（仍只做静态检查）—— 点这个按钮就是批准 clone。
                # 代码要被*执行*还得再走 /api/reproductions/run 那道批准。
                paper_id = str(body.get("paper_id", "")).strip()
                if not paper_id:
                    raise ValueError("paper_id is required")
                image = str(body.get("image", "")).strip() or None
                plan = self.reproduction_service.make_plan(paper_id, image=image)
                self._send(HTTPStatus.CREATED, plan)
            elif path == "/api/reproductions/run":
                plan_id = str(body.get("plan_id", "")).strip()
                command_id = str(body.get("command_id", "")).strip()
                if not plan_id or not command_id:
                    raise ValueError("plan_id and command_id are required")
                # 命令可以在批准前改写（README 里写的是仓库自己的相对路径，这里是 /data）。
                # 改写后的那一行会原样记进批准文件 —— 批准的就是实际要跑的命令。
                override = str(body.get("command", "")).strip()
                run = self.reproduction_service.submit(
                    plan_id, command_id, str(body.get("note", "")), command_override=override or None
                )
                self._send(HTTPStatus.ACCEPTED, run)
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
            elif path == "/api/settings/providers":
                if self.cloud_mode:
                    self._error(HTTPStatus.FORBIDDEN, "模型来源由平台管理，客户端不能修改服务器密钥。")
                    return
                # 新增或更新一套来源。`api_key` 留空＝不改已存的密钥（改地址/模型不用重填密钥）。
                status = upsert_provider(
                    provider_id=(str(body.get("id")) if body.get("id") else None),
                    name=str(body.get("name", "")),
                    base_url=str(body.get("base_url", "")),
                    model=str(body.get("model", "")),
                    api_key=str(body.get("api_key", "")),
                    models=body.get("models"),
                    preset=str(body.get("preset") or "custom"),
                )
                ledger.record_event(
                    "model_provider_saved",
                    {"id": status["active"], "model": status["model"], "count": len(status["providers"])},
                )
                self._send(HTTPStatus.OK, status)
            elif path == "/api/settings/providers/active":
                if self.cloud_mode:
                    self._error(HTTPStatus.FORBIDDEN, "模型来源由平台管理。")
                    return
                status = set_active_provider(str(body.get("id", "")))
                ledger.record_event("model_provider_activated", {"id": status["active"], "model": status["model"]})
                self._send(HTTPStatus.OK, status)
            elif path == "/api/settings/providers/delete":
                if self.cloud_mode:
                    self._error(HTTPStatus.FORBIDDEN, "模型来源由平台管理。")
                    return
                removed = str(body.get("id", ""))
                status = delete_provider(removed)
                ledger.record_event("model_provider_removed", {"id": removed, "active": status["active"]})
                self._send(HTTPStatus.OK, status)
            elif path == "/api/settings/providers/test":
                if self.cloud_mode:
                    self._error(HTTPStatus.FORBIDDEN, "请通过带积分计量的问答功能验证模型服务。")
                    return
                # 可以指定某一套来试（还没切过去也能先验证）。
                outcome = verify_connection(str(body.get("id")) if body.get("id") else None)
                self._send(HTTPStatus.OK if outcome["ok"] else HTTPStatus.BAD_GATEWAY, outcome)
            elif path == "/api/agent/ask":
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
                    usage_meter=getattr(self, "usage_meter", None),
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
            elif path == "/api/research/loop/step":
                # 走作业模式：一步可能跑满多轮模型调用，同步返回必然读超时。
                loop_job = research_loop_for(
                    self.project_root, self.workspace, usage_meter=getattr(self, "usage_meter", None)
                ).submit_step(
                    max_steps=body.get("max_steps", 1)
                )
                ledger.record_event(
                    "research_loop_step_submitted",
                    {"job_id": loop_job.job_id, "max_steps": loop_job.max_steps},
                )
                self._send(HTTPStatus.ACCEPTED, loop_job.to_dict())
            elif path == "/api/research/loop/backfill":
                state = research_loop_for(self.project_root, self.workspace).backfill(
                    rebuild=bool(body.get("rebuild"))
                )
                ledger.record_event("research_loop_backfilled", {"summary": state["summary"]})
                self._send(HTTPStatus.OK, state)
            elif path == "/api/research/loop/run":
                # 人批准之后，这次设计才真的变成一次训练。科研决策交给机器，
                # 烧机器的事留给人 —— 这条边界在这里落地。
                experiment_id = str(body.get("experiment_id", "")).strip()
                note = str(body.get("note", "")).strip()
                if not experiment_id:
                    raise ValueError("experiment_id is required")
                # 批准必须写明理由：这条记录以后要能回答"当时凭什么批的"。
                if not note:
                    raise ValueError("note is required")
                loop = research_loop_for(self.project_root, self.workspace)
                runnable, reason = loop.executable(experiment_id)
                if not runnable:
                    raise ValueError(reason)
                experiment = loop.state().experiments[experiment_id]
                config_path = self.workspace / experiment.config_path
                # 第二道门是 GPU 预算。研究层的批准说的是"这次设计该跑"，预算批准说的是
                # "这次运行可以花这些算力" —— 两件事，但人只点一次，所以这里一并记录。
                # 预算数字会随响应回给界面：批了多少是要看得见的，不能悄悄代签。
                budget = approve_training_config(self.workspace, config_path, note)
                job = self.scheduler.submit(
                    config_path,
                    hypothesis=experiment.question or None,
                )
                approval = loop.mark_running(
                    experiment_id,
                    run_id=str(job.get("job_id") or ""),
                    note=note,
                )
                ledger.record_event(
                    "research_loop_run_approved",
                    {
                        "experiment_id": experiment_id,
                        "run_id": approval["run_id"],
                        "config_path": approval["config_path"],
                        "estimated_gpu_hours": budget["estimated_gpu_hours"],
                        "requested_device": budget["requested_device"],
                    },
                )
                self._send(
                    HTTPStatus.ACCEPTED,
                    {
                        "experiment_id": experiment_id,
                        "approval": approval,
                        "budget_approval": {
                            "estimated_gpu_hours": budget["estimated_gpu_hours"],
                            "requested_device": budget["requested_device"],
                            "approval_path": budget["approval_path"],
                        },
                        "job": job,
                    },
                )
            elif path == "/api/research/loop/hypotheses":
                # 人可以直接提出假设。它进去之后与模型提的假设走同一套判据 ——
                # "是人写的"不是免检章，缺预测与反证条件一样会被编排器打回补全。
                loop = research_loop_for(self.project_root, self.workspace)
                hypothesis = loop.add_hypothesis(
                    statement=str(body.get("statement", "")),
                    predictions=body.get("predictions") if isinstance(body.get("predictions"), list) else [],
                    falsifiers=body.get("falsifiers") if isinstance(body.get("falsifiers"), list) else [],
                    rationale=body.get("rationale") if isinstance(body.get("rationale"), list) else [],
                )
                ledger.record_event(
                    "research_loop_hypothesis_added",
                    {"hypothesis_id": hypothesis["hypothesis_id"], "by": "human"},
                )
                self._send(HTTPStatus.CREATED, hypothesis)
            else:
                self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except ProjectNotSelected as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except ProjectError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except InsufficientCredits as exc:
            self._error(HTTPStatus.PAYMENT_REQUIRED, str(exc))
        except RateLimitError as exc:
            self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
        except AccountError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (ValueError, RuleImportError, MaterialIntakeError, RuntimeProbeError, TrainingScaffoldError, SettingsError, ReproductionError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (SchedulerError, MaterialSchedulerError, DataAuditSchedulerError, ResearchLoopError) as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except LLMError as exc:
            self._error(HTTPStatus.BAD_GATEWAY, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def do_DELETE(self) -> None:  # noqa: N802
        """删除项目：`DELETE /api/projects/<id>`。"""
        path = urlparse(self.path).path.rstrip("/")
        try:
            if not self._prepare_cloud_request(path):
                return
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
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
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
    cloud_mode = os.environ.get("YJL_CLOUD_MODE", "").strip() == "1"
    account_service = None
    cloud_users_root = None
    cloud_origins: set[str] = set()
    if cloud_mode:
        if not loopback_only:
            raise RuntimeError("云模式必须只绑定回环地址，并通过 HTTPS 反向代理对外服务。")
        if not os.environ.get("YJL_LLM_API_KEY", "").strip():
            raise RuntimeError("云模式需要在秘密环境中配置 YJL_LLM_API_KEY。")
        data_root_value = os.environ.get("YJL_CLOUD_DATA_ROOT", "").strip()
        if not data_root_value:
            raise RuntimeError("云模式需要配置独立持久目录 YJL_CLOUD_DATA_ROOT。")
        data_root = Path(data_root_value).expanduser()
        if not data_root.is_absolute():
            raise RuntimeError("YJL_CLOUD_DATA_ROOT 必须是绝对路径。")
        data_root = data_root.resolve()
        data_root.mkdir(parents=True, exist_ok=True)
        cloud_users_root = data_root / "users"
        cloud_users_root.mkdir(parents=True, exist_ok=True)
        account_service = AccountService(data_root / "accounts.sqlite3")
        cloud_origins = {
            "https://nucrobot.online",
            "tauri://localhost",
            "http://tauri.localhost",
            *(
                item.strip()
                for item in os.environ.get("YJL_CLOUD_ALLOWED_ORIGINS", "").split(",")
                if item.strip()
            ),
        }
    access_token = "" if loopback_only else (os.environ.get("YJL_API_TOKEN") or secrets.token_urlsafe(24))
    overrides: dict[str, Any] = {
        "project_root": project_root.resolve(),
        "access_token": access_token,
        "require_token": not loopback_only,
        "cloud_mode": cloud_mode,
        "account_service": account_service,
        "cloud_users_root": cloud_users_root,
        "cloud_allowed_origins": cloud_origins,
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
        if cloud_mode:
            print("Cloud account mode enabled; API is loopback-only behind an HTTPS reverse proxy.")
            print("Per-user workspaces and token-credit ledger use YJL_CLOUD_DATA_ROOT.")
        elif loopback_only:
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
