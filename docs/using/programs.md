# Programs and slicers

The **G-Code Files** page lists `nc_files/`: upload, preview (slicer thumbnail, toolpath),
load, rename, move (drag an entry onto a folder), delete.

## Sending from a slicer

The machine answers the OctoPrint API slicers support:

- **OrcaSlicer / PrusaSlicer** — Printer → *Physical printer*, host type **OctoPrint**,
  hostname `http://<machine-ip>`, any API key.
- **Cura** — the **OctoPrint Connection** plugin, the machine's IP, port 80, any API key.

*Upload and print* only **loads** the file, and only while LinuxCNC runs: nothing is started
from the network.

## What the converter changes

A `.gcode` upload is converted for LinuxCNC and stored as `.ngc`:

| Slicer G-code | Becomes |
|---------------|---------|
| `E` | `A`, always absolute (`M82` / `M83` / `G92 E` handled) |
| `M104 S200 T1`, `M140`, `M109`, `M190`, `M106 S255`, `M107` | `P` / `Q` form; a bare `M106` is `M106 P255` |
| `M106` / `M107` for a fan the machine does not have | commented out |
| `G4 S2` / `G4 P500` (ms) | `G4 P2` / `G4 P0.5` |
| `M117 text` | `(MSG, text)` |
| `G28` / `G29` in the start G-code | run before the program (homing routine, levelling) |
| `G28 X` later (parking) | a move to the home position |
| `start 60 215`, `PRINT_START BED=60 EXTRUDER=215` | `o<start> call [60] [215]` when `macros/start.ngc` exists |
| `SET_LED …`, `M150 …` | the LED M-code |
| an M-code LinuxCNC does not know (`M84`, `M73`, …) | commented out with the reason |
| a line over 252 characters | cut to 249 + `...` (LinuxCNC's line limit) |
| no `M2` / `M30` | `M2` appended |

Upload a file again after an update to get the current rules.
