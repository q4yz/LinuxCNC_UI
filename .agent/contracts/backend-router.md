# Backend Module Contract — Per-Domain Routers

Authoritative contract every backend module **must** satisfy. Living
document. The matching implementation lives under
[`backend/`](../../backend/) — all file references below use
`path:line` form so a reader can jump straight to the cited code.

> **What replaced `PluggableModule`.** The previous protocol used a
> `PluggableModule` class with `on_load` / `on_unload` hooks, a
> `ModuleManifest`, a `ModuleContext`, and a `SidebarEntry`. The
> `ModuleRegistry` that walked `backend/modules/<id>/` has been
> retired. There is **no `backend/modules/` directory** — the
> per-domain routers live directly under
> [`backend/routers/<id>.py`](../../backend/routers/) and are mounted
> in [`backend/main.py:88-321`](../../backend/main.py) via the
> `_MODULE_DOMAINS` table.

> **Modules are mandatory.** Every module that ships in
> `/api/v1/modules/<id>/` is a hard dependency: its router is
> `include_router`'d at boot, its `*Settings` Pydantic defaults
> model is wired into a `SettingsStore`, and the four canonical
> settings endpoints are mounted under
> `/api/v1/modules/<id>/settings`. No module is "nullable" — there
> is no concept of a module that may be absent at runtime. A module
> that is not ready to satisfy the full contract does not ship.

## 1. The router contract

File: [`backend/routers/<id>.py`](../../backend/routers/)

A module exports a **module-level** `router = APIRouter(...)` with:

- `prefix="/api/v1/modules/<id>"` — same `<id>` as the manifest.
- `tags=["modules:<id>"]` — drives the OpenAPI tag.
- One or more `@router.<verb>(...)` handlers.

The router is the only thing `main.py` imports from the module.
There are no `on_load` / `on_unload` lifecycle hooks; lifespan
work that used to live in `ModuleRegistry` has moved to plain
helpers in [`backend/main.py:138-258`](../../backend/main.py)
(`start_watchdog_if_configured`, `bind_camera_settings_store`,
`register_machineconfig_exception_handlers`, etc.).

```python
# backend/routers/tools.py:65-68
router = APIRouter(
    prefix="/api/v1/modules/tools",
    tags=["modules:tools"],
)
```

## 2. The eight canonical module ids

Taken directly from the `_MODULE_DOMAINS` table at
[`backend/main.py:88-97`](../../backend/main.py):

| `module_id`        | Router file                                                            | Tag                       | Notes |
|--------------------|------------------------------------------------------------------------|---------------------------|-------|
| `axis`             | [`routers/axis.py`](../../backend/routers/axis.py)                     | `modules:axis`            | Homing facade — single endpoint. |
| `machine_state`    | [`routers/state.py`](../../backend/routers/state.py)                   | `modules:machine_state`   | State / mode / MDI. Lives separately from `axis`. |
| `program`          | [`routers/program.py`](../../backend/routers/program.py)               | `modules:program`         | Lifecycle (load / run / stop / pause / resume / unload / parse). |
| `temperature`      | [`routers/temperature.py`](../../backend/routers/temperature.py)       | `modules:temperature`     | **Deprecated** — returns `410 GONE` for legacy callers. Real work lives in `tools`. |
| `tools`            | [`routers/tools.py`](../../backend/routers/tools.py)                   | `modules:tools`           | Spindle / extruder / heater — canonical DDD example. |
| `macros`           | [`routers/macros.py`](../../backend/routers/macros.py)                 | `modules:macros`          | `.macro` / `.ngc` / `mcode` CRUD + execute. |
| `camera`           | [`routers/camera.py`](../../backend/routers/camera.py)                 | `modules:camera`          | `ustreamer` supervisor co-located with router. |
| `machineconfig`    | [`routers/machineconfig.py`](../../backend/routers/machineconfig.py)   | `modules:machineconfig`   | Profiles / compilers / staged / active / deploy / m-codes. |

Plus four **legacy flat routers** that pre-date the split — see § 5
of [`.agent/context/BACKEND_LAYERS.md`](../context/BACKEND_LAYERS.md)
for the "Exceptions to the rule" list.

## 3. Mount order in `main.py`

The settings router is mounted **before** the module router so a
module that exposes a bare `/{name}` path cannot shadow
`/api/v1/modules/<id>/settings` — Starlette matches in registration
order
([`backend/main.py:308-321`](../../backend/main.py)):

```python
# backend/main.py:313-321
for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    app.include_router(
        _module_settings_router.build_module_settings_router(
            _settings_stores[_module_id],
        ),
        prefix=f"/api/v1/modules/{_module_id}/settings",
        tags=[f"modules:{_module_id}:settings"],
    )
    app.include_router(_router)
```

The `SettingsStore` is built once at import time per module so the
lifespan manager can hand the same instance to the watchdog, the
camera supervisor, etc.
([`backend/main.py:290-298`](../../backend/main.py)):

```python
_settings_stores: dict[str, SettingsStore] = {}
_DATA_ROOT = Path("data")
for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    _settings_stores[_module_id] = SettingsStore(
        module_id=_module_id,
        data_root=_DATA_ROOT,
        defaults=_settings_cls(),
    )
```

## 4. The settings contract

File: [`backend/models/<id>_settings.py`](../../backend/models/)

A Pydantic `BaseModel` subclass that documents the canonical shape
the [`SettingsStore`](../../backend/core/settings_store.py) will
serve on `GET /api/v1/modules/<id>/settings`. New keys can be added
in later releases without breaking existing deployments — the store
merges the defaults underneath the persisted payload so a missing
key is filled in from this schema's defaults on every read.

```python
# backend/models/tools_settings.py:37-64
class ToolsSettings(BaseModel):
    confirm_spindle_start: bool = Field(default=False, description=...)
    max_spindle_rpm: int = Field(default=12000, ge=0, le=200_000, description=...)
```

The full contract for the four canonical settings endpoints lives in
[`.agent/contracts/settings-module.md`](settings-module.md).

## 5. Lifespan hooks

There is no `on_load` / `on_unload` per module. Instead, the
lifespan manager in
[`backend/main.py:106-169`](../../backend/main.py) runs a flat
sequence of helpers that handle the cross-cutting boot work the
old per-module hooks used to do:

| Helper | Module | Source line |
|--------|--------|-------------|
| `tool_service.preload_hal_pins()` | `tools` | `main.py:123` |
| `sensor_service.preload_hal_pins()` | `temperature` | `main.py:124` |
| `HalPin.initialize_component()` | (shared) | `main.py:125` |
| `reseed_from_hardware_json()` | (mock seed) | `main.py:127` |
| `mock_system.start_simulation()` | (mock seed) | `main.py:128` |
| `get_servo_thread_service().telemetry_loop()` | (telemetry) | `main.py:131-133` |
| `reseed_temperature_defaults()` | `temperature` | `main.py:138` |
| `start_watchdog_if_configured()` | `axis` | `main.py:139` |
| `bind_camera_settings_store()` | `camera` | `main.py:140` |
| `register_machineconfig_exception_handlers(app)` | `machineconfig` | `main.py:141` |

Shutdown reverses the same hooks symmetrically.

## 6. Router hard rules

Rules enforced by code review:

- **No `import backend.hardware.*`** from a router. Feature code
  must go through a service facade so the mock layer stays
  portable.
- **Pydantic `*Command` / `*Response` models** live under
  [`backend/models/`](../../backend/models/) — see the worked
  example in [`BACKEND_LAYERS.md`](../context/BACKEND_LAYERS.md) § 2.
- **No imports of `backend.modules`** — that path does not exist.
- **No `router = None`** returns. The registry refuses to mount a
  router that returns `None`.
- **Status codes** use [`backend/exceptions/http.py`](../../backend/exceptions/http.py):
  `BadRequestError` → 400, `NotFoundError` → 404, `ConflictError`
  → 409. Anything outside that triple is a direct
  `raise HTTPException(...)`.

## 7. Acceptance checklist

A backend module is "ready" when:

- [ ] `backend/routers/<id>.py` exists and exports a module-level
      `router = APIRouter(prefix="/api/v1/modules/<id>",
      tags=["modules:<id>"])`.
- [ ] `backend/models/<id>_settings.py` exists and exports a
      non-null Pydantic `BaseModel` subclass.
- [ ] The module appears in `main.py:_MODULE_DOMAINS`.
- [ ] The router does not import `backend.hardware.*` directly.
- [ ] The router does not import from `backend.modules.*` (the
      path does not exist).
- [ ] Each handler returns a Pydantic response model declared in
      `backend/models/`.
- [ ] Status codes use `BadRequestError` / `NotFoundError` /
      `ConflictError` for the standard triple.
- [ ] Any HAL pin preload / subscription runs in the lifespan
      helpers in `main.py`, not in the router.

---

**See also:** [`.agent/context/BACKEND_LAYERS.md`](../context/BACKEND_LAYERS.md)
for the canonical Router → Service → DTO → Mapper → Storage pattern;
[`.agent/contracts/settings-module.md`](settings-module.md) for the
four canonical settings endpoints and atomic-write contract.
