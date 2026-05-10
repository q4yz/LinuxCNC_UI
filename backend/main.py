import asyncio
import logging
from contextlib import asynccontextmanager
#Test
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import our new modular routers
from routers import machine, jog, websocket, files, system, config, camera

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

    # Start the jog safety watchdog
    task_watchdog = asyncio.create_task(jog.jog_watchdog())

    yield
    
    # Shutdown gracefully
    logger.info("Shutting down LinuxCNC background tasks...")
    task_telemetry.cancel()
    task_watchdog.cancel()

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

# Include modular routers
app.include_router(machine.router)
app.include_router(machine.program_router)
app.include_router(files.router)
app.include_router(system.router)
app.include_router(config.router)
app.include_router(jog.router)
app.include_router(websocket.router)
app.include_router(camera.router)

@app.get("/")
def read_root():
    """Root health check endpoint."""
    return {"status": "ok", "service": "LinuxCNC UI Backend"}

if __name__ == "__main__":
    import uvicorn
    # Run the server on all interfaces, port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
