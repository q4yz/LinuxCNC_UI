# Your first machine

A machine is described by one Klipper-style `.cfg` file, a **profile**. Generating the machine
from it writes everything LinuxCNC needs:

| File | Content |
|------|---------|
| `machine.cfg` | a copy of the profile it was generated from |
| `hardware.json` | the machine as the UI sees it (axes, tools, sensors, fans, LEDs) |
| `machine.ini` | the LinuxCNC INI: joints, axes, limits, homing, PID sections |
| `machine.hal` | the HAL wiring: motion, steppers, heaters, probe, components |
| `webgui_connections.hal` | the UI's HAL pins (temperatures, fans, LEDs, buttons) |
| `config_mcu.txt` | the Remora board configuration, uploaded at every LinuxCNC start |

## Steps

1. Open the **Config** page and create or upload a profile `.cfg`. Start from an example —
   `machine_config/example/` in the repository — and see {doc}`../configuration/overview` for
   the sections.
2. **Generate** the machine. Errors name the section and key (a missing pin, an unknown key,
   a value out of range).
3. Make it the default machine and start LinuxCNC with its `machine.ini`.
4. Check the basics before anything moves: E-stop, power, each axis's direction with a short
   jog, endstops, then homing.

Every file except the profile is rewritten on each generate: change the profile, not the
generated files.
