"""LinuxCNC's own credential: the G-code's user M-code programs
(``machine_config/m_codes/M104`` ... ``M190``, the heater / fan / LED /
print-tuning helpers) call the machine backend over HTTP while a program
runs. Since logins (#131) an anonymous call is a viewer and was refused,
the helper failed and LinuxCNC ended the program at its first ``M106``.

The helpers send this token as ``Authorization: Bearer``;
:func:`core.auth.current_user` gives it the ``user`` role (operate, never
configure). The system service passes it to the LinuxCNC it launches
(``LINUXCNC_UI_MACHINE_TOKEN``, inherited by the M-code programs); the
helpers fall back to the file (``backend/data/machine.token``, readable by
the owner only) for a LinuxCNC started by hand.
"""
from __future__ import annotations

import hmac
import os
from functools import lru_cache

from core.secret_file import DATA_DIR, read_or_create

ENV = "LINUXCNC_UI_MACHINE_TOKEN"
TOKEN_FILE = DATA_DIR / "machine.token"
#: The name the machine's own calls show under (logs, the agent's view).
MACHINE_USER = "linuxcnc"


@lru_cache(maxsize=1)
def machine_token() -> str:
    from_env = os.environ.get(ENV, "").strip()
    if from_env:
        return from_env
    return read_or_create(TOKEN_FILE)


def is_machine_token(presented: str) -> bool:
    return bool(presented) and hmac.compare_digest(presented.encode(), machine_token().encode())


__all__ = ["ENV", "MACHINE_USER", "TOKEN_FILE", "is_machine_token", "machine_token"]
