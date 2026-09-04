# Backend Module Contract — Per-Domain Routers

Authoritative contract every backend module **must** satisfy. Living
document. The backend is split into two FastAPI apps —
`backend/machine/` (port 8000) and `backend/system/` (port 8001) —
each with its **own** `_MODULE_DOMAINS` table, its own settings-store
data root, and its own module ids; a module id belongs to exactly
one app, never both. See
[`.agent/context/ARCHITECTURE.md`](../context/ARCHITECTURE.md) for
the process-level picture.

> **No `backend/modules/` plugin directory.** There is no
> `ModuleRegistry`, `PluggableModule`, `ModuleManifest`, or
> `on_load`/`on_unload` lifecycle hook. Per-domain routers live
> directly under `backend/<app>/routers/<id>.py` and are mounted in
> that app's own `main.py` via its `_MODULE_DOMAINS` table.

> **Modules are mandatory.** Every module that ships in
> `/api/v1/modules/<id>/` is a hard dependency: its router is
> `include_router`'d at boot, its `*Settings` Pydantic defaults
> model is wired into a `SettingsStore`, and the four canonical
> settings endpoints are mounted under
> `/api/v1/modules/<id>/settings`. No module is "nullable" — there
> is no concept of a module that may be absent at runtime. A module
> that is not ready to satisfy the full contract does not ship.

## 1. The router contract

File: `backend/<app>/routers/<id>.py`

A module exports a **module-level** `router = APIRouter(...)` with:

- `prefix="/api/v1/modules/<id>"` — same `<id>` used in `_MODULE_DOMAINS`.
- `tags=["modules:<id>"]` — drives the OpenAPI tag.
- One or more `@router.<verb>(...)` handlers.

The router is the only thing `main.py` imports from the module for
mounting purposes. There are no `on_load` / `on_unload` lifecycle
hooks; any boot-time work a module needs is a plain helper function
called from that app's `lifespan()` (see `§ 5`).

```python
# backend/machine/routers/tools.py (sketch)
router = APIRouter(
    prefix="/api/v1/modules/tools",
    tags=["modules:tools"],
)
```

## 2. The module ids, split by app

### 2.1 Machine backend (`backend/machine/main.py`, port 8000)

| `module_id`        | Router file                                                                    | Tag                       | Notes |
|--------------------|---------------------------------------------------------------------------------|---------------------------|-------|
| `axis`             | [`routers/axis.py`](../../backend/machine/routers/axis.py)                     | `modules:axis`            | Homing facade — single endpoint. |
| `machine_state`    | [`routers/state.py`](../../backend/machine/routers/state.py)                   | `modules:machine_state`   | State / mode / MDI. Lives separately from `axis`. |
| `program`          | [`routers/program.py`](../../backend/machine/routers/program.py)               | `modules:program`         | Lifecycle (load / run / stop / pause / resume / unload / parse). |
| `temperature`      | [`routers/temperature.py`](../../backend/machine/routers/temperature.py)       | `modules:temperature`     | **Deprecated** — returns `410 GONE` for legacy callers. Real work lives in `tools`. |
| `tools`            | [`routers/tools.py`](../../backend/machine/routers/tools.py)                   | `modules:tools`           | Spindle / extruder / heater — canonical DDD example. |
| `camera`           | [`routers/camera.py`](../../backend/machine/routers/camera.py)                 | `modules:camera`          | `ustreamer` supervisor co-located with router. |

Plus routers mounted directly (no per-module settings, so they sit
outside `_MODULE_DOMAINS`): `BaseThreadRouter`, `ServoThreadRouter`
(telemetry, WebSocket), the Visual HAL editor's `hal` router, and
`macro_start` (the `/{name}/start` execution endpoint — CRUD for
macros lives in the system app's `macros` module).

### 2.2 System service (`backend/system/main.py`, port 8001)

| `module_id`        | Router file                                                                     | Tag                       | Notes |
|--------------------|------------------------------------------------------------------------------------|---------------------------|-------|
| `machineconfig`    | [`routers/machineconfig.py`](../../backend/system/routers/machineconfig.py)   | `modules:machineconfig`   | Profile CRUD, template generation (`hardware.json` + generated INI/HAL, see `ARCHITECTURE.md` § 7), deploy. |
| `macros`           | [`routers/macros.py`](../../backend/system/routers/macros.py)                 | `modules:macros`          | `.macro` / `.ngc` / `mcode` CRUD (the `/start` execution endpoint lives in the machine app). |

Plus routers mounted directly (no per-module settings):
`SystemRouter` (version/update), `machine_lifecycle` (start/stop/
switch the LinuxCNC process, see `ARCHITECTURE.md` § 1.3), and
`FilesRouter` (NGC program uploads for `nc_files/`).

Four routers are flagged as **exceptions to the classical
Router → Service → DTO → Mapper → Storage split** — see
[`.agent/context/BACKEND_LAYERS.md`](../context/BACKEND_LAYERS.md) § 7
(`BaseThreadRouter`, `ServoThreadRouter`, `FilesRouter`,
`SystemRouter`), plus the `state`/`program`/`camera` gaps noted
there.

## 3. Mount order in each app's `main.py`

In **both** apps, the settings router is mounted **before** the
module router so a module that exposes a bare `/{name}` path cannot
shadow `/api/v1/modules/<id>/settings` — Starlette matches in
registration order:

```python
# backend/machine/main.py (sketch — backend/system/main.py mirrors
# this with its own _MODULE_DOMAINS)
for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    app.include_router(
        module_settings_router.build_module_settings_router(
            _settings_stores[_module_id],
        ),
        prefix=f"/api/v1/modules/{_module_id}/settings",
        tags=[f"modules:{_module_id}:settings"],
    )
    app.include_router(_router)
```

The `SettingsStore` is built once at import time per module, from a
`data_root` that is **per app** —
`Path(__file__).resolve().parents[1] / "data"` resolves to
`backend/machine/data/` inside `backend/machine/main.py` and
`backend/system/data/` inside `backend/system/main.py`:

```python
_settings_stores: dict[str, SettingsStore] = {}
_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    _settings_stores[_module_id] = SettingsStore(
        module_id=_module_id,
        data_root=_DATA_ROOT,
        defaults=_settings_cls(),
    )
```

## 4. The settings contract

File: [`backend/common/models/<id>_settings.py`](../../backend/common/models/)
(shared location — both apps import their own modules' settings
classes from here)

A Pydantic `BaseModel` subclass that documents the canonical shape
the [`SettingsStore`](../../backend/common/core/settings_store.py)
will serve on `GET /api/v1/modules/<id>/settings`. New keys can be
added in later releases without breaking existing deployments — the
store merges the defaults underneath the persisted payload so a
missing key is filled in from this schema's defaults on every read.

```python
# backend/common/models/tools_settings.py (sketch)
class ToolsSettings(BaseModel):
    confirm_spindle_start: bool = Field(default=False, description=...)
    max_spindle_rpm: int = Field(default=12000, ge=0, le=200_000, description=...)
```

The full contract for the four canonical settings endpoints lives in
[`.agent/contracts/settings-module.md`](settings-module.md).

## 5. Lifespan hooks

There is no `on_load` / `on_unload` per module. Each app's
`lifespan()` runs a flat sequence of plain helper functions instead:

**Machine backend** (`backend/machine/main.py`):

| Helper | Module |
|--------|--------|
| `tool_service.preload_hal_pins()`, `sensor_service.preload_hal_pins()`, `state_service.preload_hal_pins()` | `tools`, `temperature`, `machine_state` |
| `HalPin.initialize_component()` | (shared HAL bootstrap) |
| `reseed_from_hardware_json()`, `mock_system.start_simulation()` | (mock hardware seed, only when `HAS_HAL` is false) |
| `get_servo_thread_service().telemetry_loop()` | (telemetry, launched as a background `asyncio.Task`) |
| `reseed_temperature_defaults()` | `temperature` |
| `start_watchdog_if_configured()` / `stop_watchdog_if_running()` | `axis` (jog safety watchdog, § 1.2 of `ARCHITECTURE.md`) |
| `bind_camera_settings_store()` | `camera` |
| `get_console_logger().close()` | (shutdown — flush persistent console history) |

**System service** (`backend/system/main.py`):

| Helper | Module |
|--------|--------|
| `register_machineconfig_exception_handlers(app)` | `machineconfig` — attaches the structured `ConfigValidationError` handler, covering both `machineconfig`'s and `machine_lifecycle`'s switch/generate endpoints |

Both apps probe `app.openapi()` at startup and log a loud traceback
if schema generation fails, rather than silently serving an empty
`/openapi.json`.

## 6. Router hard rules

Rules enforced by code review:

- **No `import hardware.*`** from a router. Feature code must go
  through a service facade so the mock layer stays portable.
- **Pydantic `*Command` / `*Response` models** live under
  [`backend/common/models/`](../../backend/common/models/) — see the
  worked example in [`BACKEND_LAYERS.md`](../context/BACKEND_LAYERS.md) § 2.
- **No cross-app imports.** A router in `backend/machine/` never
  imports a service, DTO, or router from `backend/system/` (or vice
  versa) — only `backend/common/` is shared.
- **No `router = None`** returns. A router that returns `None`
  cannot be mounted.
- **Status codes** use [`backend/common/exceptions/http.py`](../../backend/common/exceptions/http.py):
  `BadRequestError` → 400, `NotFoundError` → 404, `ConflictError`
  → 409. Anything outside that triple is a direct
  `raise HTTPException(...)`.
- **No bare `dict` in a signature/field, no untyped payload.** See
  the typing discipline in [`.agent/AGENT.md`](../AGENT.md).

## 7. Acceptance checklist

A backend module is "ready" when:

- [ ] `backend/<app>/routers/<id>.py` exists and exports a
      module-level `router = APIRouter(prefix="/api/v1/modules/<id>",
      tags=["modules:<id>"])`.
- [ ] `backend/common/models/<id>_settings.py` exists and exports a
      non-null Pydantic `BaseModel` subclass.
- [ ] The module appears in the owning app's `main.py:_MODULE_DOMAINS`
      — and only that app's.
- [ ] The router does not import `hardware.*` directly.
- [ ] The router does not import a service, DTO, or router from the
      other app.
- [ ] Each handler returns a Pydantic response model declared in
      `backend/common/models/`.
- [ ] Status codes use `BadRequestError` / `NotFoundError` /
      `ConflictError` for the standard triple.
- [ ] Any HAL pin preload / subscription runs in a lifespan helper
      in the owning app's `main.py`, not in the router.

---

**See also:** [`.agent/context/BACKEND_LAYERS.md`](../context/BACKEND_LAYERS.md)
for the canonical Router → Service → DTO → Mapper → Storage pattern;
[`.agent/contracts/settings-module.md`](settings-module.md) for the
four canonical settings endpoints and atomic-write contract.
