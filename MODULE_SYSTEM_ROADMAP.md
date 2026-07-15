# LinuxCNC_UI — Module System Roadmap

> **Status: planning document.** Nothing here is implemented.
> **Audience:** maintainers and AI agents preparing for the module migration.
> **Date:** 2026-07-15.

This document captures the cleanup backlog and the architecture we're moving to
*before* any module migration begins. It is a roadmap, not code.

---

## 0. Why we wrote this

The natural next step is to migrate the smallest isolated feature (`camera`)
into a per-module folder so the team can validate the architecture end-to-end.
Before doing that, we are stepping back to:

1. Reorganise the documentation folder so instructions for both humans and AI
   agents live in one discoverable place (`.agent/`).
2. Lock down the **contracts** every module must uphold — backend, frontend,
   settings, lifecycle.
3. Design the **settings subsystem** (per-module UI, backend, storage).
4. **Evaluate** whether a database is justified, and decide now.
5. Lay out the **phased order** so each step is reviewable and reversible.

No code in this document is intended to be copy-pasted verbatim. Each snippet
is the *shape* the contract must take.

---

## 1. Cleanup backlog (Phase 2a — do these first)

This phase touches **only documentation and folder layout**. No runtime code
moves yet.

### 1.1 Introduce the `.agent/` folder

Standard convention used by several agent runners (Cursor, Cline, etc.).
Contents planned:

```text
.agent/
├── README.md                  # TOC of agent-relevant docs
├── AI_INSTRUCTIONS.md         # moved from ./AI_INSTRUCTIONS.md
└── contracts/
    ├── backend-module.md      # PluggableModule protocol (canonical reference)
    ├── frontend-module.md     # FrontendModule interface
    └── settings-module.md     # Settings subsystem contract
```

### 1.2 Reorganise existing docs

| Current path | New path | Reason |
|---|---|---|
| `./AI_INSTRUCTIONS.md` | `.agent/AI_INSTRUCTIONS.md` | Agent instructions belong with the agent runner. |
| `./PROJECT_ARCHITECTURE.md` | `./PROJECT_ARCHITECTURE.md` *(kept)* | Evergreen, hand-edited, root anchor. |
| n/a | `./docs/architecture/*.md` | Pull long subsystem details out of `PROJECT_ARCHITECTURE.md` so it stays scannable. |
| `./HANDOFF.md` | `./docs/handoff/` *(or kept at root)* | Convenience for scanners; not load-bearing. |
| n/a | `./MODULE_SYSTEM_ROADMAP.md` *(this file)* | Lives at root until merged into docs. |

### 1.3 Update `PROJECT_ARCHITECTURE.md`

Append (do not rewrite):

- **§ Module System** — high-level description of the modular architecture
  with links to the contract files in `.agent/contracts/`.
- **§ Settings Subsystem** — per-module UI + backend + storage note.
- Reference `MODULE_SYSTEM_ROADMAP.md` from "see also" until its content is
  folded in.

### 1.4 Acceptance criteria for Phase 2a

- [ ] `AI_INSTRUCTIONS.md` exists *only* at `.agent/AI_INSTRUCTIONS.md`.
- [ ] `.agent/README.md` lists every contract doc.
- [ ] `PROJECT_ARCHITECTURE.md` has the two new sections and no longer
      contradicts the contract sketches in `.agent/contracts/`.
- [ ] No runtime file has moved yet (zero risk regression).

---

## 2. Goals for the module system

- **Self-contained.** Each feature owns: backend router(s), frontend store(s),
  UI components, settings UI, settings storage.
- **Registry-driven.** Adding or removing a module touches only the registry
  list, never core code.
- **Isolation.** Modules must not import each other. Cross-module communication
  is through an `EventBus`, not direct calls.
- **Settings parity.** Every module ships a settings UI panel and a Pydantic
  settings schema — never an ad-hoc config file.
- **Pluggable validation.** Removing a module folder must not break startup.
- **Future-proof storage.** JSON is the default storage; promote to SQLite only
  when a module's data shape or volume outgrows JSON.

---

## 3. Backend module contract

Lives canonically in `.agent/contracts/backend-module.md`. Sketch:

````python
# Pseudocode — shape only. Do not implement yet.

from typing import Protocol, runtime_checkable
from fastapi import APIRouter
from pydantic import BaseModel


class ModuleManifest(BaseModel):
    id: str                       # stable, used in storage paths and URLs
    name: str                     # user-facing
    version: str                  # semver
    description: str
    requires: list[str] = []      # optional dependencies on other module ids
    provides: list[str] = []      # capabilities this module contributes
    settings_schema: type[BaseModel] | None = None
    sidebar: "SidebarEntry | None" = None


class ModuleContext:
    """Per-module handle handed to on_load()."""
    app: "FastAPI"
    event_bus: "EventBus"             # cross-module pub/sub
    telemetry: "TelemetryBus | None"  # only if subscribed
    settings_store: "SettingsStore"   # per-module JSON-backed store
    logger: logging.Logger


@runtime_checkable
class PluggableModule(Protocol):
    def manifest(self) -> ModuleManifest: ...
    def router(self) -> APIRouter | None: ...
    def settings_router(self) -> APIRouter | None: ...
    def on_load(self, ctx: ModuleContext) -> None: ...
    def on_unload(self) -> None: ...
````

### Backend module folder layout

```text
backend/modules/<module_id>/
├── __init__.py             # re-exports the module class
├── module.py               # PluggableModule implementation
├── router.py               # existing routers/<module>.py logic
├── settings.py             # Pydantic settings schema + Pydantic router
├── models.py               # module-scoped Pydantic request/response models
├── README.md               # what this module does, owned endpoints
└── tests/
    └── test_router.py
```

### Lifecycle

1. **Discover** — scan `modules/*/module.py`, instantiate the module class.
2. **Filter** — drop modules whose `id` is not in `MODULES_ENABLED` (an env
   var or settings table). Empty by default, ops opt-in.
3. **Mount** — for each enabled module, call `module.router()` and
   `module.settings_router()`, then `app.include_router(...)`.
4. **Load** — call `module.on_load(ctx)` after mount. Failure here logs a
   warning but does **not** abort startup.
5. **Unload** — on shutdown, call `module.on_unload()` in reverse order.

### Nullable-module guarantee (the validation test)

> "Temporarily delete `modules/camera/` and verify the backend boots
> perfectly without it."

The registry **must**:

- Tolerate a missing `modules/<id>/` directory at startup.
- Tolerate `on_load()` raising — log + skip, continue mounting others.
- Tolerate the optional `MODULES_ENABLED` whitelist excluding all candidates.
- Treat unknown `id`s referenced by another module's `requires` as a *warning*
  in dev and a *hard error* in production (configurable via env).

---

## 4. Frontend module contract

Lives canonically in `.agent/contracts/frontend-module.md`. Sketch:

````typescript
export interface FrontendModuleManifest {
  id: string                                          // matches backend id
  name: string
  version: string
  description: string
  routes?: RouteRecordRaw[]
  sidebar?: { label: string; icon: Component; path: string }
  settingsPanel?: Component                           // mounted under /settings
  store?: () => PiniaStore                            // exposed via useXStore()
  components?: Record<string, Component>              // re-exported from index
  api?: ModuleApiSurface                              // typed wrappers
}

export interface ModuleContext {
  api: ModuleApiSurface                               // typed fetch surface
  eventBus: EventBus
  telemetry: TelemetryBus | null
  logger: Logger
}

export interface FrontendModule {
  manifest(): FrontendModuleManifest
  onMount?(ctx: ModuleContext): void | Promise<void>
  onUnmount?(): void | Promise<void>
}
````

### Frontend module folder layout

```text
frontend/src/modules/<module_id>/
├── index.ts              # exports manifest, components, store
├── api.ts                # typed wrappers over generated services
├── store.ts              # Pinia store for module-local state
├── components/
│   └── *.vue
└── README.md
```

### Store ID convention

Every Pinia store inside a module MUST declare its id in the format
`module_<id>`, where `<id>` matches the module id. The exported function
name (`useCameraStore`) is advisory; the string passed to `defineStore`
is what prevents collisions.

```ts
// inside store.ts
export const useCameraStore = defineStore('module_camera', () => {
  // setup-store form
})
```

Enforced in CI by a regex check on every `defineStore(` call inside
`frontend/src/modules/`. See § 12 Gotcha #2.

### App shell integration

- **Sidebar** — built dynamically from `registry.modules.flatMap(m => m.sidebar)`.
- **Router** — `registry.modules.flatMap(m => m.routes ?? [])` merged at
  bootstrap into the global Vue router.
- **Settings page** — `SettingsView.vue` iterates `registry.modules` and
  renders the union of every `settingsPanel`, tabbed by `id`.

### Nullable-module parity

Removing `frontend/src/modules/camera/` must yield a build that excludes the
camera route, sidebar entry, and settings tab — with zero errors and zero
warnings. Achieved with `import.meta.glob('./modules/*/index.ts')` (lazy by
default, **never** `eager: true`) + `defineAsyncComponent()` for UI mounts
+ runtime filtering by `MODULES_ENABLED`. See § 12 Gotcha #1.

---

## 5. Module registry & discovery

### Discovery options

| Option | Pros | Cons |
|---|---|---|
| **A. Explicit list in `main.py`** | No magic, easy to read | New module = code change |
| **B. Auto-discover `modules/*/module.py`** *(recommended)* | Drop folder → module loads | Requires whitelist |
| **C. Python entry-points (`importlib.metadata`)** | True plugins from anywhere | Overkill for one app |

### Recommendation: B with whitelist

```python
# backend/main.py (planned shape)
MODULES_ENABLED = set(filter(None, os.getenv("MODULES_ENABLED", "").split(",")))

def discover() -> list[type[PluggableModule]]:
    out = []
    for path in sorted(Path("backend/modules").glob("*/module.py")):
        mod = importlib.import_module(f"backend.modules.{path.parent.name}.module")
        cls = getattr(mod, "Module", None)
        if cls is not None and issubclass(cls, PluggableModule):
            out.append(cls)
    return out

for cls in discover():
    inst = cls()
    m = inst.manifest()
    if m.id not in MODULES_ENABLED:
        continue
    mount(inst, app)              # calls router(), settings_router(), on_load()
```

Why not pure auto-discovery: protects against accidentally shipping test or
half-done modules. Whitelist is `MODULES_ENABLED` env var or default-empty +
explicit opt-in.

---

## 6. Settings subsystem architecture

### 6.1 Goals

- Every module ships **a Pydantic schema** describing every setting it owns.
- The same schema is the source of truth for:
  - Validation (PUT `/settings` enforces it)
  - Default values (model defaults)
  - Frontend form rendering (via `model_json_schema()` → JSON Schema)
  - Generated docs (via `model_json_schema()` → HTML page)
- Storage is **per-module**, JSON-backed, atomic-write, default-fallback.
- Settings are server-side (not per-user) in this pass. Per-user is out of
  scope.

### 6.2 Backend

Per-module router, mounted by the registry:

```
GET    /api/v1/modules/<id>/settings          → current settings (or defaults)
PUT    /api/v1/modules/<id>/settings          → write (validated, atomic)
POST   /api/v1/modules/<id>/settings/reset    → back to defaults
GET    /api/v1/modules/<id>/settings/schema   → JSON Schema (for forms/docs)
```

Standard responses:

- `200` on read/write success.
- `404` if the module is not loaded — the registry is the single source of
  "is this module live". Frontend uses 404 to hide the panel.
- `422` if the PUT body fails Pydantic validation (already standard for
  FastAPI).

### 6.3 Frontend

```text
SettingsView.vue
└── v-for module in registry
    └── <ModuleSettingsTab :moduleId="module.id" :schema="module.schema" />
        ├── renders JSON Schema form (form generator TBD — see § 8.3)
        ├── GET on mount → fills form
        ├── PUT on submit → atomic server-side validation, then re-fetch
        └── "Reset to defaults" button → POST /reset
```

### 6.4 Storage layout

```text
data/
└── modules/
    ├── camera/
    │   └── settings.json        # atomic-write target
    └── machine/
        └── settings.json
```

- `data/` is gitignored (machine-specific, not portable).
- Reads: cache in memory on module load, serve from cache, reload on PUT.
- Writes: serialize Pydantic model → write to `settings.json.tmp` → `os.replace`
  on POSIX, `os.replace` on Windows (atomic there too).
- File permission: 0o600 (POSIX) where supported.

### 6.5 Nullability

If `data/modules/<id>/settings.json` is missing on first read:

- Fall back to Pydantic model defaults.
- Lazily created on first PUT, not at read time.

---

## 7. Settings storage backend evaluation

We want per-module settings storage. Candidate backends:

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **JSON per module** | Simple, zero deps, atomic via `tmp+rename`, per-module isolation, easy export, easy diff review | No native queries; must revalidate on every read (cheap with Pydantic) | ⭐ **Primary** |
| **Single SQLite db** (all modules) | One file, queryable, transactional | Overkill for tens of settings per module; cross-module tables get coupled; hard to back up per-module | Reject for v1 |
| **SQLite per module** | Isolation + queries | Overkill for v1 settings; more code to maintain | Reject for v1 |
| **YAML per module** | Human-friendly | Brittle atomic write, parser dep | Reject |
| **TOML per module** | Typer-safe in tools, sections | Less mature atomic-write story on Windows | Reject |
| **INI per module (reuse `machine.cfg` parser)** | Reuses existing parser | Awkward semantics (UI prefs mixed with machine state); flat sections only | Reject |
| **TinyDB** (JSON DB w/ query API) | Drop-in JSON, richer queries | Slightly more machinery than vanilla JSON, still not transactional | Acceptable alt |
| **ZOD + JSON** (frontend schema only) | Frontend validation | Backend also needs validation; do not want two schema sources | Reject |

### Recommendation: **Pydantic-validated JSON per module.**

Why:

- The Pydantic model is already required for the API (PUT validation). Using
  it directly for storage costs nothing extra.
- `model_dump_json()` + `tmp+rename` is robust and dependency-free.
- `model_json_schema()` gives the frontend a uniform form generator without
  duplicating definitions.
- Per-module isolation matches per-module settings ownership.
- Migration to SQLite (per-module) later is a drop-in: only the
  `SettingsStore` implementation changes, contracts are untouched.

### Future: optional database promotion

When a module outgrows JSON (e.g. **telemetry history**, **G-code job queue**,
**graph history**, **event log**), the registry passes a `db: sqlite3.Connection`
to its `ModuleContext`. The module opts in by declaring it in the manifest:

```python
class ModuleManifest(BaseModel):
    ...
    storage: Literal["json"] | Literal["sqlite"] = "json"
```

A "JSON → SQLite migration" helper ships later. No module author should have
to think about this until they need it.

---

## 8. Open questions (decide before phase 2c)

### 8.1 Form generator for the frontend

Choices for rendering JSON Schema into a Vue settings UI:

| Lib | Pros | Cons |
|---|---|---|
| `@json-editor/json-editor` | Mature, JSON-Schema native | Heavy, opinionated UI |
| `@rjsf/core` (React JSON Schema Form) | Mature, well-tested | React, not Vue |
| Hand-rolled `form-for-pydantic.ts` | Tiny, Vue-native, full control | Re-implement validation messages |

**Recommendation:** start with a tiny hand-rolled renderer for the few
field types we actually use (`string`, `int`, `float`, `bool`, `enum`,
`list[str]`, nested model). Revisit if it grows.

### 8.2 Where does `core/` end and `modules/` begin?

Initial split:

| Lives in `core/` (shared) | Lives in `modules/<id>/` (per-feature) |
|---|---|
| `config_manager.py` (machine.cfg parser) | Module-specific router |
| `models.py` (shared enums: `LinuxCNCState`, units, axes) | Module-specific Pydantic models |
| `hardware/` (singleton, real + mock) | Module-specific settings |
| `telemetry/` (transport + bus — Phase 4) | Module-specific store(s) and UI |

Rule of thumb: if you can imagine **two modules wanting it** without one
needing the other, it goes in `core/`.

### 8.3 Module ↔ event bus cross-talk

Initial cross-module needs:

- `machine` module publishes "homed", "estop", etc.
- `compiler` module subscribes to "machine.cfg changed" to invalidate its
  previews.
- `files` module subscribes to "program loaded" to refresh UI badges.

Implementation: a tiny in-process `EventBus` with typed topics. **No** modules
import each other's stores. **No** modules call other modules' endpoints on
the backend — that's a coupling smell.

**Contract rule:** every payload published to the bus MUST be a Pydantic
data-only model (backend) or a `Readonly` / `Object.freeze`'d TypeScript
value (frontend). Subscribers MUST treat received payloads as immutable;
if a subscriber needs a derived value it publishes a fresh payload of its
own. The `EventBus` implementation enforces this by copying payloads into
a fresh Pydantic instance (backend) or `Object.freeze` (frontend) before
fanning out to subscribers. See § 12 Gotcha #3.

### 8.4 Telemetry bus (Phase 4)

Already discussed in the review phase: today's `WebSocket` is owned by
`stores/machine.js`, which makes other modules hack-poll state. The module
contract makes it explicit:

- Backend owns the WebSocket under `telemetry/`.
- An `EventBus` re-broadcasts typed events to modules.
- No module imports `telemetry` directly — it gets a `TelemetryBus` handle
  from `ModuleContext`.

### 8.5 Auth / multi-user

Out of scope for this pass. Re-evaluate when needed. Initial assumption:
single-user LAN deployment; no token, no login.

### 8.6 Migration of existing artefacts

Mapping (1:1, no rewrite):

| Existing | New home |
|---|---|
| `backend/routers/camera.py` | `backend/modules/camera/router.py` |
| `backend/routers/machine.py` | `backend/modules/machine/router.py` |
| `backend/routers/jog.py` | `backend/modules/machine/jog.py` (kept inside `machine/`) |
| `backend/routers/files.py` | `backend/modules/files/router.py` |
| `backend/routers/config.py` | `backend/modules/config/router.py` |
| `backend/routers/compiler.py` | `backend/modules/compiler/router.py` |
| `backend/routers/system.py` | `backend/modules/system/router.py` |
| `backend/routers/websocket.py` | `backend/core/telemetry/transport.py` (cross-cutting) |
| `backend/services/hal_compiler.py` | `backend/modules/compiler/hal_compiler.py` |
| `frontend/src/components/CameraPanel.vue` | `frontend/src/modules/camera/components/CameraPanel.vue` |
| `frontend/src/components/CompilerPanel.vue` | `frontend/src/modules/compiler/components/CompilerPanel.vue` |
| ... rest follows the same pattern | |

---

## 9. Phased migration roadmap

Each phase is **reviewable independently** and **reversible**.

| Phase | Scope | Status |
|---|---|---|
| 1 | Generated client out of source + gitignore | ✅ Done |
| 2a | `.agent/` folder, doc restructure, contract docs | 🔜 Next up |
| 2b | `PluggableModule` protocol + `ModuleRegistry` skeleton (no modules migrated yet — registry starts empty) | ⏳ |
| 2c | Settings subsystem backend + frontend skeleton (empty settings page) | ⏳ |
| 2d | Migrate **camera** as the template (smallest isolated feature); validate the nullable test | ⏳ |
| 3 | Migrate `files`, `system`, `config`, `compiler`, `program` one at a time using camera's pattern | ⏳ |
| 3a | Migrate `machine` (jog + state + mode + MDI + telemetry *consumers*); leave telemetry *transport* in core | ⏳ |
| 4 | Subscription-based telemetry: `core/telemetry/transport.py` + typed `EventBus`; decompose `stores/machine.js` | ⏳ |
| 5 | Settings UI auto-renders from `model_json_schema()`; drop per-module hand-coded settings forms where they exist | ⏳ |
| 6 | Per-module SQLite opt-in for high-volume modules (telemetry history, job queue) | ⏳ |

### Why this order

- **2a before 2b:** contract first, then registry implementing the contract.
  Avoids having to refactor a registry built against a non-existent contract.
- **2b before 2c:** registry can stay empty. No new code paths in production.
- **2c before 2d:** camera migration must be able to *use* the settings subsystem,
  otherwise the camera module won't have a real settings panel to demonstrate.
- **2d first (camera) before 3:** camera is the smallest, most isolated feature.
  Validates end-to-end with minimal blast radius.
- **3a before 4:** machine touches everything. Stable machine behaviour first,
  then refactor telemetry ownership without also moving endpoints around.
- **5 after 3:** form-from-schema only matters once we have modules with
  non-trivial settings.
- **6 last:** only if/when a real module needs it.

---

## 10. Risks & open questions

- **Risk:** introducing a registry will require touching `main.py`'s
  `lifespan` context. Mitigation: keep `lifespan` thin (just calls
  `registry.boot(app)` / `registry.shutdown()`).
- **Risk:** migrating `routers/machine.py` (the biggest) before the
  telemetry refactor will entangle concerns. Mitigation: Phase 3 explicitly
  ends *before* telemetry changes.
- **Risk:** settings duplication (Pydantic on backend, Vue form on frontend)
  unless we generate the form. Mitigation: Phase 5 must precede any module
  that ships ≥ 3 settings.
- **Open:** do we want module-level permissions (e.g. "disable compiler"
  for safety)? Tabled until auth lands.
- **Open:** hot-reload modules in dev? Useful but not required for v1.
- **Open:** does a module's settings live in the same DB transaction as
  machine state? Initial answer: **no** — `machine.cfg` is the SSOT
  for machine state, settings is for module UI/runtime preferences.

---

## 11. Glossary

- **Module** — a self-contained feature owning its backend (FastAPI router),
  frontend (Pinia store + Vue components), settings schema, and storage.
- **Registry** — the runtime container that mounts/unmounts modules at
  startup/shutdown.
- **PluggableModule** — the backend protocol (Python `Protocol`) each module
  implements.
- **FrontendModule** — the frontend interface (TypeScript) each module
  implements.
- **Manifest** — a Pydantic/TS object describing a module's id, version,
  requires/provides, settings schema.
- **EventBus** — cross-module pub/sub inside one process; never spans
  modules.
- **TelemetryBus** — wrapper around the WebSocket transport that exposes
  typed `full_state`, `delta`, `error` events.
- **SettingsStore** — JSON-backed per-module settings persistence.
- **SSOT** — single source of truth (`machine.cfg`) for machine state.

---

## 12. Implementation Gotchas

These three pitfalls are not obvious from the contracts alone and have
caused real bugs in similar projects. They are **part of the contract** —
modules that violate them will be rejected on review.

### Gotcha #1 — Frontend code splitting is the nullability secret

A module being "absent" requires the build to skip it without complaint.
That is only possible if the module's index file is loaded lazily.

- **Wrong:** `import x from '@/modules/camera'` — fails the build if
  `camera/` doesn't exist.
- **Wrong:** `import.meta.glob('./modules/*/index.ts', { eager: true })` —
  Vite bundles them at build time, so a missing folder is still a build
  error.
- **Right:** `import.meta.glob('./modules/*/index.ts')` (lazy by default)
  + `defineAsyncComponent()` for any UI mounts + runtime filter by
  `MODULES_ENABLED`.

This is what makes the *nullable-module guarantee* actually hold for the
frontend. Static imports anywhere in the app shell would silently break it.

### Gotcha #2 — Pinia store namespacing

If two modules define a store with the same ID, Pinia throws or silently
overwrites — both are bad.

**Contract rule (in `.agent/contracts/frontend-module.md`):**

```ts
// inside store.ts
export const useCameraStore = defineStore('module_camera', () => {
  // setup-store form
})
```

The store **ID string** is the source of truth, not the exported function
name. Format: `module_<id>`. Enforced in CI by a regex check on every
`defineStore(` call inside `frontend/src/modules/`; any id not matching
`^module_[a-z][a-z0-9_]+$` fails the build with a clear error.

### Gotcha #3 — Event bus payloads must be immutable data-only objects

If module A publishes a raw object and module B mutates it, module C (a
later subscriber) sees the mutated version. Classic heisenbug class.
The original Python/JS objects get passed by reference and one subscriber's
`temp.value += 1` quietly rewrites what every other subscriber is reading.

**Contract rule (in `.agent/contracts/backend-module.md` and
`.agent/contracts/frontend-module.md`):**

> Payloads published to the bus MUST be Pydantic models (backend) or
> frozen TypeScript types (frontend) — data only, no behaviour.
> Subscribers MUST treat received payloads as read-only. If a subscriber
> needs a derived value, it produces and publishes its own payload.

The `EventBus` implementation enforces this — backend re-instantiates a
fresh Pydantic model from the payload before fanning out, frontend
`Object.freeze`s the value before delivery. Subscribers physically cannot
mutate the canonical payload.

---

## 13. Acceptance criteria for "module system is done"

The system is "done" when, in a single CI run on a clean checkout, you can:

1. `git clone … && cd … && ./start_dev.sh` → both backend and frontend boot.
2. Remove `backend/modules/camera/` and `frontend/src/modules/camera/` →
   re-run → everything else still works.
3. Visit `/settings` → every present module has a tab; every removed module's
   tab is absent.
4. Disable `MODULES_ENABLED=camera,system` → only those two mount; no
   warnings about missing dependencies.
5. Kill the backend, change `MODULES_ENABLED` to empty, restart → backend
   boots with zero routers mounted, the frontend still serves the dashboard
   shell with only the core views.

When all 5 pass, the modularisation is structurally complete.
