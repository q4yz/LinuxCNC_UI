# Homing routine, Z tilt and bed mesh

## Homing routine — `[homing_override]`

```ini
[homing_override]
axes: xyz            # (optional) axes whose home button runs it; default every axis
gcode:
    G91
    G0 Z5            ; lift 5 mm (works unhomed)
    G90
    G28 X
    G28 Y
    G53 G0 X100 Y100 ; centre, machine coordinates
    G28 Z
```

Runs for the Home buttons, `G28` in the console and a program's start G-code.

## Z tilt — `[z_tilt]`

Several Z motors are levelled against the probe: probe some points, fit a plane, move each Z
motor by its correction.

```ini
[z_tilt]
z_positions:         ; X, Y of each Z motor's pivot, in [stepper_z], [stepper_z1], … order
    -50, 18
    260, 18
    100, 250
points:              ; nozzle X, Y at each probe point
    30, 5
    230, 5
    100, 200
speed: 50            ; (optional) XY travel, mm/s
horizontal_move_z: 5 ; (optional) Z between points
probe_speed: 5       ; (optional) mm/s
retries: 5           ; (optional) extra rounds until within retry_tolerance
retry_tolerance: 0.0075
max_adjust: 5        ; (optional) largest correction per motor, mm
```

Run `Z_TILT_ADJUST`. The measurements go to the console under *Debug*, one summary line under
*Info*.

## Bed mesh — `[bed_mesh]`

```ini
[bed_mesh]
probe_count: 5, 5            ; (optional) grid X, Y
mesh_min: 10, 10             ; (optional) where the probe touches
mesh_max: 190, 190
speed: 50                    ; (optional)
horizontal_move_z: 5         ; (optional)
probe_speed: 5               ; (optional)
zero_reference_position: 100, 100   ; (optional) the mesh is 0 here
```

`BED_MESH_CALIBRATE [PROFILE=name]` probes the grid, saves the mesh and switches Z
compensation on. The Bed Mesh page shows it as a heat map. `G29` runs `Z_TILT_ADJUST`, then
`BED_MESH_CALIBRATE`.
