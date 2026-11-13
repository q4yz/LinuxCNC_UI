# Architecture

## Overview

```text
Browser (Vue 3 SPA / PWA)
   │   REST /api/v1/*          WebSocket, 10 Hz telemetry
   ▼
FastAPI backends on the host
   ├── machine backend (:8000) — LinuxCNC (NML), HAL, routines (homing, probing, macros)
   └── system backend          — files, settings, machine configs, generator, updates
   ▼
LinuxCNC + HAL ──SPI / Ethernet──► Remora board ──CAN──► toolhead board(s)
```

- The **machine backend** polls LinuxCNC over NML at 10 Hz, maps the raw status into typed DTOs,
  computes deltas and broadcasts them over a WebSocket. It only runs while LinuxCNC runs.
- The **system backend** always runs: files (`nc_files/`), UI settings, machine profiles, the
  generator, the OctoPrint-compatible upload API, updates.
- Every action goes through one typed REST contract (OpenAPI); the frontend's API client is
  generated from it.

| Folder | Purpose |
|--------|---------|
| `backend/machine` | the machine backend: routers → services → mappers → DTOs |
| `backend/system` | the system backend, the config parser and the HAL / INI generator |
| `backend/common` | shared code: hardware access (with a mock layer), the G-code converter, models |
| `frontend/` | Vue 3 + TypeScript: Pinia stores, Tailwind CSS, Three.js viewer, CodeMirror |
| `machine_config/` | example machines, the shared M-codes (`m_codes/`) |
| `macros/` | macros (`.ngc`) callable from programs and the UI |
| `docs/` | this manual |

## From profile to running machine

```text
profile.cfg ─parse─► config graph ─► hardware.json ─► machine.ini, machine.hal,
                                                        webgui_connections.hal, config_<mcu>.txt
```

The parser checks every section and key; the generator builds the axes and joints
(`[JOINT_N]`), the HAL wiring per component (steppers, heaters with PID loops, probe gating,
fans, LEDs, Z tilt, bed mesh compensation) and routes each pin to the MCU that owns it. The
Remora board gets its module list as `config_<mcu>.txt`, uploaded at every LinuxCNC start.

## Marlin M-codes

LinuxCNC reserves M100–M199 for user M-code programs (it cannot REMAP them): `M104`, `M109`,
`M140`, `M190`, `M106`, `M107` are executables in `machine_config/m_codes/` (`USER_M_PATH`) —
one script that acts by the name it runs as, through the machine backend's REST API. User
M-codes only receive `P` and `Q`, so uploads, macros and MDI convert Marlin's `S` / `T`.

## Safety in HAL

- E-stop chain: the E-stop input, the CAN status bit (a lost mandatory node), the UI's E-stop.
- Heater loops run in HAL (PID or watermark) and are off while the link to the board is down.
- The cold-extrusion guard is the Remora `extruder` component, netted to `halui.abort`.

## Lessons

- **No HAL client may block while it holds the HAL mutex.** `halcmd show` holds it while it
  prints; into a full pipe it blocked while `hal.get_value()` spun on the mutex holding
  Python's GIL — the whole backend hung. `halcmd` output goes through a temporary file.
- **A user M-code exits with an error** when the heater or fan it names does not exist; the
  converter comments out fan lines for fans the machine does not have.
