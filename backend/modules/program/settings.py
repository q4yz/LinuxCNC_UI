"""Pydantic defaults model for the program module settings.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/program/settings``. New keys can be added in
later releases without breaking existing deployments — the store
merges the defaults underneath the persisted payload so a missing
key is filled in from this schema's defaults on every read.

Field semantics:

* ``load_timeout_ms`` — Upper bound on how long
  ``POST /api/v1/modules/program/load`` waits for ``stat.file`` to
  land after ``program_open`` returns. The mock resolves
  synchronously; the real LinuxCNC NML cycle takes a few ticks
  and a slow operator environment can blow past the default.
  ``50 ms`` is the historical value ``execute_sync_cmd`` was
  called with before this knob existed.
* ``parser_delay_ms`` — Synthetic delay the stub
  ``POST /api/v1/modules/program/parse`` endpoint sleeps for
  before replying ``success``. The Phase 3a implementation only
  pretends to parse; the value is preserved so a future
  implementation can keep the same UI feedback duration while
  swapping the real Klipper-to-LinuxCNC compiler behind it.
* ``allow_remote_paths`` — When ``False`` (default), the router
  rejects any ``filename`` field that escapes the canonical
  ``nc_files/`` root. When ``True``, the router accepts absolute
  paths — useful for CI / e2e tests that stage files outside
  the configured sandbox. Operators should leave this ``False``.

The Phase 3a program module has no dedicated settings UI — the
``settings_panel`` flag in :mod:`backend.modules.program.module`
stays ``False`` until the frontend gains a tab for it. The
SettingsStore endpoints still expose this schema so the four
canonical settings endpoints return a non-empty payload from
first boot (the registry contract).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProgramSettings(BaseModel):
    """User-tunable knobs for the program module.

    Attributes:
        load_timeout_ms: Maximum time ``POST /load`` waits for
            ``stat.file`` to land after ``program_open`` returns.
            Bounded to ``[100, 30_000]`` ms so a misconfiguration
            cannot make the loader hang for hours.
        parser_delay_ms: Synthetic delay the stub ``POST /parse``
            endpoint sleeps for before reporting success. Bounded
            to ``[0, 10_000]`` ms so an over-eager operator cannot
            freeze the dashboard for half a minute.
        allow_remote_paths: When ``True``, ``POST /load`` accepts
            absolute paths outside the ``nc_files/`` sandbox.
            Operators should leave this ``False``; CI / e2e setups
            are the documented use case.
    """

    load_timeout_ms: int = Field(
        default=2000,
        ge=100,
        le=30_000,
        description=(
            "Upper bound on the wait for stat.file after "
            "program_open returns. Milliseconds."
        ),
    )
    parser_delay_ms: int = Field(
        default=1000,
        ge=0,
        le=10_000,
        description=(
            "Synthetic delay the stub /parse endpoint sleeps for "
            "before replying success. Milliseconds."
        ),
    )
    allow_remote_paths: bool = Field(
        default=False,
        description=(
            "Allow POST /load to accept absolute paths outside the "
            "nc_files/ sandbox. CI / e2e only; operators should "
            "leave this False."
        ),
    )


__all__ = ["ProgramSettings"]