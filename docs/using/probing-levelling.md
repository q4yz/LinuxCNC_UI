# Probing and levelling

The probe, its offsets, `[z_tilt]` and `[bed_mesh]` are set up in the profile
({doc}`../getting-started/config-reference`). The commands run in the console.

## PROBE_ACCURACY

```text
PROBE_ACCURACY [SAMPLES=10] [SAMPLE_RETRACT_DIST=2] [PROBE_SPEED=5]
```

Probes the same spot `SAMPLES` times. Each sample is logged under *Debug*, the result —
maximum, minimum, range, average, median, standard deviation — under *Info*. Z must be homed.

## PROBE_CALIBRATE — measuring z_offset

The paper test, as in Klipper:

1. Home, move the probe over the middle of the bed, run `PROBE_CALIBRATE`. It probes, lifts
   5 mm, moves the nozzle over the spot the probe touched and lowers it to the probe's trigger
   height. Bed mesh compensation is switched off for the test.
2. Lower the nozzle until a sheet of paper just drags: the Z jog buttons, or `TESTZ Z=-0.1`
   (`TESTZ Z=0.05` back up). Each `TESTZ` logs the `z_offset` that height gives.
3. `ACCEPT` logs `z_offset: 1.234`; `ABORT` stops without a value.
4. Put the value into `[probe] z_offset`, generate the machine again
   ({doc}`../getting-started/compile`) and restart LinuxCNC.

## Z_TILT_ADJUST

Levels several Z motors: probes `[z_tilt] points`, fits a plane and moves each Z motor by its
correction, repeating up to `retries` times until within `retry_tolerance`. The measurements
go to the console under *Debug*, one summary under *Info*.

## BED_MESH_CALIBRATE

```text
BED_MESH_CALIBRATE [PROFILE=name]
```

Probes the `[bed_mesh]` grid, saves the mesh and switches Z compensation on. The **Bed Mesh**
page shows it as a heat map.

`G29` runs `Z_TILT_ADJUST`, then `BED_MESH_CALIBRATE`. A program's start G-code `G29` runs the
same before the program.
