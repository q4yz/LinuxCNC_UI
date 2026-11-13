# Introduction

LinuxCNC Web UI is a browser front end for a LinuxCNC machine. A backend on the machine wraps
the LinuxCNC Python API and HAL and streams the machine state to the browser at 10 Hz over a
WebSocket; every action (jog, home, start a program, set a temperature) goes through a typed
REST API.

## What it does

- **Manual control** — DRO with live position, jogging of every axis, homing.
- **Programs** — upload (also straight from a slicer), preview, start, pause, stop; slicer
  G-code is converted for LinuxCNC on upload.
- **3D printing** — heaters with PID, part fans, the extruder as the A axis, Klipper-style
  probing: `PROBE_ACCURACY`, `PROBE_CALIBRATE`, `Z_TILT_ADJUST`, `BED_MESH_CALIBRATE`.
- **Configuration** — a Klipper-style machine `.cfg` generates the LinuxCNC INI, the HAL
  files and the Remora board config.
- **Tools for the machine builder** — HAL pin list, oscilloscope, a visual HAL editor, logs.
- **Web app** — HTTP, HTTPS or installed as an app (PWA), fully local.

## How it fits together

```text
Browser (Vue 3 app / PWA)
   │   REST /api/v1/*          WebSocket, 10 Hz telemetry
   ▼
Backends on the machine (FastAPI)
   ├── machine backend (:8000) — LinuxCNC, HAL, routines
   └── system backend          — files, settings, machine configs, updates
   ▼
LinuxCNC + HAL  ──SPI / CAN──►  Remora board(s)
```

The **machine backend** only answers while LinuxCNC runs; the **system backend** always runs,
so files, settings and the machine configuration are available with the machine off.
