# Issue #1 — Implement core module infrastructure (Phase 2b/2c)

> **Status:** not started
> **Tracks:** [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) phases 2b and 2c
> **Scope:** core infrastructure only — **no existing modules are migrated** in this issue.
> **Follow-up issues:** #2 will cover Phase 2d (camera migration as the template).

---

## Problem

The backend currently registers its routers explicitly in
[`backend/main.py`](backend/main.py) and the frontend imports each
component statically. As features accumulate, this coupling makes it hard
to:

- enable or disable features per-deployment without touching core wiring,
- share code between installations,
- onboard a new contributor without editing the global shell,
- write a single, uniform settings subsystem across all features.

The roadmap (Phase 2b/2c) defines a registry-driven module system backed
by contracts documented in `.agent/contracts/`. This issue tracks the
infrastructure that makes those contracts runnable.

---

## Goals

1. Add an empty `backend/modules/` and `frontend/src/modules/`
   discovery layer that boots cleanly with **zero** modules mounted.
2. Define `PluggableModule` (Python Protocol) and `FrontendModule`
   (TypeScript interface) in `core/` so module authors have a formal
   contract to code against.
3. Implement `ModuleRegistry` — directory scan, `MODULES_ENABLED`
   whitelist filter, router + settings-router mounting, `on_load()` /
   `on_unload()` lifecycle.
4. Implement `EventBus` and `TelemetryBus` shells with the **immutable
   payload contract** from roadmap § 12 Gotcha #3.
5. Implement `SettingsStore` (JSON-per-module, atomic `tmp + os.replace`,
   in-memory cache) and the four settings endpoints per module.
6. Add `SettingsView.vue` placeholder that renders an empty tab list
   keyed by registered modules.
7. **Zero regression** in behaviour — every existing
   `backend/routers/*.py` and `frontend/src/components/*.vue` must keep
   working unchanged.

## Non-Goals

- Migrating any existing router or component into a module folder.
- Building a settings UI form generator (Phase 5).
- Telemetry refactor (Phase 4).
- SQLite promotion (Phase 6).
- Auth / multi-user.

---

## Recommended implementation order

1. `core/protocols.py` (Python Protocol) and
   `core/modules/protocols.ts` (TypeScript interface) — both ends of the
   contract first.
2. `core/event_bus.py` and `core/modules/event-bus.ts` — cross-module
   pub/sub shells (with payload-copy enforcement).
3. `core/settings_store.py` and `core/modules/settings.ts` —
   per-module JSON storage + typed client wrapper.
4. `core/module_registry.py` and `core/modules/registry.ts` — discovery,
   whitelist filter, mount, lifecycle.
5. Wire `backend/main.py` lifespan to the registry; wire
   `frontend/src/App.vue` + `main.js` to the registry.
6. Tests for each.
7. Docs sweep (move `AI_INSTRUCTIONS.md` → `.agent/`, write the three
   contract docs, append two sections to `PROJECT_ARCHITECTURE.md`).
8. Update `MODULE_SYSTEM_ROADMAP.md` § 9 status table.

---

## Tasks

### Backend

- [ ] Create `backend/core/protocols.py`
  - `PluggableModule` `Protocol` decorated with `@runtime_checkable`.
  - `ModuleManifest` Pydantic model.
  - `ModuleContext` dataclass.
  - `SidebarEntry` Pydantic model.
- [ ] Create `backend/core/event_bus.py`
  - Typed pub/sub (`publish(topic, payload)`, `subscribe(topic, handler)`).
  - **Payload immutability:** every `publish` re-instantiates a fresh
    Pydantic model from `payload.model_dump()` before fanning out.
  - Topic names are module-id-scoped strings (`module.<id>.<event>`).
- [ ] Create `backend/core/telemetry/bus.py`
  - `TelemetryBus` shell wrapping the existing WebSocket transport
    (transport itself stays untouched in this issue).
- [ ] Create `backend/core/settings_store.py`
  - Per-module JSON at `data/modules/<id>/settings.json`.
  - Atomic write via `tmp + os.replace`.
  - In-memory cache invalidated on every PUT.
  - Default fallback to Pydantic model defaults if file missing.
- [ ] Create `backend/core/module_registry.py`
  - `discover()` scans `backend/modules/*/module.py`.
  - Filters by `MODULES_ENABLED` env var (default: empty = mount all
    discovered, so dev stays ergonomic).
  - `boot(app)`: instantiate, mount routers, call `on_load()`.
  - `shutdown()`: reverse-order `on_unload()`.
  - Logs one-line summary: `mounted=… skipped=… missing=…`.
- [ ] Update `backend/main.py`
  - `lifespan` calls `registry.boot(app)` / `registry.shutdown()`.
  - Legacy `routers/*.py` `include_router` calls remain unchanged.
- [ ] Unit tests in `backend/tests/`:
  - `test_protocols.py` — runtime checkable accepts a stub module.
  - `test_module_registry.py` — skips a missing directory; respects
    `MODULES_ENABLED` whitelist; logs `mounted=[]` when empty.
  - `test_event_bus.py` — payload mutation in one subscriber does **not**
    affect another subscriber.
  - `test_settings_store.py` — atomic write leaves no partial file on
    simulated interrupt; falls back to defaults when file missing.

### Frontend

- [ ] Create `frontend/src/core/modules/protocols.ts`
  - `FrontendModule` interface.
  - `FrontendModuleManifest` interface (route, sidebar, settingsPanel,
    store, components, api).
  - `ModuleContext` interface.
- [ ] Create `frontend/src/core/modules/event-bus.ts`
  - Typed pub/sub, `Object.freeze`-enforced payload delivery.
- [ ] Create `frontend/src/core/modules/telemetry-bus.ts`
  - Wraps the existing WebSocket in `stores/machine.js` (do **not**
    delete that store yet — Phase 4 owns that refactor).
  - Exposes typed `full_state`, `delta`, `error` events.
- [ ] Create `frontend/src/core/modules/settings.ts`
  - Typed wrapper around `GET / PUT / POST /settings…` per module.
- [ ] Create `frontend/src/core/modules/registry.ts`
  - Uses `import.meta.glob('./modules/*/index.ts')` (**lazy**, never
    `eager: true` — see roadmap § 12 Gotcha #1).
  - Filters by `MODULES_ENABLED`.
  - Exposes `sidebar`, `routes`, `settingsPanels` for the app shell.
- [ ] Update `frontend/src/App.vue` and `frontend/src/main.js`
  - Consume the registry instead of static sidebar/router lists.
  - Keep current sidebar rendering unchanged if no modules are mounted.
- [ ] Add `frontend/src/views/SettingsView.vue`
  - Iterates `registry.modules` and renders one tab per module's
    `settingsPanel`. Empty state: header copy "Settings (no modules
    mounted)".
- [ ] CI lint / pre-commit hook
  - Regex-checks every `defineStore(` call inside
    `frontend/src/modules/`. Any id not matching
    `^module_[a-z][a-z0-9_]+$` fails the build (Gotcha #2).
- [ ] Tests in `frontend/tests/`:
  - Registry test: empty `modules/` dir → empty sidebar, no warnings.
  - Glob test: deleting `src/modules/camera/` (in a fixture build)
    yields zero build errors.
  - Store id regex test: stub store with `defineStore('camera', ...)`
    fails the lint; `defineStore('module_camera', ...)` passes.

### Docs

- [ ] Move `AI_INSTRUCTIONS.md` → `.agent/AI_INSTRUCTIONS.md`.
- [ ] Create `.agent/README.md` (TOC of contract docs).
- [ ] Create `.agent/contracts/backend-module.md`
  - Canonical `PluggableModule` contract.
  - Includes the **immutable payload** rule from § 12 Gotcha #3.
- [ ] Create `.agent/contracts/frontend-module.md`
  - Canonical `FrontendModule` contract.
  - Includes the **store id** rule from § 12 Gotcha #2.
  - Includes the **immutable payload** rule from § 12 Gotcha #3.
- [ ] Create `.agent/contracts/settings-module.md`
  - Settings endpoints, storage layout, atomic-write contract.
- [ ] Append § Module System and § Settings Subsystem sections to
  [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md).
- [ ] Update [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) § 9
  status table — mark 2a / 2b / 2c as `🔧 In progress` once this issue
  is in flight.

---

## Acceptance Criteria

A CI run on a clean checkout must demonstrate **all five**:

1. **`start_dev.sh` with `MODULES_ENABLED=""`** boots backend and
   frontend. Backend log contains
   `registry: mounted=[] skipped=0 missing=0`. Frontend serves the
   dashboard shell with the existing sidebar (untouched).
2. **Visit `/settings`** — page renders header
   "Settings (no modules mounted)" with no tabs and no errors.
3. **`MODULES_ENABLED=nonexistent` + restart** — backend logs the same
   `mounted=[]` line **plus** a single `WARN unknown module id
   'nonexistent'` line. Frontend still serves.
4. **`npm run build` with `frontend/src/modules/` deleted** — succeeds
   with zero errors and zero warnings (validates Gotcha #1).
5. **Pinia store id regex check** — passes on a stub module defining
   `defineStore('module_camera', ...)`; fails on `defineStore('camera', ...)`
   with the message: *"Store id must match ^module_[a-z][a-z0-9_]+$"*.

When all five pass, Phase 2b / 2c is complete and Issue #2 (camera
migration, Phase 2d) can begin.

---

## Risks

- **`main.py` lifespan change** could regress existing routers if the
  registry accidentally double-mounts them.
  *Mitigation:* registry starts empty; legacy `routers/*.py`
  `include_router` calls stay where they are.
- **Frontend registry** must not break the static sidebar used today.
  *Mitigation:* the registry only contributes when at least one module
  is registered; the static list remains the source of truth in 2b.
- **`import.meta.glob` is mode-sensitive** — dev (`vite dev`) vs.
  production (`vite build`).
  *Mitigation:* tests run against both; CI gate on the production build.
- **Payload-copy overhead** in `EventBus` could surprise perf-sensitive
  modules (telemetry at 100 Hz).
  *Mitigation:* telemetry uses its own `TelemetryBus` with a
  by-reference path explicitly opted-in by the consumer; the rule only
  applies to `EventBus`.

---

## Out of Scope

- Migration of any `routers/*.py` or `components/*.vue` into module
  folders (Issue #2 / Phase 2d onward).
- Form generator for settings UI (Phase 5).
- Telemetry transport refactor (Phase 4).
- SQLite storage promotion (Phase 6).
- Hot-reload of modules in dev (open question in roadmap § 10).

---

## References

- [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) — full
  architecture context.
- § 12 *Implementation Gotchas* in the roadmap — **must-read** before
  starting any code in this issue.
- [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md) — to be
  extended with § Module System and § Settings Subsystem.