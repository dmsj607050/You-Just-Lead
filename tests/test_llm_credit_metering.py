"""LLM 请求在云模式下按真实 usage 结算，并处理缺失用量。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import llm_service
from app.account_service import AccountService, UsageMeter, WELCOME_TOKENS


class _Response:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class LlmCreditMeteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        service = AccountService(Path(self.temporary.name) / "accounts.sqlite3")
        account = service.register("meter001", "correct horse battery", client_key="192.0.2.1")["account"]
        self.service = service
        self.user_id = account["user_id"]
        self.meter = UsageMeter(service, self.user_id)
        credentials = patch.object(
            llm_service,
            "resolve_credentials",
            return_value=("not-a-real-key", "https://example.invalid", "test-model"),
        )
        credentials.start()
        self.addCleanup(credentials.stop)

    def test_success_charges_provider_reported_prompt_and_completion_tokens(self) -> None:
        response = _Response(
            {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
            }
        )
        with patch.object(llm_service, "urlopen", return_value=response):
            result = llm_service._request(
                {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
                usage_meter=self.meter,
            )

        self.assertIn("choices", result)
        self.assertEqual(self.service.available_tokens(self.user_id), WELCOME_TOKENS - 150)
        settled = next(
            item for item in self.service.ledger(self.user_id) if item["event_type"] == "model_usage_settled"
        )
        self.assertEqual(settled["prompt_tokens"], 120)
        self.assertEqual(settled["completion_tokens"], 30)
        self.assertEqual(sum(item["delta_tokens"] for item in self.service.ledger(self.user_id)), WELCOME_TOKENS - 150)

    def test_missing_usage_is_charged_at_reserved_limit_and_answer_is_rejected(self) -> None:
        response = _Response({"choices": [{"message": {"role": "assistant", "content": "unmetered"}}]})
        with patch.object(llm_service, "urlopen", return_value=response):
            with self.assertRaises(llm_service.LLMError):
                llm_service._request(
                    {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
                    usage_meter=self.meter,
                )

        self.assertLess(self.service.available_tokens(self.user_id), WELCOME_TOKENS)
        estimated = next(
            item for item in self.service.ledger(self.user_id) if item["event_type"] == "model_usage_estimated"
        )
        self.assertIsNone(estimated["prompt_tokens"])
        self.assertIsNone(estimated["completion_tokens"])

    def test_provider_error_releases_reservation(self) -> None:
        from urllib.error import HTTPError

        error = HTTPError("https://example.invalid", 429, "rate limit", {}, None)  # type: ignore[arg-type]
        with patch.object(llm_service, "urlopen", side_effect=error):
            with self.assertRaises(llm_service.LLMError):
                llm_service._request({"model": "test-model", "messages": []}, usage_meter=self.meter)
        self.assertEqual(self.service.available_tokens(self.user_id), WELCOME_TOKENS)


if __name__ == "__main__":
    unittest.main()
