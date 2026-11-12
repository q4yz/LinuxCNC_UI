## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the Klipper-style stepper syntax.
**Component ID Format:** `[stepper_<axis><index>]` (e.g., `[stepper_x]`, `[stepper_y1]`). The base letter dictates the logical Axis, the presence of an index indicates a tandem/gantry Joint.

**Expected Syntax:**
```cfg
[stepper_<axis_id>]
step_pin: string // The hardware pin (may include ! for invert)
dir_pin: string // The hardware pin (may include ! for invert — becomes a negative SCALE in machine.ini, on every board)
enable_pin: string // The hardware pin (may include ! for invert)
microsteps: integer // Microstepping multiplier (e.g., 16)
rotation_distance: float // Millimeters traveled per full motor revolution
full_steps_per_rotation: integer // (Optional) Steps per rev, default 200
endstop_pin: string // (Optional on tandem joints) Endstop input pin
position_min: float // (Optional) Minimum limit, default 0.0
position_max: float // Maximum limit
position_endstop: float // Where the endstop is physically located
gear_ratio: string // (Optional) Klipper's "50:17" (motor turns : output turn), chained "80:16, 3:1"; rotation_distance is then per output turn
homing_speed: float // (Optional) mm/s, HOME_SEARCH_VEL, default 10
second_homing_speed: float // (Optional) mm/s, HOME_LATCH_VEL, default homing_speed
homing_retract_dist: float // (Optional) mm, HOME = position_endstop backed off by this, default 5
homing_positive_dir: bool // (Optional) home towards +; default from which end of travel position_endstop is at
```

Every `[stepper_*]` takes all of them (X, Y, Z, gantry motors; a gantry
motor without its own falls back to its axis's first stepper). A Z homed
on the probe uses `homing_speed` / `second_homing_speed` /
`homing_retract_dist` its own way (`probe.md`).

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "axes": [
    {
      "id": "<extracted_base_axis>", // e.g., "y"
      "joint_numbers": ["<computed.joint_number>"], // Array of assigned joints
      "endstop": "<parsed_endstop_pin>",
      "position_min": { "type": "float", "value": "<parsed_value || 0.0>" },
      "position_max": { "type": "float", "value": "<parsed_value>" },
      "position_endstop": { "type": "float", "value": "<parsed_value>" }
    }
  ],
  "joints": [
    {
      "id": "stepper_<axis_id>",
      "joint_number": "<computed.joint_number>", // Sequentially assigned: 0, 1, 2...
      "driver": "driver_stepper_<axis_id>",
      "parameters": {
        "step_pin": { "type": "string", "value": "<parsed_value>" },
        "dir_pin": { "type": "string", "value": "<parsed_value>" },
        "enable_pin": { "type": "string", "value": "<parsed_value>" },
        "microsteps": { "type": "integer", "value": "<parsed_value>" },
        "rotation_distance": { "type": "float", "value": "<parsed_value>" },
        "full_steps_per_rotation": { "type": "integer", "value": "<parsed_value || 200>" }
      },
      "computed": {
        "scale": { "type": "float", "formula": "(full_steps_per_rotation * microsteps * gear_ratio) / rotation_distance" }
      }
    }
  ]
}
```
## 3. COMPILATION (INI & HAL)

machine.ini
```ini
# Generate one for each item in the "axes" array
[AXIS_<axes.id:uppercase>]
MAX_LIMIT = <axes.position_max>
MIN_LIMIT = <axes.position_min>

# Generate one for each item in the "joints" array
[JOINT_<joints.joint_number>]
TYPE = LINEAR
SCALE = <microsteps * full_steps_per_rotation * gear_ratio / rotation_distance, negative for a ! dir_pin>
HOME = <position_endstop -/+ homing_retract_dist, away from the switch>
HOME_OFFSET = <parent_axis.position_endstop>
HOME_SEARCH_VEL = <±homing_speed, + with homing_positive_dir>
HOME_LATCH_VEL = <±second_homing_speed (default homing_speed), same sign>
MIN_LIMIT = <parent_axis.position_min>
MAX_LIMIT = <parent_axis.position_max>
STEPGEN_MAXACCEL = 0 # Calculate based on machine defaults
```

machine.hal
```hal
# Component: <joints.id> (Run this block for every joint)
setp stepgen.<joints.joint_number>.position-scale [JOINT_<joints.joint_number>]SCALE
setp stepgen.<joints.joint_number>.steplen 1
setp stepgen.<joints.joint_number>.stepspace 0
setp stepgen.<joints.joint_number>.dirhold 39000
setp stepgen.<joints.joint_number>.dirsetup 39000
setp stepgen.<joints.joint_number>.maxaccel [JOINT_<joints.joint_number>]STEPGEN_MAXACCEL

net <axes.id>pos-cmd joint.<joints.joint_number>.motor-pos-cmd => stepgen.<joints.joint_number>.position-cmd
net <axes.id>pos-fb stepgen.<joints.joint_number>.position-fb => joint.<joints.joint_number>.motor-pos-fb

# ------------------------------------------------------------------
# HARDWARE-AGNOSTIC SIGNAL EXPORTS
# ------------------------------------------------------------------
# Declare each signal exactly ONCE. The MCU router (§ 4 of the mcu_*
# template) adds the reader that binds it to a physical pin. A second
# `net <sig> <= ...` for the same signal is a HAL load error
# ("signal already has writer"), so these three lines are the only
# place step/dir/enable may be written.
net <joints.id>-step   <= stepgen.<joints.joint_number>.step
net <joints.id>-dir    <= stepgen.<joints.joint_number>.dir
net <joints.id>-enable joint.<joints.joint_number>.amp-enable-out => stepgen.<joints.joint_number>.enable

# ------------------------------------------------------------------
# ENDSTOP / HOME SWITCH SIGNAL
# ------------------------------------------------------------------
# We listen for a generic home signal. The MCU will route the physical pin here.
net <axes.id>-home-sw => joint.<joints.joint_number>.home-sw-in
```

> **Class A only.** The step/dir exports above assume software
> `stepgen` (`README.md` § 2). On a class B MCU (Remora, EtherCAT)
> there is no stepgen and no step/dir signal: emit the position-command
> binding from that MCU's template instead, and treat `step_pin` /
> `dir_pin` as firmware/slave config values.
webgui_connections.hal
```hal
# No UI Bindings required for the core axis.
```