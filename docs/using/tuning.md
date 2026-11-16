# Tuning the printer

Klipper's calibration routines, run from the console ({doc}`console-commands`). Values set
at runtime last until LinuxCNC restarts: put the results into the profile and generate the
machine.

## Heater PID

```text
PID_CALIBRATE HEATER=extruder TARGET=210
PID_CALIBRATE HEATER=heater_bed TARGET=60
```

`HEATER` is `extruder`, `heater_bed` or a heater's id. The heater is switched fully on below
`TARGET − 5` and off above `TARGET` (a relay) until 12 temperature peaks are recorded — some
minutes; the console shows them under *Debug*. Then it logs `pid_Kp`, `pid_Ki`, `pid_Kd` for
the heater's section.

The numbers are in this machine's units: the PID output is 0 … 100 %, Klipper's 0 … 255, so
Klipper's own values are 2.55 times larger. The test stops — and the PID loop takes the
heater back — at 25 °C over the target, when no peak comes for 10 minutes, or in E-stop.

## Pressure advance

`[extruder] pressure_advance` (mm of filament per mm/s): the extruder runs ahead by
`K × extrusion speed` while it extrudes, so the nozzle pressure follows the speed. Change it
at runtime with `SET_PRESSURE_ADVANCE ADVANCE=<k>`, `M900 K<k>` (a slicer's), or on the Job
card. Find it with a pressure advance test print (a tower, changing K per layer). Retracts
are not advanced.

## Input shaping and the resonance test

An ADXL345 on the host's SPI (`[adxl345]`, `python3-spidev` installed) mounted on the
toolhead, then:

```text
ACCELEROMETER_QUERY          # wiring check
SHAPER_CALIBRATE             # both axes, or AXIS=X / AXIS=Y
```

The axis is shaken with a sine sweep (`min_freq` … `max_freq`) through the `jointshape`
component while the accelerometer records; the console logs per shaper its best frequency,
the vibration left and its length (under *Debug*), and recommends one:

```ini
[input_shaper]
shaper_type_x: mzv
shaper_freq_x: 52.4
```

`SET_INPUT_SHAPER SHAPER_FREQ_X=<Hz> SHAPER_FREQ_Y=<Hz>` tries a frequency; a change
applies once the axis stands still. Input shaping and the test need a Cartesian Remora
machine (not CoreXY).

## Skew correction

Print a skew calibration square, measure the diagonals AC, BD and the side AD (mm):

```text
SET_SKEW XY=140.4,141.6,99.8
```

The console logs the factor for `[skew_correction] xy_skew_factor` (or put the three
measurements in as `xy_ac`, `xy_bd`, `xy_ad`). `GET_CURRENT_SKEW` shows it, `SET_SKEW
CLEAR=1` switches it off.

## Adaptive bed mesh

`BED_MESH_CALIBRATE ADAPTIVE=1` probes only where the loaded print extrudes, plus
`[bed_mesh] adaptive_margin`, with the same number of points: a finer mesh, faster. The
area comes from the uploaded file (the converter writes it into the file's header); a
program without one gets the whole mesh. `[bed_mesh] adaptive: True` makes a print's `G29`
adaptive. Outside the probed area the compensation holds the edge values.

## Sensorless homing

TMC2209 drivers detect a stall and raise their DIAG output (StallGuard). Wire DIAG to an
endstop input (BTT boards: the DIAG jumper of the driver), then:

```ini
[stepper_x]
endstop_pin: tmc2209_stepper_x:virtual_endstop
homing_retract_dist: 0

[tmc2209 stepper_x]
uart_pin: PC4
diag_pin: ^PG6
driver_SGTHRS: 100
```

StallGuard needs StealthChop: the driver runs it while `driver_SGTHRS` is set. Start with
100: when the axis stops before the end, lower it; when it grinds at the end, raise it. Home
with a moderate `homing_speed` (Klipper suggests rotation_distance / 2 per second) and
`homing_retract_dist: 0`.
