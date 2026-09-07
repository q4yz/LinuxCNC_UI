"""LinuxCNC Web API — machine backend (FastAPI application).

Owns everything that needs a live LinuxCNC session: the 10 Hz
WebSocket telemetry, NML state/mode/MDI commands, jogging, homing,
program execution, tools/temperature HAL interactions, the HAL layout
editor feed and the USB cameras. The config-file domains
(machineconfig profiles/compile/deploy, program uploads, macro CRUD,
system version/update and the machine lifecycle) live in the system
service (``backend/system/main.py``), which stays reachable even when
this backend or the machine itself is down.

Boot order
----------

1. ``backend/common`` is pushed onto ``sys.path`` so the shared
   library (settings store, domain file services, exceptions, …)
   resolves no matter which working directory uvicorn was started
   from.
2. ``FastAPI(...)`` is constructed.
3. CORS middleware is added.
4. The legacy flat routers (``BaseThreadRouter`` /
   ``ServoThreadRouter``) and the HAL layout router are mounted.
5. The machine-owned per-domain routers are mounted under
   ``/api/v1/modules/<id>`` with their canonical settings router,
   plus the macros ``/start`` execution router.
6. The lifespan handler boots hardware preloads, starts the
   telemetry loop, and (when the ``jog_watchdog`` package was
   preserved) starts the watchdog.
"""
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Make the shared library (backend/common/) importable regardless of
# the working directory uvicorn was launched from.
_COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(_COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMON_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.settings_store import SettingsStore
import module_settings_router
from dtos.pins.HalPin import HalPin
from hardware import HAS_HAL
from hardware.mock.LinuxCNCMock import mock_system
from hardware.mock.test_helpers.mock_helpers import reseed_from_hardware_json
from routers import (
    BaseThreadRouter,
    ServoThreadRouter,
    axis as axis_router,
    camera as camera_router,
    hal as hal_router,
    macro_start as macro_start_router,
    program as program_router,
    state as state_router,
    temperature as temperature_router,
    tools as tools_router,
)
from services.ServoThreadService import (
    get_servo_thread_service,
)
from services.StateService import get_state_service
from services.TemperatureService import get_temperature_service
from services.ToolsService import get_tools_service
from services.ConsoleLogger import get_console_logger

# Machine-owned settings models (one file per domain).
from models.axis_settings import MachineSettings as AxisSettings
from models.camera_settings import CameraSettings
from models.program_settings import ProgramSettings
from models.state_settings import StateSettings
from models.temperature_settings import TemperatureSettings
from models.tools_settings import ToolsSettings


# Configure global logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.machine.main")


# Per-domain settings models — machine-owned module ids only. The
# ``machineconfig`` and ``macros`` settings stores live in the system
# service; each store is owned by exactly one process so the
# in-memory ``SettingsStore`` cache can never serve stale data across
# services. Each tuple is ``(module_id, settings_class, router)``.
_MODULE_DOMAINS = [
    ("axis", AxisSettings, axis_router.router),
    ("machine_state", StateSettings, state_router.router),
    ("program", ProgramSettings, program_router.router),
    ("temperature", TemperatureSettings, temperature_router.router),
    ("tools", ToolsSettings, tools_router.router),
    ("camera", CameraSettings, camera_router.router),
]


# Service singletons are pre-warmed by the legacy main; we keep
# the same import surface so the ``__main__`` block stays sane.
tool_service = get_tools_service()
sensor_service = get_temperature_service()
state_service = get_state_service()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan Context Manager.

    Handles startup and shutdown events cleanly: fires up the
    background telemetry task, the optional jog safety watchdog,
    and tears every domain down on shutdown.
    """
    # Seed the mock hardware layer's sensor + spindle dicts from the
    # active ``hardware.json`` so the base-thread snapshot's
    # ``sensors`` and ``tools`` blocks are populated on the very
    # first request. The seed used to run eagerly in
    # ``hardware.linuxcnc_mock`` at import time, but it was
    # deferred to :func:`reseed_from_hardware_json` to break the
    # hardware -> temperature -> hardware circular import.
    if not HAS_HAL:
        tool_service.preload_hal_pins()
        sensor_service.preload_hal_pins()
        state_service.preload_hal_pins()
        HalPin.initialize_component()

        reseed_from_hardware_json()
        mock_system.start_simulation()

    # Start the continuous WebSocket publisher.
    task_telemetry = asyncio.create_task(
        get_servo_thread_service().telemetry_loop()
    )

    # Per-domain lifecycle hooks.
    reseed_temperature_defaults()
    start_watchdog_if_configured()
    bind_camera_settings_store()

    # Probe OpenAPI schema generation now that every router is
    # mounted. A regression that triggers a silent partial
    # generation should surface a loud traceback here rather than
    # an empty /openapi.json at runtime.
    try:
        schema = app.openapi()
        logger.info(
            "OpenAPI schema ready: %d paths, %d components",
            len(schema.get("paths", {})),
            len(schema.get("components", {}).get("schemas", {})),
        )
    except Exception:  # noqa: BLE001 - we WANT every error here
        logger.exception("OpenAPI schema generation failed at startup")

    yield

    # Shutdown gracefully.
    logger.info("Shutting down LinuxCNC background tasks...")
    task_telemetry.cancel()
    # Flush the persistent console history so any in-flight rows
    # survive the uvicorn shutdown.
    try:
        get_console_logger().close()
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("ConsoleLogger close failed during shutdown: %s", exc)
    stop_watchdog_if_running()
    camera_router.stop_manager()


def start_watchdog_if_configured() -> None:
    """Start the jog safety watchdog if ``axis_settings`` has a store."""
    try:
        from services.jog_watchdog import start_watchdog
    except ImportError:  # pragma: no cover - watchdog is optional
        return

    store = _settings_stores.get("axis")
    if store is not None:
        start_watchdog(store)


def reseed_temperature_defaults() -> None:
    """Re-seed the temperature settings defaults with sensor colours."""
    from models.temperature_settings import seed_colors
    from services.temperature_config_mapper import get_temperature_sensors

    sensor_ids = [
        str(sensor["id"])
        for sensor in get_temperature_sensors()
        if sensor.get("id")
    ]
    store = _settings_stores.get("temperature")
    if store is None:
        return
    # Replace the seeded defaults with a freshly-built instance so
    # the next read returns the active sensor palette.
    store._defaults = TemperatureSettings(
        sensor_colors=seed_colors(sensor_ids),
    )


def stop_watchdog_if_running() -> None:
    """Tear the jog safety watchdog down if it is running."""
    try:
        from services.jog_watchdog import stop_watchdog
    except ImportError:  # pragma: no cover
        return
    try:
        stop_watchdog()
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("jog_watchdog.stop_watchdog raised %s", exc)


def bind_camera_settings_store() -> None:
    """Wire the camera supervisor's SettingsStore."""
    store = _settings_stores.get("camera")
    if store is None:
        return
    try:
        camera_router.bind_settings_store(store)
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("camera.bind_settings_store raised %s", exc)


# Initialise FastAPI app
app = FastAPI(
    title="LinuxCNC Machine Backend",
    description=(
        "Machine-coupled REST API and WebSocket interface for LinuxCNC: "
        "telemetry, state/MDI commands, jogging, program execution, "
        "tools, temperature and cameras."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow CORS for local frontend development (e.g., Vite dev server on
# port 5173).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Per-domain settings stores (one per id)                                     #
# --------------------------------------------------------------------------- #
#
# Built once at module import time so the lifespan manager can hand the
# same instance to the watchdog / camera supervisor. The same dict is
# re-used in the router-include loop below.

_settings_stores: dict[str, SettingsStore] = {}
_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"

for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    _settings_stores[_module_id] = SettingsStore(
        module_id=_module_id,
        data_root=_DATA_ROOT,
        defaults=_settings_cls(),
    )


# Mount the two legacy flat routers.
app.include_router(BaseThreadRouter.router)
app.include_router(ServoThreadRouter.router)

# Mount the Visual HAL editor's standalone layout router.
app.include_router(hal_router.router)


# Mount the machine-owned per-domain routers and their canonical
# settings surfaces. The settings router is mounted FIRST so a module
# that exposes a bare ``/{name}`` path cannot shadow
# ``/api/v1/modules/<id>/settings`` — Starlette matches routes in
# registration order.
for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    app.include_router(
        module_settings_router.build_module_settings_router(
            _settings_stores[_module_id],
        ),
        prefix=f"/api/v1/modules/{_module_id}/settings",
        tags=[f"modules:{_module_id}:settings"],
    )
    app.include_router(_router)

# Macros execution (the CRUD half lives in the system service).
app.include_router(macro_start_router.router)


@app.get("/")
def read_root():
    """Root health check endpoint."""
    return {"status": "ok", "service": "LinuxCNC UI Machine Backend"}


@app.get("/api/v1/health")
def machine_health():
    """Liveness probe for the frontend's machine-online heartbeat.

    The browser can only reach this service through the ``/api`` proxy
    (dev: vite, prod: nginx), so the root ``/`` endpoint above is not
    usable as a ping target from the SPA. ``composables/useMachineOnline.ts``
    polls this route every 3 s with a 2 s ``AbortSignal.timeout``; any
    non-200 or timeout counts as "machine offline" and the UI gates all
    machine-level traffic on that verdict.
    """
    return {"status": "ok", "service": "machine"}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting LinuxCNC background tasks...")

    tool_service.preload_hal_pins()
    sensor_service.preload_hal_pins()
    state_service.preload_hal_pins()
    HalPin.initialize_component()

    _reload = os.getenv("UVICORN_RELOAD", "").lower() in ("1", "true", "yes", "on")
    uvicorn.run(
        "main:app",  # import-string form is required when reload=True
        host="0.0.0.0",
        port=8000,
        reload=_reload,
    )
