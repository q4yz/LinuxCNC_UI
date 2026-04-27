# LinuxCNC Web UI - Backend

This is the FastAPI backend for the LinuxCNC Web UI. It acts as a high-speed, asynchronous bridge between the web frontend and the LinuxCNC hardware (or local mock environment).

## Architecture

*   **FastAPI**: Provides REST endpoints for machine control (Jogging, Power, E-Stop, MDI).
*   **WebSockets**: A background telemetry loop streams real-time CNC state (DRO, status) to the frontend at 10Hz.
*   **Hardware Abstraction**: Automatically detects if it is running on real LinuxCNC hardware. If the `linuxcnc` Python module is unavailable (e.g., developing on Windows/Mac), it seamlessly falls back to a robust, dynamic `linuxcnc_mock` allowing you to simulate jogging and machine states locally.

## Installation

### Prerequisites
*   Python 3.8+

### Setup Instructions

1.  **Navigate to the backend directory:**
    ```bash
    cd backend
    ```

2.  **Create a virtual environment:**
    ```bash
    # Windows
    python -m venv venv
    
    # Linux/macOS
    python3 -m venv venv
    ```
    *Note: If you are running this on an actual LinuxCNC machine and need access to the system-installed `linuxcnc` module, create the venv with the `--system-site-packages` flag: `python3 -m venv --system-site-packages venv`*

3.  **Activate the virtual environment:**
    ```bash
    # Windows
    .\venv\Scripts\activate

    # Linux/macOS
    source venv/bin/activate
    ```

4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Running the Server

Start the Uvicorn development server:

```bash
python main.py
```
*(The server runs on `http://0.0.0.0:8000` by default)*

## API Documentation
Once the server is running, you can access the auto-generated interactive API documentation at:
*   Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
*   ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
