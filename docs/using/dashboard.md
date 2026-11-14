# Dashboard and page layout

The **Dashboard** and the **Running** page show panels in two columns. Which panels, in which
column and order, is a setting: **Settings → Page layout**, one layout per page. Each panel goes
in the left column, the right column or *Hidden*; ▲ / ▼ order it. Changes save at once and are
shared by every browser.

| Panel | Shows |
|-------|-------|
| Machine (power) | machine state, E-STOP, POWER, RESET MCU |
| DRO | positions, homed state, Home all, macro buttons per axis |
| Jog controls | jog buttons and speed — {doc}`jogging` |
| Tools | extruder, spindle and heater controls |
| Temperatures | readings, targets, chart |
| I/O | fans, output and input pins |
| LEDs | `[neopixel]` colours |
| Job status | the loaded program, start / pause / stop, progress |
| Axis speed | speed multiplier (feed override), max speed |
| Console | log and MDI — {doc}`console-commands` |
| Camera | the camera stream |
| Macros & NGC, M-Codes | run macros / user M-codes |

Machine panels only appear while the machine backend is reachable (LinuxCNC running); the
console always shows — it explains why the machine is offline.

Both pages stay loaded in the background: a panel placed on both runs twice (for the camera,
two streams).

## The E-stop

The **STOP** button is always in the top-right corner, over the page. A card row that passes
under it moves its buttons left so nothing is covered.

## Temperatures

- The unit (°C, °F, K) is a setting: **Settings → Temperature**. A target typed in °F or K is
  converted; the machine always works in °C.
- **Cool all** in the card header switches every heater off.
- The eye button hides a sensor from the chart.
