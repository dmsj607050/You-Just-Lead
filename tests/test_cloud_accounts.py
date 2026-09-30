"""云模式 API 的登录门禁与用户工作区隔离。"""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app.account_service import AccountService
from app.api_server import CompetitionApiHandler


class CloudAccountApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = AccountService(self.root / "data" / "accounts.sqlite3")
        self.users_root = self.root / "data" / "users"
        self.users_root.mkdir(parents=True)
        handler = type(
            "CloudAccountTestHandler",
            (CompetitionApiHandler,),
            {
                "project_root": self.root / "unused-single-user-root",
                "cloud_mode": True,
                "account_service": self.service,
                "cloud_users_root": self.users_root,
                "cloud_allowed_origins": {"https://nucrobot.online"},
            },
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_server)
        self.port = int(self.server.server_address[1])

    def _close_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        token: str = "",
        secure_proxy: bool = True,
    ) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if secure_proxy:
            headers["X-Forwarded-Proto"] = "https"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8")) if response.length else {}
        connection.close()
        return response.status, payload

    def _register(self, username: str) -> str:
        status, payload = self._request(
            "POST",
            "/api/auth/register",
            body={"username": username, "password": "correct horse battery"},
        )
        self.assertEqual(status, 201, payload)
        return payload["token"]

    def test_every_data_route_requires_a_user_session(self) -> None:
        status, payload = self._request("GET", "/api/projects")
        self.assertEqual(status, 401)
        self.assertIn("error", payload)

        status, payload = self._request("GET", "/api/projects", secure_proxy=False)
        self.assertEqual(status, 426)
        self.assertIn("error", payload)

    def test_registration_project_state_credits_and_logout(self) -> None:
        token_a = self._register("judge001")
        token_b = self._register("judge002")

        status, payload = self._request(
            "GET", "/api/account", token=token_a
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["balance_tokens"], 100_000)
        self.assertEqual(payload["credits"], 100)
        self.assertEqual(len(payload["credit_ledger"]), 1)

        status, payload = self._request(
            "POST", "/api/projects", body={"name": "Judge A"}, token=token_a
        )
        self.assertEqual(status, 201, payload)
        self.assertEqual(len(payload["projects"]), 1)

        status, payload = self._request("GET", "/api/projects", token=token_b)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["projects"], [])

        status, _ = self._request("POST", "/api/auth/logout", token=token_a)
        self.assertEqual(status, 200)
        status, _ = self._request("GET", "/api/account", token=token_a)
        self.assertEqual(status, 401)

    def test_health_is_public_and_does_not_disclose_workspace_path(self) -> None:
        status, payload = self._request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok", "mode": "cloud"})

    def test_managed_provider_hides_server_key_and_rejects_client_changes(self) -> None:
        token = self._register("judge003")
        marker = "server-key-must-never-leave-backend"
        with patch.dict("os.environ", {"YJL_LLM_API_KEY": marker}):
            status, payload = self._request("GET", "/api/settings/providers", token=token)
            self.assertEqual(status, 200, payload)
            self.assertTrue(payload["managed"])
            self.assertEqual(payload["providers"][0]["id"], "platform-deepseek")
            self.assertEqual(payload["api_key_env"], "")
            self.assertNotIn(marker, json.dumps(payload))
            self.assertNotIn("api_key", payload["providers"][0])

        status, payload = self._request(
            "POST",
            "/api/settings/providers",
            body={"name": "attacker-controlled"},
            token=token,
        )
        self.assertEqual(status, 403, payload)

    def test_auth_preflight_does_not_require_a_session(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(
            "OPTIONS",
            "/api/auth/register",
            headers={
                "Origin": "https://nucrobot.online",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 204)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "https://nucrobot.online")
        self.assertIn("Authorization", response.getheader("Access-Control-Allow-Headers"))
        connection.close()


if __name__ == "__main__":
    unittest.main()
