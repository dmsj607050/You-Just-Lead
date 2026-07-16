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
from database.ledger import ExperimentLedger
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = PROJECT_ROOT / "workspace" / "current_competition"


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

    def do_OPTIONS(self) -> None:  # noqa: N802
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
            elif path == "/api/data-audit":
                self._send(HTTPStatus.OK, snapshot["data_audit"])
            elif path == "/api/next-actions":
                self._send(HTTPStatus.OK, {"actions": snapshot["next_actions"]})
            elif path == "/api/workflow":
                self._send(HTTPStatus.OK, snapshot["workflow"])
            elif path == "/api/capabilities":
                self._send(HTTPStatus.OK, snapshot["capabilities"])
            else:
                self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        try:
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
            else:
                self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8765, workspace: Path = DEFAULT_WORKSPACE) -> None:
    handler = type("WorkspaceApiHandler", (CompetitionApiHandler,), {"project_root": PROJECT_ROOT, "workspace": workspace.resolve()})
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
