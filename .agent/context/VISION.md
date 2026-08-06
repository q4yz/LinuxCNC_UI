# Vision

## What this project is

A modern, browser-based control surface for **LinuxCNC** that lets a
machine operator monitor and drive a CNC from any device on the local
network — desktop, tablet, or phone — without installing a native
client. The interface is inspired by **Mainsail** and **Fluidd**, and
adds a real-time 3D WebGL toolpath viewer so the operator always sees
the physical state of the toolhead, not just numbers.

## Why it exists

CNC operators need three things at once: **state visibility** (what
is the machine doing *right now*), **safe control** (jog, home, E-Stop
without typing into a terminal), and **easy configuration** (editing
HAL/INI/Klipper configs without SSH-ing into the controller box). The
stock LinuxCNC UIs solve one of these at a time. This project unifies
them behind a single responsive web app that runs on the cncfiles
controller's own hardware, with a mock layer so the same codebase
runs on a developer laptop.

## Overarching philosophy

1. **Single Source of Truth (SSOT).** `machine_config/machine.cfg`
   is the only place machine limits, axis counts, and capabilities
   live. The frontend and backend both parse it at startup; nothing
   else hardcodes those values.
2. **Hardware-agnostic core.** A clean separation between
   `backend/core/` (no `linuxcnc` imports), `backend/hardware/`
   (singleton `connection` that swaps in `linuxcnc_mock` on
   non-Linux dev machines), and the routers/UI layers (orchestrators
   only) keeps the system testable on any laptop.
3. **Modular by feature.** Every user-visible feature lives in a
   self-contained module under `backend/modules/<id>/` and
   `frontend/src/modules/<id>/`. Operators can mount or unmount
   whole features (camera, temperature, machine, machineconfig,
   tools) without touching the application shell.
4. **Safety is non-negotiable.** Continuous jogging requires a 250 ms
   frontend keep-alive and a 500 ms backend watchdog. E-Stop is a
   single tap. The dashboard defaults to `ESTOP` when no telemetry
   has arrived so the UI never claims the machine is idle when we
   have no data.
5. **Local network first.** API and WebSocket endpoints resolve
   through `window.location.hostname`; the app never hardcodes
   `localhost` or `127.0.0.1`. The Vite dev server binds to
   `0.0.0.0` so the same build works on a phone, a tablet, and the
   shop workstation.
6. **Same codebase, dev to production.** The mock hardware layer
   means the developer's laptop, the CI runner, the production
   controller, and a future multi-machine fleet all run identical
   code paths. The differences are configuration, not branches.

## What "good" looks like

- An operator powers on the controller, opens a browser, sees the
  webcam, the DRO, the temperature graph, and the jog controls
  within a second of page load.
- A developer can delete the `machine` module folder and the rest of
  the app still boots, builds, and renders placeholder cards. The
  nullable-module guarantee is a contract, not a wish.
- Adding a new feature is "drop a folder under `modules/`, declare
  a manifest, write the router or component." No edits to
  `main.py`, no `App.vue` surgery, no broken Pinia store ids.
- The test suite (frontend `node --test` + backend `pytest`) runs
  in seconds on a laptop and is a hard gate before any code lands.

## What this project is not

- **Not a cloud service.** The orchestrator runs on the local
  network. There is no hosted SaaS path; multi-machine and remote
  access are out of scope for the current vision.
- **Not a replacement for LinuxCNC's diagnostic toolchain.** The
  HAL scope, the `linuxcnc` Python REPL, and `halcmd` are still the
  primary debugging surfaces. This UI is the operator surface.
- **Not a generic IoT dashboard.** Every panel is shaped by a
  specific CNC operator workflow (jog-then-home-then-flash-then-
  deploy). Generic widget kits are not the goal.

## Audience

| Audience | Primary entry point |
|----------|---------------------|
| **Human developer** | [`README.md`](README.md) (run/build/contribute) |
| **AI agent** | [`.agent/context/hub.md`](.agent/context/hub.md) (then spokes `VISION.md`, `ARCHITECTURE.md`, `LESSONS_LEARNED.md`) |
| **Module author** | [`.agent/contracts/`](.agent/contracts/) (backend + frontend + settings) |
| **Operations reviewer** | `VISION.md` (this file) + [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) |
