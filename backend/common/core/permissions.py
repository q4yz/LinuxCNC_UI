"""Who may do what: permissions, roles, and the permission of every route.

One table, three uses:

* **enforcement** — :func:`core.auth.authorize` (a dependency on every
  route of both backends) looks the route up here and checks the
  caller's role; a route missing from the table is refused for every
  role but admin (fail closed);
* **documentation** — ``docs/reference/permissions.md`` is generated
  from it (:func:`permission_table_markdown`, kept in sync by a test);
* **the agent** — the MCP layer (later) offers the agent only the
  routes its role allows, and asks the operator first for the
  ``CONFIRM`` ones.

Who the caller is: :func:`core.auth.current_user` (accounts and
logins, #131).
"""
from __future__ import annotations

from enum import Enum
from typing import Mapping


class Permission(str, Enum):
    # -- reading ---------------------------------------------------------- #
    MACHINE_READ = "machine.read"  # state, positions, temperatures, I/O, progress
    CAMERA_VIEW = "camera.view"
    HAL_READ = "hal.read"  # HAL pins, the HAL editor, the scope
    FILES_READ = "files.read"  # G-code programs
    CONFIG_READ = "config.read"  # profiles, machine files, M-codes, the LinuxCNC log
    MACROS_READ = "macros.read"
    SETTINGS_READ = "settings.read"  # UI settings
    SYSTEM_READ = "system.read"  # version, releases, update status
    # -- running the machine -------------------------------------------- #
    MACHINE_ESTOP = "machine.estop"
    MACHINE_POWER = "machine.power"  # E-stop reset, on / off, mode
    MACHINE_MOTION = "machine.motion"  # home, MDI
    PROGRAM_RUN = "program.run"  # load, run, pause, resume, stop
    MACHINE_TUNE = "machine.tune"  # live Z offset, flow, speed, objects, mesh on/off
    HEATERS = "heaters.control"  # heater targets, extruder, spindle
    OUTPUTS = "outputs.control"  # fans, output pins, LEDs
    MACROS_RUN = "macros.run"
    CALIBRATION_RUN = "calibration.run"  # calibrations, bed mesh probing, Z tilt
    # -- changing things ------------------------------------------------- #
    FILES_WRITE = "files.write"
    CALIBRATION_MANAGE = "calibration.manage"  # reminders, reset to profile values
    BEDMESH_MANAGE = "bedmesh.manage"  # saved meshes
    SETTINGS_WRITE = "settings.write"
    MACROS_WRITE = "macros.write"
    SESSION_CONTROL = "session.control"  # start / stop / switch LinuxCNC
    HAL_WRITE = "hal.write"
    CONFIG_WRITE = "config.write"  # profiles, generation, board upload, MCU reset
    SYSTEM_UPDATE = "system.update"
    USERS_MANAGE = "users.manage"
    #: Approve or deny the assistant's actions — never the agent itself.
    AGENT_APPROVE = "agent.approve"
    #: Chat with the in-app assistant.
    AGENT_CHAT = "agent.chat"
    #: Log in, see who you are, change your own password — everyone.
    ACCOUNT = "account"


class Level(str, Enum):
    ALLOW = "allow"
    #: Allowed once the operator agrees (the agent's machine actions).
    CONFIRM = "confirm"
    DENY = "deny"


P = Permission
A, C, D = Level.ALLOW, Level.CONFIRM, Level.DENY

_READ = {P.ACCOUNT, P.MACHINE_READ, P.CAMERA_VIEW, P.HAL_READ, P.FILES_READ, P.CONFIG_READ, P.MACROS_READ, P.SETTINGS_READ, P.SYSTEM_READ}
_OPERATE = {
    P.MACHINE_ESTOP, P.MACHINE_POWER, P.MACHINE_MOTION, P.PROGRAM_RUN, P.MACHINE_TUNE, P.HEATERS,
    P.OUTPUTS, P.MACROS_RUN, P.CALIBRATION_RUN, P.FILES_WRITE, P.CALIBRATION_MANAGE, P.BEDMESH_MANAGE,
    P.SETTINGS_WRITE, P.SESSION_CONTROL, P.AGENT_APPROVE, P.AGENT_CHAT,
}


def _role(allow: set[Permission], confirm: set[Permission] = set()) -> dict[Permission, Level]:
    return {p: A if p in allow else C if p in confirm else D for p in Permission}


ROLES: Mapping[str, Mapping[Permission, Level]] = {
    "admin": _role(set(Permission)),
    #: Runs the machine; does not change its configuration or the system.
    "user": _role(_READ | _OPERATE),
    #: Watches (anyone without a login). The E-stop is never withheld from
    #: anyone who can see the machine.
    "viewer": _role(_READ | {P.MACHINE_ESTOP}),
    #: The assistant: reads freely, may always stop the machine, asks the
    #: operator before anything that moves, heats or changes a print, and
    #: never touches configuration, HAL, the system, settings or users.
    "agent": _role(
        _READ | {P.MACHINE_ESTOP},
        confirm={
            P.MACHINE_POWER, P.MACHINE_MOTION, P.PROGRAM_RUN, P.MACHINE_TUNE, P.HEATERS, P.OUTPUTS,
            P.MACROS_RUN, P.CALIBRATION_RUN, P.FILES_WRITE, P.CALIBRATION_MANAGE, P.BEDMESH_MANAGE,
        },
    ),
}

#: What every route needs: ``(method, path template) -> permission``.
#: ``WS`` is a WebSocket. Paths are FastAPI templates (``{name}``).
MACHINE_ROUTES: Mapping[tuple[str, str], Permission] = {
    ("GET", "/"): P.MACHINE_READ,
    ("GET", "/api/v1/health"): P.MACHINE_READ,
    ("GET", "/api/v1/base-thread/snapshot"): P.MACHINE_READ,
    ("WS", "/ws/telemetry"): P.MACHINE_READ,
    ("GET", "/ws/_schema/telemetry"): P.MACHINE_READ,
    ("GET", "/api/v1/modules/machine_state/state"): P.MACHINE_READ,
    ("GET", "/api/v1/modules/tools/spindle/{tool_id}"): P.MACHINE_READ,
    ("GET", "/api/v1/modules/io"): P.MACHINE_READ,
    ("GET", "/api/v1/leds"): P.MACHINE_READ,
    ("GET", "/api/v1/bedmesh/enable"): P.MACHINE_READ,
    ("GET", "/api/v1/bedmesh/calibrate"): P.MACHINE_READ,
    ("GET", "/api/v1/ztilt/status"): P.MACHINE_READ,
    ("GET", "/api/v1/print-tuning"): P.MACHINE_READ,
    ("GET", "/api/v1/calibration"): P.MACHINE_READ,
    ("GET", "/api/v1/modules/camera/devices"): P.CAMERA_VIEW,
    ("GET", "/api/v1/modules/camera/usb"): P.CAMERA_VIEW,
    ("GET", "/api/v1/modules/camera/stream"): P.CAMERA_VIEW,
    ("GET", "/api/v1/modules/camera/stream/diagnostic"): P.CAMERA_VIEW,
    ("GET", "/api/v1/modules/camera/status"): P.CAMERA_VIEW,
    ("GET", "/api/v1/hal/pins"): P.HAL_READ,
    ("POST", "/api/v1/hal/pins/values"): P.HAL_READ,
    ("GET", "/api/v1/hal/layout"): P.HAL_READ,
    ("WS", "/ws/hal-scope"): P.HAL_READ,
    ("PUT", "/api/v1/hal/layout"): P.HAL_WRITE,
    ("POST", "/api/v1/modules/machine_state/estop/activate"): P.MACHINE_ESTOP,
    ("POST", "/api/v1/modules/machine_state/state"): P.MACHINE_POWER,
    ("POST", "/api/v1/modules/machine_state/mcode_error"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/machine_state/mode"): P.MACHINE_POWER,
    ("POST", "/api/v1/modules/axis/home"): P.MACHINE_MOTION,
    ("POST", "/api/v1/modules/machine_state/mdi"): P.MACHINE_MOTION,
    ("POST", "/api/v1/modules/program/load"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/program/unload"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/program/run"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/program/run_powered"): P.MACHINE_POWER,
    ("POST", "/api/v1/modules/program/pause"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/program/pause_inspect"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/program/resume"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/program/stop"): P.PROGRAM_RUN,
    ("POST", "/api/v1/modules/axis/settings"): P.MACHINE_TUNE,
    ("PUT", "/api/v1/print-tuning"): P.MACHINE_TUNE,
    ("PUT", "/api/v1/print-tuning/objects/{index}"): P.MACHINE_TUNE,
    ("PUT", "/api/v1/bedmesh/enable"): P.MACHINE_TUNE,
    ("POST", "/api/v1/modules/tools/tools/{tool_id}/target"): P.HEATERS,
    ("POST", "/api/v1/modules/tools/extruder"): P.HEATERS,
    ("POST", "/api/v1/modules/tools/spindle"): P.HEATERS,
    ("POST", "/api/v1/modules/temperature/sensors/{name}/target"): P.HEATERS,
    ("PUT", "/api/v1/modules/io/{pin_id}"): P.OUTPUTS,
    ("PUT", "/api/v1/leds/{led_id}"): P.OUTPUTS,
    ("POST", "/api/v1/modules/macros/{name}/start"): P.MACROS_RUN,
    ("POST", "/api/v1/modules/macros/{name}/stop"): P.MACROS_RUN,
    ("POST", "/api/v1/calibration/{calibration_id}/start"): P.CALIBRATION_RUN,
    ("POST", "/api/v1/calibration/{calibration_id}/result"): P.CALIBRATION_RUN,
    ("POST", "/api/v1/bedmesh/calibrate"): P.CALIBRATION_RUN,
    ("POST", "/api/v1/ztilt/adjust"): P.CALIBRATION_RUN,
    ("PUT", "/api/v1/calibration/{calibration_id}/reminder"): P.CALIBRATION_MANAGE,
    ("DELETE", "/api/v1/calibration/{calibration_id}/values"): P.CALIBRATION_MANAGE,
    # The ACE Pro: a tool change moves the machine; feeding / drying is the unit
    ("GET", "/api/v1/ace"): P.MACHINE_READ,
    ("POST", "/api/v1/ace/change"): P.MACHINE_MOTION,
    ("POST", "/api/v1/ace/slots/{index}/feed"): P.HEATERS,
    ("POST", "/api/v1/ace/slots/{index}/unwind"): P.HEATERS,
    ("POST", "/api/v1/ace/dryer"): P.HEATERS,
    ("DELETE", "/api/v1/ace/dryer"): P.HEATERS,
    ("PUT", "/api/v1/ace/current"): P.MACHINE_TUNE,
    ("POST", "/api/v1/modules/program/parse"): P.CONFIG_WRITE,
    ("POST", "/api/v1/modules/mcu/reset"): P.CONFIG_WRITE,
}

_PROFILES = "/api/v1/modules/machineconfig/profiles"
_MACHINES = "/api/v1/modules/machineconfig/machines"
_MCODES = "/api/v1/modules/machineconfig/m-codes"
_MESHES = "/api/v1/modules/bedmesh"

SYSTEM_ROUTES: Mapping[tuple[str, str], Permission] = {
    ("GET", "/"): P.SYSTEM_READ,
    ("GET", "/api/v1/system/version"): P.SYSTEM_READ,
    ("GET", "/api/v1/system/releases"): P.SYSTEM_READ,
    ("GET", "/api/v1/system/update/status"): P.SYSTEM_READ,
    ("POST", "/api/v1/system/update"): P.SYSTEM_UPDATE,
    ("GET", "/api/v1/settings"): P.SETTINGS_READ,
    ("GET", "/api/v1/settings/{key}"): P.SETTINGS_READ,
    ("PUT", "/api/v1/settings/{key}"): P.SETTINGS_WRITE,
    ("DELETE", "/api/v1/settings/{key}"): P.SETTINGS_WRITE,
    ("GET", "/api/v1/system/machine"): P.MACHINE_READ,
    ("GET", "/api/v1/system/machine/log"): P.CONFIG_READ,
    ("POST", "/api/v1/system/machine/start"): P.SESSION_CONTROL,
    ("POST", "/api/v1/system/machine/stop"): P.SESSION_CONTROL,
    ("POST", "/api/v1/system/machine/switch"): P.SESSION_CONTROL,
    ("POST", "/api/v1/system/machine/default"): P.CONFIG_WRITE,
    ("GET", "/api/v1/programs"): P.FILES_READ,
    ("GET", "/api/v1/programs/thumbnail/{filename:path}"): P.FILES_READ,
    ("GET", "/api/v1/programs/content/{filename:path}"): P.FILES_READ,
    ("POST", "/api/v1/programs/upload"): P.FILES_WRITE,
    ("POST", "/api/v1/programs/folder"): P.FILES_WRITE,
    ("PUT", "/api/v1/programs/rename"): P.FILES_WRITE,
    ("POST", "/api/v1/programs/copy"): P.FILES_WRITE,
    ("DELETE", "/api/v1/programs/{filename:path}"): P.FILES_WRITE,
    ("PUT", "/api/v1/programs/content/{filename:path}"): P.FILES_WRITE,
    # OctoPrint emulation for slicers ("Send to printer")
    ("GET", "/api/version"): P.SYSTEM_READ,
    ("GET", "/api/server"): P.SYSTEM_READ,
    ("POST", "/api/login"): P.SYSTEM_READ,
    ("GET", "/api/settings"): P.SYSTEM_READ,
    ("GET", "/api/printerprofiles"): P.SYSTEM_READ,
    ("GET", "/api/printer"): P.MACHINE_READ,
    ("GET", "/api/job"): P.MACHINE_READ,
    ("GET", "/api/connection"): P.MACHINE_READ,
    ("POST", "/api/files/local"): P.FILES_WRITE,
    ("GET", f"{_MESHES}/meshes"): P.MACHINE_READ,
    ("GET", f"{_MESHES}/defaults"): P.MACHINE_READ,
    ("GET", f"{_MESHES}/meshes/{{name}}"): P.MACHINE_READ,
    ("POST", f"{_MESHES}/meshes"): P.BEDMESH_MANAGE,
    ("PUT", f"{_MESHES}/meshes/{{name}}"): P.BEDMESH_MANAGE,
    ("DELETE", f"{_MESHES}/meshes/{{name}}"): P.BEDMESH_MANAGE,
    ("POST", f"{_MESHES}/meshes/{{name}}/activate"): P.BEDMESH_MANAGE,
    ("GET", f"{_PROFILES}/tree"): P.CONFIG_READ,
    ("GET", f"{_PROFILES}/content"): P.CONFIG_READ,
    ("PUT", f"{_PROFILES}/content"): P.CONFIG_WRITE,
    ("POST", f"{_PROFILES}/folder"): P.CONFIG_WRITE,
    ("POST", f"{_PROFILES}/file"): P.CONFIG_WRITE,
    ("POST", f"{_PROFILES}/upload"): P.CONFIG_WRITE,
    ("POST", f"{_PROFILES}/copy"): P.CONFIG_WRITE,
    ("PUT", f"{_PROFILES}/rename"): P.CONFIG_WRITE,
    ("DELETE", f"{_PROFILES}/entry"): P.CONFIG_WRITE,
    ("GET", f"{_MACHINES}/tree"): P.CONFIG_READ,
    ("GET", f"{_MACHINES}/content"): P.CONFIG_READ,
    ("POST", f"{_MACHINES}/generate"): P.CONFIG_WRITE,
    ("PUT", f"{_MACHINES}/content"): P.CONFIG_WRITE,
    ("POST", f"{_MACHINES}/folder"): P.CONFIG_WRITE,
    ("POST", f"{_MACHINES}/file"): P.CONFIG_WRITE,
    ("POST", f"{_MACHINES}/upload"): P.CONFIG_WRITE,
    ("POST", f"{_MACHINES}/board-upload"): P.CONFIG_WRITE,
    ("POST", f"{_MACHINES}/copy"): P.CONFIG_WRITE,
    ("PUT", f"{_MACHINES}/rename"): P.CONFIG_WRITE,
    ("DELETE", f"{_MACHINES}/entry"): P.CONFIG_WRITE,
    ("GET", f"{_MCODES}/list"): P.CONFIG_READ,
    ("GET", f"{_MCODES}/content"): P.CONFIG_READ,
    ("PUT", f"{_MCODES}/content"): P.CONFIG_WRITE,
    ("DELETE", f"{_MCODES}/{{name}}"): P.CONFIG_WRITE,
    ("GET", "/api/v1/modules/macros"): P.MACROS_READ,
    ("GET", "/api/v1/modules/macros/{name}"): P.MACROS_READ,
    ("GET", "/api/v1/modules/macros/{name}/content"): P.MACROS_READ,
    ("PUT", "/api/v1/modules/macros/{name}"): P.MACROS_WRITE,
    ("DELETE", "/api/v1/modules/macros/{name}"): P.MACROS_WRITE,
    ("PUT", "/api/v1/modules/macros/{name}/content"): P.MACROS_WRITE,
    # The assistant: its MCP server, its actions waiting for the operator
    ("GET", "/api/v1/agent/status"): P.SETTINGS_READ,
    ("GET", "/api/v1/agent/confirmations"): P.AGENT_APPROVE,
    ("POST", "/api/v1/agent/confirmations/{confirmation_id}/approve"): P.AGENT_APPROVE,
    ("POST", "/api/v1/agent/confirmations/{confirmation_id}/deny"): P.AGENT_APPROVE,
    # The in-app assistant (the key is write-only; changing it is a setting)
    ("GET", "/api/v1/agent/config"): P.SETTINGS_READ,
    ("PUT", "/api/v1/agent/config"): P.SETTINGS_WRITE,
    ("POST", "/api/v1/agent/chat"): P.AGENT_CHAT,
    ("GET", "/api/v1/agent/chat/{conversation_id}"): P.AGENT_CHAT,
    ("POST", "/api/v1/agent/chat/{conversation_id}/stop"): P.AGENT_CHAT,
    ("DELETE", "/api/v1/agent/chat/{conversation_id}"): P.AGENT_CHAT,
    # Accounts (#131): logging in is for everyone, managing users for admins
    ("GET", "/api/v1/auth/me"): P.ACCOUNT,
    ("POST", "/api/v1/auth/login"): P.ACCOUNT,
    ("PUT", "/api/v1/auth/password"): P.ACCOUNT,
    ("POST", "/api/v1/auth/logout-everywhere"): P.ACCOUNT,
    ("GET", "/api/v1/users"): P.USERS_MANAGE,
    ("POST", "/api/v1/users"): P.USERS_MANAGE,
    ("PUT", "/api/v1/users/{name}"): P.USERS_MANAGE,
    ("DELETE", "/api/v1/users/{name}"): P.USERS_MANAGE,
}

#: FastAPI's own pages: open (they describe the API, they do nothing).
PUBLIC_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

BACKENDS: Mapping[str, Mapping[tuple[str, str], Permission]] = {"machine": MACHINE_ROUTES, "system": SYSTEM_ROUTES}


def level(role: str, permission: Permission) -> Level:
    """``role``'s level for ``permission``; an unknown role gets nothing."""
    return ROLES.get(role, {}).get(permission, Level.DENY)


_DESCRIPTIONS = {
    P.MACHINE_READ: "machine state, positions, temperatures, I/O, progress",
    P.CAMERA_VIEW: "camera images",
    P.HAL_READ: "HAL pins, HAL editor, scope",
    P.FILES_READ: "G-code programs",
    P.CONFIG_READ: "profiles, machine files, M-codes, LinuxCNC log",
    P.MACROS_READ: "macros",
    P.SETTINGS_READ: "UI settings",
    P.SYSTEM_READ: "version, releases, update status",
    P.MACHINE_ESTOP: "engage the E-stop",
    P.MACHINE_POWER: "E-stop reset, machine on / off, mode",
    P.MACHINE_MOTION: "homing, MDI",
    P.PROGRAM_RUN: "load, run, pause, resume, stop a program",
    P.MACHINE_TUNE: "live Z offset, flow, speed, objects, mesh on / off",
    P.HEATERS: "heater targets, extruder, spindle",
    P.OUTPUTS: "fans, output pins, LEDs",
    P.MACROS_RUN: "run a macro",
    P.CALIBRATION_RUN: "calibrations, bed mesh probing, Z tilt",
    P.FILES_WRITE: "upload, edit, move, delete programs",
    P.CALIBRATION_MANAGE: "calibration reminders, reset to profile values",
    P.BEDMESH_MANAGE: "save, delete, activate meshes",
    P.SETTINGS_WRITE: "change UI settings",
    P.MACROS_WRITE: "edit macros",
    P.SESSION_CONTROL: "start, stop, switch LinuxCNC",
    P.HAL_WRITE: "save the HAL editor layout",
    P.CONFIG_WRITE: "profiles, machine generation, board upload, MCU reset",
    P.SYSTEM_UPDATE: "update the software",
    P.USERS_MANAGE: "users and roles",
    P.AGENT_APPROVE: "approve or deny the assistant's actions",
    P.AGENT_CHAT: "chat with the in-app assistant",
    P.ACCOUNT: "log in, own account and password",
}


def permission_table_markdown() -> str:
    """``docs/reference/permissions.md`` (generated; edit this module)."""
    roles = list(ROLES)
    mark = {A: "yes", C: "confirm", D: "-"}
    out = [
        "# Permissions",
        "",
        "<!-- Generated from backend/common/core/permissions.py by",
        "     permission_table_markdown(); edit that module, not this file. -->",
        "",
        "Every route of both backends needs one permission; a role allows it,",
        "allows it after the operator confirms (`confirm`), or refuses it (`-`).",
        "For now every web user is **admin** (there are no logins yet).",
        "",
        "## Roles",
        "",
        "| Permission | What | " + " | ".join(roles) + " |",
        "|---|---|" + "---|" * len(roles),
    ]
    for p in Permission:
        out.append(f"| `{p.value}` | {_DESCRIPTIONS[p]} | " + " | ".join(mark[level(r, p)] for r in roles) + " |")
    for backend, routes in BACKENDS.items():
        out += ["", f"## Routes: {backend} backend", "", "| Method | Path | Permission | agent |", "|---|---|---|---|"]
        for (method, path), p in sorted(routes.items(), key=lambda kv: (kv[1].value, kv[0][1], kv[0][0])):
            out.append(f"| {method} | `{path}` | `{p.value}` | {mark[level('agent', p)]} |")
    return "\n".join(out) + "\n"


__all__ = [
    "BACKENDS", "Level", "MACHINE_ROUTES", "PUBLIC_PATHS", "Permission", "ROLES", "SYSTEM_ROUTES",
    "level", "permission_table_markdown",
]
