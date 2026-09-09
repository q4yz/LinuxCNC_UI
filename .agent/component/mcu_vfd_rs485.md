## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `mcu <identifier>`

**Expected Syntax:**
```cfg
[mcu <identifier>]
    connection: string // Must be "vfd_rs485" ("rs485" is the legacy alias)
    interface: string // Serial device, e.g. "/dev/ttyUSB0" or a by-id path
    baud_rate: integer // (Optional) default 9600
    node_id: integer // (Optional) Modbus slave address, default 1
    parity: string // (Optional) "none" | "even" | "odd", default "none";
                   // single-letter N|E|O is accepted and normalised
```

The serial trio (`baud_rate` / `node_id` / `parity`) is only valid
on a `vfd_rs485` (or legacy `rs485`) MCU section — on any other
connection the parser rejects it as a typo
(`InvalidValueError`), because a baud rate on a parport is not a
tuning knob. Drive-specific Modbus register maps (`model`,
`rpm_in_register`, `rpm_out_register`) are **not ingested yet** —
the `vfd.ini` register lines stay empty until a `model` field lands.

**A VFD is a controller, so it is an MCU.** It sits on its own bus,
owns a set of addressable signals, and other components reach it by
naming its pins — exactly like a parallel port or a Remora board. It
just happens to carry a spindle instead of joints.

Modelling it this way is what lets `digital_spindle.md` be one
template: the spindle declares `run_pin: vfd0:run-forward` and this
router turns that into the real `vfdmod` pin. Nothing about Modbus
leaks into the spindle.

**Prefer a stable device path.** `/dev/ttyUSB0` renumbers when another
USB serial adapter enumerates first; `/dev/serial/by-id/...` does not.
Emit `W_UNSTABLE_SERIAL_PATH` for a bare `ttyUSB*` / `ttyACM*`.

## 2. UI ABSTRACTION (hardware.json)

The implemented MCU record is flat (no `parameters` wrapper, no
`is_remora` flag — `connection` alone decides how every router
behaves). Optional keys are present only when the profile declared
them:

```json
{"mcus": [{
  "id": "<identifier>",
  "connection": "vfd_rs485",
  "interface": "/dev/serial/by-id/usb-VFD0-if00-port0",
  "baud_rate": 9600,
  "node_id": 1,
  "parity": "none"
}]}
```

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
# A VFD contributes no timing. Class C: it never defines BASE_PERIOD,
# and it must not be the only MCU on a machine that has joints.
```

vfd.ini — a sidecar next to the INI and HAL. `vfdmod` reads it for the
serial settings and the drive's Modbus register map. The `[common]`
block comes straight off the ingested MCU fields (defaults 9600 / 1 /
none when undeclared); the register numbers are **drive-specific**
(see the vfdmod project's per-VFD examples) and stay empty until a
`model` field selects a register map.
```ini
[common]
address  = <node_id || 1>
port     = <interface>
baud     = <baud_rate || 9600>
parity   = <parity || 'none'>
databits = 8
stopbits = 1

[rpmIn]
address    = <rpm_in_register>   # drive-specific, not yet ingested
multiplier = 1
divider    = 1

[rpmOut]
address    = <rpm_out_register>  # drive-specific, not yet ingested
multiplier = 1
divider    = 1
```

machine.hal
```hal
# Component: <id>
# -W blocks until vfdmod's pins exist, so the router's net lines
# below cannot race the serial handshake.
loadusr -W vfdmod vfd_<id>.ini

# No addf: vfdmod is a userspace component polling the bus at its own
# rate. That is exactly why this MCU is class C — nothing safety- or
# motion-critical may depend on it.
```

webgui_connections.hal
```hal
# No UI bindings of its own — the spindle riding on this bus owns the
# operator-facing surface (digital_spindle.md). The health signals
# this router exports are consumed there.
```

> **VERIFY the pin names against your vfdmod build.** `vfdmod` is
> third-party; the `vfdmod.control.*` / `vfdmod.spindle.*` /
> `vfdmod.rs485.*` groupings below match the commonly-shipped build,
> but forks differ. Confirm with `halcmd show pin vfdmod*` before
> generating for real hardware.

## 4. PIN ROUTER (Class C — I/O only, one peripheral)

**Hard rule first.** A VFD link cannot carry motion. If any
`joints[].step_pin` / `dir_pin` / `enable_pin` resolves here, fail with
`E_MOTION_ON_IO_MCU` (`README.md` § 3). Modbus-over-serial has tens of
milliseconds of latency and no realtime guarantee. Likewise an E-stop:
`E_SAFETY_ON_IO_MCU` — an E-stop must drop power without software.

`<pin_id>` for this MCU is a **logical drive function**, not a GPIO
number. The router maps each to a `vfdmod` pin:

| `pin_id` | HAL pin | Direction |
|---|---|---|
| `run-forward` | `vfdmod.control.run-forward` | out |
| `run-reverse` | `vfdmod.control.run-reverse` | out |
| `rpm-in` | `vfdmod.control.rpm-in` | out (command *to* the drive) |
| `rpm-out` | `vfdmod.spindle.rpm-out` | in (measured speed) |
| `at-speed` | `vfdmod.spindle.at-speed` | in |
| `fault` | `vfdmod.rs485.last-error` | in |
| `is-connected` | `vfdmod.rs485.is-connected` | in |
| `error-count` | `vfdmod.rs485.error-count` | in |

Reject an unknown `pin_id` with `E_PIN_UNAVAILABLE` rather than
emitting a `net` against a pin `vfdmod` does not create — that fails
at HAL load with a far less obvious message.

### Output (run / direction / speed command)

```hal
# Auto-Routed: <owner.id> <field> -> <mcu_id>:<pin_id>
net <signal> => vfdmod.control.<pin_id>
```

### Input (speed feedback / at-speed / fault)

```hal
# Auto-Routed: <owner.id> <field> <- <mcu_id>:<pin_id>
net <signal> <= vfdmod.spindle.<pin_id>
```

`vfdmod` has no invert parameter. An inverted signal needs an explicit
`not` stage, so the `!` is never silently dropped:

```hal
loadrt not names=not-<owner.id>-<field>
addf not-<owner.id>-<field> servo-thread
net <signal>-raw vfdmod.<group>.<pin_id> => not-<owner.id>-<field>.in
net <signal>     not-<owner.id>-<field>.out
```

`^` / `~` are meaningless on a fieldbus → `E_MODIFIER_UNSUPPORTED`.

### Health (`is-connected` / `error-count` / `fault`)

No special case — these three route through the generic Input
template above exactly like `rpm-out` or `at-speed`, because they are
just ordinary pins on `vfdmod.rs485.*`. They are only wired when the
spindle declares `is_connected_pin` / `error_count_pin` / `fault_pin`
(`digital_spindle.md` § 1); nothing is emitted automatically.

This used to be a third, hardcoded section here that wrote
`net backend-is-connected => webgui.is-connected` directly — bypassing
pin declarations entirely, and with no signal ever driving
`backend-is-connected` in the first place (a dangling net). Declaring
these as ordinary pins is what fixed both problems at once: routing
now goes through one path for every signal, and the health surface is
opt-in like everything else instead of assumed present.

### One drive per MCU

`vfdmod` is loaded per configuration file and addresses one drive.
A second spindle needs a second `[mcu]` block (its own `vfd.ini`,
`loadusr` instance and component name) — `E_MULTIPLE_DRIVES_ON_ONE_VFD`
if two spindles route to the same `vfd_rs485` MCU.
