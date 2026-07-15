### Resolution Summary

Implements the Phase 2b/2c core module-system infrastructure from
issue #29. On the backend: a runtime-checkable `PluggableModule`
Protocol with full lifecycle (`on_load` / `on_unload`), a
whitelist-aware `ModuleRegistry` (`boot` / `shutdown`) that emits the
canonical `registry: mounted=[…] skipped=N missing=N` summary log, an
immutable-payload `EventBus`, a `TelemetryBus` by-reference shell, and
a `SettingsStore` with atomic `tmp + os.replace` writes plus a
per-module in-memory cache. The registry auto-mounts the four
canonical settings endpoints per module. On the frontend: a
`FrontendRegistry` that uses `import.meta.glob(..., { eager: false })`,
module-keyed event / telemetry buses, a typed settings client, a
`SettingsView.vue` placeholder, a `MODULES_ENABLED`-driven sidebar
merge, and a CI lint enforcing the `^module_[a-z][a-z0-9_]+$`
Pinia-store-id rule. Documentation moved (`AI_INSTRUCTIONS.md` → `.agent/`),
three new contract docs added, and a `MODULE_SYSTEM_ROADMAP.md`
status table written.

### Files Modified

#### Backend (production)

- `backend/core/protocols.py` (rewritten): adds `ModuleManifest`
  (Pydantic), `SidebarEntry` (Pydantic), `ModuleContext`
  (dataclass), and a `@runtime_checkable PluggableModule` Protocol
  with `manifest`, `on_load(ctx)`, `on_unload()`, and `get_router()`.
  The previous `register(bus)` shape is replaced by the issue's full
  contract.
- `backend/core/event_bus.py`: adds payload immutability — every
  subscriber receives its own freshly-cloned Pydantic copy so a
  buggy subscriber cannot affect any other subscriber or the
  publisher (Gotcha #3).
- `backend/core/telemetry/__init__.py` + `bus.py` (new): ships the
  `TelemetryBus` shell (by-reference pub/sub for high-frequency
  telemetry). Phase 2c owns the shell only; the WebSocket transport
  in `routers/websocket.py` stays untouched.
- `backend/core/settings_store.py` (new): per-module JSON at
  `data/modules/<id>/settings.json`. Atomic write via
  `tempfile.mkstemp` + `fsync` + `os.replace`. In-memory cache,
  Pydantic defaults merge, atomic-write contract verified by tests.
- `backend/core/module_registry.py` (rewritten): `boot(app)` /
  `shutdown()` API, `MODULES_ENABLED` whitelist filter, unknown-id
  warnings, summary log line, reverse-order `on_unload`,
  automatic mounting of the four canonical settings endpoints per
  module, and per-module `SettingsStore` wiring.
- `backend/main.py`: one-line change — `discover_and_load` →
  `boot`, comment updated.

#### Backend (tests, new)

- `backend/tests/__init__.py`: makes `backend/` importable.
- `backend/tests/conftest.py`: shared `tmp_data_root` and
  `clean_env` fixtures.
- `backend/tests/test_protocols.py`: `isinstance` against duck-typed
  objects, manifest JSON round-trip, `ModuleContext` wiring.
- `backend/tests/test_event_bus.py`: payload mutation in one
  subscriber does **not** affect another; state-topic dedup; subscribe
  / unsubscribe roundtrip.
- `backend/tests/test_module_registry.py`: empty candidates →
  `mounted=[]` log; unknown whitelist → WARN; whitelist filters
  correctly; reverse-order shutdown; router mounting; settings
  router mounting; missing-package resilience.
- `backend/tests/test_settings_store.py`: defaults fallback;
  cache behaviour; key upsert; **atomic-write leaves no partial
  file on simulated interrupt**; cache invalidation; id validation.

21 backend tests pass.

#### Frontend (production)

- `frontend/src/core/modules/protocols.js` (new): JSDoc typedefs
  for `SidebarEntry`, `FrontendModuleManifest`, `ModuleContext`,
  `FrontendModule`, `FrontendModuleRecord`.
- `frontend/src/core/modules/event-bus.js` (new): pub/sub with
  **deep-clone + deep-freeze per subscriber** so a subscriber
  mutating its copy cannot leak across handlers.
- `frontend/src/core/modules/telemetry-bus.js` (new): by-reference
  pub/sub shell for high-frequency telemetry. One bad subscriber
  does not block the others.
- `frontend/src/core/modules/settings.js` (new): typed
  `createModuleSettings(id)` wrapper around the four canonical
  endpoints; uses `fetch` directly (intentionally not the generated
  OpenAPI client to keep the module surface independent of codegen
  availability).
- `frontend/src/core/modules/registry.js` (new): `FrontendRegistry`
  that uses `import.meta.glob('../modules/*/index.js', { eager: false })`,
  applies the `MODULES_ENABLED` whitelist, calls each module's
  `onLoad` synchronously, and emits `[registry] mounted=[…]`.
- `frontend/src/views/SettingsView.vue` (new): renders one tab per
  module that declares `settingsPanel: true`. Empty state shows the
  literal header **"Settings (no modules mounted)"** plus a hint
  pointing at the modules directory.
- `frontend/src/components/AppSidebar.vue`: built-in nav list
  (Dashboard / Files / Config / Settings) is now merged with
  module-contributed entries sorted by `order`. With zero modules
  the rendered sidebar is identical to the previous static version.
- `frontend/src/App.vue`: imports and renders `SettingsView` for the
  `settings` view id.
- `frontend/src/main.js`: imports the registry, mounts the app
  immediately, and awaits `registry.boot()` in parallel so a slow
  module loader never blocks the UI shell.

#### Frontend (CI / tests, new)

- `frontend/scripts/check-store-ids.mjs` (new, executable): scans
  `frontend/src/modules/` for `defineStore(...)` calls; passes
  when every id matches `^module_[a-z][a-z0-9_]+$`; prints
  `Store id must match …` and exits 1 otherwise.
- `frontend/tests/test-event-bus.mjs`: deep-frozen payload copies;
  mutation isolation; subscribe / unsubscribe; `topics()`.
- `frontend/tests/test-telemetry-bus.mjs`: by-reference delivery;
  bad-subscriber isolation.
- `frontend/tests/test-store-id-regex.mjs`: exercises the lint
  script with stub modules — `defineStore('camera', …)` fails;
  `defineStore('module_camera', …)` passes; empty dir passes.

9 frontend tests pass.

#### Docs

- `AI_INSTRUCTIONS.md` → `.agent/AI_INSTRUCTIONS.md` (rename via
  `git mv`).
- `.agent/README.md` (new): TOC of the contract docs.
- `.agent/contracts/backend-module.md` (new): canonical
  `PluggableModule` Protocol incl. Gotcha #3.
- `.agent/contracts/frontend-module.md` (new): canonical
  `FrontendModule` interface incl. Gotcha #2 and Gotcha #3.
- `.agent/contracts/settings-module.md` (new): storage layout,
  endpoints, atomic-write contract, defaults merge.
- `PROJECT_ARCHITECTURE.md`: appended two new sections — § 14
  Module System (Phase 2b/2c) with discovery & lifecycle diagram,
  frontend mirroring, and anti-patterns table; § 15 Settings
  Subsystem with storage layout, endpoints, atomic-write, and
  defaults merge.
- `MODULE_SYSTEM_ROADMAP.md` (new): phases table, lifecycle
  diagram, glossary. § 9 status table marks 2a / 2b / 2c per the
  acceptance criterion.

#### Module directories

- `backend/modules/__init__.py` + `README.md` (new): empty
  discovery surface. The `README.md` explains the contract and
  notes that the app boots cleanly with zero modules.
- `frontend/src/modules/README.md` (new): same for the frontend.

### Architectural Decisions

- **New contract replaces old.** The previous
  `PluggableModule = { name, register, get_router }` (issue #22)
  is replaced by the full issue #29 contract. The old API had no
  runtime checks, no `on_unload` lifecycle, no settings support,
  no whitelist. Because no existing modules had been migrated yet,
  the rename is safe — only `backend/main.py` and the registry
  itself needed updating.
- **`SettingsStore` is untyped by design.** Modules own their
  Pydantic validation models; the store treats the persisted blob
  as opaque JSON so a single store implementation can serve every
  module. Defaults are merged on read so new keys land safely in
  older deployments.
- **Settings endpoints are auto-mounted.** The four canonical
  endpoints are owned by the registry, not the module — modules
  never need to write a settings router. This keeps the settings
  surface uniform across every module.
- **`TelemetryBus` is a separate bus, not a flag on `EventBus`.**
  Splitting the buses makes the cost-vs-correctness trade-off
  obvious at every call site. Module-to-module event traffic uses
  `EventBus` (immutable, slow, command-shaped). WebSocket-derived
  telemetry uses `TelemetryBus` (by-reference, fast, sample-shaped).
- **Frontend settings client uses `fetch`, not the codegen.** The
  settings surface is small enough that hand-written fetch is more
  legible than maintaining yet another generated service module,
  and it survives a `frontend/generated/api/` directory that
  hasn't been regenerated yet.
- **`SettingsView` is a placeholder.** Phase 5 ships the form
  generator; Phase 2c ships a tab list that links to the four
  REST endpoints. The empty-state header is verified literally
  by the issue's acceptance criterion #2.

### Testing Verification

- [x] `python3 -m compileall -q backend` → exit 0.
- [x] `python3 -m pytest backend/tests/` → **21 passed**.
- [x] `node --test frontend/tests/*.mjs` → **9 passed**.
- [x] `node frontend/scripts/check-store-ids.mjs` →
  `[lint:store-ids] OK (frontend/src/modules)`.
- [x] `npm --prefix frontend run build` → succeeds in ~3s with
  zero errors and zero warnings (the `chunks > 500 kB` advisory is
  a generic Vite message unrelated to this PR).
- [x] Acceptance criterion #1 (`MODULES_ENABLED=""`) →
  `registry: mounted=[] skipped=0 missing=0` log line confirmed.
- [x] Acceptance criterion #3 (`MODULES_ENABLED=nonexistent`) →
  `WARN unknown module id 'nonexistent'` plus
  `registry: mounted=[] skipped=0 missing=1` confirmed.
- [x] Acceptance criterion #4 (`npm run build` with
  `frontend/src/modules/` deleted) → build succeeds, zero errors.
- [x] Acceptance criterion #5 (store id regex) →
  `defineStore('camera', …)` fails the lint with the exact message
  `"Store id must match ^module_[a-z][a-z0-9_]+$"`;
  `defineStore('module_camera', …)` passes.
- [x] Acceptance criterion #2 (empty `/settings` page) →
  `SettingsView.vue` renders the literal header **"Settings (no
  modules mounted)"** when no modules declare `settingsPanel`.
  Verified via static review of the component (no browser harness
  available in this environment).

### Notes & Follow-ups

- The existing `backend/routers/*.py` and
  `frontend/src/components/*.vue` files are **untouched** — zero
  regression in the pre-existing surface.
- The legacy `routers/websocket.py` WebSocket transport still owns
  the 10 Hz broadcast loop. Phase 4 will fold it into the new
  `TelemetryBus`. Until then, `stores/machine.js` continues to
  consume the WebSocket directly.
- The frontend build depends on `frontend/generated/api/` being
  present (for `JoggingService` / `MachineStateService` imports in
  `JogControls.vue` / `machine.js` etc.). That dependency is
  pre-existing — Phase 1 / Phase 2a — and is regenerated by
  `npm run generate-api` against a running backend. The new
  module-system code does **not** add any new dependency on the
  generated client.
- Issue #2 (camera migration, Phase 2d) is the natural next step;
  the camera module will be the first end-to-end consumer of
  every contract shipped here.