"""云端账号、会话与 DeepSeek token 积分账本。

密码使用带随机盐的 PBKDF2；会话只保存令牌摘要。余额以整数 token 记账，
1,000 token 显示为 1 积分，避免逐次调用取整造成多扣或少扣。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tools.provenance import utc_now


WELCOME_CREDITS = 100
TOKENS_PER_CREDIT = 1_000
WELCOME_TOKENS = WELCOME_CREDITS * TOKENS_PER_CREDIT
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
PASSWORD_ITERATIONS = 310_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
REGISTRATION_LIMIT_PER_IP_DAILY = 200


class AccountError(ValueError):
    """账号请求不满足服务端约束。"""


class AuthenticationError(AccountError):
    """账号或会话无效。"""


class RateLimitError(AccountError):
    """账号动作超过频率限制。"""


class InsufficientCredits(AccountError):
    """剩余 token 不足以预留模型调用额度。"""


@dataclass(frozen=True)
class AuthenticatedAccount:
    user_id: str
    username: str


class AccountService:
    """一个数据库文件内管理账号、会话及追加式积分账本。"""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if os.name != "nt":
                self.database_path.parent.chmod(0o700)
        except OSError:
            pass
        self._initialize()
        try:
            if os.name != "nt":
                self.database_path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_key TEXT NOT NULL UNIQUE,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    balance_tokens INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    created_at TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    entry_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    event_type TEXT NOT NULL,
                    delta_tokens INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    reference_id TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    reserved_tokens INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    settled_at TEXT
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    action TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    window_started INTEGER NOT NULL,
                    hits INTEGER NOT NULL,
                    PRIMARY KEY (action, subject_hash)
                );
                """
            )

    @staticmethod
    def _password_hash(password: str, salt: bytes, iterations: int = PASSWORD_ITERATIONS) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _rate_subject_hash(subject: str) -> str:
        # Rate-limit keys are one-way digests; the clear client address is not stored.
        return hashlib.sha256(subject.encode("utf-8", errors="replace")).hexdigest()

    def _check_rate_limit(
        self,
        connection: sqlite3.Connection,
        action: str,
        subject: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        now = int(time.time())
        connection.execute("DELETE FROM rate_limits WHERE window_started < ?", (now - 7 * 24 * 60 * 60,))
        subject_hash = self._rate_subject_hash(subject or "unknown")
        row = connection.execute(
            "SELECT window_started, hits FROM rate_limits WHERE action = ? AND subject_hash = ?",
            (action, subject_hash),
        ).fetchone()
        if row is None or now - int(row["window_started"]) >= window_seconds:
            connection.execute(
                "INSERT INTO rate_limits(action, subject_hash, window_started, hits) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(action, subject_hash) DO UPDATE SET window_started=excluded.window_started, hits=1",
                (action, subject_hash, now),
            )
            return
        if int(row["hits"]) >= limit:
            raise RateLimitError("请求过于频繁，请稍后再试。")
        connection.execute(
            "UPDATE rate_limits SET hits = hits + 1 WHERE action = ? AND subject_hash = ?",
            (action, subject_hash),
        )

    def _issue_session(self, connection: sqlite3.Connection, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (self._token_hash(token), user_id, utc_now(), now + SESSION_TTL_SECONDS),
        )
        return token

    @staticmethod
    def _account_payload(row: sqlite3.Row) -> dict[str, Any]:
        balance = int(row["balance_tokens"])
        return {
            "user_id": str(row["user_id"]),
            "username": str(row["username"]),
            "balance_tokens": balance,
            "credits": balance / TOKENS_PER_CREDIT,
            "welcome_credits": WELCOME_CREDITS,
            "tokens_per_credit": TOKENS_PER_CREDIT,
        }

    def register(self, username: str, password: str, *, client_key: str = "") -> dict[str, Any]:
        clean_username = username.strip()
        if not USERNAME_PATTERN.fullmatch(clean_username):
            raise AccountError("用户名需为 3–32 位英文字母、数字、点、下划线或连字符。")
        if not 8 <= len(password) <= 256 or "\x00" in password:
            raise AccountError("密码长度需为 8–256 个字符。")

        # 先写入 IP 限流计数，再做昂贵的密码哈希，避免注册接口被低成本算力耗尽。
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_rate_limit(
                    connection,
                    "register",
                    client_key,
                    limit=REGISTRATION_LIMIT_PER_IP_DAILY,
                    window_seconds=24 * 60 * 60,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt)
        user_id = uuid.uuid4().hex
        now_text = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO users(user_id, username, username_key, password_salt, password_hash, "
                    "password_iterations, balance_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        clean_username,
                        clean_username.casefold(),
                        salt,
                        password_hash,
                        PASSWORD_ITERATIONS,
                        WELCOME_TOKENS,
                        now_text,
                    ),
                )
                connection.execute(
                    "INSERT INTO credit_ledger(entry_id, user_id, event_type, delta_tokens, balance_after, created_at) "
                    "VALUES (?, ?, 'registration_grant', ?, ?, ?)",
                    (uuid.uuid4().hex, user_id, WELCOME_TOKENS, WELCOME_TOKENS, now_text),
                )
                token = self._issue_session(connection, user_id)
                account = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise AccountError("用户名已被注册。") from exc
            except Exception:
                connection.rollback()
                raise
        return {"token": token, "account": self._account_payload(account)}

    def login(self, username: str, password: str, *, client_key: str = "") -> dict[str, Any]:
        normalized = username.strip().casefold()[:64]
        if not normalized or len(password) > 256:
            raise AuthenticationError("用户名或密码不正确。")
        rate_subject = f"{client_key}|{normalized}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_rate_limit(
                    connection, "login", rate_subject, limit=20, window_seconds=15 * 60
                )
                row = connection.execute(
                    "SELECT * FROM users WHERE username_key = ?", (normalized,)
                ).fetchone()
                if row is None:
                    salt = b"YJL-login-dummy-salt"
                    candidate = self._password_hash(password, salt)
                    hmac.compare_digest(candidate, hashlib.sha256(salt + password.encode("utf-8")).digest())
                    connection.commit()
                    raise AuthenticationError("用户名或密码不正确。")
                candidate = self._password_hash(
                    password, bytes(row["password_salt"]), int(row["password_iterations"])
                )
                if not hmac.compare_digest(candidate, bytes(row["password_hash"])):
                    connection.commit()
                    raise AuthenticationError("用户名或密码不正确。")
                connection.execute(
                    "DELETE FROM rate_limits WHERE action = 'login' AND subject_hash = ?",
                    (self._rate_subject_hash(rate_subject),),
                )
                token = self._issue_session(connection, str(row["user_id"]))
                connection.commit()
                return {"token": token, "account": self._account_payload(row)}
            except (AuthenticationError, RateLimitError):
                if connection.in_transaction:
                    connection.commit()
                raise
            except Exception:
                connection.rollback()
                raise

    def authenticate(self, token: str) -> AuthenticatedAccount:
        if not token or len(token) > 128:
            raise AuthenticationError("需要登录。")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT u.user_id, u.username, s.expires_at, s.revoked_at FROM sessions s "
                "JOIN users u ON u.user_id = s.user_id WHERE s.token_hash = ?",
                (self._token_hash(token),),
            ).fetchone()
        if row is None or row["revoked_at"] is not None or int(row["expires_at"]) <= int(time.time()):
            raise AuthenticationError("登录已过期，请重新登录。")
        return AuthenticatedAccount(str(row["user_id"]), str(row["username"]))

    def logout(self, token: str) -> None:
        if not token:
            return
        with self._connection() as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (utc_now(), self._token_hash(token)),
            )

    def refresh(self, token: str) -> dict[str, Any]:
        account = self.authenticate(token)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                    (utc_now(), self._token_hash(token)),
                )
                new_token = self._issue_session(connection, account.user_id)
                row = connection.execute("SELECT * FROM users WHERE user_id = ?", (account.user_id,)).fetchone()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"token": new_token, "account": self._account_payload(row)}

    def account(self, user_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise AuthenticationError("账号不存在。")
        return self._account_payload(row)

    def available_tokens(self, user_id: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT balance_tokens FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row["balance_tokens"]) if row else 0

    def reserve_tokens(self, user_id: str, token_count: int) -> str:
        amount = max(0, int(token_count))
        reservation_id = uuid.uuid4().hex
        now_text = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT balance_tokens FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
                if row is None:
                    raise AuthenticationError("账号不存在。")
                balance = int(row["balance_tokens"])
                if amount <= 0 or amount > balance:
                    raise InsufficientCredits("积分余额不足，请等待补充额度或联系管理员。")
                remaining = balance - amount
                connection.execute(
                    "UPDATE users SET balance_tokens = ? WHERE user_id = ?", (remaining, user_id)
                )
                connection.execute(
                    "INSERT INTO reservations(reservation_id, user_id, reserved_tokens, status, created_at) "
                    "VALUES (?, ?, ?, 'reserved', ?)",
                    (reservation_id, user_id, amount, now_text),
                )
                connection.execute(
                    "INSERT INTO credit_ledger(entry_id, user_id, event_type, delta_tokens, balance_after, reference_id, created_at) "
                    "VALUES (?, ?, 'model_usage_reserved', ?, ?, ?, ?)",
                    (uuid.uuid4().hex, user_id, -amount, remaining, reservation_id, now_text),
                )
                connection.commit()
                return reservation_id
            except Exception:
                connection.rollback()
                raise

    def settle_tokens(
        self,
        user_id: str,
        reservation_id: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> int:
        now_text = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                reservation = connection.execute(
                    "SELECT * FROM reservations WHERE reservation_id = ? AND user_id = ?",
                    (reservation_id, user_id),
                ).fetchone()
                if reservation is None:
                    raise AccountError("模型用量预留记录不存在。")
                if reservation["status"] != "reserved":
                    row = connection.execute(
                        "SELECT balance_tokens FROM users WHERE user_id = ?", (user_id,)
                    ).fetchone()
                    connection.commit()
                    return int(row["balance_tokens"])
                reserved = int(reservation["reserved_tokens"])
                usage_reported = prompt_tokens is not None and completion_tokens is not None
                prompt = max(0, int(prompt_tokens)) if prompt_tokens is not None else None
                completion = max(0, int(completion_tokens)) if completion_tokens is not None else None
                actual = prompt + completion if usage_reported else reserved
                delta = reserved - actual
                user = connection.execute(
                    "SELECT balance_tokens FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
                balance = int(user["balance_tokens"])
                remaining = balance + delta
                connection.execute(
                    "UPDATE users SET balance_tokens = ? WHERE user_id = ?", (remaining, user_id)
                )
                connection.execute(
                    "UPDATE reservations SET status = 'settled', settled_at = ? WHERE reservation_id = ?",
                    (now_text, reservation_id),
                )
                connection.execute(
                    "INSERT INTO credit_ledger(entry_id, user_id, event_type, delta_tokens, balance_after, reference_id, prompt_tokens, completion_tokens, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        uuid.uuid4().hex,
                        user_id,
                        "model_usage_settled" if usage_reported else "model_usage_estimated",
                        delta,
                        remaining,
                        reservation_id,
                        prompt,
                        completion,
                        now_text,
                    ),
                )
                connection.commit()
                return remaining
            except Exception:
                connection.rollback()
                raise

    def release_tokens(self, user_id: str, reservation_id: str) -> int:
        now_text = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                reservation = connection.execute(
                    "SELECT * FROM reservations WHERE reservation_id = ? AND user_id = ?",
                    (reservation_id, user_id),
                ).fetchone()
                if reservation is None or reservation["status"] != "reserved":
                    row = connection.execute(
                        "SELECT balance_tokens FROM users WHERE user_id = ?", (user_id,)
                    ).fetchone()
                    connection.commit()
                    return int(row["balance_tokens"]) if row else 0
                amount = int(reservation["reserved_tokens"])
                user = connection.execute(
                    "SELECT balance_tokens FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
                remaining = int(user["balance_tokens"]) + amount
                connection.execute(
                    "UPDATE users SET balance_tokens = ? WHERE user_id = ?", (remaining, user_id)
                )
                connection.execute(
                    "UPDATE reservations SET status = 'released', settled_at = ? WHERE reservation_id = ?",
                    (now_text, reservation_id),
                )
                connection.execute(
                    "INSERT INTO credit_ledger(entry_id, user_id, event_type, delta_tokens, balance_after, reference_id, created_at) "
                    "VALUES (?, ?, 'model_usage_released', ?, ?, ?, ?)",
                    (uuid.uuid4().hex, user_id, amount, remaining, reservation_id, now_text),
                )
                connection.commit()
                return remaining
            except Exception:
                connection.rollback()
                raise

    def ledger(self, user_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT event_type, delta_tokens, balance_after, reference_id, prompt_tokens, completion_tokens, created_at "
                "FROM credit_ledger WHERE user_id = ? ORDER BY rowid DESC LIMIT 100",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]


class UsageMeter:
    """绑定一名用户的请求预算回调，供同步和后台模型调用复用。"""

    def __init__(self, service: AccountService, user_id: str):
        self.service = service
        self.user_id = user_id

    def reserve(self, token_count: int) -> str:
        return self.service.reserve_tokens(self.user_id, token_count)

    @property
    def available_tokens(self) -> int:
        return self.service.available_tokens(self.user_id)

    def settle(
        self,
        reservation_id: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> None:
        self.service.settle_tokens(self.user_id, reservation_id, prompt_tokens, completion_tokens)

    def release(self, reservation_id: str) -> None:
        self.service.release_tokens(self.user_id, reservation_id)


__all__ = [
    "AccountError",
    "AccountService",
    "AuthenticatedAccount",
    "AuthenticationError",
    "InsufficientCredits",
    "RateLimitError",
    "UsageMeter",
    "TOKENS_PER_CREDIT",
    "WELCOME_CREDITS",
    "WELCOME_TOKENS",
]
