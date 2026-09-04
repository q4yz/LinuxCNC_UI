# Architecture

## Overview

A monorepo with three services:

- **`backend/machine/`** — Python 3 FastAPI + Uvicorn, port 8000.
  Everything that needs a *live* LinuxCNC session: the
  high-frequency WebSocket telemetry stream, NML state/MDI/jogging,
  program execution, tools/temperature/camera HAL interactions, and
  the Visual HAL editor feed. Per-domain routers are mounted from
  `main.py:_MODULE_DOMAINS`, a flat table (see `§ 4`). See
  `.agent/contracts/backend-router.md` for the canonical router
  contract.
- **`backend/system/`** — Python 3 FastAPI + Uvicorn, port 8001. The
  **always-running** half: machine-config profile CRUD, template
  generation (`§ 7`), NGC program uploads, macro/M-code CRUD,
  version/update, and the LinuxCNC *process* lifecycle
  (start/stop/switch — see `§ 1.3`). Stays reachable even when the
  machine backend or LinuxCNC itself is down.
- **`backend/common/`** — shared library imported by both apps
  (settings store, event bus, DTOs, domain file services, hardware
  abstraction, exceptions, …). Not a running service — see `§ 1.1`.
- **`frontend/`** — Vue 3 + Vite + Pinia SPA, TypeScript. Reactive
  UI plus a Three.js 3D toolpath viewer. There is **no dynamic
  module registry** on the frontend — views and components are
  imported directly where they're used (see `§ 2`).

The frontend never talks to `backend/machine` or `backend/system`
directly — nginx (production) / the Vite dev proxy (dev) route each
`/api/v1/...` path prefix to whichever service owns it, so the SPA
sees a single origin. See `§ 1.4` for the routing table. WebSocket
traffic (`/ws/`) always goes to the machine backend.

The **orchestrator** is the AI-agent workflow that drives code
changes and runs the verification pipeline in `.agent/TEST.md`. It
is not part of the application code — it reads the `.agent/`
contracts from outside the repo. See `§ 8`.

## 1. Backend layout

```
backend/
├── common/                     # Shared library — imported by both apps, never run directly
│   ├── core/                   # settings_store.py, event_bus.py, field_masking.py, models.py
│   ├── dtos/                   # Frozen dataclass domain DTOs + HalPin handles
│   ├── mappers/, factories/    # DTO ↔ Pydantic Response translation
│   ├── models/                 # Pydantic request/response + per-module settings + machineconfig schemas
│   ├── domain_file_services/   # File-tree services shared by both apps + paths.py
│   │                           # (single source of truth for machine_config/, nc_files/, macros/)
│   ├── hardware/                # Hardware abstraction layer (see § 1.1)
│   ├── storage/                # Filesystem-backed persistence (MacroStorage, …)
│   ├── exceptions/, module_settings_router.py
│   └── tests/                  # Tests for the shared library itself
├── machine/                    # Machine backend — port 8000 (see Overview)
│   ├── main.py                 # FastAPI app + lifespan (telemetry loop, mock seed, watchdog)
│   ├── routers/                # axis, camera, hal, program, state, temperature, tools,
│   │                           # BaseThreadRouter/ServoThreadRouter (flat table + WS),
│   │                           # macro_start (POST /{name}/start only — CRUD lives in system)
│   ├── services/                # Per-domain service singletons + cross-domain facades
│   ├── hal_service/, dtos/, mappers/, factories/  (machine-only)
│   └── tests/
├── system/                     # System service — port 8001 (see Overview)
│   ├── main.py                 # Minimal lifespan; always-on
│   ├── routers/                # machineconfig, FilesRouter (programs), SystemRouter,
│   │                           # macros (CRUD only), machine_lifecycle
│   ├── services/                # machineconfig/ (hardware.json + template helpers),
│   │                           # machinetemplates/ (generator.py — the template pipeline, § 7),
│   │                           # MachineLifecycleService (start/stop/switch — § 1.3)
│   └── tests/
├── requirements.txt             # Shared dependency set (one venv for both apps)
├── requirements-machine.txt     # -r requirements.txt (machine-only deps go here later)
└── requirements-system.txt      # -r requirements.txt (system-only deps go here later)
```

Each app's own imports stay **flat** (`from services.X import Y`,
`from core.settings_store import ...`) — every entrypoint
(`main.py`, and each app's `tests/conftest.py`) pushes
`backend/common` onto `sys.path` ahead of its own directory, so a
shared module and an app-local module never need different import
syntax. A module id owned by one process is *never* imported by the
other (the routing table in `§ 1.4` doubles as the ownership map,
since each path prefix belongs to the app that owns the module
behind it) — that's what makes the split safe: no in-memory
`SettingsStore` cache can ever go stale across processes.

**Running tests.** Each app's suite must be run as a **separate**
pytest invocation — `pytest backend/common/tests`,
`pytest backend/machine/tests`, `pytest backend/system/tests` — not
combined in one command. All three directories are named `tests`
with no `__init__.py`-rooted common package, so pytest's module
cache collides (`ImportPathMismatchError`) if it tries to collect
more than one of them in the same process.

There is **no `backend/modules/` plugin directory** in either app.
Routers live directly under `<app>/routers/<id>.py` and are mounted
in that app's `main.py` via its own `_MODULE_DOMAINS` table. See
[`.agent/contracts/backend-router.md`](.agent/contracts/backend-router.md)
for the canonical contract, and
[`.agent/context/BACKEND_LAYERS.md`](.agent/context/BACKEND_LAYERS.md) for the
Router → Service → DTO → Mapper → Storage split every per-domain
module follows.

### 1.1 Hardware Abstraction Layer

`backend/common/hardware/Connection.py` exposes the hardware
abstraction (imported as `from hardware import ...` by machine-side
code). On a real LinuxCNC box it imports the official `linuxcnc`
Python API; on a developer machine it falls back to
`backend/common/hardware/mock/` automatically. Feature code never
imports `linuxcnc` directly — it calls `execute_sync_cmd(...)` on
the connection, so the backend stays portable. Only the **machine**
backend uses this at runtime (it owns the live NML/HAL session);
the system service never touches it. See
[`.agent/context/MOCK_ARCHITECTURE.md`](.agent/context/MOCK_ARCHITECTURE.md)
for the mock layer's own internal structure.

### 1.2 Safety watchdogs

The machine module's `jog_watchdog.py` runs as a background
asyncio task. The watchdog wakes every 100 ms and force-stops any
axis whose last keep-alive ping is older than
`jog_watchdog_timeout_ms` (default **500 ms**). The frontend
schedules its keep-alive at `keepalive_interval_ms` (default
**250 ms**). The 2:1 cadence is the documented contract; breaking
the cadence is a safety regression.

### 1.3 Machine process lifecycle

`backend/system/services/MachineLifecycleService.py` owns the
**LinuxCNC process** (distinct from HAL "machine power" — that's
`MachineService.py` in the machine backend, an NML-level on/off
toggle on an already-running session). It's mounted at
`/api/v1/system/machine` in the system service specifically so the
machine can be started/stopped/switched even while the machine
backend or the machine itself is down:

- `GET /api/v1/system/machine` — `pgrep`-based detection of a live
  `linuxcnc`/`emc`/`milltask`/`linuxcncsvr` session, plus whether a
  generated INI exists under `machine_config/active/`.
- `POST /api/v1/system/machine/start` — runs the console command
  `linuxcnc <machine_config/active/machine.ini>` as a detached
  process (`start_new_session=True`), console output tee'd into
  `logs/linuxcnc_console.log`. The command is overridable via the
  `LINUXCNC_START_COMMAND` env var (a `{ini}`-templated string) for
  setups that need e.g. `xterm -e linuxcnc {ini}`.
- `POST /api/v1/system/machine/stop` — SIGINT → (grace period) →
  SIGTERM → SIGKILL escalation.
- `POST /api/v1/system/machine/switch` — stop → deploy the selected
  machine's generated templates into `active/`
  (`ActiveFileService.deploy_from`, see `§ 7`) → start.

### 1.4 Two-backend routing (nginx / Vite dev proxy)

Both `install.sh` (nginx, production) and `frontend/vite.config.mjs`
(`DEV_PROXY`, dev/preview) implement the same routing table, mapping
path prefixes to whichever service owns that domain:

| Path | Owner |
|------|-------|
| `/api/v1/modules/macros/{name}/start` (regex — wins over the prefixes below) | machine :8000 |
| `/api/v1/system/` (includes `/api/v1/system/machine`, § 1.3) | system :8001 |
| `/api/v1/programs/` | system :8001 |
| `/api/v1/modules/machineconfig/` | system :8001 |
| `/api/v1/modules/macros/` (CRUD) | system :8001 |
| `/api/` (everything else) | machine :8000 |
| `/ws/` | machine :8000 |

The frontend's typed API client is generated from **both** services'
merged OpenAPI schema — `frontend/scripts/generate-api.mjs` fetches
`:8000/openapi.json` and `:8001/openapi.json` and
`frontend/scripts/merge-openapi.mjs` combines them (failing loudly on
a genuine path collision; each app's own bare `/` health check is
the one expected, intentionally-ignored collision).

## 2. Frontend layout

```
frontend/src/
├── core/                       # Cross-cutting: event-bus.ts, settings/, toast.ts, telemetry-bus.ts
├── components/                 # Reusable panels, one subfolder per domain
│   ├── camera/, machine/, machineconfig/, macros/, temperature/, tools/
│   └── AppSidebar.vue, ConsolePanel.vue, Editor.vue, FileManager.vue, …  (shared/top-level)
├── views/                      # Route-level page components (DashboardView, FilesView,
│                                 EditorView, SettingsView, ConfigView, JoggingView,
│                                 RunningView, DebugView, VisualHalEditor, hal-visual-editor/)
├── stores/                     # Pinia stores, one (or a few) per domain — see § 2.3 / § 2.4
├── router/                     # Vue Router config (hash history, static route table — § 2.2)
├── config/                     # Centralized G-code constants + helpers (gcodes.ts)
├── ui/                         # Shared design-system primitives (BaseButton, Drawer, …)
├── services/                   # apiClient.ts + hand-written service helpers
├── generated/api/              # OpenAPI-generated client (gitignored, see § 1.4)
└── *.vue, *.ts                 # App shell, main.ts, style.css
```

### 2.1 Composition API discipline

Every component uses `<script setup lang="ts">` + the Composition
API. State that crosses component boundaries lives in Pinia stores;
components destructure with `storeToRefs()` so reactivity is
preserved. Cross-store dependencies are resolved inside actions, not
at module scope, to avoid Pinia initialization-order crashes.

### 2.2 Router

Vue Router in **hash mode** (`createWebHashHistory`) keeps the
build compatible with static hosting. `frontend/src/router/index.ts`
declares a single static `BUILTIN_ROUTES` array — every route the
app has is listed there up front (`/`, `/programs`, `/jogging`,
`/running`, `/editor`, `/settings`, `/camera`, `/hal-editor`,
`/config`, `/debug`), each pointing at a statically-imported view
component. There is no dynamic route registration step; adding a
page means adding an entry to that array.

### 2.3 State Facade

`frontend/src/stores/stateFacade.ts` is the **State Facade**: the
raw integers from the WebSocket (`task_state`, `interp_state`,
`estop`, `…`) plus a clean `systemState` string getter that widgets
consume. The servo-thread store calls
`useStateFacadeStore().updateStatus({...})` on every `full_state` /
`delta` payload, so the facade is always the latest snapshot. Before
the first telemetry frame arrives, the facade defaults to `ESTOP` so
the UI never claims the machine is idle when it has no data yet.

### 2.4 Servo thread / base thread split

The dashboard reads two distinct transports from the backend,
mirroring the LinuxCNC runtime split:

* **Servo thread** — `GET /ws/telemetry`, 10 Hz WebSocket. Owns
  the time-critical fields (`task_state`, `estop`, `position`,
  `interp_state`, `g5x_index`, `errors`). Transport + reactive
  state live in `frontend/src/stores/servoThread.ts`; the State
  Facade is mirrored on every frame via `updateStatus()`.
* **Base thread** — `GET /api/v1/base-thread/snapshot`, 1 Hz REST.
  Bundles every slow stream the dashboard polls anyway
  (`progress`, `sensors`, `tools`). Owned by the
  `frontend/src/stores/baseThread.ts` Pinia store.

The split exists because the 10 Hz WebSocket must not carry
bookkeeping fields (a 100 ms stat poll would re-read the full
sensor / tool list and clog NML), and the 1 Hz snapshot must not
become the time-critical transport (the DRO / Estop panels would
jitter).

The `baseThread` store has three top-level refs (`progress`,
`sensors`, `tools`). Consumers read via `storeToRefs(baseThread)`
and watch with `deep: true` so the top-level reassignment propagates
across component boundaries. The store is booted once in `App.vue`
at the top level of `<script setup>`
(`useBaseThreadStore().start()`).

## 3. Config invariants

| Source | Consumers |
|--------|-----------|
| `machine_config/<name>/hardware.json` + generated `machine.ini` (see § 7) | Frontend reads the generated INI/hardware.json to display axis counts, limits, capabilities. Backend `backend/common/HardwareConfigService.py` (via `backend/common/models/machineconfig/{hardware_json_models.py,linuxcnc_models.py}`) parses the same files. |
| `frontend/src/config/gcodes.ts` | Every `.vue` component / Pinia action that emits G-code. Helpers like `generateSetOffset(axis, value)` keep MDI strings out of components. |
| `backend/{machine,system}/models/<id>_settings.py` | Pydantic defaults for module settings. Each app's own `main.py:_MODULE_DOMAINS` builds a `SettingsStore` from each defaults instance and falls back to it on read — a module id is owned by exactly one app (§ 4), never both. |

## 4. Backend module mount table

There is no runtime module registry on either side of the stack —
the frontend imports views/components directly (§ 2) and the
backend uses a flat, statically-declared table per app. **Each app**
(`backend/machine/main.py`, `backend/system/main.py`) declares its
own tuple of the module ids it owns and mounts each router directly
— a module id belongs to exactly one app, never both (see the
ownership split in `§ 1.4`'s routing table and the Overview):

```python
# backend/machine/main.py — module ids owned by the machine backend
_MODULE_DOMAINS = [
    ("axis", AxisSettings, axis_router.router),
    ("machine_state", StateSettings, state_router.router),
    ("program", ProgramSettings, program_router.router),
    ("temperature", TemperatureSettings, temperature_router.router),
    ("tools", ToolsSettings, tools_router.router),
    ("camera", CameraSettings, camera_router.router),
]

# backend/system/main.py — module ids owned by the system service
_MODULE_DOMAINS = [
    ("machineconfig", MachineConfigSettings, machineconfig_router.router),
    ("macros", MacrosSettings, macros_router.router),
]
```

Each `main.py` iterates its own table to mount each per-domain
router under `/api/v1/modules/<id>` and the four canonical settings
endpoints under `/api/v1/modules/<id>/settings` (settings first,
so a module's bare `/{name}` cannot shadow them). A handful of
routers are mounted directly (not through the table) because they
don't carry per-module settings — `BaseThreadRouter`,
`ServoThreadRouter`, the hal router and `macro_start_router` on the
machine side; `SystemRouter`, `machine_lifecycle_router`, and
`FilesRouter` on the system side.

**Eager boot.** Every router module is imported at the top of its
app's `main.py` (`from routers import …`) — Python runs each
module's top-level code at import time, so a router is either fully
mounted or the app fails to boot. There is no "module disabled at
build time" path — every entry in `_MODULE_DOMAINS` is a hard
dependency, mounted unconditionally via `app.include_router(_router)`.
See
[`.agent/contracts/backend-router.md`](.agent/contracts/backend-router.md)
for the canonical per-domain router contract.

## 5. Event bus

`backend/common/core/event_bus.py` and `frontend/src/core/event-bus.ts`
share the same contract:

- **Frozen payload.** Every `publish` re-instantiates a deep-cloned,
  deep-frozen copy of the payload before fanning out. A buggy
  subscriber mutating its copy throws in strict mode and the bus
  catches + logs the throw, then continues to the next subscriber.
- **Telemetry bus is the opposite.** The high-frequency stream
  (`frontend/src/core/telemetry-bus.ts`) delivers by reference so we
  don't pay a clone cost per tick. Subscribers must clone before
  storing.

## 6. Cross-cutting layers

| Concern | Where it lives |
|---------|----------------|
| Generated OpenAPI client | `frontend/generated/api/` (gitignored; regenerated from both apps' merged spec by `frontend/scripts/generate-api.mjs` + `merge-openapi.mjs`, see `§ 1.4`) |
| Backend module contract | `.agent/contracts/backend-router.md` (per-domain routers, one table per app) |
| Settings contract | `.agent/contracts/settings-module.md` |
| Settings persistence | `backend/common/core/settings_store.py` (atomic write per module; one `SettingsStore` instance per module id, owned by exactly one app) |
| Backend layered pattern | `.agent/context/BACKEND_LAYERS.md` |
| Typing discipline (no bare `dict` / `any`) | `.agent/AGENT.md` |
| Test scripts | `frontend/tests/*.mjs`, `backend/{common,machine,system}/tests/test_*.py` (run each app's suite separately — see `§ 1`) |
| Repository agent guide | `.agent/AGENT.md` |
| Test run script | `.agent/TEST.md` (the orchestrator runs this) |
| Frontend/backend operational notes | `.agent/STATE.md` |
| Known technical debt | `.agent/HANDOFF.md` § 2 |

## 7. The template pipeline — `hardware.json` v2.1 and the generated machine files

The old "compile a machine to a running config" step has been
replaced by a **template generator**
(`backend/system/services/machinetemplates/generator.py`). Given a
machine profile's `machine.cfg` (Klipper-style source), it parses
the config into a `MachineConfigGraph`, builds axes with
`AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS)`
(one joint per physical motor, so a dual-motor axis produces two
`[JOINT_N]` sections instead of collapsing them), and emits eight
files into `machine_config/<name>/`:

- `hardware.json` — the canonical machine record (schema below).
- `machine.ini` — the generated LinuxCNC INI, defaulted from the
  known-good `PrintNC-WEBGUI` example (`§` below) and populated with
  any limits found on the parsed axes/joints.
- `Machine.hal` — the main HAL file.
- `custom.hal` — always `source`s `webgui_connections.hal` (hard
  rule: every generated `custom.hal` calls it).
- `webgui_connections.hal` — the WebGUI's own HAL wiring. Its bytes
  are read back and preserved across a regenerate rather than
  overwritten, since a user may hand-edit it.
- `postgui_call_list.hal` — referenced by the INI's
  `POSTGUI_HALFILE`.
- `<name>.tbl` — the tool table.
- (plus the profile's own `machine.cfg`, unchanged).

`MachineLifecycleService.switch()` (§ 1.3) deploys these generated
files into `machine_config/active/` via `ActiveFileService.deploy_from`.
Only trivkins-based kinematics are assumed today; multiple joints
per axis letter are supported (see `AxisMappingPolicy` above), but
non-trivial kinematics (e.g. real gantry coupling) are not yet
modeled.

### `hardware.json` v2.1 schema

Versioned at the root (`"version": "2.1"`); the model rejects any
other shape. Defined by a single Pydantic model,
[`backend/common/models/machineconfig/hardware_json_models.py`](backend/common/models/machineconfig/hardware_json_models.py),
that validates every cross-reference in one pass and fails fast with
the full error list when any link is unresolved.

```
Top-level keys
--------------
version               Literal["2.1"]      — breaking-change fence
machine               str                  — profile name
source                str                  — compiler id
kinematics            str
hal_type              str
axes                  [Axis]               — kinematic axes (id = canonical letter)
joints                [Stepper]            — physical stepper motors (one per joint_number)
drivers               [Driver]             — TMC2209 / etc.
endstops              [Endstop]            — one record per physical switch (id + pin only)
tools                 [Tool]               — operator-facing commandable entities
temperature_sensors   [TemperatureSensor]
fans                  [Fan]
mcus                  [McuInfo]            — declared [mcu] / [mcu NAME] sections
```

Key relationships:

- An `Axis` owns joints via `joint_numbers: list[int]` (a multi-motor
  axis lists every driving joint) and is wired to a switch via
  *exactly one* of `endstop` (a string id into `endstops[]`) or
  `endstop_pin` (an inline pin string, mutually exclusive with
  `endstop`). Axis-level `position_max` / `position_endstop` describe
  travel in the axis coordinate frame, shared by every joint on that
  axis.
- `tools` replaces the old `heaters` list. Every entry carries a
  `type` discriminator (`extruder`, `heated_bed`, `spindle_digital`,
  `spindle_analog`, `laser` reserved) and cross-references resolve
  by parent-list: `tool.sensor` → `temperature_sensors[].id`,
  `tool.fan` → `fans[].id`. A pressure sensor is never confused with
  a temperature sensor even if the pin matches — the parent list is
  the type discriminator.
- `endstops[]` is one record per physical switch (just `id` + `pin`)
  — the previous three-role-per-switch shape (`endstop`/`homing`/
  `ignore`) was dropped; the axis that references a switch already
  carries its position and the behavioural role is implicit from
  context.
- `joint_number` is unique across `joints[]` and maps deterministically
  to a Remora stepgen channel (`remora.joint.{N}.*`), independent of
  the source Klipper config's declaration order.

The frontend reads `hardware.json` via
`GET /active/content/hardware.json` for display; the schema itself is
enforced at generation time by the Pydantic model, not at the HTTP
boundary.

## 8. What the orchestrator actually does

The orchestrator is not part of the application code — it lives
outside the repo and reads the `.agent/` contracts. Inside the repo,
its footprint is:

- `.agent/AGENT.md` — repository agent guide; stack layout,
  conventions, and quality/scope rules any agent reads before
  editing code.
- `.agent/TEST.md` — the bash script the orchestrator runs after
  every edit to verify the change.
- `.agent/contracts/` — the router and settings-module interface
  contracts the AI must respect.

The orchestrator's responsibilities (commit, push, run the full
test matrix, open the PR) are explicitly **not** the AI agent's
job. The agent edits code; the orchestrator ships it.
