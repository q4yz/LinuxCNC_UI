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

from core.settings_store import SettingsStore
import module_settings_router
from routers import (
    FilesRouter,
    SystemRouter,
    machine_lifecycle as machine_lifecycle_router,
    machineconfig as machineconfig_router,
    macros as macros_router,
)
from models.machineconfig_settings import MachineConfigSettings
from models.macros_settings import MacrosSettings


# Configure global logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.system.main")


# System-owned settings domains — each settings store is owned by
# exactly one process (the machine-owned stores live in the machine
# backend) so the in-memory ``SettingsStore`` cache can never serve
# stale data across services. Each tuple is
# ``(module_id, settings_class, router)``.
_MODULE_DOMAINS = [
    ("machineconfig", MachineConfigSettings, machineconfig_router.router),
    ("macros", MacrosSettings, macros_router.router),
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


# --------------------------------------------------------------------------- #
# Per-domain settings stores (one per id)                                     #
# --------------------------------------------------------------------------- #

_settings_stores: dict[str, SettingsStore] = {}
_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"

for _module_id, _settings_cls, _router in _MODULE_DOMAINS:
    _settings_stores[_module_id] = SettingsStore(
        module_id=_module_id,
        data_root=_DATA_ROOT,
        defaults=_settings_cls(),
    )


# System surface: version / update / machine lifecycle.
app.include_router(SystemRouter.router)
app.include_router(machine_lifecycle_router.router)

# Program file uploads (nc_files/).
app.include_router(FilesRouter.router)

# Per-domain routers with their canonical settings surfaces. The
# settings router is mounted FIRST so a module that exposes a bare
# ``/{name}`` path (the macros module) cannot shadow
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
