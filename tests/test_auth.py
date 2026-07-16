from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.auth import AuthStore


def test_passwords_and_session_tokens_are_not_stored_in_plaintext(tmp_path: Path) -> None:
    database = tmp_path / "auth.db"
    store = AuthStore(database)
    user = store.create_user("reader_01", "UniquePass123!")
    token = store.create_session(user.id)

    with sqlite3.connect(database) as connection:
        password_hash = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        token_hash = connection.execute("SELECT token_hash FROM sessions").fetchone()[0]

    assert password_hash.startswith("$argon2id$")
    assert "UniquePass123!" not in password_hash
    assert token != token_hash
    assert store.authenticate("READER_01", "UniquePass123!") == user
    assert store.user_for_session(token) == user
    store.revoke_session(token)
    assert store.user_for_session(token) is None


def test_duplicate_username_is_case_insensitive(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.db")
    store.create_user("Reader", "UniquePass123!")
    with pytest.raises(ValueError, match="已被注册"):
        store.create_user("reader", "AnotherPass123!")


def test_existing_database_is_migrated_for_admin_fields(tmp_path: Path) -> None:
    database = tmp_path / "auth.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL, username_key TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, created_at TEXT NOT NULL
            )
            """
        )
    store = AuthStore(database)
    user = store.create_user("migrated_user", "StrongPass123!")
    assert user.is_admin is False
    assert user.is_active is True
