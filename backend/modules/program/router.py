"""Program lifecycle HTTP router.

Hosts the program endpoints that used to live in
``routers/machine.py`` (run / stop / pause / resume / parse / load).
The router is mounted by the registry under
``/api/v1/modules/program``.

The lifecycle mirrors LinuxCNC's canonical two-step flow:

1. ``POST /load {filename}`` calls ``command.program_open(path)``
   which sets ``stat.file`` while leaving ``interp_state`` at
   ``INTERP_IDLE``. The "loaded" state is implicit (file is set,
   interpreter is idle) — see :func:`hardware.linuxcnc_mock.is_program_loaded`.

   On real LinuxCNC ``program_open`` is asynchronous: the call
   returns immediately but the interpreter needs a few NML ticks
   to actually populate ``stat.file``. We therefore pass a non-zero
   ``cmd_timeout`` to :func:`hardware.connection.execute_sync_cmd`
   (so ``wait_complete`` blocks until the command is processed) and
   additionally poll ``stat.file`` until it matches the requested
   path — the same pattern the upstream LinuxCNC Python example
   documents. If the file does not appear within the budget we
   raise ``504 Gateway Timeout`` so the operator knows the load
   never landed.
2. ``POST /run`` calls ``auto(AUTO_RUN, line)`` which flips
   ``interp_state`` to ``INTERP_READING``. The endpoint refuses
   with ``409 Conflict`` when no file has been loaded so the
   frontend cannot accidentally start the interpreter on an empty
   program.

The dedicated UI for this module lands in Phase 3 per the roadmap;
this router is the contract that backs the dashboard widget's
"Loaded" branch.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, get_machine_stat, linuxcnc, linuxcnc_mock
from services import (
    get_program_service,
    raise_bad_request,
    raise_conflict,
    raise_not_found,
)

logger = logging.getLogger("backend.modules.program.router")


# ---------------------------------------------------------------------------
# Line-count cache
# ---------------------------------------------------------------------------
#
# Real LinuxCNC's ``linuxcnc.stat`` exposes ``current_line`` /
# ``motion_line`` but never ``total_lines``. We derive the total at
# ``program_open`` time by reading the file once and caching the count
# keyed by the absolute path LinuxCNC committed into ``stat.file``.
# The mock already stamps ``total_lines`` on ``_machine_state`` so the
# cache entry is just a mirror of the mock's value for that driver.
#
# The cache is intentionally small (one entry per loaded file); a
# single program run only ever has one file loaded, but the router
# does not enforce that and a multi-file batch is conceivable.
_TOTAL_LINES_CACHE: Dict[str, int] = {}


class StatusResponse(BaseModel):
    """Generic response model for endpoints that return a status string."""

    status: str = Field(
        ...,
        description=(
            "Outcome reported by the hardware layer (e.g., 'success')"
        ),
    )


class ProgramProgressResponse(BaseModel):
    """Progress snapshot for the active G-code program.

    Returned by ``GET /api/v1/modules/program/progress`` so the dashboard
    can poll once a second without saturating NML. ``total_lines``
    comes from a backend-side line-count cache populated when the
    file is loaded; ``current_line`` and ``motion_line`` come
    straight from ``linuxcnc.stat``. ``interp_state`` mirrors the
    raw integer so the widget can decide whether to keep polling.
    """

    current_line: int = Field(
        ...,
        ge=0,
        description=(
            "Line the RS274NGC interpreter is currently reading. "
            "Mirrors ``stat.current_line``."
        ),
    )
    motion_line: int = Field(
        ...,
        ge=0,
        description=(
            "Source line motion is currently executing. Mirrors "
            "``stat.motion_line``; ``0`` when the interpreter is idle."
        ),
    )
    total_lines: int = Field(
        ...,
        ge=0,
        description=(
            "Total line count of the loaded G-code file, populated "
            "from a backend-side cache at ``program_open`` time. "
            "``0`` when no file is loaded or the file was unreadable."
        ),
    )
    file: str = Field(
        ...,
        description=(
            "Absolute path of the loaded G-code file (``stat.file``) "
            "or empty string when nothing is loaded."
        ),
    )
    interp_state: int = Field(
        ...,
        description=(
            "Current ``linuxcnc.INTERP_*`` state. ``1`` IDLE, "
            "``2`` READING, ``3`` PAUSED, ``4`` WAITING."
        ),
    )


class ParseResponse(BaseModel):
    """Response model for the Klipper-to-LinuxCNC parser trigger."""

    status: str = Field(..., description="Outcome of the parser trigger")
    message: str = Field(..., description="Human-readable status message")


router = APIRouter(tags=["modules:program"])

class LoadProgramRequest(BaseModel):
    filename: str




@router.post(
    "/run",
    summary="Run Program",
    description=(
        "Start or resume the loaded G-code program from a specific "
        "line. Requires ``POST /load`` to have been called first "
        "with a valid filename; otherwise returns ``409 Conflict``."
    ),
    operation_id="runProgram",
    response_model=StatusResponse,
)
def run_program(line_number: int = 0) -> StatusResponse:
    """Start the loaded G-code program.

    Mirrors LinuxCNC's two-step contract: the ``program_open`` call
    (handled by ``POST /load``) must have set ``stat.file`` before
    the interpreter can be told to start. Without a loaded file we
    return ``409 Conflict`` so the frontend can surface a clear
    "no program loaded" message instead of the interpreter silently
    reading nothing.
    """
    if not linuxcnc_mock.is_program_loaded():
        raise_conflict("No program loaded. Call POST /load first.")
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_RUN", 0), line_number
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/stop",
    summary="Stop Program",
    description="Stop/abort the currently running program.",
    operation_id="stopProgram",
    response_model=StatusResponse,
)
def stop_program() -> StatusResponse:
    """Stop/abort the currently running program."""
    result = execute_sync_cmd("abort")
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/unload",
    summary="Unload Program",
    description=(
        "Explicitly clear the file pointer from the interpreter. "
        "Unlike ``POST /stop``, which only aborts the active move, "
        "this endpoint closes the loaded program so the operator "
        "lands in a pure Idle state."
    ),
    operation_id="unloadProgram",
    response_model=StatusResponse,
)
def unload_program() -> StatusResponse:
    """Clear the file pointer from the interpreter.

    The frontend's state-machine facade computes ``SystemState.LOADED``
    from the file pointer being non-empty. Without this endpoint, the
    only way to clear the loaded state is to load a different file
    (which replaces the pointer) — the ``POST /stop`` endpoint only
    aborts the active move and leaves the file open. This endpoint
    gives the operator a true "Unload" button that lands them in
    pure Idle without a follow-up load.

    On real LinuxCNC the ``command`` channel has no
    ``program_unload`` method, so we fall back to the canonical
    "clear the loaded file" verb: ``program_open("")``. The mock
    accepts the empty string as a valid path and clears its
    ``_machine_state.file`` field; on the real driver the
    interpreter commits the empty file pointer within the same
    ``wait_complete`` window as a normal ``program_open``.
    """
    # Same wait budget as ``load_program`` so the next telemetry
    # tick observes ``stat.file == ""`` before we return.
    execute_sync_cmd("program_open", LOAD_TIMEOUT_S, "")
    # The cached line count is meaningless once the file pointer is
    # cleared — drop the whole map so a follow-up ``/progress`` does
    # not surface a stale total for a file that is no longer loaded.
    _clear_total_lines_cache()
    return StatusResponse(status="success")


@router.post(
    "/pause",
    summary="Pause Program",
    description="Pause the currently running program.",
    operation_id="pauseProgram",
    response_model=StatusResponse,
)
def pause_program() -> StatusResponse:
    """Pause the currently running program."""
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_PAUSE", 1)
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/resume",
    summary="Resume Program",
    description="Resume a paused program.",
    operation_id="resumeProgram",
    response_model=StatusResponse,
)
def resume_program() -> StatusResponse:
    """Resume a paused program."""
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_RESUME", 2)
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/parse",
    summary="Trigger Parser",
    description=(
        "Manually trigger the Klipper-to-LinuxCNC configuration "
        "parser."
    ),
    operation_id="triggerParser",
    response_model=ParseResponse,
)
def trigger_parser() -> ParseResponse:
    """Trigger the parser (mocked as a 1 s delay in v1)."""
    logger.info("Triggering Klipper-to-LinuxCNC parser...")
    time.sleep(1)  # mock delay
    return ParseResponse(status="success", message="Parsing complete")


"""Time budget (in seconds) for ``POST /load`` to wait for the file
to actually appear in LinuxCNC's ``stat.file`` after ``program_open``.
The bound is loose — a slow interpreter (large file, slow disk)
should still have time to commit — but tight enough that an
unresponsive runtime surfaces as ``504 Gateway Timeout`` rather than
a stale success.
"""
LOAD_TIMEOUT_S = 5.0


def _count_lines(path: str) -> int:
    """Return the line count of ``path`` or ``0`` if it cannot be read.

    Real LinuxCNC never reports a total-line count, so the dashboard
    cannot render a meaningful percentage without it. We read the
    file once at load time and cache the count keyed by path; this
    helper is the single place that touches the filesystem so the
    ``try/except`` boundary is easy to reason about.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Could not count lines in %s: %s", path, exc)
        return 0
    if not text:
        return 0
    # ``splitlines`` swallows the trailing newline of the last line,
    # matching LinuxCNC's own line-counter convention. An empty file
    # becomes ``[]`` which we already covered with the early return.
    return len(text.splitlines())


def _clear_total_lines_cache() -> None:
    """Drop every cached line count.

    Called from the abort path so a follow-up run cannot accidentally
    read a stale total for a file that has been replaced.
    """
    _TOTAL_LINES_CACHE.clear()


def _stat_file_path() -> str:
    """Read ``stat.file`` from whichever stat channel is reachable.

    The helper prefers the live LinuxCNC channel (``get_machine_stat``)
    so the predicate works for both real and mock drivers: the mock's
    :class:`stat` class exposes the same ``file`` attribute that the
    real ``linuxcnc.stat`` populates, so a single read covers both
    surfaces. ``None`` means the channel is not yet connected; the
    caller treats that as "not loaded yet" and keeps polling.

    We call :meth:`stat.poll` first so the cached snapshot reflects
    the latest ``_machine_state.file`` (the connection layer caches
    the ``stat`` instance for the lifetime of the channel; without
    an explicit poll the cached value lingers across ``program_open``
    calls and the predicate reads stale data).
    """
    stat = get_machine_stat()
    if stat is None:
        return ""
    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()
    return str(getattr(stat, "file", "") or "")


def _await_load(target_path) -> None:
    """Poll ``stat.file`` until it matches ``target_path`` or the budget runs out.

    On real LinuxCNC the ``program_open`` command returns via the
    NML queue before the interpreter actually finishes loading the
    file. Without this loop ``POST /run`` would race ahead and
    raise ``409 Conflict`` even when the load succeeded. The mock
    updates ``stat.file`` synchronously, so the loop also exits on
    the first iteration in mock mode.
    """
    import time as _time
    target_str = str(target_path)
    deadline = _time.monotonic() + LOAD_TIMEOUT_S
    while True:
        current = _stat_file_path()
        if current and current == target_str:
            return
        if _time.monotonic() >= deadline:
            # 504 Gateway Timeout — LinuxCNC is connected but the
            # interpreter never reported ``stat.file``. Outside the
            # three helpers' scope so we keep the inline form.
            raise HTTPException(
                status_code=504,
                detail=(
                    f"LinuxCNC did not load '{target_str}' within "
                    f"{LOAD_TIMEOUT_S:.1f}s after program_open"
                ),
            )
        _time.sleep(0.05)


@router.post(
    "/load",
    summary="Load G-Code Program",
    description=(
        "Open a previously uploaded G-code file in the LinuxCNC "
        "interpreter. The file must live under the upload root "
        "served by ``routers/files.py``; returns ``404`` if the "
        "filename is unknown and ``400`` if the path fails the "
        "``safe_join`` invariant. After this call succeeds the "
        "program is in the loaded state (``stat.file`` set, "
        "``interp_state`` is ``INTERP_IDLE``); the next "
        "``POST /run`` starts it."
    ),
    operation_id="loadProgram",
    response_model=StatusResponse,
)
def load_program(payload: LoadProgramRequest) -> StatusResponse:
    """Open a G-code file in the interpreter (the load step).

    The filename is validated against the upload root using
    :meth:`ProgramFileService.safe_join` so a client cannot ask the
    mock to open an arbitrary path on disk. The forward to
    ``program_open`` runs with a non-zero ``cmd_timeout`` so the
    connection layer's ``wait_complete`` blocks until the NML queue
    drains; on top of that we poll ``stat.file`` to confirm the
    interpreter has actually populated the loaded file pointer. On
    real LinuxCNC ``program_open`` returns before the load is
    visible in ``stat``; without the poll the next ``POST /run``
    would race ahead and return ``409``.
    """
    logger.info("Loading G-code program: %s", payload.filename)

    service = get_program_service()
    try:
        target = service.safe_join(payload.filename)
    except ValueError as exc:
        raise_bad_request(str(exc))
    if not target.exists():
        raise_not_found(
            f"G-code file '{payload.filename}' not found in upload root"
        )

    execute_sync_cmd("program_open", LOAD_TIMEOUT_S, str(target))
    # Wait for the interpreter to commit the load. The mock's stat
    # is in sync with ``program_open`` so the loop returns
    # immediately; real LinuxCNC needs a few NML ticks.
    _await_load(target)
    # Cache the line count so ``GET /progress`` can return a real
    # denominator. Real LinuxCNC never reports ``total_lines``; the
    # mock stamps a 1000-line placeholder but its file pointer is
    # the absolute path, so caching by path keeps both drivers
    # consistent. We cache **after** the load commits so a slow
    # interpreter cannot cache a total for a file the interpreter
    # hasn't actually loaded yet.
    _TOTAL_LINES_CACHE[str(target)] = _count_lines(str(target))
    return StatusResponse(status="success")


@router.get(
    "/progress",
    summary="Get Program Progress",
    description=(
        "Return a 1 Hz-friendly snapshot of the active program's "
        "progress: ``current_line`` and ``motion_line`` from "
        "``linuxcnc.stat``, plus the cached ``total_lines`` for the "
        "loaded file. Cheap enough for the dashboard to poll once a "
        "second without saturating NML."
    ),
    operation_id="getProgramProgress",
    response_model=ProgramProgressResponse,
)
def get_program_progress() -> ProgramProgressResponse:
    """Return the active program's progress snapshot.

    Reads from the cached NML stat channel so the response stays
    consistent with ``stat.poll()`` consumed elsewhere. ``current_line``
    and ``motion_line`` are read with ``getattr`` defaults because
    older mock revisions did not populate ``motion_line`` and a
    fresh connection can briefly return ``None`` for either field
    before the first poll lands.

    ``total_lines`` comes from :data:`_TOTAL_LINES_CACHE` keyed by the
    interpreter's ``stat.file``. The cache is populated by ``POST /load``
    and cleared by ``POST /unload`` so a stale total can never leak
    across runs.
    """
    stat = get_machine_stat()
    file_path = ""
    current_line = 0
    motion_line = 0
    interp_state = int(getattr(linuxcnc, "INTERP_IDLE", 1))
    if stat is not None:
        poll = getattr(stat, "poll", None)
        if callable(poll):
            poll()
        file_path = str(getattr(stat, "file", "") or "")
        current_line = int(getattr(stat, "current_line", 0) or 0)
        motion_line = int(getattr(stat, "motion_line", 0) or 0)
        interp_state = int(getattr(stat, "interp_state", interp_state) or interp_state)

    total_lines = _TOTAL_LINES_CACHE.get(file_path, 0)
    return ProgramProgressResponse(
        current_line=max(0, current_line),
        motion_line=max(0, motion_line),
        total_lines=max(0, total_lines),
        file=file_path,
        interp_state=interp_state,
    )


__all__ = [
    "router",
    "run_program",
    "stop_program",
    "unload_program",
    "pause_program",
    "resume_program",
    "trigger_parser",
    "load_program",
    "get_program_progress",
    "StatusResponse",
    "ProgramProgressResponse",
    "ParseResponse",
    "LoadProgramRequest",
]
