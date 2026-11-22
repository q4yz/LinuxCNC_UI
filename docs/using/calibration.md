# Calibration

The **Calibration** tab has a card for each calibration the machine can run — scroll sideways
(swipe on a phone). Each card shows:

- **Last tested** and the **result** of the last successful run;
- **In use**: the values the machine runs with now (calibrated, or the profile's);
- **Reminder**: a date, once — the card turns amber and the tab shows a badge when it is due;
  running the calibration after that clears it;
- what it is good for, **Instructions**, its settings (e.g. the PID target) and **Start**.

| Card | Runs | Saves |
|------|------|-------|
| Bed mesh | `BED_MESH_CALIBRATE` | the mesh (*Details*: the meshes, heat map, editing) |
| Z tilt | `Z_TILT_ADJUST` | the Z motor offsets |
| Probe accuracy | `PROBE_ACCURACY` | — (the result only) |
| Probe Z offset | `PROBE_CALIBRATE`, then the paper test with the card's buttons | `[probe] z_offset` |
| Heater PID (per heater) | `PID_CALIBRATE` | `pid_Kp` / `pid_Ki` / `pid_Kd` |
| Input shaper | `SHAPER_CALIBRATE` | the shaper type and frequency per axis |
| Skew | a test print, then you measure it | the XY skew factor |
| Pressure advance | a test print, then you measure it | the pressure advance |
| Extruder steps | extrudes 100 mm, then you measure it | the extruder's steps / mm (`[JOINT_n] SCALE`) |
| Flow | a test print, then you measure it | the flow % the machine starts with |
| First layer | a test print you tune with the live Z offset | the probe's `z_offset`, or Z's home position |
| Retraction | a test print, then you measure it | `[firmware_retraction]` length and speed |
| Sensorless homing (per axis) | homes the axis; you say how it went | the driver's StallGuard threshold |

A card the machine cannot run (no probe, no accelerometer) says what is missing.

## Test prints

Skew, pressure advance, extruder steps, flow and first layer cannot measure themselves. **Print test** generates a test object from the profile
(the bed's size and centre, the nozzle and filament diameter, the temperatures on the card),
converts it like an uploaded slicer file into `nc_files/calibration/` and starts it — it heats,
homes and prints; it asks first. Then measure the print, enter the values under *Measure the
test print* (the drawing shows where) and **Calculate & save**: the result is saved and active
at once.

- **Skew** — a square frame (100 mm, smaller on a small bed). A solid tab inside the frame marks
  corner A (front left); B, C, D follow counter-clockwise. Measure the outer corners: the
  diagonals AC and BD and the left side AD. The square is printed with the skew factor in use;
  the new factor is that plus what the print still shows. Needs the `jointshape` component:
  an empty `[skew_correction]` section in the profile is enough.
- **Pressure advance** — a hollow single-wall tower. Its pressure advance is
  *start + factor × height*, raised every millimetre; afterwards the value before the print is
  set again. Find the height where the corners are sharpest (lower: they bulge, higher: gaps
  or rounded corners) and enter it: K = start + factor × that height. Factor 0.005 suits a
  direct drive, 0.02 a Bowden extruder.
- **Extruder steps** (Klipper's `rotation_distance`) — mark the filament 120 mm above the
  extruder's inlet; the test heats, lifts the nozzle and extrudes 100 mm slowly. Measure from the
  inlet to the mark again and enter it: the steps / mm become *SCALE × 100 / (120 − remaining)*,
  from the next LinuxCNC start (changing it on a running machine would make the extruder jump).
  The result also says by how much to change `rotation_distance` in the profile.
- **Flow** — a single-wall cube with a brim. Measure the wall (one wall) with calipers above the
  brim; the flow becomes *flow while printing × planned width / measured*. The machine starts
  with that flow, the Job card can still change it per print. Calibrate the extruder steps
  first.
- **First layer** — five single-layer patches, the middle one first. While it prints, turn the
  live Z offset with the card's buttons (+ = nozzle up) until the lines are flat and touch; the
  corner patches show whether the bed mesh / Z tilt fits. After the print, **Save live offset**:
  the offset goes into the probe's `z_offset` (Z homes on the probe, or the bed mesh holds
  absolute heights) or into Z's `HOME_OFFSET` (a Z switch). It applies from the next LinuxCNC
  start — the live offset stays until then; home (and probe the mesh) again after the
  restart.
- **Retraction** — two small towers; every travel between them retracts *start + factor ×
  height* (stepped every millimetre) at the card's speed. Enter the height from which no strings
  are left: that length and speed become `[firmware_retraction]`. It is used for the `G10` /
  `G11` of files uploaded from then on — set the slicer to *firmware retraction* and upload
  earlier files again.

## Sensorless homing

A card per axis homed by StallGuard (`endstop_pin: tmc2209_stepper_x:virtual_endstop`). The
threshold is a driver register the board sets when LinuxCNC starts, so every try is: **Home X**,
then say how it went — *Stopped early* (too sensitive), *Ground at end* (not sensitive enough) or
*Good*. Each answer halves the range left and suggests the next threshold; **Save & restart
LinuxCNC** saves it and restarts LinuxCNC (switch on and home again). At every start the UI
writes the saved thresholds into the board config (`config_<mcu>.txt`, StealthChop on), which the
board takes over from its SD card; the generated values are kept in the file, so **Clear** goes
back to the profile's `driver_SGTHRS`. Keep a hand on the E-stop for the first tries.
**Clear** removes a card's saved values: back to the profile's.

## calibration.ini

The results go to `calibration.ini` next to the machine's `machine.ini` and `hardware.json`
(`machine_config/machines/<name>/config/`). Generate never touches it, so the results
survive a regenerated profile, and they override the profile:

- PID gains and the shaper types are `machine.ini` keys. LinuxCNC uses the **first** value of
  a key, so a second INI read after `machine.ini` could not override anything: at every machine
  start the UI writes `machine.calibrated.ini` — `machine.ini` with the calibrated keys
  replaced — and starts LinuxCNC with it. Do not edit that file; it is written again at every
  start.
- The probe's Z offset, pressure advance, the shaper frequencies and the skew factor are read
  by the UI's machine backend, over the profile's values. A new Z offset also moves Z's home
  when Z homes on the probe.

```ini
[HEATER_EXTRUDER]
PID_KP = 8.512
PID_KI = 0.421
PID_KD = 43.02

[INPUT_SHAPER]
TYPE_X = 4

[CALIBRATION]
PROBE_Z_OFFSET = 1.732
SHAPER_FREQ_X = 52.4
SHAPER_TYPE_X = ei

[CALIBRATION_STATE]
bed_mesh.last = 2026-11-14T10:00:00
bed_mesh.result = 5 × 5, range 0.182 mm ('default')
bed_mesh.remind = 2026-12-14
```

You may edit it by hand (with LinuxCNC stopped); deleting a line goes back to the profile's
value. A broken file never stops the machine: it then starts with the profile's values and the
system log says why.
