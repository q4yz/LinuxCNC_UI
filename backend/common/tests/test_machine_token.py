"""LinuxCNC's own M-code programs authenticate with the machine token."""
from __future__ import annotations

import os
import stat

from starlette.requests import HTTPConnection

from core import machine_token as module
from core.auth import GUEST, current_user
from core.permissions import Level, Permission, level


def _conn(header):
    headers = [(b"authorization", header.encode())] if header else []
    return HTTPConnection({"type": "http", "headers": headers})


def test_created_once_and_private(tmp_path, monkeypatch):
    monkeypatch.delenv(module.ENV, raising=False)
    monkeypatch.setattr(module, "TOKEN_FILE", tmp_path / "machine.token")
    module.machine_token.cache_clear()
    try:
        first = module.machine_token()
        assert len(first) >= 32
        assert stat.S_IMODE(os.stat(module.TOKEN_FILE).st_mode) == 0o600
        module.machine_token.cache_clear()
        assert module.machine_token() == first
        assert module.is_machine_token(first) and not module.is_machine_token("") and not module.is_machine_token("x")
    finally:
        module.machine_token.cache_clear()


def test_the_machine_token_operates_but_never_configures(monkeypatch):
    monkeypatch.setenv(module.ENV, "machine-secret")
    module.machine_token.cache_clear()
    try:
        user = current_user(_conn("Bearer machine-secret"))
        assert (user.name, user.role) == (module.MACHINE_USER, "user")
        for allowed in (Permission.HEATERS, Permission.OUTPUTS, Permission.MACHINE_TUNE):
            assert level(user.role, allowed) is Level.ALLOW
        assert level(user.role, Permission.CONFIG_WRITE) is Level.DENY
        assert current_user(_conn("Bearer other")) == GUEST
    finally:
        module.machine_token.cache_clear()
