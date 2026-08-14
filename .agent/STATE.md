# Frontend Module System — Current State

This document is the single source of truth for the current state of
the frontend module system. It replaces the long-form context that
used to live as inline comments inside `frontend/src/**`. The
`MODULE_SYSTEM_ROADMAP.md` at the repo root stays the design
backlog; this file is the as-built snapshot.

If a comment in source code used to say "see issue #N", it now says
"see `.agent/STATE.md` § N" — the table below maps the old labels to
the current sections.

---

## 12. Base-Thread Snapshot Store (servo ↔ base-thread split)

The dashboard reads two distinct transport streams from the backend:

* **Servo thread** — `GET /ws/telemetry`, 10 Hz WebSocket. Carries
  the time-critical fields the DRO / Estop / status panels need on
  every frame (`task_state`, `estop`, `position`, `interp_state`,
  `g5x_index`, `state`, `file`, `homed`, `errors`). Owned by the
  machine module's WebSocket handler.
* **Base thread** — `GET /api/v1/base-thread/snapshot`, 1 Hz REST
  round-trip. Carries the slow streams the dashboard polls anyway:
  `progress` (G-code line counters), `sensors` (temperature), `tools`
  (operator-facing tool list), `timestamp` (ISO-8601 UTC).

The base-thread store lives at
`frontend/src/stores/baseThread.js`. It is a Pinia OPTIONS-API
store with three top-level refs (`progress`, `sensors`, `tools`)
and three actions (`refresh`, `start`, `stop`). The full contract
— including how to boot it, how to consume it, and how to add a
new stream — is documented in the file's header comment.

### 12.1 Why two transports

The split mirrors the LinuxCNC runtime: the 10 Hz WebSocket is the
"servo thread" for time-critical panels; the 1 Hz snapshot is the
"base thread" for bookkeeping. Conflating them either:

1. Saturates NML — every 100 ms stat poll would re-read the full
   sensor / tool list and clog the status channel.
2. Wastes bandwidth — the 30 s temperature chart never needs a
   10 Hz update.

The snapshot endpoint
(`backend/routers/base_thread.py`) is the single canonical source
for every slow stream the dashboard cares about. Adding a new
slow stream is one new top-level field on the response, one new
ref on the store, and one new consumer — no new endpoint, no new
timer.

### 12.2 What lives on the WebSocket (servo thread) only

* `task_state`, `estop`, `task_mode`, `state`, `interp_state` —
  fast-changing task state.
* `position`, `actual_position`, `relative_position` — DRO axes
  at 10 Hz so the position display does not jitter.
* `g5x_index`, `homed`, `file`, `errors` — status / mode / file
  context.

### 12.3 What lives on the snapshot (base thread) only

* `progress` — G-code `current_line` / `motion_line` / `total_lines`.
* `sensors` — temperature sensor dict (keyed by sensor name).
* `tools` — operator-facing tool list with runtime state overlaid.
* `timestamp` — ISO-8601 UTC, lets the frontend detect a stalled
  poll.

### 12.4 What was deliberately removed from the WebSocket

The legacy `target_temp` / `actual_temp` fields were dropped from
the WebSocket payload when the snapshot landed. The mock still
keeps them on `_machine_state` for simulation-loop bookkeeping,
but the telemetry surface no longer exposes them. The temperature
module reads them via the snapshot's `sensors` dict instead.

### 12.5 Adding a new slow stream

```text
1. backend/routers/base_thread.py
   - Add a top-level field to ``BaseThreadSnapshotResponse``.
   - Populate it in ``get_base_thread_snapshot()``.
2. ``npm run generate-api`` (regenerates the TS client).
3. frontend/src/stores/baseThread.js
   - Add a ref to ``state``.
   - Add a defensive write inside ``refresh()`` mirroring the
     existing ``sensors`` / ``tools`` blocks.
4. Consumer module
   - ``const baseThread = useBaseThreadStore()``
   - ``const { newStream } = storeToRefs(baseThread)``
   - Pull the current value synchronously at setup time
     (``newStream.value = baseThread.newStream``) so the panel
     renders populated on the first frame.
   - Watch with ``deep: true`` so cross-module reactivity
     propagates the top-level reassignment.
```

### 12.6 Gotchas (also see `LESSONS_LEARNED.md` § 2.5)

* `_pollHandle` on the baseThread store is a non-state property
  on the Pinia store instance — it starts as `undefined`. The
  `start` / `stop` gates must use a truthy check (`if (this._pollHandle)`),
  not a strict-null check. A strict-null check returns early on
  the first call and silently disables the 1 Hz poll.
* Consumer modules must read the snapshot directly via
  `storeToRefs(baseThread)` and watch with `deep: true`. The
  Pinia OPTIONS-API proxy does not always rebroadcast a
  top-level reassignment across module boundaries.
* `useBaseThreadStore().start()` is called once from `App.vue`
  at the top level of `<script setup>`. Do NOT also call it from
  a module's `onLoad` — that would stack intervals on hot-reload.

---

## 1. Module Discovery

Modules are discovered via Vite's **eager** `import.meta.glob`
with `eager: true`. The glob lives in
`frontend/src/core/modules/registry.js` — it is the single
source of truth for module discovery. Components inside a
module are imported **statically** in `DashboardView.vue` and
`App.vue`. An empty `modules/` folder is graceful — the
registry boots with zero modules — but every module that
ships in the repo is mandatory (see § 7).

**Path geometry.** `registry.js` lives at
`frontend/src/core/modules/`, so the glob uses `../../modules/*/index.js`
(two segments up). Don't copy the one-segment path from
`DashboardView.vue` — the tripwire comment lives in
`registry.js`.

---

## 2. Store ID Naming

Every Pinia store id declared inside `frontend/src/modules/` MUST
match `^module_[a-z][a-z0-9_]+$`. The `module_` prefix prevents
collisions with the legacy top-level stores (`machine`, `console`,
`machineStore`) which still exist during the migration window.

CI lint script: [`frontend/scripts/check-store-ids.mjs`](frontend/scripts/check-store-ids.mjs).

**Pattern in code.** Store ids are built by concatenation rather than
hard-coded as a literal string:

```js
const STORE_ID = `module_${manifest.id}`;
```

This avoids the store-id lint script false-positive-matching the
id-literal inside the comment above it.

---

## 3. EventBus — Frozen Payload Contract

`frontend/src/core/modules/event-bus.js` enforces: every subscriber
receives a deep-cloned, deep-frozen copy of the payload. A buggy
subscriber mutating its copy throws in strict mode (ES modules are
strict by default) and the bus catches the throw, logs it, and
continues to the next subscriber.

The `TelemetryBus` is the opposite: it delivers by reference so the
high-frequency stream does not pay a clone cost per tick. Modules
that subscribe to `telemetryBus` must clone before storing.

---

## 4. Eager Module Store Boot

Module stores are **eagerly** initialised inside `onLoad`. The
`activePinia` race that motivated the previous lazy-store
pattern is no longer relevant because the boot sequence is
deterministic: `main.js` calls `app.use(pinia)` before
`registry.boot()`, so `useXxxStore()` inside `onLoad` finds the
active Pinia instance.

Consequence: a module's polling loop / WebSocket transport
starts at app boot, not at first mount. Operators get a
populated dashboard on the first frame.

---

## 5. Settings Surface

Every module that needs persisted settings imports the canonical
client from `frontend/src/core/modules/settings.js`:

```js
import { createModuleSettings } from '../../core/modules/settings.js';
const settings = createModuleSettings('camera');
```

The client wraps the four canonical REST endpoints in
`backend/modules/<id>/settings.py`. The full contract lives in
[`contracts/settings-module.md`](contracts/settings-module.md).
The frontend deliberately uses hand-rolled `fetch` rather than the
generated OpenAPI client so modules keep working even when
`frontend/generated/api/` has not been regenerated yet.

---

## 6. State Facade

The `stores/stateFacade.js` Pinia store is the facade for raw
LinuxCNC telemetry. The backend's WebSocket stream ships raw
integers (`task_state`, `interp_state`, `estop`, ...) to the
browser. The facade exposes those raw values verbatim **and** offers
a clean `systemState` string getter so widgets never have to do
integer math against the wire protocol.

The runtime split: the 10 Hz WebSocket telemetry lives in
`stores/servoThread.js` (the "servo thread"); the 1 Hz REST
snapshot lives in `stores/baseThread.js` (the "base thread").
The servo-thread store calls
`useStateFacadeStore().updateStatus({...})` on every `full_state` /
`delta` payload to keep the facade in sync. When the machine module
is not mounted the facade renders its initial defaults (which bias
toward `ESTOP` — the UI must never claim the machine is idle when we
have no data).

The mocked `recentFiles` getter on the facade is a placeholder. The
real implementation will read from `NcFilesService.listFiles` once
the file-load contract is finalised.

---

## 7. Modules Are Mandatory

Every module that ships in `frontend/src/modules/<id>/` is a hard
dependency: its code is loaded eagerly, its `onLoad` runs at app
boot, its sidebar entry is merged into the nav, and its
`mainView` / `settingsPanel` is rendered when the user navigates
to the matching route. **No module is "nullable"** — there is no
concept of a module that may be absent at runtime. A module that
is not ready to satisfy the full contract does not ship.

The `MODULES_ENABLED` whitelist remains as a deployment opt-out
(see § 9 below) but it does not change the fact that every
module is mandatory at the code level. Excluding a module from
the whitelist leaves its JS in the bundle (Vite's `eager: true`
glob ships it) and skips only the `onLoad` boot and the sidebar
merge.

The previous nullable-module guarantee (with the per-module
table) was retired in the rewrite that produced § 13. Modules are
now uniformly mandatory.

---

## 8. Module Authoring Cheatsheet

Skeleton (`frontend/src/modules/<id>/index.js`):

```js
export default {
  manifest: {
    id: 'camera',
    title: 'Camera',
    sidebar: { id: 'camera', label: 'Camera', order: 30 },
    settingsPanel: true,
  },
  onLoad(/* ctx */) {},
  onUnload() {},
  settingsPanel: SomeVueComponent, // optional
};
```

Acceptance checklist:

- [ ] Default export has `manifest`, `onLoad`, (optionally) `onUnload`.
- [ ] `manifest.id` matches the backend manifest.
- [ ] Pinia store ids match `^module_[a-z][a-z0-9_]+$` (lint passes).
- [ ] EventBus subscribers treat payloads as frozen.
- [ ] `onUnload` is idempotent.

---

## 9. Active Modules

| Module id    | File                                | Sidebar | Settings tab | Notes |
|--------------|-------------------------------------|---------|--------------|-------|
| `camera`     | `frontend/src/modules/camera/`      | optional | yes | Viewers + settings panel. Backend delegates streaming to `ustreamer` (one subprocess per `/dev/videoN`); `/stream` is a 302 redirect to the per-device `http://127.0.0.1:{port}/?action=stream` URL. Per-camera operator preferences (rename / flip / mirror / hide-from-cycle) persist server-side via the per-module settings store at `backend/data/modules/camera/settings.json`; the store hydrates on boot and PUTs an immediate write per change. `GET /status` returns `{running, active_id, ustreamer_url, message}`; `message` is a single-line operator hint that distinguishes "ustreamer not installed" from "device unplugged" from "platform unsupported" — the CameraViewer and CameraSettings render it verbatim so operators see a dependency hint rather than a silent broken image. |
| `temperature`| `frontend/src/modules/temperature/` | no       | yes | 30 s chart, °C/K unit, per-sensor colours. |
| `machine`    | `frontend/src/modules/machine/`     | no       | no  | DRO + jog controls, owns the WebSocket transport. |
| `machineconfig` | `frontend/src/modules/machineconfig/` | yes (`sidebar.id: 'machineconfig'`) | yes | Profiles editor, compilers, deploy. Owns its own `/machineconfig` route (registered at boot by `router/index.js::registerModuleRoutes`); the `MachineConfigView` carves the panel grid out of the legacy `EditorView.vue`. The legacy `/config/:filename?` editor route remains for deep-linking but is editor-only. Also exposes the `/m-codes/...` endpoints the universal editor uses to edit bare ``M<num>`` files under `machine_config/m_codes/`. |
| `tools`      | `frontend/src/modules/tools/`       | no       | no  | Spindle / extruder MDI panel. |
| `macros`     | `frontend/src/modules/macros/`      | no       | yes | Three kinds via ``?kind=``: ``.macro`` (Run via MDI), ``.ngc`` (LinuxCNC native, edit-only), ``mcode`` (LinuxCNC M100..M199 under `machine_config/m_codes/`, edit-only). The ``.ngc`` toggle lives in the Create dialog; ``mcode`` has its own dashboard / machine-config panels. |

---

## 10. Migration Window Notes

The following legacy files still exist and are intentionally kept
until the migration window closes:

- `frontend/src/stores/machine.js` — pre-module monolith. Replaced by
  `frontend/src/modules/machine/store.js`, but the compat shim keeps
  it importable.
- `frontend/src/stores/stateFacade.js` — the canonical State Facade
  Pinia store (exposes `systemState`, `printProgress`,
  `isEstopActive`, `recentFiles`, the `updateStatus()` action, and
  the `TASK_STATE` / `INTERP_STATE` / `SystemState` constant
  tables). Renamed from `stores/machineStore.js`.
- `frontend/src/stores/servoThread.js` — the 10 Hz WebSocket
  transport (`/ws/telemetry`) and the time-critical reactive
  state (`status` with position / task_state / errors).
- `frontend/src/stores/baseThread.js` — the 1 Hz REST snapshot
  store (program progress, temperature sensors, tool list).
- `frontend/src/stores/machine.js` — the cross-module machine
  store (jog / home / set-position / program-lifecycle actions
  + DRO computed values + module-scoped settings). The machine
  module's own components import via the module's
  ``../store.js`` re-export.
- `frontend/src/components/FileManager.vue` — the G-code file list,
  still mounted as a full-page view rather than a module shell.
- `frontend/src/components/ActivePrintWidget.vue` — the print
  controls. Currently has mocked click handlers pending the
  backend's file-load contract; a follow-up can swap the
  `consoleStore.debug(...)` calls for the real
  `useMachineStore().startProgram(...)` / `pauseProgram(...)` / etc.
- `frontend/src/modules/camera/components/CameraPanel.vue` —
  removed. The module now exports `mainView: CameraViewer` so the
  route and the dashboard mount the same component; the 1:1 wrapper
  is no longer needed.

---

## 11. Unsaved-Changes Guard

The editor store tracks `pristineContent` as the last loaded or successfully
saved snapshot and exposes `isDirty`. Editor route leaves, same-component file
switches, and the editor Close action use the queue-based confirm service in
`frontend/src/core/confirm.js`. `ModalConfirmHost.vue` is mounted once in
`App.vue`; feature code calls the Promise-based `useConfirm()` API rather than
native `window.confirm` dialogs.

---

## 13. No-Lazy-Imports Rule

Lazy imports inside the module surface are forbidden. The
contract documented in
[`.agent/contracts/frontend-module.md`](contracts/frontend-module.md)
bans every flavour of lazy import the codebase used to rely on:

- `import.meta.glob(..., { eager: false })` is forbidden inside
  any module surface. The single allowed glob is the registry's
  `import.meta.glob('../../modules/*/index.js', { eager: true })`
  in `frontend/src/core/modules/registry.js`.
- `defineAsyncComponent(() => import('./foo.vue'))` is
  forbidden. Components are imported statically.
- Dynamic `import()` of any module-owned path is forbidden.
- Module stores are constructed eagerly inside `onLoad` (see
  § 4) — no lazy `useXxxStore()` indirection from inside the
  components.

The CI lint `frontend/scripts/check-no-lazy-imports.mjs`
enforces the rule at build time. It scans every `.vue`, `.js`,
and `.ts` file under `frontend/src/modules/` and
`frontend/src/core/` for the forbidden patterns and exits
non-zero on the first hit. The script is wired into
[`.agent/TEST.md`](TEST.md) so the rule trips before the bundle
is built.

**Why now.** The previous contract allowed modules to be
nullable (see § 7) and lazy imports made that work: deleting a
module folder left the build green because nothing referenced
the deleted path statically. Modules are mandatory now, so
there is no upside to lazy imports — they hide module
dependencies instead of making them explicit. The eager surface
catches missing modules at build time (a static import errors)
and makes the dependency graph readable in the IDE.

The legacy `defineAsyncComponent` and `import.meta.glob(..., {
eager: false })` calls were removed from every module entrypoint
(`frontend/src/modules/<id>/index.js`) and from `App.vue` /
`DashboardView.vue` as part of this rewrite. The registry's
glob remains the one eager exception — its purpose is module
discovery, not lazy loading.
