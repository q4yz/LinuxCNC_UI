## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below. 
**Component ID Format:** `mcu <identifier>`

**Expected Syntax:**
```cfg
 [mcu <identifier>] 
    connection: string // Must be "parallelport"
    interface: string // The port address, usually "0" or a hex value like "0x378"
    board: string // (Optional) never autofilled — HAL cares about the port, not the PCB name

```

**Timing keys are not ingested yet.** `step_time`, `step_space`,
`direction_hold`, `direction_setup`, `base_period_max_jitter`,
`direction` ("out"/"in") and `reset_time` describe real parport
behaviour but have no `[mcu]` schema keys today — the compiler uses
documented defaults (`StepperHalMapper`'s timing constants,
`reset-time 2500`). They land when per-MCU timing moves into the
schema; until then the parser rejects them with
`UndefinedKeywordError` (surfaced to the UI as the structured 400
envelope) rather than silently accepting values it cannot honour.
## 2. UI ABSTRACTION (hardware.json)

The implemented MCU record is flat (no `parameters` wrapper, no
`is_remora`-style derived flag — `connection` alone decides how every
router behaves, same as every other MCU type). `interface` is the
only field this router reads today; `direction` / `reset_time` /
`step_time` / `step_space` / `direction_hold` / `direction_setup` /
`base_period_max_jitter` are **not ingested yet** (§ 1's note) — the
router uses documented defaults for all of them until per-MCU parport
timing lands in the schema:

```json
{"mcus": [{
  "id": "<identifier>",
  "connection": "parallelport",
  "interface": "0",
  "board": null
}]}
```

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[EMCMOT]
# Not yet computed from real timing (see § 1) — the documented default.
BASE_PERIOD = 50000
SERVO_PERIOD = 1000000
```

machine.hal
```hal
# Component: <id>
# <interface> is the ingested port address; direction/reset-time are
# the documented defaults ("out" / 2500 ns) until § 1's timing keys land.
loadrt hal_parport cfg="<interface || '0'> out"
setp parport.0.reset-time 2500

# Thread Attachments (Must run in the high-speed base-thread)
addf parport.0.read base-thread
addf parport.0.write base-thread
addf parport.0.reset base-thread
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

`<mcu_index>` is always `0` — single-port only, the router never
addresses a second `hal_parport` instance. `<pin_id>` is zero-padded
to two digits (`2` → `02`) to match `parport.N.pin-NN-*`.

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
