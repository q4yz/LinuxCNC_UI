> **Implemented status:** `RemoraFirmwareConfigMapper`
> (`backend/system/services/halcompiler/components/
> RemoraFirmwareConfigMapper.py`) owns the `{"Board", "Modules"}` root
> shape — pulled out of `HalAssembler._render_firmware_configs`, which
> used to build it inline (the assembler decides *which* modules
> belong to *which* MCU; the firmware target's own JSON shape is a
> mapper's job, same as every other Remora-specific shape here).
> `RemoraRouterMapper.base_fragment()` emits the board's `"Reset Pin"`
> module when `reset_pin` is declared, and `route()`'s `ANALOG_IN`
> branch emits a real `"Temperature"` module (§ 4) when
> `temperature_sensors[].type` matches a known thermistor preset
> ("Generic 3950" — the standard NTC 100K B3950 curve, not fabricated)
> — an unrecognised or absent type stays the same honest gap as
> before. `hardware_json_generator.build_hardware_json` also now
> auto-populates `duplicate_pin_overrides` for every heater's own
> generator-created fan-shares-heater-pin case (`heater.md`'s
> `W_FAN_SHARES_HEATER_PIN`) — without it, `HalAssembler` (which never
> silently merges a physical-pin collision without explicit
> permission) emitted two independent `"PWM"` config.txt modules for
> one physical pin, a real firmware defect only surfaced by actually
> loading a real generated machine.

## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `mcu <identifier>`

**Expected Syntax:**
```cfg
[mcu <identifier>]
    connection: string // Must be "remora-spi" (the default when a bare [mcu] omits it)
    board: string // (Optional) firmware target, e.g. "BIGTREETECH OCTOPUS" / "SKR v1.4".
                   // Never autofilled — an absent board stays absent; HAL generation
                   // cares about protocols and device paths, not PCB names. Klipper
                   // needs a board to compile firmware; this HAL pipeline does not.
    interface: string // (Optional) transport selector, e.g. a spidev path
    servo_period: integer // (Optional) ns per servo cycle, default 1000000
    reset_pin: string // (Optional) the board's own reset GPIO. Real, not invented:
                        // every module in the reference config.txt is preceded by a
                        // "Reset Pin" module. Only valid on remora-spi/remora-eth.
```

**No step timing here.** Remora is capability class B (`README.md` § 2):
the MCU generates the step pulses itself from a position setpoint, so
LinuxCNC needs no `stepgen` and no base thread. Emitting `loadrt
stepgen` for a Remora machine is `E_UNNEEDED_STEPGEN`.

> Grounded in the working config at
> `machine_config/example/ender3/` (`ender3.hal`, `3Dprinter.hal`,
> `ender3.ini`) — a Remora SKR v1.4 printer. Pin names below are taken
> from it rather than from documentation.

## 2. UI ABSTRACTION (hardware.json)

The implemented MCU record is flat and keyed entirely off
`connection` — there is no `is_remora` flag (a boolean cannot scale
past two transport families; Mesa cards and EtherCAT would need a
third value). Optional keys appear only when the profile declared
them:

```json
{"mcus": [{
  "id": "<identifier>",
  "connection": "remora-spi",
  "board": "BIGTREETECH OCTOPUS"
}]}
```

The repo's own example machine is this shape —
`machine_config/machines/example/configs/hardware.json` carries
`"connection": "remora-spi"` (with `"board"` only when the profile
declared one).

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[EMCMOT]
EMCMOT = motmod
# Class B: the servo thread is the only thread. BASE_PERIOD must still
# be DECLARED (the standard loadrt line below references it) but set to
# 0 — that is what tells motmod not to create a base thread.
BASE_PERIOD = 0
SERVO_PERIOD = <parameters.servo_period>

[KINS]
JOINTS = <joint count, extruders included>
```

machine.hal
```hal
loadrt [KINS]KINEMATICS
loadrt [EMCMOT]EMCMOT base_period_nsec=[EMCMOT]BASE_PERIOD servo_period_nsec=[EMCMOT]SERVO_PERIOD num_joints=[KINS]JOINTS

# Component: <id>
loadrt <computed.component> SPI_clk_div=<parameters.spi_clk_div>

# ------------------------------------------------------------------
# E-STOP / LINK CHAIN
# ------------------------------------------------------------------
# The SPI link IS the watchdog: if the board stops answering,
# SPI-status drops and LinuxCNC faults. Wire all three.
net user-enable-out     <= iocontrol.0.user-enable-out     => remora.SPI-enable
net user-request-enable <= iocontrol.0.user-request-enable => remora.SPI-reset
net remora-status       <= remora.SPI-status               => iocontrol.0.emc-enable-in

# ------------------------------------------------------------------
# THREAD ATTACHMENT — order matters
# ------------------------------------------------------------------
addf remora.read            servo-thread
addf motion-command-handler servo-thread
addf motion-controller      servo-thread
addf remora.update-freq     servo-thread
addf remora.write           servo-thread

# ------------------------------------------------------------------
# JOINTS — position in, position out. No stepgen, no step/dir nets.
# Run this block for every joint on this MCU.
# ------------------------------------------------------------------
setp remora.joint.<joints.joint_number>.scale    [JOINT_<joints.joint_number>]SCALE
setp remora.joint.<joints.joint_number>.maxaccel [JOINT_<joints.joint_number>]STEPGEN_MAXACCEL
# Optional per-joint tuning, emitted only when the cfg supplies them
# (implemented — RemoraStepperHalMapper, ingested via `[stepper_*]`
# `deadband:` / `pgain:` keys):
#   setp remora.joint.<n>.pgain    [JOINT_<n>]PGAIN
#   setp remora.joint.<n>.deadband 0.005

net j<n>pos-cmd joint.<n>.motor-pos-cmd => remora.joint.<n>.pos-cmd
net j<n>pos-fb  remora.joint.<n>.pos-fb => joint.<n>.motor-pos-fb
net j<n>enable  joint.<n>.amp-enable-out => remora.joint.<n>.enable
```

Note `SCALE` lives on `remora.joint.N.scale`, not on a stepgen — the
board applies it. A negative `SCALE` reverses the axis, which is how
the reference config flips its extruder (`SCALE = -48.8638`).

webgui_connections.hal
```hal
# Link health, if the machine's webgui build exposes a connection pin:
#   net remora-status => webgui.is-connected
# A front-panel reset button, as the reference config wires it:
#   net PRUreset <= webgui.<button> => remora.PRU-reset
```

## 4. PIN ROUTER (Class B — position command)

**Joint pins never become HAL nets.** For a joint on this MCU,
`step_pin` / `dir_pin` / `enable_pin` are **firmware** values: they go
into the board's `config.txt` (a JSON document on its SD card), which
Remora reads at boot to build its motion modules. HAL only ever sees
`remora.joint.N.*`.

Sweep behaviour — `pin_id` here is an MCU-native port name (`PF13`,
`PE3`, `PC0`), not an index:

> **Every shape below is verified against the real, working**
> **`machine_config/example/ender3/config.txt`** — a config actually
> flashed to real Remora firmware, not generic Remora documentation.
> Where the two disagree, this file's own earlier draft was wrong and
> has been corrected to match the real config: the root object is
> `{"Board": ..., "Modules": [...]}` (**no** top-level `"Thread"`
> frequency block — Remora doesn't read one), every module carries a
> `"Name"` in addition to `"Comment"`, module `"Type"` strings are
> exact (`"Stepgen"`, not `"Stepper"`; `"Digital Pin"` **with the
> space**, not `"DigitalPin"`), and every STM32 pin is spelled with an
> underscore between the port letter and the number (`"PF_13"`, not
> Klipper's `"PF13"` — see `RemoraFirmwarePinMapper`). A temperature
> module's `"Sensor"` field is the flat **string** `"Thermistor"`
> (never the sensor's own type name, e.g. `"Generic 3950"`), with the
> actual curve nested one level down under `"Thermistor": {"Pin",
> "beta", "r0", "t0"}` — an earlier draft of this file claimed the
> opposite (`"Sensor": "Generic 3950"`, no nesting) before the real
> `config.txt` existed to check it against; that claim was wrong.

### The board's own reset pin → `config.txt`, nothing in HAL

MCU-intrinsic, emitted unconditionally by `RemoraRouterMapper.
base_fragment()` whenever `reset_pin` is declared — the same way the
SPI-enable/reset/status chain above it is, not something any routed
request triggers. Always the *first* module in the file (matches the
real reference exactly):

```json
{ "Name": "reset_pin", "Thread": "Servo", "Type": "Reset Pin",
  "Comment": "Reset pin", "Pin": "<firmware pin of reset_pin>" }
```

### Joint pins → `config.txt`, nothing in HAL

```json
{
  "Board": "<mcus[].board || 'BIGTREETECH OCTOPUS'>",
  "Modules": [
    {
      "Name": "<joints.id>",
      "Thread": "Base", "Type": "Stepgen",
      "Comment": "<joints.id> step generator",
      "Joint Number": <joints.joint_number>,
      "Step Pin": "<firmware pin of step_pin>",
      "Direction Pin": "<'!' if invert else ''><firmware pin of dir_pin>",
      "Enable Pin": "<'!' if invert else ''><firmware pin of enable_pin>"
    }
  ]
}
```

### TMC2209 UART tuning → `config.txt`, nothing in HAL

One module per joint whose `[tmc2209 ...]` driver declares a
`uart_pin` — firmware-only, exactly like the joint's own `Stepgen`
module:

```json
{
  "Name": "driver_<joints.id>", "Thread": "On load", "Type": "TMC2209",
  "Comment": "<joints.id> TMC driver",
  "RX pin": "<firmware pin of driver.uart_pin>",
  "RSense": "<driver.sense_resistor || 0.11>",
  "Current": "<round(driver.run_current * 1000) — amps in, milliamps out>",
  "Microsteps": "<driver.microsteps || 16>",
  "Stealth chop": "<'on' if driver.stealthchop_threshold else 'off'>",
  "Stall sensitivity": 0
}
```

`"Stealth chop"` is the **string** `"on"`/`"off"`, not a JSON boolean.
Only `"RX pin"` is declared — no `"TX pin"`, no `"Address"` — matching
this project's single-wire UART wiring and non-Modbus addressing;
don't add either field on the strength of generic TMC2209/Remora
advice that doesn't hold for this firmware target. `"Stall
sensitivity"` has no `.cfg` key yet — every reference module uses `0`.

### Digital input (endstop, probe, filament sensor) → `remora.input.NN`

The board exposes inputs as an indexed, **zero-padded two-digit** bank.
The router assigns the index in declaration order, scoped to this
role alone — an interleaved heater/spindle request must never shift
an endstop's index (`E_FIRMWARE_HAL_SKEW` below is exactly this bug
class):

```hal
# Auto-Routed: <axes.id> home switch <- <mcu_id> pin <pin_id> (input <NN>)
net <axes.id>-home-sw remora.input.<NN> => joint.<n>.home-sw-in joint.<n>.neg-lim-sw-in
```

```json
{ "Name": "endstop_<axes.id>", "Thread": "Servo", "Type": "Digital Pin",
  "Comment": "<axes.id> home",
  "Pin": "<'^' if pullup else ''><firmware pin of pin_id>",
  "Mode": "Input", "Data Bit": <NN> }
```

Inversion is a firmware-side flag on the pin string, not a HAL `-not`
twin — put the `!` in `config.txt`.

### Analog / PWM output (heater, fan, laser) → `remora.SP.N`

`SP` = setpoint. The board owns the PWM, so a PID's 0–100 % output is
sent as a number and never needs a `pwmgen`. Each request also gets a
`config.txt` module — the board has to know which physical pin `SP.N`
drives:

```hal
# Auto-Routed: <owner.id> <field> -> <mcu_id> pin <pin_id> (SP <N>)
net <owner.id>-heater-SP => remora.SP.<N>
```

```json
{ "Name": "pwm_<owner.id>", "Thread": "Servo", "Type": "PWM",
  "Comment": "<owner.id>", "SP[i]": <N>, "PWM Pin": "<firmware pin of pin_id>" }
```

A heater's own auto-derived "fan" (`heater.md`'s `W_FAN_SHARES_HEATER_PIN`
— every generated machine with a `heater_pin` has one, real but the
compiler's own doing, not the operator's) always shares that exact
pin. `HalAssembler` never silently merges a physical-pin collision
without explicit permission (`[duplicate_pin_override]`) — so
`build_hardware_json` auto-populates that permission itself for this
one, compiler-created case, collapsing the heater's own PID output and
its placeholder fan onto one signal, one `SP.N`, one `"PWM"` module.
Without this a heater with no real declared cooling fan got **two**
independent PWM modules on the same physical pin — invalid firmware,
not a cosmetic duplicate.

### Analog input (thermistor) → `remora.PV.N`

`PV` = process variable:

```hal
# Auto-Routed: <sensor.id> <- <mcu_id> pin <pin_id> (PV <N>)
net <sensor.id>-PV <= remora.PV.<N>
```

The matching `config.txt` `"Temperature"` module is emitted when
`temperature_sensors[].type` matches a known thermistor preset:

```json
{ "Name": "temp_<sensor.id>", "Thread": "Servo", "Type": "Temperature",
  "Comment": "<sensor.id>", "PV[i]": <N>, "Sensor": "Thermistor",
  "Thermistor": { "Pin": "<firmware pin of pin_id>",
                  "beta": <curve.beta>, "r0": <curve.r0>, "t0": <curve.t0> } }
```

Curve lookup (`RemoraRouterMapper._THERMISTOR_CURVES`, case-insensitive):

| `temperature_sensors[].type` | beta | r0 (Ω) | t0 (°C) |
|---|---|---|---|
| `"Generic 3950"` | 3950 | 100000 | 25 |

Verified against the real `config.txt`'s `temp_extruder`/`temp_bed`
modules — this is the standard NTC 100K B3950 curve Klipper/Marlin
ship as their own default, not a fabricated number. An unrecognised
(or absent) `type` stays an honest gap: no module, since a guessed
curve would silently misreport real temperatures — the HAL `net` line
above is still emitted either way. Extending the table to a new
thermistor type is a one-line addition once its curve is verified
against real hardware.

### Skew

Because HAL sees an **index** while `config.txt` names the **port**,
the two files must come from one allocation pass — this compiler's
assembler is that one pass (`HalAssembler._render_firmware_configs`),
not two independent generators. Regenerating either file alone (by
hand, or from a stale intermediate) silently mis-wires the machine:
`E_FIRMWARE_HAL_SKEW`, not yet a validator rule.

`~` (pull-down) has no `Digital Pin` equivalent on most targets →
`E_MODIFIER_UNSUPPORTED`.
