# Backend Layers — Canonical Pattern

Authoritative description of the layered split every backend module
follows: **Router → Service → DTO → Mapper → Storage**, with Pydantic
**Response** models sitting on top of the DTO layer as the wire
shape. Living document. The matching implementation lives under
[`backend/`](../..) — all file references below use `path:line`
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

File: [`backend/routers/<module>.py`](../../backend/routers/)

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
# backend/routers/tools.py:78-100
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

- Never `import backend.hardware.*` from a router. Feature code must
  call [`backend/hardware/connection.py`](../../backend/hardware/connection.py)
  through a service facade so the mock layer stays portable.
- Pydantic `*Command` / `*Response` models live under
  [`backend/models/`](../../backend/models/) (or, for legacy
  modules, inline at the top of the router file).
- Status codes use [`backend/exceptions/http.py`](../../backend/exceptions/http.py):
  `BadRequestError` → 400, `NotFoundError` → 404, `ConflictError` → 409.
  Anything outside that triple is a direct `raise HTTPException(...)`.

### 1.2 Service — business logic

File: [`backend/services/<Name>Service.py`](../../backend/services/)

A class with `__init__(self)` that takes no arguments, plus a
module-level `_<name>_service: Optional[<Name>Service] = None` and a
`get_<name>_service()` accessor that lazily builds the singleton.
The service owns:

- The translation between operator vocabulary (`"on"`, `"mdi"`,
  `"forward"`) and linuxcnc NML integer constants
  ([`backend/services/StateService.py:71-104`](../../backend/services/StateService.py)).
- The orchestration of DTOs and HAL pins.
- The dispatch to [`backend/hardware/`](../../backend/hardware/) —
  either `execute_sync_cmd(...)`, `execute_gcode(...)`, or
  `connection.get_machine_stat()`.

```python
# backend/services/AxisService.py:70-88
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
  singleton under `uvicorn --reload` without breaking imports
  ([`backend/services/AxisService.py:91-104`](../../backend/services/AxisService.py)).
- The service is **stateless across requests**; any per-process
  cache lives on `self` and is rebuilt by `preload_hal_pins()` at
  boot ([`backend/services/ToolsService.py:30-46`](../../backend/services/ToolsService.py)).

### 1.3 DTO / Entity — domain value objects

File: [`backend/dtos/<domain>/`](../../backend/dtos/)

Frozen, slotted dataclasses (`@dataclass(frozen=True, slots=True)`)
that hold the **runtime** shape of a domain object — values pulled
out of HAL pins, raw integers from linuxcnc NML, configuration
floats. Domain enums (`MachineState`, `DirectionStateType`) live
in the same folder.

```python
# backend/dtos/tools/HeaterDto.py:15-31
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
- DTOs must not import `backend.hardware.*`. The service translates
  HAL pins into DTOs via a mapper.
- HAL pin handles are themselves DTOs — see
  [`backend/dtos/HalPin.py`](../../backend/dtos/HalPin.py) and the
  concrete subclasses `StaticHalPin`, `ReadOnlyDynamicHalPin`,
  `ReadWriteDynamicHalPin`, `UnconnectedHalPin`.

### 1.4 Mapper — translation between layers

File: [`backend/mappers/<domain>/`](../../backend/mappers/)

A class with `fromclassmethod` methods that translate:

- `dict → *Pins` (boot path: `hardware.json` record → HAL pin bundle)
- `*Pins → *StateDTO` (snapshot path: HAL pin reads → DTO)
- `*Command → *SettingsDTO` (request path: HTTP body → internal command)
- `*StateDTO → *Response` (response path: DTO → wire shape)

The mapper is the **only** layer that owns `ResponseTier` field
masking via [`core/field_masking.py`](../../backend/core/field_masking.py).
A field that should only appear in the static config uses
`include_static(...)`; a field that belongs to the 1 Hz base thread
uses `include_base(...)`.

```python
# backend/mappers/tools/HeaterMapper.py:54-62
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

File: [`backend/storage/<Name>Storage.py`](../../backend/storage/),
[`backend/core/settings_store.py`](../../backend/core/settings_store.py),
[`backend/services/{FileService,domain_file_services}.py`](../../backend/services/)

Framework-agnostic CRUD over disk. Two flavours:

- **Per-module settings** —
  [`core/settings_store.py`](../../backend/core/settings_store.py).
  One file per module at
  `<data_root>/modules/<module_id>/settings.json`. Atomic write
  through `tempfile.mkstemp + os.replace`. Thread-safe via
  `threading.Lock`.
- **Filesystem payloads** —
  [`storage/MacroStorage.py`](../../backend/storage/MacroStorage.py)
  for `.macro` / `.ngc` files;
  [`services/domain_file_services.py`](../../backend/services/domain_file_services.py)
  for profiles / staged / active / m-codes / nc_files.

```python
# backend/storage/MacroStorage.py:309-361
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
`tools` module. Every reference uses `path:line` so a reader can
jump to the cited line.

### 2.1 Wire shape — inbound

The OpenAPI client posts a `SpindleDigitalCommand`:

```python
# backend/models/tools/SpindleDigitalModels.py (full file, 39 lines)
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
# backend/routers/tools.py:78-99
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
# backend/mappers/tools/SpindleDigitalMapper.py:57-76
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
# backend/services/SpindleDigitalService.py (sketch — see file for the canonical implementation)
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

The service uses [`execute_sync_cmd`](../../backend/hardware/Connection.py)
to drive the linuxcnc task through the NML channel. The M-code
constants come from [`backend/tools_constants.py`](../../backend/tools_constants.py).

### 2.5 Wire shape — outbound

The router wraps the M-code into the response envelope:

```python
# backend/models/tools/ToolModels.py
class ToolCommandResponse(BaseModel):
    status: str
    command: str
    tool_id: str
```

The OpenAPI schema sees `ToolCommandResponse`; the frontend codegen
emits a `controlSpindle()` call that returns exactly that shape.

### 2.6 Summary diagram

```
HTTP POST /api/v1/modules/tools/spindle
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ routers/tools.py::control_spindle                   │
│   - validates SpindleDigitalCommand (Pydantic)       │
│   - SpindleDigitalMapper.from_command_to_settings_dto│
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ mappers/tools/SpindleDigitalMapper.py               │
│   - action literal → DirectionStateType enum        │
│   - emits SpindleDigitalSettingsDTO                 │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ services/SpindleDigitalService.py::set_spindle      │
│   - MODE_MDI pre-switch                             │
│   - M3 / M4 / M5 dispatch via execute_sync_cmd      │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
            hardware.Connection
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

The **internal** payload between layers is the frozen dataclass
DTO, not a Pydantic model — see
[`backend/dtos/tools/HeaterDto.py`](../../backend/dtos/tools/HeaterDto.py).

The mapping back to the wire shape uses the mapper:

```python
# backend/mappers/tools/SpindleDigitalMapper.py:79-112
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
# backend/services/StateService.py:315-328
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
touching the router
([`backend/routers/state.py:35`](../../backend/routers/state.py)).

The lifespan manager pre-warms the singletons that need to seed
HAL pins before the WebSocket loop starts
([`backend/main.py:138`](../../backend/main.py)):

```python
# backend/main.py:102-103
tool_service = get_tools_service()
sensor_service = get_temperature_service()
```

### 4.2 Per-module settings stores

A `SettingsStore` is built once per module at import time so the
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

### 4.3 The four canonical settings endpoints

[`backend/routers/_module_settings_router.py`](../../backend/routers/_module_settings_router.py)
mounts the same four endpoints under
`/api/v1/modules/<id>/settings` for every module. Modules never
add their own `/settings` routes — see
[`.agent/contracts/settings-module.md`](../contracts/settings-module.md) § 2.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/v1/modules/{id}/settings` | Read full payload (defaults merged in). |
| `GET`  | `/api/v1/modules/{id}/settings/{k}` | Read single key (404 if missing). |
| `PUT`  | `/api/v1/modules/{id}/settings` | Replace full payload, returns merged. |
| `PUT`  | `/api/v1/modules/{id}/settings/{k}` | Upsert single key, returns merged. |

Settings endpoints are mounted **first** so a module that exposes
a bare `/{name}` path cannot shadow them — Starlette matches in
registration order
([`backend/main.py:308-321`](../../backend/main.py)).

## 5. ResponseTier + field masking

The base-thread snapshot serves three "tiers" of consumer from one
endpoint via `?mode=` query. The mapper layer implements the tier
selection through [`core/field_masking.py`](../../backend/core/field_masking.py):

```python
# backend/core/field_masking.py
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
([`backend/routers/BaseThreadRouter.py:24-44`](../../backend/routers/BaseThreadRouter.py)).

**Rules of thumb:**

- Configuration fields (`min_rpm`, `max_rpm`, `min_temp`, `max_temp`,
  axis limits) → `include_static`.
- Live runtime fields (`actual_rpm`, `actual_temperature`,
  `current_line`, `motion_line`) → `include_base`.
- Identity / structural fields (`id`, `type`) → always populated;
  no helper needed.

## 6. Cross-cutting helpers

### 6.1 HTTP errors

[`backend/exceptions/http.py`](../../backend/exceptions/http.py)
exposes three subclasses of `HTTPException` that cover the
operator-facing error vocabulary:

```python
# backend/exceptions/http.py:40-86
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

[`backend/dtos/HalPin.py`](../../backend/dtos/HalPin.py) is the
abstract base. The concrete subclasses live next to it:

| Subclass | Mutability | Used for |
|----------|------------|----------|
| [`StaticHalPin`](../../backend/dtos/StaticHalPin.py) | read-only | Configuration pins (`min_rpm`, `min_temp`) |
| [`ReadOnlyDynamicHalPin`](../../backend/dtos/ReadOnlyDynamicHalPin.py) | read-only | Telemetry pins (`actual_rpm`, `actual_temperature`) |
| [`ReadWriteDynamicHalPin`](../../backend/dtos/ReadWriteDynamicHalPin.py) | read/write | Control pins (`override`, `absolute_master_override`) |
| [`UnconnectedHalPin`](../../backend/dtos/UnconnectedHalPin.py) | n/a | Default value when a HAL pin is not declared |

Pins are bundled by `*Mapper.from_dict_to_*Pins(...)` at boot, then
read by `*Mapper.to_state_dto(...)` on every snapshot
([`backend/mappers/tools/HeaterMapper.py:18-43`](../../backend/mappers/tools/HeaterMapper.py)).

### 6.3 Persistent console log

[`backend/services/console_logger.py`](../../backend/services/console_logger.py)
mirrors every MDI dispatch and every machine error into an
on-disk log so the in-browser console clears don't lose history.
The router that dispatches MDI calls `console_logger.log_command()`
before the dispatch and `console_logger.log_response()` after, with
errors logged at `LogLevel.ERROR` and successes at `LogLevel.INFO`
([`backend/routers/state.py:195-209`](../../backend/routers/state.py)).

## 7. Exceptions to the rule (legacy flat routers)

Four routers in the tree pre-date the classical split. They are
flagged here as **won't fix** unless the roadmap changes. New
module authors should NOT copy their shape.

### 7.1 `BaseThreadRouter`

[`backend/routers/BaseThreadRouter.py`](../../backend/routers/BaseThreadRouter.py)
is a single-file aggregator. It pulls in seven domain services
directly inside one handler (`get_base_thread_snapshot`) and
orchestrates their results into a `BaseThreadSnapshotResponse`:

```python
# backend/routers/BaseThreadRouter.py:38-72
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
([`backend/services/BaseThreadService.py`](../../backend/services/BaseThreadService.py))
already, so the router is just a dispatch wrapper. Refactoring it
to use a dedicated DTO/Mapper split is **low value** because the
snapshot is by definition a cross-domain aggregate that no module
owns.

### 7.2 `ServoThreadRouter`

[`backend/routers/ServoThreadRouter.py`](../../backend/routers/ServoThreadRouter.py)
hosts a WebSocket loop plus the inbound-message dispatcher in the
same module as the route registration. The pattern fits because
FastAPI's WebSocket lifecycle is per-connection, not per-request,
so the typical "thin router / fat service" split adds a layer of
indirection without isolation.

The DTO and mapper for the servo thread state live in
[`backend/dtos/ServoThreadState.py`](../../backend/dtos/ServoThreadState.py)
and [`backend/mapper/ServoThreadStateMapper.py`](../../backend/mapper/ServoThreadStateMapper.py)
respectively — the service in
[`backend/services/ServoThreadService.py`](../../backend/services/ServoThreadService.py)
delegates to them. The router itself stays a dispatcher.

### 7.3 `FilesRouter` and `SystemRouter`

[`backend/routers/FilesRouter.py`](../../backend/routers/FilesRouter.py)
and [`backend/routers/SystemRouter.py`](../../backend/routers/SystemRouter.py)
are the legacy flat routers for filesystem browsing and system
status. Both pre-date the module split and both are routed through
[`backend/services/FileService.py`](../../backend/services/FileService.py).
They are exempt from the classical split because their endpoints
are cross-cutting and not owned by any single module.

### 7.4 `camera` router — supervisor co-located

[`backend/routers/camera.py`](../../backend/routers/camera.py) is
~900 lines because the `UstreamerSupervisor` class lives in the
same file as the endpoints. The classical split would extract the
supervisor into `backend/services/camera_supervisor.py` and the
DTOs/responses into a dedicated `models/camera_models.py`. This
is a **known gap**; the camera module's contract is small enough
that the co-location has not blocked any feature. Future
refactoring should split the supervisor out without changing the
OpenAPI surface.

### 7.5 `state` and `program` routers — inline Pydantic models

[`backend/routers/state.py`](../../backend/routers/state.py) and
[`backend/routers/program.py`](../../backend/routers/program.py)
define their Pydantic models inline at the top of the file
(`_StateCommand`, `_StateSnapshot`, `StatusResponse`,
`ParseResponse`, `LoadProgramRequest`). The classical pattern
lifts these into `backend/models/state/` and
`backend/models/program_models.py`. Both routers were written
during the original module-system retirement before the model
folder layout stabilised, and they are still inside the gap.
Touching them is a low-risk, low-reward cleanup.

## 8. Module cheat-sheet

| Module id | Router | Service(s) | DTO | Mapper | Pydantic response | Storage | Classical? |
|-----------|--------|-----------|-----|--------|-------------------|---------|------------|
| `axis` | [`routers/axis.py`](../../backend/routers/axis.py) | [`AxisService`](../../backend/services/AxisService.py) | [`dtos/axis/axis_dtos.py`](../../backend/dtos/axis/axis_dtos.py) | [`mappers/axis/axis_mapper.py`](../../backend/mappers/axis/axis_mapper.py) | [`models/axis_model.py`](../../backend/models/axis_model.py) | n/a (HAL-driven) | Yes |
| `machine_state` | [`routers/state.py`](../../backend/routers/state.py) | [`StateService`](../../backend/services/StateService.py) | [`dtos/state/machine_state_dto.py`](../../backend/dtos/state/machine_state_dto.py) | (inline in router) | inline `_StateSnapshot` | n/a | **Gap** — inline Pydantic, no mapper |
| `program` | [`routers/program.py`](../../backend/routers/program.py) | [`ProgramService`](../../backend/services/ProgramService.py), [`domain_file_services`](../../backend/services/domain_file_services.py) | n/a | n/a | inline, [`ProgramProgressResponse`](../../backend/services/ProgramService.py) | filesystem via `domain_file_services` | **Gap** — lifecycle ok, no DTO/Mapper |
| `temperature` | [`routers/temperature.py`](../../backend/routers/temperature.py) | (deprecated) | (deprecated) | (deprecated) | (deprecated) | n/a | **Deprecated** — 410 redirect to `tools` |
| `tools` | [`routers/tools.py`](../../backend/routers/tools.py) | [`ToolsService`](../../backend/services/ToolsService.py), [`SpindleDigitalService`](../../backend/services/SpindleDigitalService.py), [`ExtruderService`](../../backend/services/ExtruderService.py), [`HeaterService`](../../backend/services/HeaterService.py) | [`dtos/tools/`](../../backend/dtos/tools/) | [`mappers/tools/`](../../backend/mappers/tools/) | [`models/tools/`](../../backend/models/tools/), [`models/tools_settings.py`](../../backend/models/tools_settings.py) | `SettingsStore` (settings) | **Yes — canonical** |
| `macros` | [`routers/macros.py`](../../backend/routers/macros.py) | [`MacroService`](../../backend/services/MacroService.py) | n/a | n/a | inline in `MacroService` | [`storage/MacroStorage.py`](../../backend/storage/MacroStorage.py), `MCodeFileService` | Yes — no DTO layer (text-in / text-out) |
| `camera` | [`routers/camera.py`](../../backend/routers/camera.py) | `UstreamerSupervisor` (co-located) | n/a | n/a | inline | `SettingsStore` | **Gap** — supervisor co-located with router |
| `machineconfig` | [`routers/machineconfig.py`](../../backend/routers/machineconfig.py) | [`domain_file_services`](../../backend/services/domain_file_services.py) (`ConfigFileService`, `StagedFileService`, `ActiveFileService`, `MCodeFileService`) | n/a | n/a | inline | `domain_file_services` | Yes — no DTO layer (filesystem CRUD) |
| (telemetry) | [`routers/BaseThreadRouter.py`](../../backend/routers/BaseThreadRouter.py) | [`BaseThreadService`](../../backend/services/BaseThreadService.py) | n/a | [`mapper/BaseThreadSnapshotMapper.py`](../../backend/mapper/BaseThreadSnapshotMapper.py) | [`models/BaseThreadStateResponse.py`](../../backend/models/BaseThreadStateResponse.py) | n/a | **Exception** — legacy aggregator |
| (telemetry) | [`routers/ServoThreadRouter.py`](../../backend/routers/ServoThreadRouter.py) | [`ServoThreadService`](../../backend/services/ServoThreadService.py) | [`dtos/ServoThreadState.py`](../../backend/dtos/ServoThreadState.py) | [`mapper/ServoThreadStateMapper.py`](../../backend/mapper/ServoThreadStateMapper.py) | [`models/ServoThreadStateResponse.py`](../../backend/models/ServoThreadStateResponse.py) | n/a | **Exception** — WebSocket lifecycle |
| (legacy) | [`routers/FilesRouter.py`](../../backend/routers/FilesRouter.py) | [`FileService`](../../backend/services/FileService.py) | n/a | n/a | inline | `FileService` | **Exception** — legacy flat |
| (legacy) | [`routers/SystemRouter.py`](../../backend/routers/SystemRouter.py) | [`SystemService`](../../backend/services/SystemService.py) (or inline) | n/a | n/a | inline | n/a | **Exception** — legacy flat |

## 9. Anti-patterns

Things that should never land in a code review:

- **`import backend.hardware.*` from a router.** Feature code goes
  through a service facade so the mock layer stays portable. The
  [`tools`](../../backend/routers/tools.py) router is the canonical
  reference: it imports services, never `hardware.*`.
- **Mutable `@dataclass` for a snapshot DTO.** Use
  `@dataclass(frozen=True, slots=True)`. The `*SettingsDTO` flavour
  is mutable (`@dataclass(slots=True)`) but only because the
  service normalises it — never the snapshot DTO.
- **Pydantic models inside `backend/dtos/`.** The DTO layer is
  pure Python. Pydantic lives in `backend/models/`. A DTO that
  imports `pydantic.BaseModel` is a layering bug.
- **Inline `_StatusResponse` / `_Command` Pydantic classes at the
  top of a router.** Move them to `backend/models/<domain>/`. See
  the `state` and `program` router gaps in § 7.
- **Two mapper folders.** Today `backend/mapper/` (singular,
  `BaseThreadSnapshotMapper.py`, `ServoThreadStateMapper.py`) and
  `backend/mappers/` (plural, per-domain) both exist. New mappers
  go under `backend/mappers/<domain>/`; the singular folder is a
  migration leftover. Touching it is a separate cleanup ticket.
- **A service that builds its own HTTPException.** Raise the typed
  errors from `backend/exceptions/http.py`; the router layer is the
  only place that decides between `400` / `404` / `409` / `503`.
- **A storage class that imports FastAPI or Pydantic.** Storage is
  framework-agnostic and unit-testable with `tmp_path`. The
  `MacroStorage` and `SettingsStore` classes are the reference
  shape.

---

**See also:** [`.agent/contracts/backend-module.md`](../contracts/backend-module.md)
for the `PluggableModule` protocol; [`.agent/contracts/settings-module.md`](../contracts/settings-module.md)
for the four canonical settings endpoints; [`.agent/context/ARCHITECTURE.md`](ARCHITECTURE.md)
for the high-level backend layout and the module registry graph.
