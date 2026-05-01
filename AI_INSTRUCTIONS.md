# LinuxCNC Web UI - AI & Development Guidelines

This document outlines the strict architectural and developmental rules for this monorepo. Any AI agent or developer working on this codebase MUST adhere to these instructions to maintain stability, scalability, and safety.

## 1. Frontend Architecture (Vue 3)

### Stack
*   **Framework**: Vue 3 using the `<script setup>` Composition API.
*   **Build Tool**: Vite.
*   **Styling**: TailwindCSS v3.
*   **State Management**: Pinia.

### UI Modularity Rule
*   **NO MONOLITHIC FILES**: Every new feature, panel, or widget MUST be an isolated, self-contained component inside `src/components/` (e.g., `DroPanel.vue`, `JogControls.vue`, `ConsolePanel.vue`).
*   **Layout Wrapper**: `App.vue` is strictly a layout wrapper. It should only be used to arrange the imported components using Tailwind CSS Grid/Flexbox classes. No heavy business logic should live in `App.vue`.

### State Management & Reactivity Rule
*   **No Prop-Drilling**: Do not pass deep reactive state down through multiple layers of components via props. 
*   **Store Independence**: Components should independently import the Pinia stores they need (e.g., `import { useMachineStore } from '../stores/machine'`).
*   **Destructuring**: When extracting reactive variables from a Pinia store to use in a template, ALWAYS use `storeToRefs()` to ensure Vue retains reactivity (e.g., `const { droX } = storeToRefs(store)`).
*   **Cross-Store Communication**: When an action in one store needs to interact with another store (e.g., logging an error to the Console store from the Machine store), instantiate the target store *inside* the action method to avoid circular dependency crashes upon initialization.

### G-Code Configuration Rule (CRITICAL)
*   **No Hardcoding**: Absolutely no raw G-code strings should be hardcoded directly into `.vue` components or Pinia actions.
*   **Centralized Config**: All machine-specific commands, coordinate systems, and offsets MUST be defined in `src/config/gcodes.js`. Export helper functions (e.g., `generateSetOffset`) to construct strings dynamically.

## 2. Backend Architecture (FastAPI)

### Stack
*   **Framework**: FastAPI (Python 3.8+).
*   **Server**: Uvicorn.
*   **Hardware Interface**: Official `linuxcnc` Python API.

### Hardware Abstraction Layer
*   The backend must support running on a standard PC without real CNC hardware. 
*   All hardware interactions must go through `backend/hardware/connection.py`, which handles the fallback to `backend/hardware/linuxcnc_mock.py` if the real `linuxcnc` module throws an `ImportError`.

### APIRouter Modularity Rule
*   Do not write endpoints in `main.py`.
*   All REST routes must be broken down by feature into `backend/routers/` (e.g., `machine.py`, `jog.py`).
*   Every endpoint MUST include `summary` and `description` parameters, and every router MUST declare appropriate `tags` to maintain clean auto-generated OpenAPI documentation.

### Telemetry & Safety
*   **WebSockets**: Machine state is broadcasted continuously to clients at 10Hz via a background async task.
*   **Continuous Jogging**: Jogging the machine continuously poses a massive safety risk. The backend utilizes a strictly enforced `jog_watchdog`. If the frontend fails to ping the Keep-Alive endpoint (`/api/v1/machine/jog/keepalive`) every 500ms, the watchdog will aggressively inject a `JOG_STOP` command to halt runaway hardware.