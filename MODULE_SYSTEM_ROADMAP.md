# LinuxCNC Web UI — Module System Roadmap

**Status:** Phase 2a (Protocol + Registry skeleton) — **shipped** in #22.
**In Flight:** Phase 2b/2c (Settings + EventBus + TelemetryBus shells)
                — issue #29.
**Next:** Phase 2d (Camera migration as the template) — issue #2.

This document captures the architecture plan for turning the
LinuxCNC Web UI into a **registry-driven platform** so new features
can be added by dropping a module under `backend/modules/<id>/`
plus its frontend counterpart under `frontend/src/modules/<id>/`,
without touching the global shell.

---

## 1. Goals

1.  Enable or disable features per-deployment without editing
    `main.py` or `App.vue`.
2.  Share code between installations (fork → customise without
    forking the upstream shell).
3.  Onboard new contributors by limiting their edits to a single
    module folder.
4.  Provide a single, uniform settings subsystem across all
    features.
5.  Keep **zero regression** in behaviour: every existing router and
    component must keep working unchanged.

## 2. Phases

| Phase | Title                                | Owner | Status | Issue |
|-------|--------------------------------------|-------|--------|-------|
| 1     | Flat router layout                   | core  | ✅ shipped | n/a |
| 2a    | Protocol + Registry skeleton         | core  | ✅ shipped | #22 |
| 2b    | Settings subsystem + EventBus shells | core  | 🔧 in progress | #29 |
| 2c    | TelemetryBus + frontend registry     | core  | 🔧 in progress | #29 |
| 2d    | Camera module migration (template)   | apps  | 📋 next | #2 |
| 3     | Module authoring docs & DX           | docs  | 📋 planned | — |
| 4     | Telemetry transport refactor         | core  | 📋 planned | — |
| 5     | Settings UI form generator           | apps  | 📋 planned | — |
| 6     | SQLite storage promotion             | core  | 📋 planned | — |

(Phase 2b and 2c are tracked together under issue #29 because the
acceptance criteria from the issue's plan cover both layers.)

## 3. Discovery Layout

```
backend/modules/
└── <module_id>/
    ├── __init__.py            # re-exports ``setup``
    ├── module.py              # implements ``setup()`` factory + ``PluggableModule``
    ├── router.py              # optional APIRouter
    └── settings.py            # optional Pydantic defaults model
```

```
frontend/src/modules/
└── <module_id>/
    └── index.js               # default-export { manifest, onLoad, onUnload }
```

## 4. Whitelist — `MODULES_ENABLED`

A single env var controls which modules boot. Empty / unset mounts
everything (dev-friendly default). Comma-separated module ids mount
only those:

```
MODULES_ENABLED=camera,vfd npm run dev
```

Unknown ids log a dev-only warning; missing modules log `WARN unknown
module id '<id>'` and are ignored.

## 5. Authoritative Contract Documents

- `.agent/contracts/backend-module.md` — `PluggableModule` Protocol
- `.agent/contracts/frontend-module.md` — `FrontendModule` interface
- `.agent/contracts/settings-module.md` — Settings endpoints

## 6. Architecture Diagram

```
                       ┌────────────────────────┐
                       │ backend/main.py        │
                       │  lifespan:             │
                       │    registry.boot(app)  │
                       │  yield                 │
                       │    registry.shutdown() │
                       └─────────────┬──────────┘
                                     │
                       ┌─────────────▼──────────┐
                       │ core/module_registry.py │
                       │  ModuleRegistry         │
                       └────┬───────────┬────────┘
                            │           │
              ┌─────────────▼─┐   ┌─────▼────────────┐
              │ EventBus      │   │ SettingsStore    │
              │ (Gotcha #3:   │   │ (atomic write +  │
              │  deep copy)   │   │  defaults merge) │
              └───────────────┘   └──────────────────┘
```

The frontend mirrors the layout with `core/modules/registry.js`,
`core/modules/event-bus.js`, `core/modules/telemetry-bus.js`, and
`core/modules/settings.js`.

## 7. Migration Plan

Phase 2d (next) migrates the camera as the **template** module — the
first end-to-end exercise of the full contract. Issue #2 tracks it.
Subsequent migrations (spindle, temperature, etc.) follow the same
recipe.

## 8. Open Questions

- Hot-reload of modules in dev (currently requires backend restart).
- Auth / multi-user (out of scope for Phases 2b-2d).
- Telemetry back-pressure handling (currently first-publish-wins).

## 9. Status Table

| Phase | Title                                | Status        | Notes |
|-------|--------------------------------------|---------------|-------|
| 2a    | Protocol + Registry skeleton         | ✅ shipped    | Issue #22 — `PluggableModule` Protocol + `ModuleRegistry` with `discover_and_load`. |
| 2b    | Settings + EventBus shells (backend) | 🔧 in progress | Issue #29 — `SettingsStore` (atomic write + defaults merge), `EventBus` payload immutability, four canonical settings endpoints. |
| 2c    | Frontend registry + telemetry shell  | 🔧 in progress | Issue #29 — `FrontendRegistry` with `import.meta.glob` (lazy), `TelemetryBus` by-reference shell, `SettingsView.vue` empty-state placeholder. |
| 2d    | Camera migration (template)          | 📋 next       | Issue #2 — first end-to-end module under the new contract. |
| 3     | Module authoring docs & DX           | 📋 planned    | Follow-up to #29 once 2d lands. |
| 4     | Telemetry transport refactor         | 📋 planned    | Fold `routers/websocket.py` broadcast loop into `TelemetryBus`. |
| 5     | Settings UI form generator           | 📋 planned    | Replaces the placeholder panels in `SettingsView.vue`. |
| 6     | SQLite storage promotion             | 📋 planned    | Replaces `SettingsStore`'s flat JSON. |

(2b and 2c are tracked together under issue #29 because the
issue's acceptance criteria cover both layers in one PR.)

## 10. References

- [`.agent/contracts/backend-module.md`](.agent/contracts/backend-module.md)
- [`.agent/contracts/frontend-module.md`](.agent/contracts/frontend-module.md)
- [`.agent/contracts/settings-module.md`](.agent/contracts/settings-module.md)
- Issue #29 — this phase
- Issue #22 — predecessor (Phase 2a)
- Issue #2 — successor (Phase 2d camera migration)

## 11. Glossary

- **Module** — A self-contained feature delivered as a Python
  package (`backend/modules/<id>/`) plus an optional JS counterpart
  (`frontend/src/modules/<id>/`).
- **Registry** — The discovery layer (`ModuleRegistry` /
  `FrontendRegistry`) that walks the module tree at startup and
  wires each module into the runtime.
- **Manifest** — Static metadata describing a module
  (`ModuleManifest` / `FrontendModuleManifest`).
- **Lifecycle** — `on_load(ctx)` / `on_unload()` hooks called by the
  registry. `on_unload` is idempotent and runs in reverse
  registration order during shutdown.

---

**Last Updated:** Phase 2b/2c in flight (issue #29).