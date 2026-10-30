"""Авторизация и сессии пользователей (SQLite, PBKDF2-HMAC-SHA256).

Демо-пользователь (config.DEMO_USER / config.DEMO_PASSWORD) создаётся
автоматически при первом создании базы.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app import config

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16
_DEMO_FULL_NAME = "Демонстрационный пользователь"


class AuthService:
    """Регистрация пользователей, вход по паролю, сессионные токены."""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else Path(config.USERS_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ensure_demo_user()

    # ---------- служебные методы ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _tx(self):
        """Соединение с авто-commit и гарантированным закрытием."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._tx() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _hash_password(self, password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
        )
        return f"{salt.hex()}${digest.hex()}"

    def _verify_password(self, password: str, stored: str) -> bool:
        try:
            salt_hex, _ = stored.split("$", 1)
            salt = bytes.fromhex(salt_hex)
        except (ValueError, TypeError):
            return False
        candidate = self._hash_password(password, salt)
        return hmac.compare_digest(candidate, stored)

    def _insert_user(self, conn, username: str, password: str, full_name: str) -> None:
        salt = secrets.token_bytes(_SALT_BYTES)
        password_hash = self._hash_password(password, salt)
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (username, password_hash, full_name, self._now_iso()),
        )

    def _ensure_demo_user(self) -> None:
        """При первом создании БД добавляет демо-пользователя из config."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (config.DEMO_USER,)
            ).fetchone()
            if row is None:
                self._insert_user(
                    conn, config.DEMO_USER, config.DEMO_PASSWORD, _DEMO_FULL_NAME
                )

    def _purge_expired_sessions(self) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))

    # ---------- публичный интерфейс ----------

    def register(self, username: str, password: str, full_name: str) -> dict:
        """Регистрация нового пользователя.

        Возвращает {"ok": True} или {"ok": False, "error": "..."}.
        """
        username = (username or "").strip()
        full_name = (full_name or "").strip()
        if not _USERNAME_RE.fullmatch(username):
            return {
                "ok": False,
                "error": "Имя пользователя должно содержать 3–32 символа: "
                "латиницу, цифры и знак подчёркивания",
            }
        if not isinstance(password, str) or len(password) < 6:
            return {"ok": False, "error": "Пароль должен содержать не менее 6 символов"}
        if not full_name:
            return {"ok": False, "error": "Укажите полное имя"}
        with self._tx() as conn:
            exists = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if exists is not None:
                return {
                    "ok": False,
                    "error": "Пользователь с таким именем уже существует",
                }
            self._insert_user(conn, username, password, full_name)
        return {"ok": True}

    def login(self, username: str, password: str) -> Optional[str]:
        """Возвращает сессионный токен или None при неверных учётных данных."""
        self._purge_expired_sessions()
        username = (username or "").strip()
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None or not self._verify_password(password or "", row["password_hash"]):
            return None
        token = secrets.token_hex(32)
        expires_at = time.time() + float(config.SESSION_TTL_HOURS) * 3600
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token, row["id"], self._now_iso(), expires_at),
            )
        return token

    def user_of(self, token: str) -> Optional[dict]:
        """Возвращает {"username", "full_name"} для действующего токена, иначе None."""
        if not token:
            return None
        with self._tx() as conn:
            row = conn.execute(
                """
                SELECT s.expires_at, u.username, u.full_name
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token = ?
                """,
                (token,),
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < time.time():
            with self._tx() as conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return {"username": row["username"], "full_name": row["full_name"]}

    def logout(self, token: str) -> None:
        """Завершает сессию по токену."""
        if not token:
            return
        with self._tx() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
