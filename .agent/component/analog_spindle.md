## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `[spindle_analog <identifier>]`

**Expected Syntax:**
```cfg
[spindle_analog <identifier>]
    max_rpm: integer // RPM at full-scale output
    min_rpm: integer // Lowest RPM the VFD will hold (0 if it stalls cleanly)
    pwm_pin: string // Output pin driving the 0-10 V converter
    enable_pin: string // (Optional) run/enable relay
    direction_pin: string // (Optional) reverse relay; omit for one-way spindles
    at_speed_pin: string // (Optional) VFD "at speed" input back to LinuxCNC
    pwm_frequency: float // (Optional) Hz, default 100.0
    scale: float // (Optional) RPM per unit output; default = max_rpm
    offset: float // (Optional) output at 0 RPM, for VFDs with a dead band
    spindle_number: integer // (Optional) LinuxCNC spindle index, default 0
```

**What "analog" means here:** LinuxCNC emits a PWM duty cycle,
an external filter/converter turns it into 0–10 V, and the VFD reads
that as a speed reference. There is no feedback path unless
`at_speed_pin` is wired — the controller is open-loop and cannot tell
whether the spindle actually reached the commanded speed.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "tools": [
    {
      "id": "spindle_analog_<identifier>",
      "name": "<identifier> (Analog)",
      "type": "spindle_analog",
      "ui_group": "Tools",
      "spindle_number": { "type": "integer", "value": "<parsed_value || 0>" },
      "min_rpm": { "type": "float", "value": "<parsed_value>" },
      "max_rpm": { "type": "float", "value": "<parsed_value>" },
      "parameters": {
        "pwm_pin": { "type": "string", "value": "<parsed_value>" },
        "enable_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "direction_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "at_speed_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "pwm_frequency": { "type": "float", "value": "<parsed_value || 100.0>" },
        "offset": { "type": "float", "value": "<parsed_value || 0.0>" }
      },
      "computed": {
        "scale": { "type": "float", "formula": "parsed_scale || max_rpm" },
        "has_feedback": { "type": "boolean", "formula": "at_speed_pin != ''" },
        "reversible": { "type": "boolean", "formula": "direction_pin != ''" }
      }
    }
  ]
}
```

The live example machine carries the matching shape already —
`{"id": "spindle_analog", "type": "spindle_analog", "min_rpm": 5000.0,
"max_rpm": 24000.0}` in
`machine_config/machines/example/configs/hardware.json`.

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[SPINDLE_<spindle_number>]
MAX_FORWARD_VELOCITY = <max_rpm>
MIN_FORWARD_VELOCITY = <min_rpm>

[TRAJ]
SPINDLES = <count of spindle tools>
```

machine.hal
```hal
# Component: <id>
# output_type=1 -> single PWM output pin (use 2 for PWM + direction).
loadrt pwmgen output_type=1
addf pwmgen.make-pulses base-thread
addf pwmgen.update      servo-thread

setp pwmgen.0.pwm-freq   <parameters.pwm_frequency>
setp pwmgen.0.scale      <computed.scale>
setp pwmgen.0.offset     <parameters.offset>
setp pwmgen.0.dither-pwm true

# Speed reference: commanded RPM in, duty cycle out.
net spindle-speed-cmd spindle.<spindle_number>.speed-out => pwmgen.0.value
net spindle-on        spindle.<spindle_number>.on        => pwmgen.0.enable

# ------------------------------------------------------------------
# HARDWARE-AGNOSTIC SIGNAL EXPORTS
# ------------------------------------------------------------------
# The MCU router binds these to physical pins (README.md § 5).
net spindle-pwm     <= pwmgen.0.pwm
net spindle-forward <= spindle.<spindle_number>.forward
net spindle-reverse <= spindle.<spindle_number>.reverse

# --- IF computed.has_feedback --------------------------------------
# Router drives this from at_speed_pin.
net spindle-at-speed => spindle.<spindle_number>.at-speed

# --- ELSE ----------------------------------------------------------
# No feedback wire: tell LinuxCNC the spindle is always "at speed",
# otherwise every M3 blocks forever waiting for a bit nothing drives.
# The trade-off is that G-code will start cutting before the spindle
# has spun up — set [SPINDLE_n] a dwell in the tool-change macro.
setp spindle.<spindle_number>.at-speed true
```

`pwmgen` needs a `base-thread`, so an analog spindle is only valid on a
class A machine (`README.md` § 2). On a class B MCU the drive takes a
speed word over the fieldbus instead — use
`digital_spindle.md` with a fieldbus pin; on Remora, use its own
PWM module.
Emit `E_PWM_WITHOUT_BASE_THREAD` if no base thread exists.

webgui_connections.hal
```hal
# UI Bindings for <id>
# Pin names below are the webgui component's real surface — see the
# generated pin catalog at the top of machine.hal for the exact list
# on this machine (backend/system/services/machinetemplates/pin_catalog.py).

# Commanded speed readout.
net spindle-speed-cmd => webgui.TargetRpm

# An analog spindle has no tachometer: echo the command as the
# "actual" reading so the UI shows something coherent, and leave
# rpm-out unwired if the machine's build prefers a blank field.
net spindle-speed-cmd => webgui.rpm-out

net spindle-forward => webgui.spindle-forward
net spindle-reverse => webgui.spindle-reverse

# --- IF computed.has_feedback ---
net spindle-at-speed => webgui.spindle-at-speed

# Operator override: webgui writes a scaled count, halui applies it.
setp halui.spindle.0.override.direct-value true
setp halui.spindle.0.override.scale 0.01
net spindle-override webgui.override => halui.spindle.0.override.counts
```

> **VERIFY the halui override spelling** against the target LinuxCNC
> version — `halui.spindle.N.override.counts` vs `.count`, and the
> unindexed `halui.spindle-override.*` form on older releases. The
> three lines above match the convention already used in
> `digital_spindle.md`; fix both files together if it turns out
> the target release disagrees.

## 4. ROUTING NOTES

The exports this component leaves for the MCU router:

| Signal | Direction | Bound from |
|---|---|---|
| `spindle-pwm` | out | `pwm_pin` |
| `spindle-on` | out | `enable_pin` (if present) |
| `spindle-reverse` | out | `direction_pin` (if present) |
| `spindle-at-speed` | in | `at_speed_pin` (if present) |

A `pwm_pin` routed to a parallel port lands on a plain binary output —
that is correct here, because `pwmgen` is what makes it a duty cycle;
the pin only ever carries the square wave. Do **not** let the router
insert an `-out-reset` on it (that is step-pulse behaviour and would
truncate every PWM period): `E_RESET_ON_PWM_PIN`.
