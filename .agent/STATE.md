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

Modules are discovered via Vite's lazy `import.meta.glob` with
`eager: false`. The glob lives in both
`frontend/src/core/modules/registry.js` and
`frontend/src/views/DashboardView.vue`. An empty `modules/`
folder is graceful — the registry boots with zero modules.

**Why lazy?** Original bug: eager imports pulled every module's JS
into the bundle even when the `MODULES_ENABLED` whitelist excluded
it. The current behaviour makes the whitelist meaningful.

**Path geometry.** `registry.js` lives at
`frontend/src/core/modules/`, so the glob uses `../../modules/*/index.js`
(two segments up). `DashboardView.vue` lives at
`frontend/src/views/`, so it uses `../modules/*/components/*.vue`
(one segment up). The two-segment path is the easy one to get
wrong — the tripwire comment lives in `registry.js`.

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

## 4. Lazy Module Store Boot

Module stores are **lazily** initialised on the first
`useXxxStore()` call inside the component, not in `onLoad`. The
registry boots modules as part of `main.js` and the timing of
`app.use(pinia)` relative to module `onLoad` is fragile — Pinia 3.x's
`useStore` reads `pinia._s` and throws
`Cannot read properties of undefined (reading 'has')` when
`activePinia` has not been wired through Vite's pre-bundled Pinia
instance. Letting the panel trigger the first call sidesteps that
race entirely.

Consequence: a module whose view is never mounted will never start
its polling loop. This is intentional — no resource cost for
unmounted modules.

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

The `stores/machineStore.js` Pinia store is the facade for raw
LinuxCNC telemetry. The backend's WebSocket stream ships raw
integers (`task_state`, `interp_state`, `estop`, ...) to the
browser. The facade exposes those raw values verbatim **and** offers
a clean `systemState` string getter so widgets never have to do
integer math against the wire protocol.

The machine module's WebSocket handler calls
`useMachineStore().updateStatus({...})` on every `full_state` /
`delta` payload to keep the facade in sync. When the machine module
is not mounted the facade renders its initial defaults (which bias
toward `ESTOP` — the UI must never claim the machine is idle when we
have no data).

The mocked `recentFiles` getter on the facade is a placeholder. The
real implementation will read from `NcFilesService.listFiles` once
the file-load contract is finalised.

---

## 7. Nullable-Module Guarantee

Every dashboard panel and every sidebar entry checks
`registry.modules.has(id)` before rendering. The reactive Map
means the `computed` re-evaluates the moment the registry flips a
module into its mounted set after boot completes. The
`stores/machine-compat.js` shim provides a fallback `useMachineStore`
so the shell can render even when the machine module is excluded.

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
| `camera`     | `frontend/src/modules/camera/`      | optional | yes | Viewers + settings panel. Per-camera operator preferences (rename / flip / mirror / hide-from-cycle) persist server-side via the per-module settings store at `backend/data/modules/camera/settings.json`; the store hydrates on boot and PUTs a debounced 400 ms write per change. |
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
- `frontend/src/stores/machine-compat.js` — the optional adapter
  that lets the shell render without the machine module mounted.
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
