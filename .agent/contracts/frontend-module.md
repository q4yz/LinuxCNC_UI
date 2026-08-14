# Frontend Module Contract (`FrontendModule`)

The canonical contract every pluggable frontend module **must**
satisfy. Authoritative source for what the registry expects and what
module authors must implement. Living document — the matching JS
code lives in
[`frontend/src/core/modules/protocols.js`](frontend/src/core/modules/protocols.js)
and
[`frontend/src/core/modules/registry.js`](frontend/src/core/modules/registry.js).

> **Modules are mandatory.** Every module that ships in
> `frontend/src/modules/<id>/` is a hard dependency: its code is
> loaded eagerly by Vite at app start, its `onLoad` runs during
> `registry.boot()`, its sidebar entry is merged into the nav, and
> its `mainView` / `settingsPanel` is rendered when the user navigates
> to the matching route. No module is "nullable" — there is no
> concept of a module that may be absent at runtime. A module that
> is not ready to satisfy the full contract does not ship.

> **No lazy imports.** Module code is loaded **eagerly**. The
> registry walks `frontend/src/modules/<id>/index.js` via a **static**
> import — `import.meta.glob(..., { eager: true })` only. Dynamic
> `import()`, `defineAsyncComponent`, and `import.meta.glob(..., {
> eager: false })` are forbidden inside any module surface. The CI
> lint `frontend/scripts/check-no-lazy-imports.mjs` rejects any
> violation. See `.agent/STATE.md` § 13 for the rationale.

## 1. The `FrontendModule` Interface

```js
/**
 * @typedef {Object} FrontendModule
 * @property {FrontendModuleManifest} manifest
 * @property {(ctx: ModuleContext) => void} onLoad
 * @property {() => void} onUnload
 * @property {import('vue').Component} mainView
 * @property {import('vue').Component} settingsPanel
 */
```

A module is any object whose default export has every field above —
none are optional. The registry walks `frontend/src/modules/<id>/index.js`
statically and consumes the default export.

## 2. FrontendModuleManifest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Must match the backend `ModuleManifest.id`. |
| `title` | `string` | yes | Human-readable display name. |
| `version` | `string` | yes | Semantic-ish version. No default — every module declares one. |
| `description` | `string` | yes | One-line description. Empty string is fine. |
| `sidebar` | `SidebarEntry` | yes | Sidebar entry the module contributes. No `undefined`. |
| `settingsPanel` | `boolean` | yes | Whether this module exposes a Settings tab. |
| `mainView` | `import('vue').Component` | yes | Top-level view rendered by `App.vue` when this module's route is active. |

## 3. SidebarEntry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Stable route id, unique app-wide. |
| `label` | `string` | yes | Display text. |
| `icon` | `string` | yes | SVG/HTML icon string. Empty string allowed. |
| `order` | `number` | yes | Sort weight. Lower numbers appear earlier. |

## 4. ModuleContext

```js
/**
 * @typedef {Object} ModuleContext
 * @property {string} id
 * @property {EventBus} eventBus
 * @property {TelemetryBus} telemetryBus
 * @property {ModuleSettingsApi} settings
 */
```

`settings` is a typed client bound to the four canonical settings
endpoints exposed by the backend `SettingsStore`. The full client
API lives in [`.agent/contracts/settings-module.md`](.agent/contracts/settings-module.md).

## 5. Store ID Naming Rule (Gotcha #2)

Every Pinia store id declared inside `frontend/src/modules/` MUST
match `^module_[a-z][a-z0-9_]+$`. The leading `module_` prefix
prevents collisions with the legacy top-level stores (`machine`,
`console`) and gives a regex hook for the CI lint.

The lint script lives at
[`frontend/scripts/check-store-ids.mjs`](frontend/scripts/check-store-ids.mjs)
and runs in CI before the bundle is built:

```js
defineStore('module_camera', { … }) // ✅ passes
defineStore('camera', { … })         // ❌ fails: Store id must match ^module_[a-z][a-z0-9_]+$
```

## 6. EventBus Contract — Frozen Payloads (Gotcha #3)

Every `eventBus.publish(topic, payload)` call hands every subscriber
its own **deep-cloned, deep-frozen** copy of the payload. A buggy
subscriber mutating its copy throws in strict mode (ES modules are
strict by default) and the bus catches the throw, logging it and
continuing to the next subscriber.

Frozen copies exist for the same reason as the backend: modules are
independent codebases we don't trust to be disciplined about payload
mutation.

## 7. TelemetryBus — By-Reference Escape Hatch

`TelemetryBus` is the sibling bus for high-frequency telemetry
(typically 10-100 Hz). It delivers payloads **by reference** so
consumers don't pay a clone cost on every tick. Consumers are part
of the core platform (the existing `stores/machine.js` WebSocket
handler is the first) and must be disciplined about payload
mutation.

Modules that subscribe to `telemetryBus` should treat every payload
as read-only. If a module needs to mutate a payload (e.g. to push
into a history array), it must clone first:

```js
const seen = [];
telemetryBus.subscribe('full_state', (topic, payload) => {
  seen.push(structuredClone(payload));
});
```

## 8. Discovery — Eager Static Glob

The registry walks `frontend/src/modules/<id>/index.js` via a **static,
eager** glob:

```js
const moduleImports = import.meta.glob(
  '../modules/*/index.js',
  { eager: true },
);
```

`{ eager: true }` is mandatory. A module that ships in the repo
ships its code at app start; there is no "module disabled at build
time" path. The whitelist still exists (see § 9) but it only
controls whether `onLoad` is called and whether the module record
enters the registry map, not whether the JS is loaded.

## 9. Whitelist — `MODULES_ENABLED`

The same `MODULES_ENABLED` env var that gates the backend registry
also gates the frontend registry. The frontend reads it via
`import.meta.env.VITE_MODULES_ENABLED` in Vite, falling back to
`process.env.MODULES_ENABLED` in node-side tests.

- Empty / unset → mount everything discovered (dev-friendly default).
- `MODULES_ENABLED=camera` → only mount the `camera` module.
- Unknown ids log a dev-only warning and are ignored.

The whitelist is a deployment opt-out, not a removal path. A
module excluded by the whitelist still has its JS in the bundle
(it was loaded eagerly), it just does not run `onLoad` and is not
visible in the sidebar / settings.

## 10. Eager Module Store Boot

Module stores are created in `onLoad` (not lazily on first
`useXxxStore()` call). The `activePinia` race documented in the
previous contract is now resolved by ordering:

1. `main.js` calls `app.use(pinia)` before `registry.boot()`.
2. `registry.boot()` calls `onLoad(ctx)` which may call
   `useXxxStore()` to construct the store against the wired
   Pinia instance.
3. `onLoad` returns synchronously; a module may not return a
   Promise from `onLoad`.

The Pinia 3.x `activePinia._s.has(...)` timing trap that motivated
the lazy-store pattern is no longer relevant because the boot
sequence is deterministic.

## 11. Module Skeleton

```js
// frontend/src/modules/camera/index.js
import CameraViewer from "./components/CameraViewer.vue";
import CameraSettings from "./components/CameraSettings.vue";

export default {
  manifest: {
    id: 'camera',
    title: 'Camera',
    sidebar: { id: 'camera', label: 'Camera', order: 30 },
    settingsPanel: true,
    mainView: CameraViewer,
  },
  mainView: CameraViewer,
  settingsPanel: CameraSettings,
  onLoad(ctx) {
    ctx.eventBus.subscribe('module.camera.snapshot', (topic, payload) => {
      // payload is deep-frozen; clone before storing.
      console.log(payload)
    })
  },
  onUnload() {
    // idempotent teardown — clear intervals, remove listeners.
  },
}
```

## 12. Acceptance Checklist

A frontend module is "ready" when:

- [ ] Default export has every required field (`manifest`, `onLoad`,
      `onUnload`, `mainView`, `settingsPanel`).
- [ ] `manifest.id` matches the backend manifest.
- [ ] `manifest.sidebar` is set (no `undefined`).
- [ ] `mainView` is a non-null Vue component imported **statically**.
- [ ] `settingsPanel` is a non-null Vue component imported **statically**.
- [ ] Pinia store ids match `^module_[a-z][a-z0-9_]+$` (lint passes).
- [ ] Subscribers treat `eventBus` payloads as frozen.
- [ ] `telemetryBus` payloads are cloned before storing.
- [ ] `onUnload` is idempotent.
- [ ] `onLoad` returns synchronously (no `Promise<void>`).
- [ ] No `defineAsyncComponent`, dynamic `import()`, or
      `import.meta.glob(..., { eager: false })` anywhere in the
      module surface (lint passes).
