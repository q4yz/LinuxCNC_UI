## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `mcu <identifier>`

**Expected Syntax:**
```cfg
[mcu <identifier>]
    connection: string // Must be "usb_arduino"
    serial: string // Device path, e.g. "/dev/ttyACM0" or a by-id path
    baud: integer // (Optional) default 115200
    board: string // (Optional) "uno" | "mega2560" | "nano" — sets the pin count
    poll_period: integer // (Optional) ms between polls, default 20
```

**Prefer a stable device path.** `/dev/ttyACM0` renumbers when another
USB serial device enumerates first; `/dev/serial/by-id/usb-Arduino...`
does not. A compiler should emit `W_UNSTABLE_SERIAL_PATH` for a bare
`ttyACM*` / `ttyUSB*`.

## 2. UI ABSTRACTION (hardware.json)

```json
{"mcus": [{
  "id": "mcu_<identifier>",
  "type": "usb_arduino",
  "ui_group": "Controllers",
  "capability_class": "C",
  "realtime": false,
  "parameters": {
    "serial": { "type": "string", "value": "<parsed_value>" },
    "baud": { "type": "integer", "value": "<parsed_value || 115200>" },
    "board": { "type": "string", "value": "<parsed_value || 'uno'>" },
    "poll_period": { "type": "integer", "value": "<parsed_value || 20>" }
  },
  "computed": {
    "digital_pin_count": { "type": "integer", "formula": "board == 'mega2560' ? 54 : 14" },
    "analog_pin_count": { "type": "integer", "formula": "board == 'mega2560' ? 16 : 6" }
  }
}]}
```

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
# Contributes no timing. A class C MCU never defines BASE_PERIOD, and
# must not be the only MCU on a machine that has joints.
```

machine.hal
```hal
# Component: <id>
# Userspace serial bridge. -W blocks until its pins exist, so the
# net lines below (and the router's) cannot race the handshake.
loadusr -W arduino-connector -d <parameters.serial> -b <parameters.baud>

# No addf: a userspace component is not in a realtime thread. It
# updates at its own poll rate (<parameters.poll_period> ms), which is
# why nothing safety-critical may live here — see § 4.
```

webgui_connections.hal
```hal
# UI Bindings for <id> — surface link health if the machine's webgui
# build exposes a connection pin for it:
#   net arduino-link-ok arduino.connected => webgui.is-connected
```

> **VERIFY: pick the bridge component before generating.** There is no
> single canonical Arduino-over-USB HAL component in LinuxCNC. The
> common choices — `arduino-connector`, a Firmata bridge, or a
> hand-written `hal.component` Python script — each use a different
> executable name *and* a different pin namespace (`arduino.dpin.N`
> vs `arduino.pin-N` vs a custom prefix). Fix the choice in this
> template's § 4 before the compiler emits anything, and confirm with
> `halcmd show pin arduino*`.

## 4. PIN ROUTER (Class C — I/O only)

**Hard rule first.** This MCU cannot carry motion. If any
`joints[].step_pin` / `dir_pin` / `enable_pin` resolves here, fail with
`E_MOTION_ON_IO_MCU` (`README.md` § 3). USB serial has milliseconds of
jitter and no realtime guarantee; step pulses generated across it would
lose position silently. There is no flag to override this — the fix is
a different MCU.

The same reasoning bars it from anything that must react within a
servo cycle:

| Signal | Allowed here? |
|---|---|
| step / dir / enable | **No** — `E_MOTION_ON_IO_MCU` |
| E-stop chain | **No** — `E_SAFETY_ON_IO_MCU`. An E-stop must be a hardware chain that also drops power without software; at most mirror its *state* here for display. |
| Limit / home switch | Discouraged — `W_SLOW_ENDSTOP`. Homing accuracy becomes poll-rate bound (±`poll_period` × feed rate). Acceptable for a probe-less hobby setup, not for a machine that homes against hard stops. |
| Buttons, lamps, relays, coolant, non-critical sensors | Yes |

`<pin_id>` grammar for this MCU: `d<N>` for a digital pin, `a<N>` for
an analog input, matching the board's silkscreen (`d13`, `a0`).
Reject an index above `computed.digital_pin_count` /
`analog_pin_count` with `E_PIN_UNAVAILABLE`.

### Digital input (button, non-critical sensor)

```hal
# Auto-Routed: <owner.id> <field> <- <mcu_id> pin <pin_id>
net <owner.id>-<field> <= arduino.dpin.<N>-in
```

Inversion has no HAL-side parameter on a userspace bridge. Emit an
explicit `not`, so the `!` is never silently dropped:

```hal
# invert == true
loadrt not names=not-<owner.id>-<field>
addf not-<owner.id>-<field> servo-thread
net <owner.id>-<field>-raw arduino.dpin.<N>-in => not-<owner.id>-<field>.in
net <owner.id>-<field>     not-<owner.id>-<field>.out
```

`^` / `~` map to the board's internal pull-up (`INPUT_PULLUP`); a
pull-down has no AVR equivalent → `E_MODIFIER_UNSUPPORTED` for `~`.
The pull-up is a bridge-side configuration, not a HAL pin — record it
in the bridge's own config, the same skew concern as
`mcu_spi_remora.md` § 4.

### Digital output (lamp, relay, coolant)

```hal
# Auto-Routed: <owner.id> <field> -> <mcu_id> pin <pin_id>
net <owner.id>-<field> => arduino.dpin.<N>-out
```

### Analog input (non-critical temperature, potentiometer)

```hal
# Auto-Routed: <owner.id> <field> <- <mcu_id> pin <pin_id>
net <owner.id>-<field> <= arduino.apin.<N>-in
```

A thermistor read through this path is display-only. Routing a
`tools[].sensor` here while the matching `heater_pin` drives a real
heater is `E_SLOW_SENSOR_ON_CONTROL_LOOP`: the PID would run on
20 ms-stale data with no fault detection if the USB link drops.
