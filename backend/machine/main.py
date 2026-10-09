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
   library (domain file services, exceptions, …)
   resolves no matter which working directory uvicorn was started
   from.
2. ``FastAPI(...)`` is constructed.
3. CORS middleware is added.
4. The legacy flat routers (``BaseThreadRouter`` /
   ``ServoThreadRouter``) and the HAL layout router are mounted.
5. The machine-owned per-domain routers are mounted under
   ``/api/v1/modules/<id>``, plus the macros ``/start`` execution
   router. (UI settings live in the system service.)
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

from dtos.pins.HalPin import HalPin
from exceptions import register_command_error_handler
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
    mcu as mcu_router,
    program as program_router,
    state as state_router,
    temperature as temperature_router,
    tools as tools_router,
)
from services.ServoThreadService import (
    get_servo_thread_service,
)
from services.FansService import get_fans_service
from services.McuService import get_mcu_service
from services.ProgramService import get_program_lifecycle_service
from services.StateService import get_state_service
from services.TemperatureService import get_temperature_service
from services.ToolsService import get_tools_service
from services.ConsoleLogger import get_console_logger



# Configure global logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.machine.main")


# Machine-owned per-domain routers (``/api/v1/modules/<id>``).
_MODULE_ROUTERS = [
    axis_router.router,
    state_router.router,
    program_router.router,
    temperature_router.router,
    tools_router.router,
    camera_router.router,
]


# Service singletons are pre-warmed by the legacy main; we keep
# the same import surface so the ``__main__`` block stays sane.
tool_service = get_tools_service()
sensor_service = get_temperature_service()
state_service = get_state_service()
fans_service = get_fans_service()
mcu_service = get_mcu_service()
program_service = get_program_lifecycle_service()


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
        fans_service.preload_hal_pins()
        mcu_service.preload_hal_pins()
        program_service.preload_hal_pins()
        HalPin.initialize_component()

        reseed_from_hardware_json()
        mock_system.start_simulation()

    # Start the continuous WebSocket publisher.
    task_telemetry = asyncio.create_task(
        get_servo_thread_service().telemetry_loop()
    )

    # Per-domain lifecycle hooks.
    start_watchdog_if_available()

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


def start_watchdog_if_available() -> None:
    """Start the jog safety watchdog (fixed timeout, not a setting)."""
    try:
        from services.jog_watchdog import start_watchdog
    except ImportError:  # pragma: no cover - watchdog is optional
        return
    start_watchdog()


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

# Hardware command failures (``hardware.Connection.errors``) carry
# their own HTTP status; answer them like an ``HTTPException``.
register_command_error_handler(app)


# Mount the two legacy flat routers.
app.include_router(BaseThreadRouter.router)
app.include_router(ServoThreadRouter.router)

# Mount the Visual HAL editor's standalone layout router.
app.include_router(hal_router.router)


# Mount the machine-owned per-domain routers. UI settings are not
# served here: they live in the system service (``/api/v1/settings``)
# so they stay available while this backend is offline.
for _router in _MODULE_ROUTERS:
    app.include_router(_router)

# Macros execution (the CRUD half lives in the system service).
app.include_router(macro_start_router.router)

# MCU actions (reset). The MCU list rides on the base-thread snapshot.
app.include_router(mcu_router.router)


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
    fans_service.preload_hal_pins()
    mcu_service.preload_hal_pins()
    program_service.preload_hal_pins()
    HalPin.initialize_component()

    _reload = os.getenv("UVICORN_RELOAD", "").lower() in ("1", "true", "yes", "on")
    uvicorn.run(
        "main:app",  # import-string form is required when reload=True
        host="0.0.0.0",
        port=8000,
        reload=_reload,
    )
