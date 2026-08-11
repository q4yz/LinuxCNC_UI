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
