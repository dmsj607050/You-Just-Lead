"""云端账号会话与按实际 token 用量记账。"""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.account_service import (
    AccountError,
    AccountService,
    AuthenticationError,
    InsufficientCredits,
    WELCOME_TOKENS,
)


class AccountServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service = AccountService(Path(self.temporary.name) / "accounts.sqlite3")

    def _register(self, username: str = "judge001") -> dict:
        return self.service.register(username, "correct horse battery", client_key="192.0.2.10")

    def test_registration_grants_one_hundred_credits_and_password_is_not_stored(self) -> None:
        created = self._register()
        self.assertEqual(created["account"]["balance_tokens"], WELCOME_TOKENS)
        self.assertEqual(created["account"]["credits"], 100)
        self.assertEqual(created["account"]["tokens_per_credit"], 1_000)
        with self.assertRaises(AccountError):
            self.service.register("JUDGE001", "another safe password", client_key="192.0.2.11")
        with self.service._connection() as connection:
            row = connection.execute("SELECT password_salt, password_hash FROM users").fetchone()
        self.assertNotIn(b"correct horse battery", bytes(row["password_hash"]))

    def test_login_logout_and_session_refresh(self) -> None:
        created = self._register()
        token = created["token"]
        self.assertEqual(self.service.authenticate(token).username, "judge001")

        refreshed = self.service.refresh(token)
        self.assertNotEqual(refreshed["token"], token)
        with self.assertRaises(AuthenticationError):
            self.service.authenticate(token)

        logged_in = self.service.login("JUDGE001", "correct horse battery", client_key="192.0.2.10")
        self.assertEqual(logged_in["account"]["user_id"], created["account"]["user_id"])
        self.service.logout(logged_in["token"])
        with self.assertRaises(AuthenticationError):
            self.service.authenticate(logged_in["token"])

    def test_failed_login_does_not_reveal_account_existence(self) -> None:
        self._register()
        with self.assertRaises(AuthenticationError) as wrong_password:
            self.service.login("judge001", "wrong password", client_key="192.0.2.20")
        with self.assertRaises(AuthenticationError) as missing_user:
            self.service.login("missing001", "wrong password", client_key="192.0.2.21")
        self.assertEqual(str(wrong_password.exception), str(missing_user.exception))

    def test_reservation_settlement_charges_reported_input_and_output_tokens(self) -> None:
        user_id = self._register()["account"]["user_id"]
        reservation = self.service.reserve_tokens(user_id, 5_000)
        self.assertEqual(self.service.account(user_id)["balance_tokens"], 95_000)
        remaining = self.service.settle_tokens(user_id, reservation, 1_200, 300)
        self.assertEqual(remaining, WELCOME_TOKENS - 1_500)
        entries = self.service.ledger(user_id)
        self.assertEqual(sum(item["delta_tokens"] for item in entries), remaining)
        settled = next(item for item in entries if item["event_type"] == "model_usage_settled")
        self.assertEqual(settled["delta_tokens"], 3_500)
        self.assertEqual(settled["prompt_tokens"] + settled["completion_tokens"], 1_500)

    def test_failed_model_call_releases_reserved_tokens(self) -> None:
        user_id = self._register()["account"]["user_id"]
        reservation = self.service.reserve_tokens(user_id, 4_096)
        remaining = self.service.release_tokens(user_id, reservation)
        self.assertEqual(remaining, WELCOME_TOKENS)
        self.assertEqual(sum(item["delta_tokens"] for item in self.service.ledger(user_id)), WELCOME_TOKENS)

    def test_concurrent_reservations_cannot_spend_the_same_balance_twice(self) -> None:
        user_id = self._register()["account"]["user_id"]

        def reserve() -> str:
            return self.service.reserve_tokens(user_id, 60_000)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: self._try_reserve(reserve), range(2)))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(self.service.account(user_id)["balance_tokens"], 40_000)

    @staticmethod
    def _try_reserve(reserve):
        try:
            return reserve()
        except InsufficientCredits:
            return None


if __name__ == "__main__":
    unittest.main()
