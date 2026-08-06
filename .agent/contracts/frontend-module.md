# Frontend Module Contract (`FrontendModule`)

The canonical contract every pluggable frontend module must satisfy.
Authoritative source for what the registry expects and what module
authors must implement. Living document — the matching JS code lives
in [`frontend/src/core/modules/protocols.js`](frontend/src/core/modules/protocols.js)
and [`frontend/src/core/modules/registry.js`](frontend/src/core/modules/registry.js).

## 1. The `FrontendModule` Interface

```js
/**
 * @typedef {Object} FrontendModule
 * @property {FrontendModuleManifest} manifest
 * @property {(ctx: ModuleContext) => void} onLoad
 * @property {() => void} [onUnload]
 */
```

A module is any object whose default export has the three fields above.
The registry walks `frontend/src/modules/<id>/index.js` via
`import.meta.glob` and consumes the default export.

## 2. FrontendModuleManifest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Must match the backend `ModuleManifest.id`. |
| `title` | `string` | yes | Human-readable display name. |
| `version` | `string` | no | Semantic-ish version. Default `"0.0.0"`. |
| `description` | `string` | no | One-line description. |
| `sidebar` | `SidebarEntry` | no | Sidebar entry the module contributes. |
| `settingsPanel` | `boolean` | no | Whether this module exposes a Settings tab. Default `false`. |

## 3. SidebarEntry

Same shape as the backend equivalent:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Stable route id, unique app-wide. |
| `label` | `string` | yes | Display text. |
| `icon` | `string` | no | SVG/HTML icon string. |
| `order` | `number` | no | Sort weight. Lower numbers appear earlier. Default `100`. |

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
mutation. See `MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #3` (not present in the working tree)
for the design rationale.

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

## 8. Discovery — `import.meta.glob`

The registry uses Vite's `import.meta.glob` with `eager: false` to
discover modules:

```js
const moduleImports = import.meta.glob(
  '../modules/*/index.js',
  { eager: false },
);
```

The glob is **lazy** (see
`MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1` (not present in the working tree)
so a module disabled by the `MODULES_ENABLED` whitelist never
appears in the bundle, even at runtime. See
`MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1` (not present in the
working tree).

## 9. Whitelist — `MODULES_ENABLED`

The same `MODULES_ENABLED` env var that gates the backend registry
also gates the frontend registry. The frontend reads it via
`import.meta.env.VITE_MODULES_ENABLED` in Vite, falling back to
`process.env.MODULES_ENABLED` in node-side tests.

- Empty / unset → mount everything discovered (dev-friendly default).
- `MODULES_ENABLED=camera` → only mount the `camera` module.
- Unknown ids log a dev-only warning and are ignored.

## 10. Module Skeleton

```js
// frontend/src/modules/camera/index.js
export default {
  manifest: {
    id: 'camera',
    title: 'Camera',
    sidebar: { id: 'camera', label: 'Camera', order: 30 },
    settingsPanel: true,
  },
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

## 11. Acceptance Checklist

A frontend module is "ready" when:

- [ ] Default export has `manifest`, `onLoad`, and (optionally) `onUnload`.
- [ ] `manifest.id` matches the backend manifest.
- [ ] Pinia store ids match `^module_[a-z][a-z0-9_]+$` (lint passes).
- [ ] Subscribers treat `eventBus` payloads as frozen.
- [ ] `telemetryBus` payloads are cloned before storing.
- [ ] `onUnload` is idempotent.