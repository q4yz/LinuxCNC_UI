import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.module_registry import registry
from hardware.mock.linuxcnc_mock import mock_system
from hardware.mock.test_helpers.mock_helpers import reseed_from_hardware_json
from services.console_logger import get_console_logger


# Import our remaining flat-file routers. The ``machine`` /
# ``jog`` / ``program`` routers were migrated to the
# ``modules/machine`` + ``modules/program`` sub-packages; the registry
# picks them up automatically via ``registry.boot(app)`` further down.
#
# Issue #49 retired the legacy ``compiler`` router: the
# machineconfig module's ``/compile`` and ``/deploy`` endpoints
# supersede it and the frontend no longer references it.
from routers import base_thread, servo_thread, files, system

# Configure global logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Lifespan Context Manager.
    Handles startup and shutdown events cleanly, such as firing up
    background threads for the WebSocket telemetry and safety watchdogs.

    The historical boot-time load of ``core.config_manager.MachineConfig``
    was retired: that module relied on a hard-coded
    ``machine_config/machine.cfg`` file that lives only on Windows
    dev boxes and breaks the Linux boot path. Profile parsing is now
    per-request inside the ``machineconfig`` module router.
    """
    logger.info("Starting LinuxCNC background tasks...")

    # Seed the mock hardware layer's sensor + spindle dicts from the
    # active ``hardware.json`` so the base-thread snapshot's
    # ``sensors`` and ``tools`` blocks are populated on the very
    # first request. The seed used to run eagerly in
    # ``hardware.linuxcnc_mock`` at import time, but it was
    # deferred to ``reseed_from_hardware_json()`` to break the
    # hardware -> temperature -> hardware circular import. This
    # lifespan is the single canonical production caller — see
    # the matching note in ``hardware/linuxcnc_mock.py``.

    reseed_from_hardware_json()

    # Start the continuous WebSocket publisher
    task_telemetry = asyncio.create_task(servo_thread.telemetry_loop())

    # Discover / load pluggable hardware modules. ``registry`` injects
    # the EventBus into each module and mounts any routers they expose
    # under ``/api/v1/modules/{id}``. Missing or empty ``modules/``
    # package is logged but never fatal; the ``MODULES_ENABLED`` env
    # var (comma-separated) restricts which discovered modules boot.
    #
    # The jog safety watchdog ships inside
    # ``modules/axis/jog_watchdog.py`` and is started/stopped by
    # ``AxisModule.on_load`` / ``AxisModule.on_unload`` — the
    # registry ``boot`` / ``shutdown`` pair below manages it for us.
    registry.boot(app)
    app.state.module_registry = registry

    # Probe OpenAPI schema generation now that every router is mounted.
    # Previously this died silently on some platforms (the symptom being
    # an empty /openapi.json with no error log); the probe turns a
    # silent failure into a loud traceback so the next regression
    # leaves a breadcrumb.
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

    # Shutdown gracefully
    logger.info("Shutting down LinuxCNC background tasks...")
    task_telemetry.cancel()
    # Flush the persistent console history so any in-flight rows
    # survive the uvicorn shutdown. The logger is a process-wide
    # singleton so it is safe to close even when no module has
    # emitted anything.
    try:
        get_console_logger().close()
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("ConsoleLogger close failed during shutdown: %s", exc)
    # The registry's shutdown hook unloads modules in reverse order and
    # cancels the machine-module watchdog. It is idempotent under reload.
    registry.shutdown()

# Initialize FastAPI app
app = FastAPI(
    title="LinuxCNC Web API", 
    description="Modern, modular REST API and WebSocket interface for LinuxCNC", 
    version="1.0.0",
    lifespan=lifespan
)

# Allow CORS for local frontend development (e.g., Vite dev server on port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include modular routers. The ``axis`` / ``machine_state`` /
# ``program`` modules are mounted by the ``registry.boot(app)`` call
# inside ``lifespan`` (see above), which routes them under
# ``/api/v1/modules/{id}``. ``axis`` exposes ``/home``;
# ``machine_state`` exposes ``/state``, ``/mode``, ``/mdi``. Each
# router calls into its own dedicated service singleton from the
# matching ``modules/<name>/tool_service.py`` module.
app.include_router(files.router)
app.include_router(system.router)
app.include_router(base_thread.router)
app.include_router(servo_thread.router)

@app.get("/")
def read_root():
    """Root health check endpoint."""
    return {"status": "ok", "service": "LinuxCNC UI Backend"}

if __name__ == "__main__":
    import uvicorn
    # Run the server on all interfaces, port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
