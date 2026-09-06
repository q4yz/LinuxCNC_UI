# Backend Layers — Canonical Pattern

Authoritative description of the layered split every backend module
follows: **Router → Service → DTO → Mapper → Storage**, with Pydantic
**Response** models sitting on top of the DTO layer as the wire
shape. Living document.

The backend is split into three processes — `backend/machine/`
(port 8000), `backend/system/` (port 8001), and `backend/common/`
(shared library, never runs by itself) — see
[`.agent/context/ARCHITECTURE.md`](ARCHITECTURE.md) for the
process-level picture. **Routers and services are per-app**
(`backend/<app>/routers/`, `backend/<app>/services/`); **DTOs,
mappers, models, core helpers, exceptions, and storage are shared**
and live under `backend/common/`, since none of them hold
process-specific state. All file references below use `path:line`
form so a reader can jump straight to the cited code.

> **Why this doc exists.** The backend is built around a classical
> five-layer split, but the split was applied unevenly. The `tools`
> module is the canonical example; `BaseThreadRouter` and
> `ServoThreadRouter` pre-date it and are flagged as **exceptions
> to the rule** in § 7. New module authors should clone the `tools`
> shape and read § 9 before merging anything that breaks the
> pattern.

## 1. The five layers

### 1.1 Router — HTTP edge

File: `backend/<app>/routers/<module>.py` (machine app:
[`backend/machine/routers/`](../../backend/machine/routers/); system
app: [`backend/system/routers/`](../../backend/system/routers/))

A FastAPI [`APIRouter`](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
with a `prefix` and a `tags=[...]` list. Each handler is a thin
function that:

- Validates the inbound payload against a Pydantic `*Command` model.
- Calls **one** service method (no fan-out, no orchestration).
- Maps the result through a `*Mapper` (when a response model
  exists).
- Returns the response model so FastAPI can serialise it for the
  OpenAPI schema.

```python
# backend/machine/routers/tools.py:78-100
@router.post(
    "/spindle",
    response_model=ToolCommandResponse,
    operation_id="controlSpindle",
)
def control_spindle(cmd: SpindleDigitalCommand) -> ToolCommandResponse:
    if cmd.action not in _SPINDLE_ACTIONS:
        raise BadRequestError(f"Invalid spindle action: {cmd.action!r}")
    settings = SpindleDigitalMapper.from_command_to_settings_dto(cmd)
    mdi = spindle_digital_service.set_spindle(settings)
    return ToolCommandResponse(status="success", command=mdi, tool_id=cmd.tool_id)
```

**Hard rules** (all of them enforced by review):

- Never `import hardware.*` from a router. Feature code must call
  [`backend/common/hardware/Connection.py`](../../backend/common/hardware/Connection.py)
  through a service facade so the mock layer stays portable.
- Pydantic `*Command` / `*Response` models live under
  [`backend/common/models/`](../../backend/common/models/) (or, for
  a handful of routers, inline at the top of the router file — see
  `§ 7.5`).
- Status codes use [`backend/common/exceptions/http.py`](../../backend/common/exceptions/http.py):
  `BadRequestError` → 400, `NotFoundError` → 404, `ConflictError` → 409.
  Anything outside that triple is a direct `raise HTTPException(...)`.

### 1.2 Service — business logic

File: `backend/<app>/services/<Name>Service.py` (machine app:
[`backend/machine/services/`](../../backend/machine/services/);
system app: [`backend/system/services/`](../../backend/system/services/))

A class with `__init__(self)` that takes no arguments, plus a
module-level `_<name>_service: Optional[<Name>Service] = None` and a
`get_<name>_service()` accessor that lazily builds the singleton.
The service owns:

- The translation between operator vocabulary (`"on"`, `"mdi"`,
  `"forward"`) and linuxcnc NML integer constants
  ([`backend/machine/services/StateService.py`](../../backend/machine/services/StateService.py)).
- The orchestration of DTOs and HAL pins.
- The dispatch to [`backend/common/hardware/`](../../backend/common/hardware/) —
  either `execute_sync_cmd(...)`, `execute_gcode(...)`, or
  `connection.get_machine_stat()`.

```python
# backend/machine/services/AxisService.py (sketch)
def home_all_axes(self) -> None:
    """Home all axes according to the INI file's HOME_SEQUENCE."""
    execute_sync_cmd("mode", 1, getattr(linuxcnc, "MODE_MANUAL", 1))
    execute_sync_cmd("teleop_enable", 1.0, 0)
    execute_sync_cmd("home", 3, -1)


def home_single_axes(self, axis: int) -> None:
    if axis == -1:
        self.home_all_axes()
        return
    execute_sync_cmd("mode", 1, getattr(linuxcnc, "MODE_MANUAL", 1))
    execute_sync_cmd("teleop_enable", 1.0, 0)
    execute_sync_cmd("home", 3, axis)
```

**Hard rules:**

- The router imports the singleton accessor (`get_<name>_service()`)
  — never the class directly. The lifespan can rebuild the
  singleton under `uvicorn --reload` without breaking imports.
- The service is **stateless across requests**; any per-process
  cache lives on `self` and is rebuilt by `preload_hal_pins()` at
  boot ([`backend/machine/services/ToolsService.py`](../../backend/machine/services/ToolsService.py)).
- A service in one app never imports a service from the other app.
  Only `backend/common/` is shared.

### 1.3 DTO / Entity — domain value objects

File: [`backend/common/dtos/<domain>/`](../../backend/common/dtos/)
(shared by both apps)

Frozen, slotted dataclasses (`@dataclass(frozen=True, slots=True)`)
that hold the **runtime** shape of a domain object — values pulled
out of HAL pins, raw integers from linuxcnc NML, configuration
floats. Domain enums (`MachineState`, `DirectionStateType`) live
in the same folder.

```python
# backend/common/dtos/tools/HeaterDto.py (sketch)
@dataclass(frozen=True, slots=True)
class HeaterStateDTO:
    """Operator-facing snapshot of the heater's live state."""
    id: str
    target_temperature: float = 0.0
    actual_temperature: float = 0.0
    fan: float = 0.0
    min_temp: float = 0.0
    max_temp: float = 0.0


@dataclass(slots=True)
class HeaterSettingsDTO:
    """Payload for commanding the heater to a new target temperature."""
    id: str
    target_temperature: float
    enable: bool = True
```

Three flavours of DTO live in this folder:

| DTO | Purpose | Mutability |
|-----|---------|------------|
| `*Pins` | A bundle of `HalPin` handles keyed by HAL pin name. Built once at boot by a factory from `hardware.json`. | `frozen=True` (the bundle itself) |
| `*StateDTO` | A *snapshot* of current runtime values. Built by the mapper from `*Pins`. | `frozen=True` |
| `*SettingsDTO` | A *command* payload — what the operator just asked for. Built by the mapper from a Pydantic `*Command` model. | `slots=True` (mutable so the service can normalise it) |

**Hard rules:**

- DTOs must not import Pydantic. The DTO layer is pure Python;
  Pydantic is reserved for the wire-shape layer.
- DTOs must not import `hardware.*`. The service translates HAL pins
  into DTOs via a mapper.
- HAL pin handles are themselves DTOs — see
  [`backend/common/dtos/pins/HalPin.py`](../../backend/common/dtos/pins/HalPin.py) and the
  concrete subclasses `StaticHalPin`, `ReadOnlyDynamicHalPin`,
  `ReadWriteDynamicHalPin`, `UnconnectedHalPin`.

### 1.4 Mapper — translation between layers

File: [`backend/common/mappers/<domain>/`](../../backend/common/mappers/)
(shared by both apps)

A class with `classmethod` methods that translate:

- `dict → *Pins` (boot path: `hardware.json` record → HAL pin bundle)
- `*Pins → *StateDTO` (snapshot path: HAL pin reads → DTO)
- `*Command → *SettingsDTO` (request path: HTTP body → internal command)
- `*StateDTO → *Response` (response path: DTO → wire shape)

The mapper is the **only** layer that owns `ResponseTier` field
masking via [`backend/common/core/field_masking.py`](../../backend/common/core/field_masking.py).
A field that should only appear in the static config uses
`include_static(...)`; a field that belongs to the 1 Hz base thread
uses `include_base(...)`.

```python
# backend/common/mappers/tools/HeaterMapper.py (sketch)
@classmethod
def to_response(cls, dto: HeaterStateDTO, r: ResponseTier = ResponseTier.ALL) -> HeaterStateResponse:
    return HeaterStateResponse(
        id=dto.id,
        target=include_base(dto.target_temperature, r),
        actual=include_base(dto.actual_temperature, r),
        min_temp=include_static(dto.min_temp, r),
        max_max=include_static(dto.max_temp, r),
    )
```

**Hard rules:**

- Mappers must not import FastAPI or any router. A mapper is
  framework-agnostic and can be unit-tested without an app.
- Mappers must not call services or hardware. Translation only.

### 1.5 Storage — persistence

File: [`backend/common/storage/<Name>Storage.py`](../../backend/common/storage/),
[`backend/common/core/settings_store.py`](../../backend/common/core/settings_store.py),
[`backend/common/domain_file_services/`](../../backend/common/domain_file_services/)

Framework-agnostic CRUD over disk. Two flavours:

- **Per-module settings** —
  [`core/settings_store.py`](../../backend/common/core/settings_store.py).
  One file per module at `<data_root>/modules/<module_id>/settings.json`,
  where `<data_root>` is **per app** — `backend/machine/data/` for
  modules owned by the machine backend, `backend/system/data/` for
  modules owned by the system service (each `main.py` resolves it
  relative to its own file, so the split holds regardless of the
  process's working directory). Atomic write through
  `tempfile.mkstemp + os.replace`. Thread-safe via `threading.Lock`.
- **Filesystem payloads** —
  [`storage/MacroStorage.py`](../../backend/common/storage/MacroStorage.py)
  for `.macro` / `.ngc` files;
  [`domain_file_services/`](../../backend/common/domain_file_services/)
  for profiles / staged / active / m-codes / nc_files (shared by
  both apps — see `§ 1` of `ARCHITECTURE.md`).

```python
# backend/common/storage/MacroStorage.py (sketch)
def write(self, name: str, content: str, kind: str = MacroKind.MACRO) -> int:
    """Persist ``content`` to ``<name><ext>`` atomically."""
    valid = self._validate(name)
    extension = _extension_for(kind)
    self._root.mkdir(parents=True, exist_ok=True)
    path = self._root / f"{valid}{extension}"
    fd, tmp_path = tempfile.mkstemp(prefix=f".{valid}-", suffix=f"{extension}.tmp", dir=str(self._root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path.stat().st_size
```

**Hard rules:**

- Storage classes never import FastAPI or Pydantic. Validation is
  the service's job; storage's job is to make bytes durable.
- Every write goes through `tempfile.mkstemp + fsync + os.replace`
  so a crash mid-write leaves the previous file intact.

## 2. Worked example — `POST /spindle` end-to-end

Following one HTTP request through every layer of the canonical
`tools` module (machine app). Every reference uses `path:line` where
a stable line exists, or `(sketch)` where the file has since
changed shape but the pattern still holds.

### 2.1 Wire shape — inbound

The OpenAPI client posts a `SpindleDigitalCommand`:

```python
# backend/common/models/tools/SpindleDigitalModels.py (sketch)
class SpindleDigitalCommand(BaseModel):
    tool_id: str = Field(..., min_length=1)
    action: Literal["forward", "backward", "stop"] = Field(...)
    speed: int = Field(..., ge=0, le=200_000)
    override: float = Field(default=1.0, ge=0.0, le=2.0)
    master_override_enable: bool = Field(default=False)
    master_override: int = Field(default=0, ge=0, le=200_000)
```

### 2.2 Router — accept the command

```python
# backend/machine/routers/tools.py (sketch)
@router.post(
    "/spindle",
    response_model=ToolCommandResponse,
    summary="Control SpindleDigital",
    operation_id="controlSpindle",
)
def control_spindle(cmd: SpindleDigitalCommand) -> ToolCommandResponse:
    if cmd.action not in _SPINDLE_ACTIONS:
        raise BadRequestError(f"Invalid spindle action: {cmd.action!r}")
    settings = SpindleDigitalMapper.from_command_to_settings_dto(cmd)
    mdi = spindle_digital_service.set_spindle(settings)
    return ToolCommandResponse(status="success", command=mdi, tool_id=cmd.tool_id)
```

The router validates `cmd.action` against an allow-list, then
delegates to the mapper + the service.

### 2.3 Mapper — translate to the internal command

```python
# backend/common/mappers/tools/SpindleDigitalMapper.py (sketch)
@classmethod
def from_command_to_settings_dto(cls, cmd: "SpindleDigitalCommand") -> SpindleDigitalSettingsDTO:
    """Translates the HTTP command payload into the strict internal domain DTO."""
    action_map = {
        "forward": DirectionStateType.FORWARD,
        "backward": DirectionStateType.BACKWARD,
        "stop": DirectionStateType.IDLE,
    }
    mapped_state = action_map.get(cmd.action.lower(), DirectionStateType.IDLE)
    return SpindleDigitalSettingsDTO(
        id=cmd.tool_id,
        speed=cmd.speed,
        master_override=cmd.master_override,
        override=cmd.override,
        master_override_enable=cmd.master_override_enable,
        state=mapped_state,
    )
```

The mapper produces the `SpindleDigitalSettingsDTO` — the only type
the service is allowed to receive.

### 2.4 Service — dispatch to hardware

```python
# backend/machine/services/SpindleDigitalService.py (sketch — see file for the canonical implementation)
def set_spindle(self, settings: SpindleDigitalSettingsDTO) -> str:
    """Set the spindle to the requested state and return the M-code that was dispatched."""
    # 1. Switch to MDI mode so a stale MODE_AUTO does not swallow the dispatch.
    execute_sync_cmd("mode", 5, getattr(linuxcnc, "MODE_MDI", 3))
    # 2. Translate the operator vocabulary to the M-code.
    if settings.state == DirectionStateType.FORWARD:
        return self._dispatch(M3_FORWARD, settings)
    if settings.state == DirectionStateType.BACKWARD:
        return self._dispatch(M4_BACKWARD, settings)
    return M5_STOP
```

The service uses [`execute_sync_cmd`](../../backend/common/hardware/Connection.py)
to drive the linuxcnc task through the NML channel.

### 2.5 Wire shape — outbound

The router wraps the M-code into the response envelope:

```python
# backend/common/models/tools/ToolModels.py (sketch)
class ToolCommandResponse(BaseModel):
    status: str
    command: str
    tool_id: str
```

The OpenAPI schema sees `ToolCommandResponse`; the frontend codegen
emits a `controlSpindle()` call that returns exactly that shape.

### 2.6 Summary diagram

```
HTTP POST /api/v1/modules/tools/spindle   (machine :8000)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ backend/machine/routers/tools.py::control_spindle    │
│   - validates SpindleDigitalCommand (Pydantic)       │
│   - SpindleDigitalMapper.from_command_to_settings_dto│
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ backend/common/mappers/tools/SpindleDigitalMapper.py │
│   - action literal → DirectionStateType enum         │
│   - emits SpindleDigitalSettingsDTO                  │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ backend/machine/services/SpindleDigitalService.py    │
│   - MODE_MDI pre-switch                              │
│   - M3 / M4 / M5 dispatch via execute_sync_cmd       │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
          common/hardware.Connection
                     │
                     ▼
               linuxcnc NML
```

## 3. The wire shape — Request / Internal / Response

Every classical module's edge carries three Pydantic models per
endpoint:

| Layer | Naming convention | Example |
|-------|-------------------|---------|
| Request body | `<Verb><Entity>Command` | `SpindleDigitalCommand`, `HeaterCommand`, `ExtruderCommand`, `LoadProgramRequest` |
| Response body | `<Entity>Response`, `<Entity>CommandResponse`, `<Entity>StateResponse` | `ToolCommandResponse`, `HeaterStateResponse`, `SpindleDigitalStateResponse`, `ProgramProgressResponse` |
| Settings defaults | `<Module>Settings` (one per module) | `ToolsSettings`, `CameraSettings`, `TemperatureSettings` |

All three live in [`backend/common/models/`](../../backend/common/models/),
shared by both apps.

The **internal** payload between layers is the frozen dataclass
DTO, not a Pydantic model — see
[`backend/common/dtos/tools/HeaterDto.py`](../../backend/common/dtos/tools/HeaterDto.py).

The mapping back to the wire shape uses the mapper:

```python
# backend/common/mappers/tools/SpindleDigitalMapper.py (sketch)
@classmethod
def to_response(cls, dto: SpindleDigitalStateDTO, r: ResponseTier = ResponseTier.ALL) -> "SpindleDigitalStateResponse":
    """Translates the internal State DTO to the HTTP Response Model."""
    if dto.spindle_forward:
        state_str = "forward"
    elif dto.spindle_reverse:
        state_str = "backward"
    else:
        state_str = "idle"
    return SpindleDigitalStateResponse(
        id=dto.id,
        target_rpm=include_base(dto.target_rpm, r),
        actual_rpm=include_base(dto.actual_rpm, r),
        ...
        state=include_base(state_str, r),
    )
```

## 4. Singletons, lifespan, settings

### 4.1 The `get_<name>_service()` pattern

Every service exports a lazy module-level singleton:

```python
# backend/machine/services/StateService.py (sketch)
_state_service: Optional[StateService] = None


def get_state_service() -> StateService:
    """Lazy module-level singleton (state / mode / MDI facade)."""
    global _state_service
    if _state_service is None:
        _state_service = StateService()
    return _state_service
```

Routers import the accessor (`get_state_service`) — never the
class directly — so the singleton lifecycle can change without
touching the router.

Each app's `main.py` lifespan pre-warms the singletons that need to
seed HAL pins before the WebSocket loop starts
([`backend/machine/main.py`](../../backend/machine/main.py)):

```python
tool_service = get_tools_service()
sensor_service = get_temperature_service()
```

### 4.2 Per-module settings stores

A `SettingsStore` is built once per module at import time, inside
each app's own `main.py`, so the lifespan manager can hand the same
instance to the watchdog, the camera supervisor, etc.:

```python
# backend/machine/main.py (sketch — backend/system/main.py mirrors this
# with its own _MODULE_DOMAINS and its own backend/system/data/ root)
_settings_stores: dict[str, SettingsStore] = {}
_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    _settings_stores[_module_id] = SettingsStore(
        module_id=_module_id,
        data_root=_DATA_ROOT,
        defaults=_settings_cls(),
    )
```

### 4.3 The four canonical settings endpoints

[`backend/common/module_settings_router.py`](../../backend/common/module_settings_router.py)
mounts the same four endpoints under
`/api/v1/modules/<id>/settings` for every module, in **both** apps.
Modules never add their own `/settings` routes — see
[`.agent/contracts/settings-module.md`](../contracts/settings-module.md) § 2.

| Method | Path | Description |
|--------|------|--------------|
| `GET`  | `/api/v1/modules/{id}/settings` | Read full payload (defaults merged in). |
| `GET`  | `/api/v1/modules/{id}/settings/{k}` | Read single key (404 if missing). |
| `PUT`  | `/api/v1/modules/{id}/settings` | Replace full payload, returns merged. |
| `PUT`  | `/api/v1/modules/{id}/settings/{k}` | Upsert single key, returns merged. |

Settings endpoints are mounted **first** so a module that exposes
a bare `/{name}` path cannot shadow them — Starlette matches in
registration order (see each app's `main.py`).

## 5. ResponseTier + field masking

The base-thread snapshot serves three "tiers" of consumer from one
endpoint via `?mode=` query. The mapper layer implements the tier
selection through
[`backend/common/core/field_masking.py`](../../backend/common/core/field_masking.py):

```python
# backend/common/core/field_masking.py
class ResponseTier(str, Enum):
    STATIC = "static"
    BASE = "base"
    ALL = "all"


def include_base(value: Any, current_mode: Union[ResponseTier, str]) -> Optional[Any]:
    """Shorthand wrapper to include a field ONLY in the 1Hz Base thread."""
    return include_if(value, current_mode, {ResponseTier.BASE})


def include_static(value: Any, current_mode: Union[ResponseTier, str]) -> Optional[Any]:
    """Shorthand wrapper to include a field ONLY in the Static config."""
    return include_if(value, current_mode, {ResponseTier.STATIC})


def include_both(value: Any, current_mode: Union[ResponseTier, str]) -> Optional[Any]:
    """Shorthand wrapper to include a field in BOTH Base and Static payloads."""
    return include_if(value, current_mode, {ResponseTier.BASE, ResponseTier.STATIC})
```

A route that uses `response_model_exclude_none=True` drops the
masked-out field from the JSON payload
([`backend/machine/routers/BaseThreadRouter.py`](../../backend/machine/routers/BaseThreadRouter.py)).

**Rules of thumb:**

- Configuration fields (`min_rpm`, `max_rpm`, `min_temp`, `max_temp`,
  axis limits) → `include_static`.
- Live runtime fields (`actual_rpm`, `actual_temperature`,
  `current_line`, `motion_line`) → `include_base`.
- Identity / structural fields (`id`, `type`) → always populated;
  no helper needed.

## 6. Cross-cutting helpers

### 6.1 HTTP errors

[`backend/common/exceptions/http.py`](../../backend/common/exceptions/http.py)
exposes three subclasses of `HTTPException` that cover the
operator-facing error vocabulary:

```python
# backend/common/exceptions/http.py
class BaseAPIException(HTTPException): ...
class NotFoundError(BaseAPIException):
    def __init__(self, name: str) -> None:
        super().__init__(status_code=404, detail=name)
class BadRequestError(BaseAPIException):
    def __init__(self, msg: str) -> None:
        super().__init__(status_code=400, detail=msg)
class ConflictError(BaseAPIException):
    def __init__(self, msg: str) -> None:
        super().__init__(status_code=409, detail=msg)
```

Routers `raise` one of these — they never construct
`HTTPException` directly for the 400/404/409 triple. Outside
that triple, `HTTPException` is fine (e.g. `410 GONE` for the
deprecated temperature router, `503` for offline hardware,
`504` for the program-load timeout).

### 6.2 HAL pin handles

[`backend/common/dtos/pins/HalPin.py`](../../backend/common/dtos/pins/HalPin.py)
is the abstract base. The concrete subclasses live next to it:

| Subclass | Mutability | Used for |
|----------|------------|----------|
| [`StaticHalPin`](../../backend/common/dtos/pins/StaticHalPin.py) | read-only | Configuration pins (`min_rpm`, `min_temp`) |
| [`ReadOnlyDynamicHalPin`](../../backend/common/dtos/pins/ReadOnlyDynamicHalPin.py) | read-only | Telemetry pins (`actual_rpm`, `actual_temperature`) |
| [`ReadWriteDynamicHalPin`](../../backend/common/dtos/pins/ReadWriteDynamicHalPin.py) | read/write | Control pins (`override`, `absolute_master_override`) |
| [`UnconnectedHalPin`](../../backend/common/dtos/pins/UnconnectedHalPin.py) | n/a | Default value when a HAL pin is not declared |

Pins are bundled by `*Mapper.from_dict_to_*Pins(...)` at boot, then
read by `*Mapper.to_state_dto(...)` on every snapshot
([`backend/common/mappers/tools/HeaterMapper.py`](../../backend/common/mappers/tools/HeaterMapper.py)).

### 6.3 Persistent console log

[`backend/machine/services/ConsoleLogger.py`](../../backend/machine/services/ConsoleLogger.py)
mirrors every MDI dispatch and every machine error into an
on-disk log so the in-browser console clears don't lose history.
The state router calls `console_logger.log_command()` before the
dispatch and `console_logger.log_response()` after, with errors
logged at `LogLevel.ERROR` and successes at `LogLevel.INFO`
([`backend/machine/routers/state.py`](../../backend/machine/routers/state.py)).

## 7. Exceptions to the rule — flat and aggregator routers

A handful of routers pre-date the classical split, or don't fit it
by nature (a cross-domain aggregate, a WebSocket lifecycle). They
are flagged here as **won't fix** unless the shape of the feature
changes. New module authors should NOT copy their shape.

### 7.1 `BaseThreadRouter`

[`backend/machine/routers/BaseThreadRouter.py`](../../backend/machine/routers/BaseThreadRouter.py)
is a single-file aggregator. It pulls in several domain services
directly inside one handler (`get_base_thread_snapshot`) and
orchestrates their results into a `BaseThreadSnapshotResponse`:

```python
# backend/machine/routers/BaseThreadRouter.py (sketch)
def get_base_thread_snapshot(mode: str = Query("all", ...)) -> BaseThreadSnapshotResponse:
    requested_mode = ResponseTier(mode.strip().lower())
    service = get_base_thread_service()
    if requested_mode == ResponseTier.STATIC:
        return service.get_static_response()
    if requested_mode == ResponseTier.BASE:
        return service.get_base_response()
    if requested_mode == ResponseTier.ALL:
        return service.get_snapshot()
    raise HTTPException(status_code=400, detail=f"Mode '{requested_mode.value}' is not supported as a standalone response.")
```

The orchestration belongs in `BaseThreadService`
([`backend/machine/services/BaseThreadService.py`](../../backend/machine/services/BaseThreadService.py))
already, so the router is just a dispatch wrapper. Refactoring it
to use a dedicated DTO/Mapper split is **low value** because the
snapshot is by definition a cross-domain aggregate that no module
owns.

### 7.2 `ServoThreadRouter`

[`backend/machine/routers/ServoThreadRouter.py`](../../backend/machine/routers/ServoThreadRouter.py)
hosts a WebSocket loop plus the inbound-message dispatcher in the
same module as the route registration. The pattern fits because
FastAPI's WebSocket lifecycle is per-connection, not per-request,
so the typical "thin router / fat service" split adds a layer of
indirection without isolation.

The DTO and mapper for the servo thread state live in
[`backend/common/dtos/ServoThreadState.py`](../../backend/common/dtos/ServoThreadState.py)
and [`backend/common/mappers/ServoThreadStateMapper.py`](../../backend/common/mappers/ServoThreadStateMapper.py)
respectively — the service in
[`backend/machine/services/ServoThreadService.py`](../../backend/machine/services/ServoThreadService.py)
delegates to them. The router itself stays a dispatcher.

### 7.3 `FilesRouter` and `SystemRouter`

[`backend/system/routers/FilesRouter.py`](../../backend/system/routers/FilesRouter.py)
routes NGC program uploads/browsing through
[`domain_file_services.ProgramFileService`](../../backend/common/domain_file_services/ProgramFileService.py).
[`backend/system/routers/SystemRouter.py`](../../backend/system/routers/SystemRouter.py)
has no dedicated service at all — version-info and update-trigger
logic is inline in the router module. Both are cross-cutting
(filesystem browsing, system status) rather than owned by a single
domain module, which is why they don't carry the full DTO/Mapper
split.

### 7.4 `camera` router — resolved via a process-boundary split, not the classical one

[`backend/machine/routers/camera.py`](../../backend/machine/routers/camera.py)
has no domain data to map — it supervises a subprocess and proxies
bytes — so the classical Router → Service → DTO → Mapper → Storage
split would be ceremony, not clarity. It carried two real problems
instead, now fixed:

* `UstreamerSupervisor` (subprocess lifecycle) lived in the same file
  as the HTTP endpoints, doubling the file's job. Extracted to
  [`backend/machine/services/camera/ustreamer_supervisor.py`](../../backend/machine/services/camera/ustreamer_supervisor.py)
  — the router file dropped from ~960 to ~380 lines and now reads as
  one thing (endpoints + stream proxying), not two stapled together.
* Five placeholder classes (`USBDevicePayload`, `USBDevicesResponse`,
  `DevicePayload`, `DevicesResponse`, `StreamStatusResponse`) looked
  like response models but were never wired to any `response_model=`
  and were referenced nowhere — pure dead weight. Deleted; each
  endpoint's `description=` already documents its wire shape.

Still no DTO/Mapper layer here, deliberately — that's the right call
for a process supervisor, not a remaining gap.

### 7.5 `state` and `program` routers — resolved, inline Pydantic models moved

[`backend/machine/routers/state.py`](../../backend/machine/routers/state.py) and
[`backend/machine/routers/program.py`](../../backend/machine/routers/program.py)
used to define their Pydantic models inline at the top of the file
(`_StateCommand`, `_StateSnapshot`, `ParseResponse`,
`LoadProgramRequest`). Moved to
[`backend/common/models/state/state_models.py`](../../backend/common/models/state/state_models.py)
(`StateCommand`, `ModeCommand`, `MdiCommand`, `StateSnapshotResponse`,
`StatusResponse` — this file already existed, prepared but unused
until now) and
[`backend/common/models/program/program_models.py`](../../backend/common/models/program/program_models.py)
(`StatusResponse`, `ParseResponse`, `LoadProgramRequest`) respectively.

`state`'s operator-facing `MachineState` enum had the same problem —
defined inline in `StateService.py`, duplicating an already-existing,
unused `backend/common/dtos/state/MachineStateDto.py`. Consolidated
into that DTO module (the dead `MachineStateSnapshotDTO` dataclass
next to it was removed — `StateService.get_state_snapshot()` builds
`StateSnapshotResponse` directly, matching `ServoThreadService`'s
established pattern of returning the mapped response itself rather
than a separate DTO no consumer needed); `StateService` re-exports
`MachineState` since `SpindleDigitalService` and tests already import
it from there.

One deliberate non-change: `StateCommand.state` / `ModeCommand.mode`
stay plain `str`, not `Literal[...]` — the router's `400 Invalid
state` / `400 Invalid mode` (pinned by `test_machine_state_module.py`)
depends on the bad value reaching `StateService._resolve` rather than
being rejected by FastAPI's validation layer as a `422` first.

## 8. Module cheat-sheet

| Module id | App | Router | Service(s) | DTO | Mapper | Pydantic response | Storage | Classical? |
|-----------|-----|--------|-----------|-----|--------|-------------------|---------|------------|
| `axis` | machine | [`routers/axis.py`](../../backend/machine/routers/axis.py) | [`AxisService`](../../backend/machine/services/AxisService.py) | [`common/dtos/axis/AxisDto.py`](../../backend/common/dtos/axis/AxisDto.py) | [`common/mappers/axis/axis_mapper.py`](../../backend/common/mappers/axis/axis_mapper.py) | [`common/models/axis_model.py`](../../backend/common/models/axis_model.py) | n/a (HAL-driven) | Yes |
| `machine_state` | machine | [`routers/state.py`](../../backend/machine/routers/state.py) | [`StateService`](../../backend/machine/services/StateService.py) | [`common/dtos/state/MachineStateDto.py`](../../backend/common/dtos/state/MachineStateDto.py) (enum only) | n/a — service builds the response directly | [`common/models/state/state_models.py`](../../backend/common/models/state/state_models.py) | n/a | Yes — no mapper needed, see § 7.5 |
| `program` | machine | [`routers/program.py`](../../backend/machine/routers/program.py) | [`ProgramService`](../../backend/machine/services/ProgramService.py), [`domain_file_services`](../../backend/common/domain_file_services/) | n/a | n/a | [`common/models/program/program_models.py`](../../backend/common/models/program/program_models.py) for the router's own endpoints; `ProgramProgressResponse` is still inline in `ProgramService.py` (untouched — not named in § 7.5, tracked separately) | filesystem via `domain_file_services` | Yes — no DTO layer needed (text-in / status-out), see § 7.5 |
| `temperature` | machine | [`routers/temperature.py`](../../backend/machine/routers/temperature.py) | (deprecated) | (deprecated) | (deprecated) | (deprecated) | n/a | **Deprecated** — 410 redirect to `tools` |
| `tools` | machine | [`routers/tools.py`](../../backend/machine/routers/tools.py) | [`ToolsService`](../../backend/machine/services/ToolsService.py), [`SpindleDigitalService`](../../backend/machine/services/SpindleDigitalService.py), [`ExtruderService`](../../backend/machine/services/ExtruderService.py), [`HeaterService`](../../backend/machine/services/HeaterService.py) | [`common/dtos/tools/`](../../backend/common/dtos/tools/) | [`common/mappers/tools/`](../../backend/common/mappers/tools/) | [`common/models/tools/`](../../backend/common/models/tools/), [`common/models/tools_settings.py`](../../backend/common/models/tools_settings.py) | `SettingsStore` (settings) | **Yes — canonical** |
| `camera` | machine | [`routers/camera.py`](../../backend/machine/routers/camera.py) | [`UstreamerSupervisor`](../../backend/machine/services/camera/ustreamer_supervisor.py) | n/a | n/a | inline | `SettingsStore` | **Exception** — process-boundary split, not classical (§ 7.4) |
| (telemetry) | machine | [`routers/BaseThreadRouter.py`](../../backend/machine/routers/BaseThreadRouter.py) | [`BaseThreadService`](../../backend/machine/services/BaseThreadService.py) | n/a | [`common/mappers/BaseThreadSnapshotMapper.py`](../../backend/common/mappers/BaseThreadSnapshotMapper.py) | [`common/models/BaseThreadStateResponse.py`](../../backend/common/models/BaseThreadStateResponse.py) | n/a | **Exception** — cross-domain aggregator (§ 7.1) |
| (telemetry) | machine | [`routers/ServoThreadRouter.py`](../../backend/machine/routers/ServoThreadRouter.py) | [`ServoThreadService`](../../backend/machine/services/ServoThreadService.py) | [`common/dtos/ServoThreadState.py`](../../backend/common/dtos/ServoThreadState.py) | [`common/mappers/ServoThreadStateMapper.py`](../../backend/common/mappers/ServoThreadStateMapper.py) | [`common/models/ServoThreadStateResponse.py`](../../backend/common/models/ServoThreadStateResponse.py) | n/a | **Exception** — WebSocket lifecycle (§ 7.2) |
| `macros` (CRUD) | system | [`routers/macros.py`](../../backend/system/routers/macros.py) | [`MacroService`](../../backend/system/services/MacroService.py) | n/a | n/a | inline in `MacroService` | [`common/storage/MacroStorage.py`](../../backend/common/storage/MacroStorage.py), `MCodeFileService` | Yes — no DTO layer (text-in / text-out) |
| `macros` (start) | machine | [`routers/macro_start.py`](../../backend/machine/routers/macro_start.py) | [`MacroExecutionService`](../../backend/machine/services/MacroExecutionService.py) | n/a | n/a | inline | n/a | Yes — no DTO layer |
| `machineconfig` | system | [`routers/machineconfig.py`](../../backend/system/routers/machineconfig.py) | [`domain_file_services`](../../backend/common/domain_file_services/) (`ConfigFileService`, `MachineFileService`, `MCodeFileService`), `machinetemplates.generator` | n/a | n/a | inline | `domain_file_services` | Yes — no DTO layer (filesystem CRUD + template generation, see `ARCHITECTURE.md` § 7) |
| (programs) | system | [`routers/FilesRouter.py`](../../backend/system/routers/FilesRouter.py) | [`ProgramFileService`](../../backend/common/domain_file_services/ProgramFileService.py) | n/a | n/a | inline | `ProgramFileService` | **Exception** — cross-cutting filesystem browsing (§ 7.3) |
| (system) | system | [`routers/SystemRouter.py`](../../backend/system/routers/SystemRouter.py) | (inline in router) | n/a | n/a | inline | n/a | **Exception** — cross-cutting, no dedicated service (§ 7.3) |
| (machine lifecycle) | system | [`routers/machine_lifecycle.py`](../../backend/system/routers/machine_lifecycle.py) | [`MachineLifecycleService`](../../backend/system/services/MachineLifecycleService.py) | n/a | n/a | inline | n/a | Yes — process lifecycle, see `ARCHITECTURE.md` § 1.3 |

## 9. Anti-patterns

Things that should never land in a code review:

- **`import hardware.*` from a router.** Feature code goes
  through a service facade so the mock layer stays portable. The
  [`tools`](../../backend/machine/routers/tools.py) router is the canonical
  reference: it imports services, never `hardware.*`.
- **Mutable `@dataclass` for a snapshot DTO.** Use
  `@dataclass(frozen=True, slots=True)`. The `*SettingsDTO` flavour
  is mutable (`@dataclass(slots=True)`) but only because the
  service normalises it — never the snapshot DTO.
- **Pydantic models inside `backend/common/dtos/`.** The DTO layer
  is pure Python. Pydantic lives in `backend/common/models/`. A DTO
  that imports `pydantic.BaseModel` is a layering bug.
- **Inline `_StatusResponse` / `_Command` Pydantic classes at the
  top of a router.** Move them to `backend/common/models/<domain>/`.
  See the `state` and `program` router gaps in § 7.5.
- **A router in one app importing a service or DTO from the other
  app's `routers`/`services` tree.** Only `backend/common/` is
  shared — see `ARCHITECTURE.md` § 1.
- **A bare `dict` or `any`.** See the typing discipline in
  [`.agent/AGENT.md`](../AGENT.md) — DTOs, settings, and response
  models are exactly the places a bare `dict` likes to hide.
- **A service that builds its own HTTPException.** Raise the typed
  errors from `backend/common/exceptions/http.py`; the router layer
  is the only place that decides between `400` / `404` / `409` / `503`.
- **A storage class that imports FastAPI or Pydantic.** Storage is
  framework-agnostic and unit-testable with `tmp_path`. The
  `MacroStorage` and `SettingsStore` classes are the reference
  shape.

---

**See also:** [`.agent/contracts/backend-router.md`](../contracts/backend-router.md)
for the per-domain router contract, split into a machine-app table
and a system-app table; [`.agent/contracts/settings-module.md`](../contracts/settings-module.md)
for the four canonical settings endpoints; [`.agent/context/ARCHITECTURE.md`](ARCHITECTURE.md)
for the three-process split and the backend module mount table.
