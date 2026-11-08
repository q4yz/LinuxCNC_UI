# Component: Slicer G-code upload + Marlin M-codes

> **Implemented status:** converter `backend/common/core/gcode_converter.py`
> (called by `ProgramFileService.save_upload`, so the UI's upload and
> the OctoPrint-compatible slicer upload both convert), Marlin heater /
> fan M-codes `backend/system/services/machinetemplates/marlin_mcodes.py`
> (INI `REMAP`, `subroutines/`, `mcodes/`), example start macro
> `macros/start.ngc`. Tests: `backend/common/tests/test_gcode_converter.py`,
> `backend/system/tests/test_marlin_mcodes.py`, `test_octoprint.py`.
>
> Not yet: arc blending / `G64` tolerance and other path optimisation;
> `M109 R` (wait while cooling); a toolhead's own MCU temperature.

## 1. Upload: `.gcode` -> `.ngc`

A `.gcode` / `.gco` / `.g` upload is converted and stored as `.ngc`
(the original is not kept); `.ngc` is stored as it is.

| Slicer (Marlin) | Stored (LinuxCNC) |
|---|---|
| `G1 X10 E1.5` | `G1 X10 A1.5` — `A` always absolute: `M82` / `M83` / `G90` / `G91` / `G92 E` are tracked by the converter, no `G92` offset is set (under `G91` the delta) |
| `M104 S215 T0` / `M109 S215` | `M104 P215 Q0` / `M109 P215` |
| `M140 S60` / `M190 S60` | `M140 P60` / `M190 P60` |
| `M106 S255 P1` / `M107` | `M106 P255 Q1` / `M107` |
| `G4 S2` / `G4 P500` (ms) | `G4 P2` / `G4 P0.5` |
| `M117 text` | `(MSG, text)` |
| `start 60 215`, `PRINT_START BED=60 EXTRUDER=215` | `o<start> call [60] [215]` — when `macros/start.ngc` exists, values in order; otherwise commented out |
| `G28`, `G29`, `T0`, `M82`, `M83`, `G92 E…`, any M-code LinuxCNC does not know (`M84`, `M400`, `M201`, `M73`, …) | commented out: `; G28  ; [homing / leveling: run it before the program]` |
| no `M2` / `M30` | `M2` appended |

`;` comments and slicer thumbnails pass through (LinuxCNC reads `;` as a
comment). Home the machine before running a print — a program cannot
home in LinuxCNC.

## 2. Start macro

`macros/start.ngc` (an example, yours to edit) is what a slicer's start
G-code `start <bed> <hotend>` calls: `#1` bed, `#2` hotend. Any
`macros/<name>.ngc` works the same way (`end`, `print_start`, …), and it
can be run from the macro panel as well.

## 3. Marlin M-codes (machine generation)

A machine with a heater or a part fan gets, in `machine.ini`
`[RS274NGC]`:

```ini
USER_M_PATH = <repo>/machine_config/m_codes:mcodes
SUBROUTINE_PATH = <repo>/macros:subroutines
REMAP=M104 modalgroup=10 argspec=pq ngc=m104
REMAP=M109 modalgroup=10 argspec=pq ngc=m109
REMAP=M140 modalgroup=10 argspec=p ngc=m140
REMAP=M190 modalgroup=10 argspec=p ngc=m190
REMAP=M106 modalgroup=10 argspec=pq ngc=m106
REMAP=M107 modalgroup=10 argspec=q ngc=m107
```

Each `subroutines/m1xx.ngc` calls a helper user M-code in `mcodes/`
(LinuxCNC runs it as a program and waits until it exits):

| Helper | Does |
|---|---|
| `M180 P<°C> Q<heater>` | heater target through the machine backend (`POST /api/v1/modules/tools/tools/<id>/target`) |
| `M181 P<°C> Q<heater>` | the same, then waits until `webgui.<sensor>` (`halcmd getp`) is within 2 °C below it (30 min timeout) |
| `M182 P<0-255> Q<fan>` | a part fan in % (`PUT /api/v1/modules/io/<fan>`) |

`Q`: extruder index (0 = first), `-1` = bed; fans: index of the part
fans in declaration order (a heater's placeholder fan, which shares its
pin, is never one). The ids are written into the helpers at generation.

The remapped codes take `P` / `Q`, not Marlin's `S` / `T`: in LinuxCNC
an `S` word also sets the spindle speed. Uploads are converted; in MDI
and macros write `M104 P215`, `M190 P60`, `M106 P255`.
