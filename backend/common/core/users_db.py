"""User accounts (#131): a SQLite database both backends read.

``backend/data/users.db`` (``LINUXCNC_UI_USERS_DB`` overrides it). The
system backend creates and changes accounts; the machine backend only
reads them to check a session token (:mod:`core.session_token`).

An account is a name, a password (scrypt) and a role (``admin``,
``user`` or ``viewer``; :mod:`core.permissions`). ``token_version``
revokes every session token of the account when it changes (password
changed, "log out everywhere"); a deleted account's tokens fail too.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from core.secret_file import DATA_DIR

ENV = "LINUXCNC_UI_USERS_DB"
DEFAULT_PATH = DATA_DIR / "users.db"

#: The roles an account can have (the agent is not an account).
ACCOUNT_ROLES = ("admin", "user", "viewer")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
MIN_PASSWORD = 4
MAX_PASSWORD = 256

# scrypt cost: ~16 MiB, well under a second on a Raspberry Pi
_N, _R, _P = 2**14, 8, 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    token_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
)
"""


class UserError(ValueError):
    """An account change that is not allowed (shown to the operator)."""


@dataclass(frozen=True, slots=True)
class Account:
    name: str
    role: str
    token_version: int


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_PATTERN.match(name):
        raise UserError("User names are 1-64 letters, digits or _ . @ -")
    return name


def _check_password(password: str) -> str:
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise UserError(f"Passwords are {MIN_PASSWORD} to {MAX_PASSWORD} characters")
    return password


def _check_role(role: str) -> str:
    if role not in ACCOUNT_ROLES:
        raise UserError(f"Role must be one of {', '.join(ACCOUNT_ROLES)}")
    return role


class UserStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or os.environ.get(ENV) or DEFAULT_PATH)
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        if not self._ready:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_SCHEMA)
            conn.commit()
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            self._ready = True
        return conn

    def _query(self, sql: str, args: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, args).fetchall()
                conn.commit()
                return rows
            finally:
                conn.close()

    # -- reading ----------------------------------------------------------- #

    def has_accounts(self) -> bool:
        return bool(self._query("SELECT 1 FROM users LIMIT 1"))

    def get(self, name: str) -> Account | None:
        rows = self._query("SELECT name, role, token_version FROM users WHERE name = ?", (name,))
        if not rows:
            return None
        n, role, ver = rows[0]
        return Account(str(n), str(role), int(ver))  # type: ignore[call-overload]

    def list(self) -> list[Account]:
        rows = self._query("SELECT name, role, token_version FROM users ORDER BY name COLLATE NOCASE")
        return [Account(str(n), str(r), int(v)) for n, r, v in rows]  # type: ignore[call-overload]

    def authenticate(self, name: str, password: str) -> Account | None:
        rows = self._query("SELECT name, role, token_version, password_hash FROM users WHERE name = ?", (name or "",))
        if not rows:
            # same work as a real check: a wrong name takes as long as a wrong password
            verify_password(password or "", hash_password("x"))
            return None
        n, role, ver, stored = rows[0]
        if not verify_password(password or "", str(stored)):
            return None
        return Account(str(n), str(role), int(ver))  # type: ignore[call-overload]

    # -- changing ---------------------------------------------------------- #

    def create(self, name: str, password: str, role: str) -> Account:
        name, role = _check_name(name), _check_role(role)
        digest = hash_password(_check_password(password))
        try:
            self._query("INSERT INTO users (name, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                        (name, digest, role, time.time()))
        except sqlite3.IntegrityError:
            raise UserError(f"User '{name}' exists already") from None
        account = self.get(name)
        assert account is not None
        return account

    def create_first_admin(self, name: str, password: str) -> Account:
        """The first account (setup): only while there is none."""
        if self.has_accounts():
            raise UserError("An account exists already: log in as an admin to add users")
        return self.create(name, password, "admin")

    def set_password(self, name: str, password: str) -> None:
        """New password; every session token of the account ends."""
        digest = hash_password(_check_password(password))
        self._require(name)
        self._query("UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE name = ?",
                    (digest, name))

    def set_role(self, name: str, role: str) -> None:
        _check_role(role)
        account = self._require(name)
        if account.role == "admin" and role != "admin" and self._admins() <= 1:
            raise UserError("The last admin cannot lose the admin role")
        self._query("UPDATE users SET role = ? WHERE name = ?", (role, name))

    def revoke_sessions(self, name: str) -> None:
        self._require(name)
        self._query("UPDATE users SET token_version = token_version + 1 WHERE name = ?", (name,))

    def delete(self, name: str) -> None:
        account = self._require(name)
        if account.role == "admin" and self._admins() <= 1:
            raise UserError("The last admin cannot be deleted")
        self._query("DELETE FROM users WHERE name = ?", (name,))

    def _require(self, name: str) -> Account:
        account = self.get(name)
        if account is None:
            raise UserError(f"No user '{name}'")
        return account

    def _admins(self) -> int:
        return int(self._query("SELECT COUNT(*) FROM users WHERE role = 'admin'")[0][0])  # type: ignore[call-overload]


_STORE: UserStore | None = None


def get_user_store() -> UserStore:
    global _STORE
    if _STORE is None:
        _STORE = UserStore()
    return _STORE


def set_user_store(store: UserStore | None) -> None:
    """Tests: point both backends' checks at another database."""
    global _STORE
    _STORE = store


__all__ = [
    "ACCOUNT_ROLES", "Account", "UserError", "UserStore", "get_user_store", "hash_password", "set_user_store",
    "verify_password",
]
