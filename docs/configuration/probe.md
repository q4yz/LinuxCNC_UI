# Probe

```ini
[probe]
pin: !sb2209:PB6
x_offset: -25        # (optional) probe X minus nozzle X, mm
y_offset: 10         # (optional) probe Y minus nozzle Y, mm
z_offset: 1.20       # (optional) nozzle height above the bed when the probe triggers
```

The offsets mean what they mean in Klipper:

- **Bed mesh** — `mesh_min` / `mesh_max` are where the probe touches the bed; the nozzle goes
  `x_offset`, `y_offset` away from there.
- **Z tilt** — `points` are nozzle positions; the probe measures `x_offset`, `y_offset` from
  there and the tilt is fitted where it actually touched.
- **Heights** — a probed height is the nozzle's Z at the trigger minus `z_offset`.

## Z homed on the probe

```ini
[stepper_z]
endstop_pin: probe:z_virtual_endstop
homing_speed: 5
second_homing_speed: 2.5
homing_retract_dist: 5
```

Z homes with LinuxCNC's own homing, the probe as the Z switch. `[probe] z_offset` is Z at the
trigger point; do not also set a different `position_endstop` (an error when generating).
X and Y must put the probe over the bed first — `[homing_override]`, {doc}`levelling`.

## PROBE_ACCURACY

```text
PROBE_ACCURACY [SAMPLES=10] [SAMPLE_RETRACT_DIST=2] [PROBE_SPEED=5]
```

Probes the same spot `SAMPLES` times. Each sample is logged under *Debug*, the result —
maximum, minimum, range, average, median, standard deviation — under *Info*. Z must be homed.

## PROBE_CALIBRATE — measuring z_offset

The paper test, as in Klipper:

1. Home, move the probe over the middle of the bed, run `PROBE_CALIBRATE` in the console.
   It probes, lifts 5 mm, moves the nozzle over the spot the probe touched and lowers it to
   the probe's trigger height. Bed mesh compensation is switched off for the test.
2. Lower the nozzle until a sheet of paper just drags: the Z jog buttons, or
   `TESTZ Z=-0.1` (`TESTZ Z=0.05` back up). Each `TESTZ` logs the `z_offset` that height
   gives.
3. `ACCEPT` logs `z_offset: 1.234`; `ABORT` stops without a value.
4. Put the value into `[probe] z_offset`, generate the machine again and restart LinuxCNC.
