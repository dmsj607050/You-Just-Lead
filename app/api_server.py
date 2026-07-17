"""Minimal local REST API for the competition workspace.

The API binds to loopback by default. It exposes persisted state and creates
drafts, but never starts training, downloads code, or submits predictions.
"""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.dashboard_service import dashboard_snapshot
from app.deepseek_service import DeepSeekError, chat_completion, verify_connection
from app.runtime_service import local_runtime_snapshot
from app.settings_service import SettingsError, configure_deepseek, deepseek_settings_status
from database.ledger import ExperimentLedger
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = PROJECT_ROOT / "workspace" / "current_competition"
DESKTOP_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "http://127.0.0.1:1420", "http://localhost:1420"}
SENSITIVE_LOCAL_ENDPOINTS = {
    "/api/settings/deepseek",
    "/api/settings/deepseek/test",
    "/api/agent/deepseek",
}


def _draft_id(workspace: Path) -> str:
    existing = [path.stem for path in (workspace / "experiments" / "drafts").glob("DRAFT-*.json")]
    numbers = [int(item.split("-", 1)[1]) for item in existing if item.split("-", 1)[1].isdigit()]
    return f"DRAFT-{max(numbers, default=0) + 1:04d}"


class CompetitionApiHandler(BaseHTTPRequestHandler):
    project_root: Path
    workspace: Path

    server_version = "CompetitionAgent/0.2"

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._send(status, {"error": message})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 32_768:
            raise ValueError("Request body is too large")
        value = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _trusted_local_origin(self) -> bool:
        """Block browser cross-site requests that could spend a local API key."""
        origin = self.headers.get("Origin")
        return origin is None or origin in DESKTOP_ORIGINS

    def do_OPTIONS(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if path in SENSITIVE_LOCAL_ENDPOINTS and not self._trusted_local_origin():
            self._error(HTTPStatus.FORBIDDEN, "This endpoint is available only to the desktop app")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            snapshot = dashboard_snapshot(self.project_root, self.workspace)
            if path == "/health":
                self._send(HTTPStatus.OK, {"status": "ok", "workspace": str(self.workspace)})
            elif path == "/api/dashboard":
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
            elif path == "/api/capabilities":
                self._send(HTTPStatus.OK, snapshot["capabilities"])
            elif path == "/api/runtime/local":
                self._send(HTTPStatus.OK, local_runtime_snapshot())
            elif path == "/api/settings/deepseek":
                self._send(HTTPStatus.OK, deepseek_settings_status())
            else:
                self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        try:
            if path in SENSITIVE_LOCAL_ENDPOINTS and not self._trusted_local_origin():
                self._error(HTTPStatus.FORBIDDEN, "This endpoint is available only to the desktop app")
                return
            body = self._body()
            ledger = ExperimentLedger(self.project_root / "database" / "competition_agent.sqlite")
            if path == "/api/experiments/drafts":
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
                response = chat_completion(
                    "你是竞赛模型训练 Agent。只能基于用户明确提供的内容提出分析、计划和风险提示。"
                    "不得声称已经执行训练、下载代码、读取未提供文件或提交结果；高成本训练必须提醒用户审批。",
                    f"当前阶段：{stage}\n\n用户请求：{prompt}",
                )
                ledger.record_event("deepseek_agent_response", {"stage": stage, "model": response["model"]})
                self._send(HTTPStatus.OK, response)
            else:
                self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except (ValueError, SettingsError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except DeepSeekError as exc:
            self._error(HTTPStatus.BAD_GATEWAY, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace: Path = DEFAULT_WORKSPACE,
    project_root: Path = PROJECT_ROOT,
) -> None:
    handler = type(
        "WorkspaceApiHandler",
        (CompetitionApiHandler,),
        {"project_root": project_root.resolve(), "workspace": workspace.resolve()},
    )
    with ThreadingHTTPServer((host, port), handler) as server:
        print(f"Competition Agent API listening on http://{host}:{port}")
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local Competition Agent API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--workspace")
    args = parser.parse_args()
    serve(args.host, args.port, Path(args.workspace).resolve() if args.workspace else DEFAULT_WORKSPACE)


if __name__ == "__main__":
    main()
