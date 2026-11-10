# Component: Z tilt adjust (`[z_tilt]`)

> **Implemented status:** parser (`MachineConfigParser._parse_z_tilt`),
> `hardware_json_generator._z_tilt_payload`, `ZTiltHalMapper` /
> `ZTiltWebguiMapper`, math `backend/common/core/z_tilt.py`, machine
> backend `ZTiltService` + `/api/v1/ztilt`, the `Z_TILT_ADJUST` line in
> macros (`MacroExecutionService`) and in `[homing_override]`
> (`HomingRoutineService`). Tests: `backend/system/tests/test_z_tilt_config.py`,
> `backend/machine/tests/test_z_tilt.py`.

Levels a Z axis that is driven by two or more motors (`[stepper_z]`,
`[stepper_z1]`, ...): probe some points, fit a plane, move each Z motor
by itself until the probed heights agree. Klipper's `[z_tilt]` /
`Z_TILT_ADJUST`.

## 1. INGESTION (Hand-Written CFG)

```cfg
[z_tilt]
z_positions:         ; X, Y of each Z motor's pivot (where it lifts),
    -50, 18          ;   one per Z motor, in [stepper_z], [stepper_z1], ... order
    260, 18
    100, 250
points:              ; X, Y of the nozzle at each probe point (the probe measures [probe] x_offset, y_offset from there)
    30, 5
    230, 5
    100, 200
speed: 50            ; (Optional) XY travel, mm/s, default 50
horizontal_move_z: 5 ; (Optional) machine Z between points, default 5
probe_speed: 5       ; (Optional) G38.2 feed, mm/s, default 5
retries: 5           ; (Optional) extra rounds until within retry_tolerance, default 0
retry_tolerance: 0.0075 ; (Optional) mm, default 0
max_adjust: 5        ; (Optional) largest offset per motor, mm, default 5
```

Needs a `[probe]` (its pin is `motion.probe-input`). Two points are
enough for two motors; three or more motors need points that are not
all on one line. A probe move searches down to `[stepper_z]
position_min` (machine coordinates, `G53`).

## 2. hardware.json

```json
"z_tilt": { "z_positions": [[-50, 18], [260, 18], [100, 250]], "points": [[30, 5], [230, 5], [100, 200]],
            "joints": [2, 3, 4], "speed": 50, "horizontal_move_z": 5, "probe_speed": 5,
            "probe_min_z": 0, "retries": 5, "retry_tolerance": 0.0075, "max_adjust": 5 }
```

`joints` are the Z axis's joints, matched to `z_positions` by order.

## 3. COMPILATION

LinuxCNC moves every joint of one axis together, so each Z motor gets an
offset of its own, between the joint and its driver (`offset`: the motor
gets `cmd + offset`, motion gets `fb - offset` back and never sees it),
ramped in at 2 mm/s by a `limit2` clamped to `±max_adjust`:

```hal
loadrt offset names=ztilt-0,ztilt-1,ztilt-2
loadrt limit2 names=ztilt-ramp-0,ztilt-ramp-1,ztilt-ramp-2
addf ztilt-0.update-feedback servo-thread   # after remora.read, before motion
addf ztilt-ramp-0 servo-thread              # after motion, before remora.write
addf ztilt-0.update-output servo-thread
setp ztilt-ramp-0.maxv 2
setp ztilt-ramp-0.min -5
setp ztilt-ramp-0.max 5
net j2pos-cmd joint.2.motor-pos-cmd => ztilt-0.in
net j2pos-cmd-tilt ztilt-0.out => remora.joint.2.pos-cmd
net j2pos-fb-raw remora.joint.2.pos-fb => ztilt-0.fb-in
net j2pos-fb ztilt-0.fb-out => joint.2.motor-pos-fb
net ztilt-0-offset ztilt-ramp-0.out => ztilt-0.offset
```

(`ZTiltHalMapper` rewrites the stepper mappers' two position nets per Z
joint, so a step/dir `stepgen.N` machine gets the same splice.)

webgui_connections.hal — the machine backend's target per motor:

```hal
net ztilt-0-target webgui.ztilt-0 => ztilt-ramp-0.in
```

## 4. RUNTIME

`Z_TILT_ADJUST` — a line of its own in a `.macro` file or in the
`[homing_override]` routine, or `POST /api/v1/ztilt/adjust` (background;
`GET /api/v1/ztilt/status`). X, Y and Z must be homed. Per round:

1. `G90`, `G53 G0 Z<horizontal_move_z>`; per point `G53 G1 X Y F<speed>`,
   `G91 G38.2 Z-<horizontal_move_z − probe_min_z> F<probe_speed>` (relative: LinuxCNC allows `G53` only with `G0`/`G1`), `G90`, the height from
   `stat.probed_position`, back up to `horizontal_move_z`.
2. With `retries`: done once the heights are within `retry_tolerance`;
   stops if the spread grew (the pivots do not match the motors) or
   after the last retry.
3. Plane fit (a line when the points are on one); each motor's
   correction = plane height at its pivot − the mean of those heights,
   added to its offset (mean Z kept). Refused beyond `max_adjust`.
   Waits until the ramps reached the targets.

Every probed point (X, Y, height), each round's spread and the calculated
per-motor adjust are logged in the console under DEBUG; one INFO line
when it succeeded (rounds, final spread, motor offsets). The offsets live for the LinuxCNC
session; the motors keep their corrected positions physically after a
restart. If Z homes on the probe, home Z again afterwards:

```cfg
[homing_override]
gcode:
    G28
    Z_TILT_ADJUST
    G28 Z
```

## 5. VALIDATION

| Error | When |
|---|---|
| `MissingRequiredKeywordError` | no `z_positions` / `points`. |
| `InvalidValueError` | a line that is not `X, Y`; fewer than two points; `speed` / `probe_speed` / `max_adjust` not above 0; negative `horizontal_move_z` / `retry_tolerance` / `retries`; no `[probe]`; a Z axis with one motor; not one `z_positions` entry per Z motor; three+ motors with all points on one line. |
