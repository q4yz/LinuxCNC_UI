"""LinuxCNC Web API — single FastAPI application.

The previous backend shipped a pluggable module system: every
feature lived under ``backend/modules/<id>/`` and was mounted by
:class:`core.module_registry.ModuleRegistry`. The module layer was
retired — every per-domain router now lives directly under
``backend/routers/<id>.py`` and is ``include_router``'d here.
The per-module settings surface (``/api/v1/modules/<id>/settings``)
is still mounted explicitly so the four canonical settings
endpoints stay reachable for every id.

Boot order
----------

1. ``FastAPI(...)`` is constructed.
2. CORS middleware is added.
3. The four legacy flat routers (``FilesRouter`` / ``SystemRouter``
   / ``BaseThreadRouter`` / ``ServoThreadRouter``) are mounted.
4. The eight per-domain routers are mounted under
   ``/api/v1/modules/<id>`` and the canonical settings router is
   mounted under ``/api/v1/modules/<id>/settings`` for each id.
5. The lifespan handler boots hardware preloads, starts the
   telemetry loop, and (when the ``jog_watchdog`` package was
   preserved) starts the watchdog.

Mount order is preserved from the legacy registry implementation
so the boot summary log line stays stable.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.settings_store import SettingsStore
from dtos.HalPin import HalPin
from hardware import HAS_HAL
from hardware.mock.LinuxCNCMock import mock_system
from hardware.mock.test_helpers.mock_helpers import reseed_from_hardware_json
from routers import (
    BaseThreadRouter,
    FilesRouter,
    ServoThreadRouter,
    SystemRouter,
    _module_settings_router,
    axis as axis_router,
    camera as camera_router,
    machineconfig as machineconfig_router,
    macros as macros_router,
    program as program_router,
    state as state_router,
    temperature as temperature_router,
    tools as tools_router,
)
from services.ServoThreadService import (
    ServoThreadService,
    get_servo_thread_service,
)
from services.TemperatureService import get_temperature_service
from services.ToolsService import get_tools_service
from services.console_logger import get_console_logger

# Models live at the backend root (one file per domain).
from models.axis_settings import MachineSettings as AxisSettings
from models.camera_settings import CameraSettings
from models.machineconfig_settings import (
    MachineConfigSettings,
)
from models.macros_settings import MacrosSettings
from models.program_settings import ProgramSettings
from models.state_settings import StateSettings
from models.temperature_settings import TemperatureSettings
from models.tools_settings import ToolsSettings


# Configure global logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.main")


# Per-domain settings models — keep order matching the legacy
# module-discovery summary so the boot log diff is small. Each
# tuple is ``(module_id, settings_class, router)``. The router
# already carries its own ``prefix`` so we don't add another
# here; we just stamp the OpenAPI tag.
_MODULE_DOMAINS = [
    ("axis", AxisSettings, axis_router.router),
    ("machine_state", StateSettings, state_router.router),
    ("program", ProgramSettings, program_router.router),
    ("temperature", TemperatureSettings, temperature_router.router),
    ("tools", ToolsSettings, tools_router.router),
    ("macros", MacrosSettings, macros_router.router),
    ("camera", CameraSettings, camera_router.router),
    ("machineconfig", MachineConfigSettings, machineconfig_router.router),
]


# Service singletons are pre-warmed by the legacy main; we keep
# the same import surface so the ``__main__`` block stays sane.
tool_service = get_tools_service()
sensor_service = get_temperature_service()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan Context Manager.

    Handles startup and shutdown events cleanly: fires up the
    background telemetry task, the optional jog safety watchdog,
    and tears every domain down on shutdown. Replaces the legacy
    :class:`ModuleRegistry.boot` / :func:`shutdown` pair.
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
        HalPin.initialize_component()

        reseed_from_hardware_json()
        mock_system.start_simulation()

    # Start the continuous WebSocket publisher.
    task_telemetry = asyncio.create_task(
        get_servo_thread_service().telemetry_loop()
    )

    # Per-domain lifecycle hooks. The legacy
    # :meth:`PluggableModule.on_load` hooks are now plain
    # ``lifespan`` calls.
    reseed_temperature_defaults()
    start_watchdog_if_configured()
    bind_camera_settings_store()
    register_machineconfig_exception_handlers(app)

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
    """Start the jog safety watchdog if ``axis_settings`` has a store.

    The legacy :meth:`AxisModule.on_load` started the watchdog via
    ``jog_watchdog.start_watchdog(ctx.settings)``. The settings
    store is the one we just constructed for the axis domain.
    """
    try:
        from services.jog_watchdog import start_watchdog
    except ImportError:  # pragma: no cover - watchdog is optional
        return

    store = _settings_stores.get("axis")
    if store is not None:
        start_watchdog(store)


def reseed_temperature_defaults() -> None:
    """Re-seed the temperature settings defaults with sensor colours.

    The legacy :meth:`TemperatureModule.on_load` re-read the
    active heater list and rebuilt the typed defaults so the
    ``sensor_colors`` map surfaced the current palette. After the
    module-system retirement, the equivalent work runs here so a
    fresh checkout still gets seeded colours out of the active
    ``hardware.json``.
    """
    from models.temperature_settings import seed_colors
    from temperature_config_mapper import get_temperature_sensors

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
    """Wire the camera supervisor's SettingsStore.

    The legacy :meth:`CameraModule.on_load` called
    :func:`bind_settings_store` so the supervisor could read
    ``default_device_id`` from the per-module :class:`SettingsStore`.
    After consolidation this runs once at lifespan startup.
    """
    store = _settings_stores.get("camera")
    if store is None:
        return
    try:
        camera_router.bind_settings_store(store)
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("camera.bind_settings_store raised %s", exc)


def register_machineconfig_exception_handlers(app) -> None:
    """Register the structured ``ConfigValidationError`` handler.

    The legacy ``MachineConfigModule.on_load`` attached a
    FastAPI exception handler that translates
    :class:`ConfigValidationError` into a 400 with the
    operator-facing envelope shape. Re-install it during lifespan
    boot so the compile endpoint surfaces structured errors.
    """
    try:
        machineconfig_router.register_exception_handlers(app)
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("machineconfig.register_exception_handlers raised %s", exc)


# Initialise FastAPI app
app = FastAPI(
    title="LinuxCNC Web API",
    description=(
        "Modern, modular REST API and WebSocket interface for LinuxCNC"
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
_DATA_ROOT = Path("data")

for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    _settings_stores[_module_id] = SettingsStore(
        module_id=_module_id,
        data_root=_DATA_ROOT,
        defaults=_settings_cls(),
    )


# Mount the four legacy flat routers.
app.include_router(FilesRouter.router)
app.include_router(SystemRouter.router)
app.include_router(BaseThreadRouter.router)
app.include_router(ServoThreadRouter.router)


# Mount the eight per-domain routers and their canonical settings
# surfaces. The settings router is mounted FIRST so a module that
# exposes a bare ``/{name}`` path (the macros module) cannot shadow
# ``/api/v1/modules/<id>/settings`` — Starlette matches routes in
# registration order.
for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    app.include_router(
        _module_settings_router.build_module_settings_router(
            _settings_stores[_module_id],
        ),
        prefix=f"/api/v1/modules/{_module_id}/settings",
        tags=[f"modules:{_module_id}:settings"],
    )
    app.include_router(_router)


@app.get("/")
def read_root():
    """Root health check endpoint."""
    return {"status": "ok", "service": "LinuxCNC UI Backend"}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting LinuxCNC background tasks...")

    tool_service.preload_hal_pins()
    sensor_service.preload_hal_pins()
    HalPin.initialize_component()

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    # uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
