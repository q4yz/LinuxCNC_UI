## 1. INGESTION (Hand-Written CFG)

> **Filename note:** this file is `exturder.md` (transposed). The
> component is `extruder`. Rename when convenient — nothing references
> it by name yet.

> **Implemented status:** the motion half was already covered — an
> extruder's `[JOINT_N]`/`[AXIS_A]` compile through the same
> `RemoraStepperHalMapper`/`StepperHalMapper` any other joint does,
> since `hardware_json_generator` already emits it as an ordinary
> joint + axis. `HeaterHalMapper` now covers the thermal half too
> ("identical to `heater.md`" holds in code, not just in the spec).
> **Not implemented:** the § 3 cold-extrusion guard (`wcomp`/`and2`
> gating `enable-safe`) — an extruder's raw `j<n>enable` reaches the
> hardware unconditionally today, so this is a real safety gap versus
> what's documented here.

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `[extruder]` / `[extruder<index>]`, emitted as
`tools[].id = "heater_<identifier>"` — an extruder *is* a heater plus a
motion joint, so it inherits the heater id rule (`heater.md` § 2).

**Expected Syntax:**
```cfg
[extruder]
    # --- Motion (Klipper-style stepper fields) ---
    step_pin: string // The hardware pin (may include ! for invert)
    dir_pin: string // The hardware pin (may include ! for invert)
    enable_pin: string // The hardware pin (may include ! for invert)
    microsteps: integer // Microstepping multiplier
    rotation_distance: float // Filament mm per full motor revolution
    full_steps_per_rotation: integer // (Optional) default 200
    gear_ratio: string // (Optional) e.g. "50:17" for a geared extruder
    axis_letter: string // (Optional) LinuxCNC axis to expose it as, default "A"
    min_extrude_temp: float // (Optional) cold-extrusion guard, default 170.0
    filament_diameter: float // (Optional) mm, default 1.75, UI only
    nozzle_diameter: float // (Optional) mm, UI only
    # --- Heating (identical to [heater_*], see heater.md) ---
    sensor: string
    heater_pin: string
    fan: string // (Optional)
    control: string // "pid" | "watermark"
    min_temp: float
    max_temp: float
    pid_kp: float
    pid_ki: float
    pid_kd: float
```

An extruder spans two subsystems: it is a **heater** (`heater.md`) and
a **joint** (`stepper.md`). Parse once, emit into both. The thermal
half is `heater.md` verbatim and is not repeated here.

> Grounded in the working printer at `machine_config/example/ender3/`
> — extruder = `[JOINT_3]` + `[AXIS_A]`, PID via `PIDcontroller`.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "tools": [
    {
      "id": "heater_<identifier>",
      "name": "<identifier>",
      "type": "extruder",
      "ui_group": "Tools",
      "sensor": "<parsed_sensor_id>",
      "heater_pin": "<parsed_value>",
      "fan": "<parsed_fan_id || null>",
      "control": "pid",
      "min_temp": 0.0,
      "max_temp": 250.0,
      "position": "<hal_pin_name || '<tools.id>_position'>"
    }
  ],
  "axes": [
    {
      "id": "<axis_letter || 'a'>",
      "joint_numbers": ["<computed.joint_number>"],
      "is_extruder": true,
      "endstop": null,
      "position_min": -9999.0,
      "position_max": 999999999.0
    }
  ],
  "joints": [
    {
      "id": "extruder_<identifier>",
      "joint_number": "<computed.joint_number>",
      "is_extruder": true,
      "parameters": {
        "step_pin": { "type": "string", "value": "<parsed_value>" },
        "dir_pin": { "type": "string", "value": "<parsed_value>" },
        "enable_pin": { "type": "string", "value": "<parsed_value>" },
        "microsteps": { "type": "integer", "value": "<parsed_value>" },
        "rotation_distance": { "type": "float", "value": "<parsed_value>" },
        "full_steps_per_rotation": { "type": "integer", "value": "<parsed_value || 200>" },
        "gear_ratio": { "type": "string", "value": "<parsed_value || '1:1'>" }
      },
      "computed": {
        "gear_factor": { "type": "float", "formula": "gear_ratio.numerator / gear_ratio.denominator" },
        "scale": { "type": "float", "formula": "(full_steps_per_rotation * microsteps * gear_factor) / rotation_distance" }
      }
    }
  ]
}
```

**The extruder DOES get an axis.** LinuxCNC's G-code has no `E` word —
the reference printer exposes the extruder as **A** (`[AXIS_A]`,
`KINEMATICS = trivkins coordinates=XYZA`, `TRAJ COORDINATES = X Y Z A`)
and converts slicer output with `E` → `A` before running it (see
`ender3/gcode2ngc.py`). A joint with no axis is unreachable from
G-code: `E_EXTRUDER_NO_AXIS`.

`position` is the extruder's HAL feedback pin name. `ExtruderMapper`
defaults it to `f"{tool_id}_position"`, so `heater_extruder_test`
yields `webgui.heater_extruder_test_position`.

**Scale differs from a linear joint.** `stepper.md`'s formula is steps
per mm of *travel*; an extruder's is steps per mm of *filament*, and it
must include the gear reduction. A 50:17 geared extruder computed with
a 1:1 formula under-extrudes by ~3×. A negative scale reverses the
direction — the reference config uses `SCALE = -48.8638`.

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[KINS]
JOINTS = <total joint count, extruders included>
KINEMATICS = trivkins coordinates=<XYZ + axis_letter>

[TRAJ]
COORDINATES = <X Y Z + axis_letter>

# Unbounded travel: filament is continuous, there is nothing to hit.
[AXIS_<axis_letter>]
MAX_VELOCITY = 150.0
MAX_ACCELERATION = 2500.0
MIN_LIMIT = -9999.0
MAX_LIMIT = 999999999.0

[JOINT_<joint_number>]
TYPE = LINEAR              # filament advance is linear, not angular
SCALE = <computed.scale>
MIN_LIMIT = -9999.0
MAX_LIMIT = 999999999.0
MAX_VELOCITY = 160.0
MAX_ACCELERATION = 2500.0
STEPGEN_MAXACCEL = 3000.0
HOME = 0.0
HOME_OFFSET = 0.0
HOME_SEARCH_VEL = 0        # never homed — there is no endstop
HOME_LATCH_VEL = 0
HOME_SEQUENCE = 0

# Heater half — see heater.md § 3.
[EXT<index>]
PID_PONM = 1
PID_DIR  = 0
PID_KP   = <parameters.pid_kp>
PID_KI   = <parameters.pid_ki>
PID_KD   = <parameters.pid_kd>
PID_SPMIN = 0.0
PID_SPMAX = <parameters.max_temp>
PID_CVMIN = 0.0
PID_CVMAX = 100.0
```

Set `NO_FORCE_HOMING = 1` in `[TRAJ]` (as the reference does) or the
un-homeable extruder axis blocks the machine from ever going ready.

machine.hal
```hal
# Component: <id> — MOTION HALF
# Class B (Remora / EtherCAT) — the board owns the pulses:
setp remora.joint.<joint_number>.scale    [JOINT_<joint_number>]SCALE
setp remora.joint.<joint_number>.maxaccel [JOINT_<joint_number>]STEPGEN_MAXACCEL
setp remora.joint.<joint_number>.pgain    [JOINT_<joint_number>]PGAIN

net j<n>pos-cmd joint.<n>.motor-pos-cmd => remora.joint.<n>.pos-cmd
net j<n>pos-fb  remora.joint.<n>.pos-fb => joint.<n>.motor-pos-fb
net j<n>enable  joint.<n>.amp-enable-out => remora.joint.<n>.enable

# Class A (parport) — emit stepper.md's stepgen block instead, with
# this component's scale, and export step/dir/enable for the router.
# No <axis>-home-sw either way: an extruder is never homed.

# ------------------------------------------------------------------
# Component: <id> — THERMAL HALF
# ------------------------------------------------------------------
# Emit heater.md § 3 verbatim with this id, sensor and section name.
# An extruder is always `control: pid` in practice; watermark on a
# nozzle oscillates badly.

# ------------------------------------------------------------------
# COLD-EXTRUSION GUARD
# ------------------------------------------------------------------
# Extruding below ~170 C strips the filament and jams the drive gear.
# Gate the motor enable on the nozzle being up to temperature.
loadrt wcomp names=wcomp-<id>-hot
addf wcomp-<id>-hot servo-thread
setp wcomp-<id>-hot.min <parameters.min_extrude_temp || 170.0>
setp wcomp-<id>-hot.max <parameters.max_temp>
net <sensor.id>-PV  => wcomp-<id>-hot.in
net <id>-hot-enough <= wcomp-<id>-hot.out

loadrt and2 names=and-<id>-extrude-ok
addf and-<id>-extrude-ok servo-thread
net <id>-hot-enough    => and-<id>-extrude-ok.in0
net j<n>enable         => and-<id>-extrude-ok.in1
net <id>-enable-safe   <= and-<id>-extrude-ok.out
```

If the guard is emitted, the enable that reaches the hardware must be
`<id>-enable-safe`, not the raw `j<n>enable` — otherwise the guard is
wired but bypassed. On class B that means feeding
`remora.joint.<n>.enable` from the safe signal; on class A it is what
the router binds to `enable_pin`. `E_GUARD_BYPASSED` if both exist and
the raw one is the one connected.

webgui_connections.hal
```hal
# UI Bindings for <id>
# Thermal half — same pins as any heater (heater.md § 3). The setpoint
# is the tool's; the reading is the sensor's, one pin:
net <id>-SP <= webgui.target-temperature<suffix>
net <sensor.id>-PV => webgui.<sensor.id>

# Motion half — the UI's extrude/retract control reads position:
net j<n>pos-fb => webgui.<tools.id>_position
```

## 4. ROUTING NOTES

| Signal | Direction | Bound from |
|---|---|---|
| `<joints.id>-step` / `-dir` | out | `step_pin` / `dir_pin` (class A only) |
| `<id>-enable-safe` | out | `enable_pin` |
| `<id>-heater-SP` | out | `heater_pin` |
| `<sensor.id>-PV` | in (analog) | `temperature_sensors[].pin` — routed to `webgui.<sensor.id>`, see `heater.md` § 4 |

Validation specific to extruders:

* Inherits every rule in `heater.md` § 4 and every motion rule in
  `README.md` § 3.
* `E_EXTRUDER_NO_AXIS` — the extruder joint is in no `[AXIS_*]`
  section, so no G-code word can reach it.
* `E_EXTRUDER_AXIS_COLLISION` — `axis_letter` is already used by a
  Cartesian axis, or two extruders claim the same letter.
* `E_EXTRUDER_HOMED` — the joint carries an `endstop_pin`, or
  `HOME_SEARCH_VEL != 0`.
* `W_MISSING_GEAR_RATIO` — `rotation_distance` is set, `gear_ratio` is
  absent, and the resulting scale lands outside a plausible
  80–1000 steps/mm band. Usually a forgotten reduction.
* `W_NO_E_TRANSLATION` — the machine has an extruder axis but no
  post-processing step mapping slicer `E` words onto it.
