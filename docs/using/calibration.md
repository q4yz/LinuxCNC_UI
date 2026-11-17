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

A card the machine cannot run (no probe, no accelerometer) says what is missing.
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
