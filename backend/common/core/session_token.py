"""Session tokens (#131): a JSON Web Token (HS256) naming an account.

``{"sub": <name>, "ver": <token_version>, "iat": <time>}``, signed with
a secret both backends share (``backend/data/session.secret``;
``LINUXCNC_UI_SESSION_SECRET`` overrides it). The token does not expire
— logging in once on a device is enough — and ends when the account's
``token_version`` moves on (password changed, "log out everywhere") or
the account is deleted. The role is read from the database on every
request, so a role change applies at once.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from functools import lru_cache

from core.secret_file import DATA_DIR, read_or_create
from core.users_db import Account, UserStore

ENV = "LINUXCNC_UI_SESSION_SECRET"
SECRET_FILE = DATA_DIR / "session.secret"
_HEADER = {"alg": "HS256", "typ": "JWT"}


@lru_cache(maxsize=1)
def _secret() -> bytes:
    return (os.environ.get(ENV, "").strip() or read_or_create(SECRET_FILE)).encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(signing_input: str) -> str:
    return _b64(hmac.new(_secret(), signing_input.encode(), hashlib.sha256).digest())


def issue(account: Account, *, now: float | None = None) -> str:
    payload = {"sub": account.name, "ver": account.token_version, "iat": int(now if now is not None else time.time())}
    signing_input = f"{_b64(json.dumps(_HEADER, separators=(',', ':')).encode())}." \
                    f"{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    return f"{signing_input}.{_sign(signing_input)}"


def verify(token: str, store: UserStore) -> Account | None:
    """The account the token belongs to, or None (forged, revoked, deleted)."""
    try:
        header_b64, payload_b64, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(f"{header_b64}.{payload_b64}")):
            return None
        if json.loads(_unb64(header_b64)).get("alg") != "HS256":
            return None
        payload = json.loads(_unb64(payload_b64))
        name, ver = payload["sub"], payload["ver"]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    account = store.get(str(name))
    if account is None or account.token_version != ver:
        return None
    return account


__all__ = ["ENV", "SECRET_FILE", "issue", "verify"]
