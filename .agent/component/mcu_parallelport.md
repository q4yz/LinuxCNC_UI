## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below. 
**Component ID Format:** `mcu <identifier>`

**Expected Syntax:**
```cfg
 [mcu <identifier>] 
    connection: string // Must be "parallelport"
    step_time: 5000 ns
    step_space: 5000 ns
    direction_hold: 20000 ns
    direction_setup: 20000 ns
    base_period_max_jitter: 15000 ns
    address: string // The port address, usually "0" or a hex value like "0x378"
    direction: string // "out" or "in" (typically "out" for CNC stepper control)
    reset_time: integer // Time in nanoseconds for pulse clearing (usually 2500)

```

## 2. UI ABSTRACTION (hardware.json)

```json
 {"mcus": [{
  "id": "mcu_<identifier>",
  "type": "parallelport",
  "ui_group": "Controllers",
  "parameters": {
    "address": { "type": "string", "value": "<parsed_value>" },
    "direction": { "type": "string", "value": "<parsed_value>" },
    "reset_time": { "type": "integer", "value": "<parsed_value>" },
    "step_time": { "type": "integer", "value": "<parsed_value>" },
    "step_space": { "type": "integer", "value": "<parsed_value>" },
    "direction_hold": { "type": "integer", "value": "<parsed_value>" },
    "direction_setup": { "type": "integer", "value": "<parsed_value>" },
    "base_period_max_jitter": { "type": "integer", "value": "<parsed_value>" }
  },
  "computed": {
    "cfg_string": { "type": "string", "formula": "address + ' ' + direction" },
    "port_index": { "type": "integer", "formula": "0" },
    "base_period": { "type": "integer", "formula": "base_period_max_jitter + max(step_time + step_space, direction_setup + direction_hold)" }
  }
}]}
```
## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[EMCMOT]
# The master high-speed thread timing based on the MCU's jitter and stepper driver limits
BASE_PERIOD = <computed.base_period>
SERVO_PERIOD = 1000000
```

machine.hal
```hal
# Component: <id>
loadrt hal_parport cfg="<computed.cfg_string>"
setp parport.<computed.port_index>.reset-time <parameters.reset_time>

# Thread Attachments (Must run in the high-speed base-thread)
addf parport.<computed.port_index>.read base-thread
addf parport.<computed.port_index>.write base-thread
addf parport.<computed.port_index>.reset base-thread
```
webgui_connections.hal
```hal
# No UI Bindings required for the core parallel port driver.
```

## 4. PIN ROUTER (Class A — step/dir realtime)

**Capability class:** A. Software `stepgen` makes the pulses; this MCU
is a dumb pin driver. See `README.md` § 2.

**Instruction:** After every hardware-agnostic component is generated,
sweep all pin-valued parameters (`step_pin`, `dir_pin`, `enable_pin`,
`endstop_pin`, `heater_pin`, fan pins, …). For each one:

1. Parse it with the § 1 grammar in `README.md` → `{mcu_id, pin_id, invert, …}`.
2. Skip it unless `mcu_id` resolves to *this* `parallelport` block.
3. Emit the matching template below, appended to the bottom of `machine.hal`.

`<mcu_index>` is `computed.port_index`. `<pin_id>` is zero-padded to
two digits (`2` → `02`) to match `parport.N.pin-NN-*`.

**Pin ranges — `E_PIN_UNAVAILABLE` if violated.** A parport in `out`
mode exposes: pins 1..9, 14, 16, 17 as outputs; pins 10..13, 15 as
inputs. Pins 18–25 are ground. (In `x` / bidirectional mode 2..9 flip
to inputs — a different, rarer wiring; reject it unless the compiler
grows explicit support.)

### `step_pin` → output, auto-reset

The `-out-reset` parameter is what makes one-cycle step pulses possible:
`parport.N.reset` (already added to the base-thread in § 3) clears the
pin `reset-time` ns after it was set.

```hal
# Auto-Routed: <joints.id> step -> <mcu_id> pin <pin_id>
net <joints.id>-step => parport.<mcu_index>.pin-<pin_id>-out
setp parport.<mcu_index>.pin-<pin_id>-out-reset 1
setp parport.<mcu_index>.pin-<pin_id>-out-invert <invert ? 1 : 0>
```

### `dir_pin` → output

```hal
# Auto-Routed: <joints.id> dir -> <mcu_id> pin <pin_id>
net <joints.id>-dir => parport.<mcu_index>.pin-<pin_id>-out
setp parport.<mcu_index>.pin-<pin_id>-out-invert <invert ? 1 : 0>
```

### `enable_pin` → output

```hal
# Auto-Routed: <joints.id> enable -> <mcu_id> pin <pin_id>
net <joints.id>-enable => parport.<mcu_index>.pin-<pin_id>-out
setp parport.<mcu_index>.pin-<pin_id>-out-invert <invert ? 1 : 0>
```

### `endstop_pin` → input

**Inversion works differently on inputs.** `parport.N.pin-NN-in-not` is
a second *pin* carrying the inverted level — it is NOT a settable
parameter. Select the pin, do not `setp` it:

```hal
# Auto-Routed: <axes.id> home switch <- <mcu_id> pin <pin_id>
# invert == false:
net <axes.id>-home-sw <= parport.<mcu_index>.pin-<pin_id>-in
# invert == true (NC switch / active-low sensor):
net <axes.id>-home-sw <= parport.<mcu_index>.pin-<pin_id>-in-not
```

A parport has no pull-ups: `^` / `~` modifiers on a parport pin are
`E_MODIFIER_UNSUPPORTED` — the pull resistor has to be physical.

### Generic digital output (heater, fan, relay, lamp)

```hal
# Auto-Routed: <owner.id> <field> -> <mcu_id> pin <pin_id>
net <owner.id>-<field> => parport.<mcu_index>.pin-<pin_id>-out
setp parport.<mcu_index>.pin-<pin_id>-out-invert <invert ? 1 : 0>
```

A parport pin is **binary only**. A `heater_pin` routed here is
bang-bang (`control: watermark`); a PID heater or a 0–10 V spindle
needs a `pwmgen` stage first — see `analog_spindle.md` § 3 — and the
router then binds `pwmgen.N.pwm` rather than the raw signal.
