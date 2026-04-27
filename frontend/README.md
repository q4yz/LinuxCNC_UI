# LinuxCNC Web UI - Frontend

This is the modern, reactive frontend for the LinuxCNC Web UI, architected using Vue 3, Pinia, and TailwindCSS. It draws design inspiration from popular 3D printing interfaces like Mainsail and Fluidd.

## Features

*   **Vue 3 Composition API**: Clean, modular, and reactive components.
*   **Pinia State Management**: Maintains a real-time, global machine state synchronized securely via WebSockets.
*   **Three.js 3D Viewer**: A dedicated WebGL canvas that renders a live-updating toolhead tracking the machine's actual XYZ coordinates in 3D space.
*   **Safety Watchdogs**: Implements safe, continuous jogging with keep-alive intervals.

## Installation

### Prerequisites
*   Node.js (v16+)
*   npm (v8+)

### Setup Instructions

1.  **Navigate to the frontend directory:**
    ```bash
    cd frontend
    ```

2.  **Install Node dependencies:**
    ```bash
    npm install
    ```

## Running the Development Server

Start the Vite development server:

```bash
npm run dev
```

*   The frontend will be available at `http://localhost:5173`.
*   **Note**: The Vite server uses an internal proxy (`vite.config.js`) to route `/api` and `/ws` requests directly to the FastAPI backend running on port `8000`. You must have the backend running simultaneously for the UI to function and connect to the machine.

## Building for Production

To compile and minify the frontend for production deployment:

```bash
npm run build
```
The compiled assets will be output to the `frontend/dist/` directory, which can be served by Nginx, Apache, or directly by the FastAPI backend.
