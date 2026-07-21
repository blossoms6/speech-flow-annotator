from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings


SESSION_COOKIE = "sfa_session"
SESSION_SECONDS = 14 * 24 * 60 * 60
GUEST_COOKIE = "sfa_guest"
GUEST_SECONDS = 30 * 24 * 60 * 60
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
GUEST_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
PASSWORD_HASHER = PasswordHasher()
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(24))


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    created_at: str
    is_admin: bool = False
    is_active: bool = True

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "created_at": self.created_at,
            "is_admin": self.is_admin,
            "is_active": self.is_active,
        }


class AuthStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.auth_db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_key TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS sessions_expires_at ON sessions(expires_at);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "is_admin" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
                )
            if "is_active" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                )

    @staticmethod
    def _username_parts(username: str) -> tuple[str, str]:
        display = username.strip()
        if not USERNAME_PATTERN.fullmatch(display):
            raise ValueError("用户名只能包含英文字母、数字和下划线，长度为3–32位。")
        return display, display.lower()

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8 or len(password) > 128:
            raise ValueError("密码长度必须为8–128位。")

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> AuthUser:
        return AuthUser(
            row["id"],
            row["username"],
            row["created_at"],
            bool(row["is_admin"]),
            bool(row["is_active"]),
        )

    def create_user(self, username: str, password: str, *, is_admin: bool = False) -> AuthUser:
        display, username_key = self._username_parts(username)
        self._validate_password(password)
        user = AuthUser(
            uuid.uuid4().hex,
            display,
            datetime.now(timezone.utc).isoformat(),
            is_admin=is_admin,
        )
        password_hash = PASSWORD_HASHER.hash(password)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users(
                        id, username, username_key, password_hash, created_at, is_admin, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        user.id,
                        user.username,
                        username_key,
                        password_hash,
                        user.created_at,
                        int(user.is_admin),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该用户名已被注册。") from exc
        return user

    def authenticate(self, username: str, password: str) -> AuthUser | None:
        _, username_key = self._username_parts(username)
        self._validate_password(password)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, password_hash, created_at, is_admin, is_active
                FROM users WHERE username_key = ?
                """,
                (username_key,),
            ).fetchone()
        encoded_hash = row["password_hash"] if row else DUMMY_HASH
        try:
            valid = PASSWORD_HASHER.verify(encoded_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            valid = False
        if not row or not valid or not row["is_active"]:
            return None
        if PASSWORD_HASHER.check_needs_rehash(encoded_hash):
            with self._connect() as connection:
                connection.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (PASSWORD_HASHER.hash(password), row["id"]),
                )
        return self._user_from_row(row)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (self._token_hash(token), user_id, now, now + SESSION_SECONDS),
            )
        return token

    def user_for_session(self, token: str | None) -> AuthUser | None:
        if not token:
            return None
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.username, users.created_at, users.is_admin,
                       users.is_active, sessions.expires_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                """,
                (self._token_hash(token),),
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] <= now or not row["is_active"]:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),)
                )
                return None
        return self._user_from_row(row)

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),))

    def user_by_username(self, username: str) -> AuthUser | None:
        _, username_key = self._username_parts(username)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, created_at, is_admin, is_active
                FROM users WHERE username_key = ?
                """,
                (username_key,),
            ).fetchone()
        return self._user_from_row(row) if row else None

    def user_by_id(self, user_id: str) -> AuthUser | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, created_at, is_admin, is_active
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return self._user_from_row(row) if row else None

    def list_users(self, query: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        pattern = f"%{query.strip().lower()}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT users.id, users.username, users.created_at, users.is_admin,
                       users.is_active, COUNT(sessions.token_hash) AS session_count
                FROM users
                LEFT JOIN sessions ON sessions.user_id = users.id AND sessions.expires_at > ?
                WHERE users.username_key LIKE ?
                GROUP BY users.id
                ORDER BY users.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (time.time(), pattern, limit, offset),
            ).fetchall()
        return [
            {
                **self._user_from_row(row).public(),
                "session_count": row["session_count"],
            }
            for row in rows
        ]

    def user_counts(self) -> dict[str, int]:
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN is_admin = 1 AND is_active = 1 THEN 1 ELSE 0 END) AS admins
                FROM users
                """
            ).fetchone()
            sessions = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE expires_at > ?", (now,)
            ).fetchone()[0]
        return {
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "admins": int(row["admins"] or 0),
            "sessions": int(sessions),
        }

    def set_user_active(self, user_id: str, active: bool) -> AuthUser:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET is_active = ? WHERE id = ?", (int(active), user_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(user_id)
            if not active:
                connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        user = self.user_by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def set_user_admin(self, user_id: str, is_admin: bool) -> AuthUser:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(user_id)
        user = self.user_by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return user


auth_store = AuthStore()


def create_guest_token() -> str:
    return secrets.token_urlsafe(32)


def guest_owner_id(token: str | None) -> str | None:
    if not token or not GUEST_TOKEN_PATTERN.fullmatch(token):
        return None
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    return f"guest:{digest}"
