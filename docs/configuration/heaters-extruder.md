# Heaters and the extruder

## Heaters

`[extruder]`, `[heater_bed]` and `[heater_generic <name>]` share the heater keys:

```ini
[heater_bed]
heater_pin: PA1
sensor_type: Generic 3950
sensor_pin: PF3
control: pid          # or watermark
pid_Kp: 54.0
pid_Ki: 0.8
pid_Kd: 900
min_temp: 0
max_temp: 120
max_power: 0.8        # (optional) 0.0 … 1.0, default 1.0
```

- `max_temp` is the highest target the heater accepts.
- `max_power` caps the heater's output — `0.8` is at most 80 % (Klipper's meaning), e.g. for
  an undersized bed MOSFET.
- `min_temp` is the sensor's lower fault limit, not a minimum target.

## The extruder

The extruder is a heater plus a motor. LinuxCNC has no E axis: the extruder is the **A axis**,
and uploaded G-code is converted from `E` to `A` (see {doc}`../using/programs`).

```ini
[extruder]
step_pin: PE2
dir_pin: PE3
enable_pin: !PD4
microsteps: 16
rotation_distance: 22.68
gear_ratio: 50:10           # (optional) a geared extruder
full_steps_per_rotation: 200
nozzle_diameter: 0.4
filament_diameter: 1.75
heater_pin: PA2
sensor_type: Generic 3950
sensor_pin: PF4
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 280
max_power: 1.0
min_extrude_temp: 170       # (optional) default 170
```

## Cold-extrusion guard

Below `min_extrude_temp` the extruder must not move: cold filament strips in the drive gear.
The Remora `extruder` HAL component watches the extruder's commanded movement and the hotend
temperature; when the extruder is commanded to move (extrude or retract) for 50 ms while the
hotend is below `min_extrude_temp`, the program or MDI move is stopped (`halui.abort`) with

```text
extruder: extrude below minimum temp (23.5 < 170.0 C): stopped
```

Homing is ignored. Set `min_extrude_temp: 0` to switch the guard off. The component has to be
installed — see {doc}`../hardware/remora-components`.

## Marlin temperature and fan codes

`M104`, `M109`, `M140`, `M190`, `M106` and `M107` work in programs, macros and MDI — see
{doc}`../using/console-commands`.
