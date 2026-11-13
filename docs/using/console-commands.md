# Console and MDI commands

The console shows the log — LinuxCNC's messages and errors, the UI's own (probing results,
macros, routines) — filtered by level: *Debug* (measurements), *Info* (results), *Warning*,
*Error*. Its input line sends MDI commands; suggestions appear while typing.

## Commands of the UI

Besides LinuxCNC's own G-code, the console takes these, named like Klipper's:

| Command | Does |
|---------|------|
| `G28` / `G28 X Y` | home (the homing routine, or the axes named) |
| `G29` | `Z_TILT_ADJUST`, then `BED_MESH_CALIBRATE` |
| `Z_TILT_ADJUST` | level the Z motors — {doc}`../configuration/levelling` |
| `BED_MESH_CALIBRATE [PROFILE=name]` | probe the bed mesh |
| `PROBE_ACCURACY [SAMPLES=10] …` | probe repeatability — {doc}`../configuration/probe` |
| `PROBE_CALIBRATE [SPEED=5]`, `TESTZ Z=<mm>`, `ACCEPT`, `ABORT` | measure `[probe] z_offset` |
| `SET_LED LED=<name> RED= GREEN= BLUE= [INDEX=]` | an LED colour |

While a routine runs, the state reads *Busy* (a program: *Running*).

## Marlin temperature and fan codes

LinuxCNC reserves M100–M199 for *user M-code programs*: executables named like the code in
`machine_config/m_codes/`. The Marlin codes are such programs:

| Code | Does |
|------|------|
| `M104 S<°C> [T<extruder>]` | hotend target |
| `M109 S<°C> [T<extruder>]` | hotend target, wait until reached |
| `M140 S<°C>` | bed target |
| `M190 S<°C>` | bed target, wait |
| `M106 [S<0-255>] [P<fan>]` | part fan (no S: full speed) |
| `M107 [P<fan>]` | part fan off |

A user M-code only receives `P` and `Q`, so Marlin's `S` / `T` (and a fan's `P`) are converted:
in uploaded G-code, in macros and in the console — `M104 S215 T0` becomes `M104 P215 Q0`. A
line already written with `P` / `Q` is sent as it is.
