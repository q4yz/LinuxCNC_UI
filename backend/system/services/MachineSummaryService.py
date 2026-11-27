"""A short machine summary for the assistant, read fresh for every model
call (``services.AssistantChatService``).

The operator acts on the machine between messages (resets the E-stop,
homes, starts a print); without a fresh look the assistant answered
from what it had seen earlier ("the machine is in E-stop"). Each request
to the model now carries a ``<machine_state>`` block taken just before
it: the machine backend's state, homing, program and heaters, or that
LinuxCNC is not running. Short timeouts: a slow backend delays a reply
by at most a second or two.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from core.agent_token import agent_token
from services.AgentMcpService import DEFAULT_BACKENDS

TIMEOUT_S = 1.5
AXES = "XYZABCUVW"

_STATE_TEXT = {
    "offline": "offline (LinuxCNC not answering)",
    "estop": "E-STOP ENGAGED",
    "power_off": "E-stop released, machine power OFF",
    "idle": "ON, idle",
    "loaded": "ON, program loaded, idle",
    "running": "ON, program RUNNING",
    "paused": "ON, program PAUSED",
}


def _num(value: Any) -> str:
    return f"{value:.1f}" if isinstance(value, (int, float)) else "?"


def render(state: dict[str, Any] | None, snapshot: dict[str, Any] | None, now: float | None = None) -> str:
    """The block the model sees (``state``: ``GET /machine_state/state``,
    ``snapshot``: ``GET /base-thread/snapshot``; None = not reachable)."""
    stamp = time.strftime("%H:%M:%S", time.localtime(now if now is not None else time.time()))
    lines = [f'<machine_state taken="{stamp}">']
    if state is None:
        lines.append("LinuxCNC: not running (machine backend unreachable) - machine tools are unavailable.")
    else:
        code = str(state.get("state", ""))
        lines.append(f"State: {_STATE_TEXT.get(code, code or 'unknown')}")
        lines.append(f"E-stop: {'ENGAGED' if state.get('raw_estop') else 'released'}")
        homed = [AXES[i] for i, h in enumerate(state.get("homed") or []) if h and i < len(AXES)]
        lines.append(f"Homed: {' '.join(homed) if homed else 'none'}")
        lines.append(f"Loaded program: {state.get('file') or 'none'}")
    progress = (snapshot or {}).get("progress") or {}
    total = progress.get("total_lines") or 0
    if total and state is not None and state.get("state") in ("running", "paused"):
        current = progress.get("motion_line") or progress.get("current_line") or 0
        lines.append(f"Progress: line {current} of {total} ({100 * current / total:.0f} %)")
    heaters = [s for s in ((snapshot or {}).get("sensors") or {}).values() if isinstance(s, dict)]
    temps = []
    for s in heaters:
        if s.get("type") == "heater":
            target = s.get("target")
            temps.append(f"{s.get('id')} {_num(s.get('actual'))} °C (target {_num(target) if target else 'off'})")
        else:
            temps.append(f"{s.get('id')} {_num(s.get('actual'))} °C")
    if temps:
        lines.append("Temperatures: " + ", ".join(temps))
    lines.append("This is the machine right now; it supersedes anything seen earlier in the conversation.")
    lines.append("</machine_state>")
    return "\n".join(lines)


async def _get(client: httpx.AsyncClient, path: str) -> dict[str, Any] | None:
    try:
        response = await client.get(path)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


async def machine_summary(base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """The ``<machine_state>`` block, read now."""
    async with httpx.AsyncClient(
        base_url=base_url or DEFAULT_BACKENDS["machine"],
        headers={"Authorization": f"Bearer {agent_token()}"},
        timeout=TIMEOUT_S,
        transport=transport,
    ) as client:
        state, snapshot = await asyncio.gather(
            _get(client, "/api/v1/modules/machine_state/state"),
            _get(client, "/api/v1/base-thread/snapshot"),
        )
    return render(state, snapshot)


__all__ = ["machine_summary", "render"]
