"""LinuxCNC Web API — system service (FastAPI application).

The always-running half of the two-service backend split. It owns
every domain that must stay reachable while the machine (or the
machine backend) is down:

* machineconfig — profile CRUD, compile, deploy, machine templates
* programs — NGC file uploads for ``nc_files/``
* macros — macro/m-code file CRUD (the ``/start`` execution endpoint
  lives in the machine backend)
* system — version / update
* machine lifecycle — start/stop the ``linuxcnc`` process and switch
  the active machine (compile → deploy → restart)

The machine-coupled domains (telemetry WebSocket, NML state/MDI
commands, jogging, program execution, tools, temperature, cameras)
live in the machine backend (``backend/machine/main.py``) on port
8000; nginx routes this service's path prefixes to port 8001.
"""
import logging
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

from routers import (
    FilesRouter,
    SystemRouter,
    machine_lifecycle as machine_lifecycle_router,
    machineconfig as machineconfig_router,
    macros as macros_router,
    ui_settings as ui_settings_router,
)


# Configure global logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.system.main")


# System-owned per-domain routers (``/api/v1/modules/<id>``).
_MODULE_ROUTERS = [
    machineconfig_router.router,
    macros_router.router,
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Probe OpenAPI generation at startup.

    Note: exception handlers must NOT be registered here. The
    middleware stack is built from a snapshot of
    ``app.exception_handlers`` before the lifespan body runs
    (verified on FastAPI 0.136 / Starlette 1.0), so a handler added
    at this point never intercepts anything — every parser error
    then crashes the request as a raw 500. Registration happens at
    app construction below instead.
    """
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

    logger.info("Shutting down system service...")


def register_machineconfig_exception_handlers(app: FastAPI) -> None:
    """Attach the structured ``ConfigValidationError`` handler.

    Covers both the machineconfig router's generate endpoint and the
    lifecycle router's switch endpoint (which compiles too). Must be
    called BEFORE the first request — see the lifespan note above.
    """
    machineconfig_router.register_exception_handlers(app)


# Initialise FastAPI app
app = FastAPI(
    title="LinuxCNC System Service",
    description=(
        "Always-running system REST API: machine configuration "
        "(profiles, compile, deploy), program uploads, macro CRUD, "
        "version/update and the LinuxCNC machine lifecycle."
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

# Structured 400 envelope for every ConfigValidationError the parser
# raises (issue #99) — registered at construction so the middleware
# stack's snapshot of exception handlers includes it. Registering in
# lifespan is too late: the stack is built before the lifespan body
# runs, and a late registration silently degrades every parser error
# to a raw 500 crash (the exact bug seen on POST /machines/generate).
register_machineconfig_exception_handlers(app)


# System surface: version / update / machine lifecycle.
app.include_router(SystemRouter.router)

# Central UI settings (single settings.json) — lives here so it stays
# available while the machine backend is offline.
app.include_router(ui_settings_router.router)
app.include_router(machine_lifecycle_router.router)

# Program file uploads (nc_files/).
app.include_router(FilesRouter.router)

# Per-domain routers.
for _router in _MODULE_ROUTERS:
    app.include_router(_router)


@app.get("/")
def read_root():
    """Root health check endpoint."""
    return {"status": "ok", "service": "LinuxCNC UI System Service"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",  # import-string form is required when reload=True
        host="127.0.0.1",
        port=8001,
    )
