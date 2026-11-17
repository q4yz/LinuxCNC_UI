# Programs and slicers

The **G-Code Files** page lists `nc_files/`: upload, preview (slicer thumbnail, toolpath),
load, rename, move (drag an entry onto a folder), delete.

## Sending from a slicer

The machine answers the OctoPrint API slicers support:

- **OrcaSlicer / PrusaSlicer** — Printer → *Physical printer*, host type **OctoPrint**,
  hostname `http://<machine-ip>`, any API key.
- **Cura** — the **OctoPrint Connection** plugin, the machine's IP, port 80, any API key.

*Upload* stores the file; *Upload and print* also loads it into LinuxCNC (while it runs).

**Starting from the slicer** — switch on **Settings → Slicer → Start prints sent from the
slicer**, and *Upload and print* starts the print like the Start button: the file's `G28` /
`G29` (homing, levelling) run first, then the program. The machine must be on and idle; a
machine that is off, unhomed or busy only loads the file (the console says why). Off by default:
then nothing is ever started from the network.

## What the converter changes

The conversion runs in the background: the upload returns at once and the file list shows the
file as *converting…* until it is stored (a large print takes some seconds, more on a small host
such as the BTT CB1); then the console reports it ready and it can be loaded. A file whose
conversion failed is listed as *conversion failed* — the tooltip says why — for ten minutes.

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
| a bare `G10` / `G11` (firmware retraction) | the `[firmware_retraction]` move on A |
| `M221 S95` (flow) | `M184 P95` |
| `SET_GCODE_OFFSET Z_ADJUST=-0.02` | `M185 P-0.02 Q1` (the live Z offset) |
| `M600` | kept: the machine's filament change |
| labelled objects (`EXCLUDE_OBJECT_START`, `M486`, `; printing object`, `; OBJECT_ID:`, Cura's `;MESH:`) | each object's part wrapped so it can be excluded during the print |
| `M73 P R` (progress) | kept as a comment: the card's *Slicer* progress |
| no `M2` / `M30` | `M2` appended |

Upload a file again after an update to get the current rules.
