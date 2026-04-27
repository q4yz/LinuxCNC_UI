# LinuxCNC Web UI

A modern, high-performance web interface for LinuxCNC, heavily inspired by "Fluidd" and "Mainsail". 

This project provides a complete, decoupled architecture allowing you to monitor and control your LinuxCNC machine from any browser, complete with a real-time 3D WebGL Toolpath viewer.

## Architecture

This is a Monorepo containing two distinct projects:

1.  **[Backend](./backend/README.md)**: A modern Python 3 FastAPI application that exposes standard REST API endpoints and a high-speed (10Hz) WebSocket telemetry stream. It includes a robust mock hardware layer for local development on non-Linux machines.
2.  **[Frontend](./frontend/README.md)**: A reactive Single Page Application (SPA) built with Vue 3, Pinia (for state management), TailwindCSS, and Three.js (for the 3D toolhead viewer).

## Quick Start

### 1. Start the Backend
Open a terminal, navigate to the `backend/` folder, install the python requirements, and start the API:
```bash
cd backend
python -m venv venv
# Windows: .\venv\Scripts\activate | Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### 2. Start the Frontend
Open a *second* terminal, navigate to the `frontend/` folder, install the node modules, and start the Vite dev server:
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser. The Vite proxy will automatically route API and WebSocket traffic to your running backend!

*For detailed installation instructions, see the individual READMEs in the `backend/` and `frontend/` directories.*


