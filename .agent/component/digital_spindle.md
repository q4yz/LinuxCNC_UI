## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `[spindle]` / `[spindle <identifier>]`

**Expected Syntax:**
```cfg
[spindle <identifier>]
    # --- Wiring: pins, exactly like every other component ---
    run_pin: string // Start/stop. On a VFD MCU this is a control bit, not a GPIO
    reverse_pin: string // (Optional) reverse direction; omit for one-way spindles
    speed_pin: string // Speed reference out (RPM or drive units — see rpm_scale)
    speed_fb_pin: string // (Optional) measured speed back from the drive
    at_speed_pin: string // (Optional) drive reports "reached commanded speed"
    fault_pin: string // (Optional) drive fault / trip
    is_connected_pin: string // (Optional) link/bus health — drive is answering
    error_count_pin: string // (Optional) cumulative comms/drive error counter
    # --- Limits and scaling ---
    max_rpm: integer // Maximum allowable RPM
    min_rpm: integer // Minimum RPM the drive will hold (0 if it stalls cleanly)
    rpm_scale: float // (Optional) drive units per RPM, default 1.0
    spindle_number: integer // (Optional) LinuxCNC spindle index, default 0
```

**One template, any transport.** A digital spindle declares *pins*
like a stepper or a heater does; the pin's `<mcu_id>:` prefix says
which controller carries it, and that MCU's router turns it into real
HAL. The spindle never mentions RS-485, Modbus, EtherCAT or `vfdmod` —
that knowledge belongs to the MCU template, which is the only place
that knows how a pin becomes a signal.

That is why this file replaces the earlier per-protocol pair
(`digital_spindle_rs485.md` + `digital_spindle_ethercat.md`): the
protocol split duplicated the MCU concept on the component, and made
the spindle the only component in the set that could not be routed.

```cfg
# The VFD is a controller — declare it as an MCU (mcu_vfd_rs485.md).
[mcu vfd0]
    type: vfd_rs485
    port: /dev/ttyUSB0
    address: 1

[spindle]
    run_pin:      vfd0:run-forward
    reverse_pin:  vfd0:run-reverse
    speed_pin:    vfd0:rpm-in
    speed_fb_pin: vfd0:rpm-out
    at_speed_pin: vfd0:at-speed
    is_connected_pin: vfd0:is-connected
    error_count_pin:  vfd0:error-count
    max_rpm: 24000
    min_rpm: 5000
```

The same spindle on an EtherCAT drive changes only the pin strings —
not this template, and not the compiler's spindle mapper:

```cfg
[spindle]
    run_pin:      ec0:vfd0.cia-controlword
    speed_pin:    ec0:vfd0.vl-target-velocity
    speed_fb_pin: ec0:vfd0.vl-velocity-actual
    max_rpm: 24000
    min_rpm: 5000
```

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "tools": [
    {
      "id": "spindle_digital_<identifier>",
      "name": "<identifier> (Digital)",
      "type": "spindle_digital",
      "ui_group": "Tools",
      "spindle_number": { "type": "integer", "value": "<parsed_value || 0>" },
      "min_rpm": { "type": "float", "value": "<parsed_value>" },
      "max_rpm": { "type": "float", "value": "<parsed_value>" },
      "parameters": {
        "run_pin": { "type": "string", "value": "<parsed_value>" },
        "reverse_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "speed_pin": { "type": "string", "value": "<parsed_value>" },
        "speed_fb_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "at_speed_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "fault_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "is_connected_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "error_count_pin": { "type": "string", "value": "<parsed_value || ''>" },
        "rpm_scale": { "type": "float", "value": "<parsed_value || 1.0>" }
      },
      "computed": {
        "reversible": { "type": "boolean", "formula": "reverse_pin != ''" },
        "has_feedback": { "type": "boolean", "formula": "speed_fb_pin != '' or at_speed_pin != ''" },
        "has_health": { "type": "boolean", "formula": "is_connected_pin != '' or error_count_pin != '' or fault_pin != ''" }
      }
    }
  ]
}
```

`type` stays `spindle_digital` whatever the transport — the UI backs
both with the same `SpindleDigitalPins` container. Nothing downstream
of `hardware.json` needs to know which bus is underneath.

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[SPINDLE_<spindle_number>]
MAX_FORWARD_VELOCITY = <max_rpm>
MIN_FORWARD_VELOCITY = <min_rpm>

[TRAJ]
SPINDLES = <count of spindle tools>
```

machine.hal — the transport-independent half. Everything here is the
same on RS-485, EtherCAT or anything added later; the MCU router
supplies the other half.
```hal
# Component: <id>
# Speed reference: RPM -> drive units. Emit the scale stage only when
# rpm_scale != 1.0; a 1:1 drive wires spindle.N.speed-out straight
# through.
loadrt scale names=scale-<id>-cmd
addf scale-<id>-cmd servo-thread
setp scale-<id>-cmd.gain <parameters.rpm_scale>

net spindle-speed-cmd spindle.<spindle_number>.speed-out => scale-<id>-cmd.in
net <id>-speed-out    scale-<id>-cmd.out          # -> speed_pin

# Run / direction.
net spindle-forward spindle.<spindle_number>.forward   # -> run_pin
net spindle-reverse spindle.<spindle_number>.reverse   # -> reverse_pin

# --- IF computed.has_feedback -------------------------------------
# Feedback: drive units -> RPM, then back into LinuxCNC.
loadrt scale names=scale-<id>-fb
addf scale-<id>-fb servo-thread
setp scale-<id>-fb.gain <1.0 / parameters.rpm_scale>

net <id>-speed-fb-raw => scale-<id>-fb.in            # <- speed_fb_pin
net spindle-speed-fb scale-<id>-fb.out => spindle.<spindle_number>.speed-in

# at_speed_pin wired -> use the drive's own bit:
net spindle-at-speed => spindle.<spindle_number>.at-speed
# speed_fb_pin only -> derive it inside a tolerance band:
loadrt near names=near-<id>-at-speed
addf near-<id>-at-speed servo-thread
setp near-<id>-at-speed.scale 1.02
setp near-<id>-at-speed.difference <min_rpm * 0.05>
net spindle-speed-cmd => near-<id>-at-speed.in1
net spindle-speed-fb  => near-<id>-at-speed.in2
net spindle-at-speed  near-<id>-at-speed.out => spindle.<spindle_number>.at-speed

# --- ELSE (no feedback at all) ------------------------------------
# Nothing drives at-speed, so every M3 would block forever.
setp spindle.<spindle_number>.at-speed true

# --- Health exports — one hardware-agnostic signal per declared pin,
# each routed independently. No signal is emitted for a pin the
# operator left unset; webgui_connections.hal only wires what exists.
# --- IF parameters.fault_pin ---
net <id>-fault          # <- fault_pin
# --- IF parameters.is_connected_pin ---
net <id>-is-connected   # <- is_connected_pin
# --- IF parameters.error_count_pin ---
net <id>-error-count    # <- error_count_pin
```

webgui_connections.hal
```hal
# UI Bindings for <id> — transport-independent. The exact pin list for
# this machine is in the generated catalog at the top of machine.hal.
net spindle-speed-cmd => webgui.TargetRpm
net spindle-forward   => webgui.spindle-forward
net spindle-reverse   => webgui.spindle-reverse

# --- IF computed.has_feedback ---
net spindle-speed-fb => webgui.rpm-out
net spindle-at-speed => webgui.spindle-at-speed
# --- ELSE: echo the command so the UI shows something coherent ---
net spindle-speed-cmd => webgui.rpm-out

# Operator override.
setp halui.spindle.0.override.direct-value true
setp halui.spindle.0.override.scale 0.01
net spindle-override webgui.override => halui.spindle.0.override.counts

# Drive health — each signal above only exists when the operator
# declared the matching pin, so each line here is independently
# optional. This was previously hardcoded to three "backend-*"
# signals that nothing ever drove (a dangling net) — declaring the
# pins is what makes this routable per-MCU instead of assuming
# vfdmod. Hold error-count at 0 when the pin is absent rather than
# leaving webgui.error-count unwired, so the UI reads "healthy"
# instead of "unknown".
# --- IF parameters.is_connected_pin ---
net <id>-is-connected => webgui.is-connected
# --- IF parameters.error_count_pin ---
net <id>-error-count => webgui.error-count
# --- ELSE ---
setp webgui.error-count 0
# --- IF parameters.fault_pin ---
net <id>-fault => webgui.last-error
```

> **VERIFY the halui override spelling** against the target LinuxCNC
> version — `halui.spindle.N.override.counts` vs `.count`, and the
> unindexed `halui.spindle-override.*` form on older releases.

## 4. ROUTING NOTES

The exports this component leaves for the MCU router:

| Signal | Direction | Bound from |
|---|---|---|
| `spindle-forward` | out | `run_pin` |
| `spindle-reverse` | out | `reverse_pin` (if present) |
| `<id>-speed-out` | out | `speed_pin` |
| `<id>-speed-fb-raw` | in | `speed_fb_pin` (if present) |
| `spindle-at-speed` | in | `at_speed_pin` (if present) |
| `<id>-fault` | in | `fault_pin` (if present) |
| `<id>-is-connected` | in | `is_connected_pin` (if present) |
| `<id>-error-count` | in | `error_count_pin` (if present) |

Validation:

* `E_UNKNOWN_MCU` — a spindle pin names an undeclared controller.
* `E_SPINDLE_NO_RUN_PIN` — no `run_pin`: nothing can start the spindle.
* `E_SPINDLE_NO_SPEED_PIN` — no `speed_pin` on a spindle whose
  `max_rpm != min_rpm`: the speed command has nowhere to go.
* `E_RPM_RANGE` — `min_rpm >= max_rpm`.
* `E_MULTIPLE_SPINDLES` — more than one tool claims the same
  `spindle_number`; additional spindles need distinct indices and
  `[TRAJ] SPINDLES = N`.
* `W_NO_SPINDLE_FEEDBACK` — neither `speed_fb_pin` nor `at_speed_pin`:
  `at-speed` is forced true, so G-code starts cutting before the
  spindle has spun up. Add a dwell in the tool-change macro.
* `W_NO_SPINDLE_HEALTH` — none of `fault_pin` / `is_connected_pin` /
  `error_count_pin` set on a spindle whose MCU is a fieldbus/serial
  transport (not `dummy`): a dropped VFD link looks identical to a
  healthy, idle spindle in the UI.
