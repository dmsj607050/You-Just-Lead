"""模型客户端的网络重试：链路抖动要能自己过去，请求本身的错不该重试。

起因是一次真实失败：`ANALYZE_RESULT EXP-0007` 整步因为 `IncompleteRead(0 bytes read)`
作废了 —— 那只是一次响应被截断，重试一次就能过去，但客户端当时一次都不重试。
"""

from __future__ import annotations

import json
import unittest
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import HTTPError

from app import llm_service
from app.llm_service import REQUEST_ATTEMPTS, LLMError


class _Response:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def _payload() -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


class RequestRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        # 这几条用例只测网络层，「凭据从哪来」不是重点，直接给一套假的。
        key = patch.object(
            llm_service,
            "resolve_credentials",
            return_value=("test-key", "https://example.invalid", "test-model"),
        )
        key.start()
        self.addCleanup(key.stop)
        # 退避等待在测试里没有意义，只让用例变慢。
        sleeper = patch.object(llm_service.time, "sleep", return_value=None)
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_a_truncated_response_is_retried(self) -> None:
        calls: list[int] = []

        def flaky(*_args: object, **_kwargs: object) -> _Response:
            calls.append(1)
            if len(calls) == 1:
                raise IncompleteRead(b"")
            return _Response(_payload())

        with patch.object(llm_service, "urlopen", side_effect=flaky):
            result = llm_service._request({})

        self.assertEqual(len(calls), 2)
        self.assertIn("choices", result)

    def test_an_http_error_is_not_retried(self) -> None:
        """状态码错误是请求本身或额度/权限的问题，重试只是把同一个错误再犯一遍。"""
        calls: list[int] = []

        def failing(*_args: object, **_kwargs: object) -> _Response:
            calls.append(1)
            raise HTTPError("http://example.invalid", 400, "bad request", {}, None)  # type: ignore[arg-type]

        with patch.object(llm_service, "urlopen", side_effect=failing):
            with self.assertRaises(LLMError):
                llm_service._request({})

        self.assertEqual(len(calls), 1)

    def test_it_gives_up_after_the_attempt_budget(self) -> None:
        calls: list[int] = []

        def always(*_args: object, **_kwargs: object) -> _Response:
            calls.append(1)
            raise IncompleteRead(b"")

        with patch.object(llm_service, "urlopen", side_effect=always):
            with self.assertRaises(LLMError) as caught:
                llm_service._request({})

        self.assertEqual(len(calls), REQUEST_ATTEMPTS)
        # 错误信息要说清"重试过了"，否则看到的人会以为是第一次就失败。
        self.assertIn("不稳定", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
