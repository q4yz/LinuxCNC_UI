# Backend Module Contract (`PluggableModule`)

The canonical contract every pluggable backend module must satisfy.
Authoritative source for what the registry expects and what module
authors must implement. Living document — the matching Python types
live in [`backend/core/protocols.py`](../../backend/core/protocols.py)
and [`backend/core/module_registry.py`](../../backend/core/module_registry.py).

## 1. The `PluggableModule` Protocol

```python
@runtime_checkable
class PluggableModule(Protocol):
    manifest: ModuleManifest
    def on_load(self, ctx: ModuleContext) -> None: ...
    def on_unload(self) -> None: ...
    def get_router(self) -> Optional[APIRouter]: ...
```

A module is **any object** with these four members — no inheritance
required. The registry uses `isinstance(obj, PluggableModule)` to
validate candidates at boot time.

## 2. ModuleManifest

Static metadata read by the registry before `on_load` runs. Fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | yes | Unique module identifier. Used as URL prefix and settings namespace. |
| `title` | `str` | yes | Human-readable display name. |
| `version` | `str` | no | Semantic-ish version string. Defaults to `"0.0.0"`. |
| `description` | `str` | no | One-line description. |
| `sidebar` | `SidebarEntry` | no | Optional sidebar entry the module contributes. |
| `settings_panel` | `bool` | no | Whether this module contributes a Settings tab. Defaults to `False`. |

Manifests are Pydantic models so they serialize to JSON cleanly and
the OpenAPI / settings subsystems can consume them without any
module-specific code.

## 3. SidebarEntry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | yes | Stable route identifier; must be unique app-wide. |
| `label` | `str` | yes | Display text. |
| `icon` | `str` | no | SVG/HTML icon string. |
| `order` | `int` | no | Sort weight. Lower numbers appear earlier. Default `100`. |

## 4. ModuleContext

The runtime context handed to `on_load`. Modules must treat it as
read-only — they can read `event_bus` / `settings` and attach
additional fields under `extras`, but they must not replace them.

```python
@dataclass
class ModuleContext:
    module_id: str
    event_bus: EventBus
    settings: SettingsStore
    extras: Dict[str, Any] = field(default_factory=dict)
```

## 5. Lifecycle

```
  ┌──────────────────┐
  │ ModuleRegistry   │
  │ .discover()      │  scans backend/modules/*/ for setup() factories
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ whitelist filter │  MODULES_ENABLED env var; unknown IDs WARN
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ _mount() per id  │  build ctx, call on_load(ctx), mount routers
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ one-line summary │  "registry: mounted=[…] skipped=N missing=N"
  └──────────────────┘
```

`on_unload` is called in **reverse registration order** during
shutdown. It must be idempotent because the registry may call it more
than once under `--reload`.

## 6. Router Mounting

If `get_router()` returns a router, the registry mounts it at:

```
/api/v1/modules/<module_id>
```

with OpenAPI tag `modules:<module_id>`. Settings endpoints are
mounted separately by the registry — modules do **not** expose
settings routes via `get_router()`.

## 7. Settings Surface

The registry always mounts the four canonical settings endpoints at:

```
/api/v1/modules/<module_id>/settings
```

See [`settings-module.md`](settings-module.md) for the full contract.

## 8. EventBus Contract — Immutable Payloads (Gotcha #3)

Every `event_bus.publish(topic, payload)` call hands every subscriber
its own **freshly-cloned copy** of the payload. Subscribers can
mutate their copy without affecting other subscribers or the
publisher.

For Pydantic `BaseModel` payloads the bus uses `payload.model_copy(deep=True)`.
Plain dicts/lists/scalars are passed by reference — the contract
deliberately only deep-copies models because perf-sensitive publishers
(e.g. telemetry at 100 Hz) would suffer otherwise.

## 9. Module Discovery Convention

A module is a sub-package of `backend/modules/` that exposes a
top-level `setup()` factory returning a `PluggableModule`. The
package name becomes the candidate id; the manifest's `id` is the
**public** identifier (used in URLs and the whitelist).

```python
# backend/modules/camera/__init__.py
from .module import setup  # re-export for the registry
```

```python
# backend/modules/camera/module.py
from fastapi import APIRouter
from core.protocols import ModuleContext, ModuleManifest, PluggableModule

class CameraModule:
    manifest = ModuleManifest(
        id="camera",
        title="Camera",
        sidebar={"id": "camera", "label": "Camera"},
    )

    def on_load(self, ctx: ModuleContext) -> None:
        ctx.event_bus.subscribe("state.machine", self._on_state)

    def on_unload(self) -> None:
        # idempotent cleanup
        ...

    def get_router(self) -> APIRouter:
        return _router  # built lazily if needed

def setup() -> PluggableModule:
    return CameraModule()
```

## 10. Acceptance Checklist

A module is "ready" when:

- [ ] `isinstance(instance, PluggableModule)` returns `True`.
- [ ] `manifest.id` is unique app-wide.
- [ ] `on_load` is non-blocking.
- [ ] `on_unload` is idempotent.
- [ ] Subscribers treat payloads as read-only.
- [ ] Settings endpoints (when `manifest.settings_panel=True`) use
      the four canonical routes — no custom settings router.
- [ ] The package's `__init__.py` re-exports `setup` so the registry
      can find it.