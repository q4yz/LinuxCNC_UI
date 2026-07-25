import asyncio
import logging
from contextlib import asynccontextmanager
#Test
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config_manager import MachineConfig
from core.module_registry import registry
from hardware.connection import connection
from services.console_logger import get_console_logger


# Import our remaining flat-file routers. The ``machine`` /
# ``jog`` / ``program`` routers were migrated to the
# ``modules/machine`` + ``modules/program`` sub-packages in
# issue #38; the registry picks them up automatically via
# ``registry.boot(app)`` further down.
from routers import websocket, files, system, config, compiler

# Configure global logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Lifespan Context Manager.
    Handles startup and shutdown events cleanly, such as firing up
    background threads for the WebSocket telemetry and safety watchdogs.
    """
    logger.info("Starting LinuxCNC background tasks...")

    # Load machine configuration and inject into hardware layer
    try:
        cfg = MachineConfig()  # uses machine_config/machine.cfg by default
        app.state.config = cfg
        try:
            connection.set_machine_config(cfg)
        except Exception as e:
            logger.warning("Failed to inject machine config into hardware connection: %s", e)
        logger.info("Loaded machine.cfg from machine_config/")
    except FileNotFoundError as e:
        logger.warning("Machine config not found at startup: %s", e)
        app.state.config = None
    except Exception as e:
        logger.error("Failed to load machine config: %s", e)
        raise

    # Start the continuous WebSocket publisher
    task_telemetry = asyncio.create_task(websocket.telemetry_loop())

    # Discover / load pluggable hardware modules. ``registry`` injects
    # the EventBus into each module and mounts any routers they expose
    # under ``/api/v1/modules/{id}``. Missing or empty ``modules/``
    # package is logged but never fatal; the ``MODULES_ENABLED`` env
    # var (comma-separated) restricts which discovered modules boot.
    #
    # The jog safety watchdog (formerly in ``routers/jog.py``) now
    # ships inside ``modules/machine/jog_watchdog.py`` and is
    # started/stopped by ``MachineModule.on_load`` /
    # ``MachineModule.on_unload`` — the registry ``boot`` /
    # ``unload`` pair below manages it for us.
    registry.boot(app)
    app.state.module_registry = registry

    yield

    # Shutdown gracefully
    logger.info("Shutting down LinuxCNC background tasks...")
    task_telemetry.cancel()
    registry.unload()
    # Flush the persistent console history so any in-flight rows
    # survive the uvicorn shutdown. The logger is a process-wide
    # singleton so it is safe to close even when no module has
    # emitted anything.
    try:
        get_console_logger().close()
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("ConsoleLogger close failed during shutdown: %s", exc)

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

# Include modular routers. The ``machine`` / ``program`` routers are
# mounted by the ``registry.boot(app)`` call inside ``lifespan`` (see
# above), which routes them under ``/api/v1/modules/{id}``. Keeping
# the include order flat means the legacy flat-file routers mount
# first and the module-mounted routers layer on top with no conflict.
app.include_router(files.router)
app.include_router(system.router)
app.include_router(config.router)
app.include_router(websocket.router)
app.include_router(compiler.router)

@app.get("/")
def read_root():
    """Root health check endpoint."""
    return {"status": "ok", "service": "LinuxCNC UI Backend"}

if __name__ == "__main__":
    import uvicorn
    # Run the server on all interfaces, port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
