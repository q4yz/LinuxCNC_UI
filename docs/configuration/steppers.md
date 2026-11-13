# Steppers and homing

One `[stepper_<axis>]` per motor: `stepper_x`, `stepper_y`, `stepper_z`; a second motor on an
axis is `stepper_y1`, `stepper_z1`, … (a gantry or several Z motors).

```ini
[stepper_x]
step_pin: PF12
dir_pin: PF11
enable_pin: !PB3
microsteps: 8
rotation_distance: 40
full_steps_per_rotation: 200   # 400 for a 0.9° motor
endstop_pin: ^PF3
position_min: 0
position_endstop: 250
position_max: 250
homing_speed: 25               # (optional) mm/s
second_homing_speed: 5         # (optional) mm/s, the slow second touch
homing_retract_dist: 5         # (optional) mm
homing_positive_dir: true      # (optional)
gear_ratio: 50:17              # (optional) only with a gearbox
```

## Steps per mm

LinuxCNC's `SCALE` (steps per mm) is

```text
SCALE = microsteps × full_steps_per_rotation × gear_ratio / rotation_distance
```

- `rotation_distance` — mm the axis moves per turn: per **motor** turn without a gearbox, per
  **output** turn with one.
- `gear_ratio` — `50:17` means 50 motor turns per 17 output turns; chained stages as
  `80:16, 3:1`. Leave it out on a belt or leadscrew driven straight by the motor — setting it
  there makes every move too short.
- A `!` on `dir_pin` reverses the axis (a negative `SCALE`).

## Homing

| Key | Effect | Default |
|-----|--------|---------|
| `position_endstop` | where the switch is | — |
| `homing_speed` | search speed (`HOME_SEARCH_VEL`) | 10 mm/s |
| `second_homing_speed` | the slow second touch (`HOME_LATCH_VEL`) | `homing_speed` |
| `homing_retract_dist` | after homing, the axis moves this far off the switch (`HOME`) | 5 mm |
| `homing_positive_dir` | home towards + | from which end of travel `position_endstop` is at |

A gantry motor (`stepper_y1`) without its own keys uses the axis's first stepper's.

**Z on the probe** — `endstop_pin: probe:z_virtual_endstop` homes Z on the probe; see
{doc}`probe`.

**A homing routine** — `[homing_override]` replaces the plain homing order, e.g. to lift Z and
move to the bed centre before homing Z; see {doc}`levelling`.
