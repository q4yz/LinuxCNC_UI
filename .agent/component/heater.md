> **Implemented status:** `HeaterHalMapper` emits the § 3 PID and
> watermark loops, the sensor `-PV` reading, and a referenced fan's
> `-SP` as a plain passthrough (matching the reference machine exactly
> — `ext0-cooling-SP => remora.SP.2`, no temperature gating). Routed
> today only through `RemoraRouterMapper` (`remora.SP.N`/`remora.PV.N`
> — class B). The watermark branch's `comp.out` (a HAL **bit**) is
> converted to a float via `conv_bit_float` + `scale` before it
> reaches `<id>-heater-SP` — linking a bit pin straight to
> `remora.SP.N` (a float) is a HAL load-time type error, not shown in
> the § 3 sketch above. `ini_template_generator` now writes the
> matching `[<SECTION>]PID_*` machine.ini block for every PID heater
> (`generate_machine_templates` — a real bug before this: the HAL side
> referenced an ini-var no file ever defined, so every gain silently
> resolved to nothing). `HeaterWebguiMapper` seeds `webgui_connections.hal`
> (first generation only — hand edits are preserved on regenerate) with the
> operator's target-temperature write into `<id>-SP`, the sensor's `-PV`
> reading (only when a sensor is set — no sensor means `HeaterHalMapper`
> creates no `-PV` signal to bind), and a referenced fan's `-SP` write
> keyed by the fan's own bare id (no suffix on the webgui side). Pin names
> verified against the real runtime consumer,
> `common/mappers/tools/HeaterMapper.py::from_dict_to_HeaterPins`
> (`suffix = tool_id.replace("heater", "")`). Not yet implemented: class A `pwmgen` staging
> (`E_PID_WITHOUT_PWM`), `E_NO_ANALOG_INPUT` on a parport-only machine,
> and `W_NO_RUNAWAY_GUARD`. A heater pin routed to an MCU with no
> analog handling is silently dropped by that router today rather than
> erroring — same "honest gap" class as `remora-eth`, not yet a
> validator rule.

## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `[heater_<identifier>]` — the `heater` prefix is
load-bearing, see § 2.

**Expected Syntax:**
```cfg
[heater_<identifier>]
    name: string // (Optional) operator-facing label, default = identifier
    type: string // "heater" | "heated_bed"
    sensor: string // id of the [temperature_sensor] that reads this heater
    heater_pin: string // Output driving the heater element (SSR / MOSFET)
    fan: string // (Optional) id of a [fan] used as the cooling fan
    control: string // "pid" | "watermark"
    min_temp: float // Lower bound, default 0.0
    max_temp: float // Upper bound — the setpoint is clamped to it
    pid_kp: float // (control: pid) proportional gain
    pid_ki: float // (control: pid) integral gain
    pid_kd: float // (control: pid) derivative gain
    pid_on_measurement: bool // (Optional) proportional-on-measurement, default true
    max_power: float // (Optional) 0-100 duty ceiling, default 100.0
    hysteresis: float // (control: watermark) degrees of dead band, default 2.0
```

```cfg
[temperature_sensor <identifier>]
    sensor_type: string // e.g. "EPCOS 100K B57560G104F", "PT1000", "thermocouple"
    sensor_pin: string // Analog input pin that reads it
    pullup_resistor: float // (Optional) ohms, default 4700
```

> Grounded in the working printer at `machine_config/example/ender3/`
> (`3Dprinter.hal`, `ender3.ini`) — a bed + one extruder on Remora.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "tools": [
    {
      "id": "heater_<identifier>",
      "name": "<parsed_name || identifier>",
      "type": "<heater | heated_bed>",
      "ui_group": "Tools",
      "sensor": "<parsed_sensor_id>",
      "heater_pin": "<parsed_value>",
      "fan": "<parsed_fan_id || null>",
      "control": "<pid | watermark>",
      "min_temp": 0.0,
      "max_temp": 250.0
    }
  ],
  "temperature_sensors": [
    { "id": "<identifier>", "pin": "<parsed_sensor_pin>", "type": "<sensor_type>" }
  ],
  "fans": [
    { "id": "fan_heater_<identifier>", "pin": "<parsed_fan_pin>" }
  ]
}
```

**The `heater` prefix in the id is load-bearing.** The app derives the
HAL pin suffix by stripping it —
`suffix = id.replace("heater", "")`, see
`backend/common/mappers/tools/HeaterMapper.py`:

| `tools[].id` | suffix | setpoint pin |
|---|---|---|
| `heater_bed` | `_bed` | `webgui.target-temperature_bed` |
| `heater_extruder_test` | `_extruder_test` | `webgui.target-temperature_extruder_test` |
| `bed_heater` | `bed_` | `webgui.target-temperaturebed_` ← malformed |

Only the **setpoint** is derived this way. The **reading** is not: a
heater carries its sensor, so `actual_temperature` resolves to
`webgui.<sensor_id>` — one pin per thermistor, addressed the same way
whether or not a heater claims it. The app enforces the pairing by
never building a separate sensor entity for a claimed sensor
(`TemperatureService.preload_hal_pins`, `pin_catalog`).

Emit `E_HEATER_ID_PREFIX` if the id does not start with `heater`, and
`E_HEATER_ID_COLLISION` if two heaters reduce to the same suffix.
`min_temp` / `max_temp` are static config constants — never wired,
they only bound the UI slider.

**A sensor's HAL identity is its id; its `pin` is wiring.** The two
must never be confused:

| Field | Meaning | Who consumes it |
|---|---|---|
| `temperature_sensors[].id` | The logical sensor. Becomes the HAL pin `webgui.<id>`. | The app (`TemperatureSensorMapper`), and any `net` line in `machine.hal`. |
| `temperature_sensors[].pin` | The **MCU** pin the thermistor is physically on (`"PA1"`). | **The compiler only** — it routes `webgui.<id>` to `<mcu>.<pin>` (§ 4). |

So sensor `bed` on `PA0` yields the HAL pin `webgui.bed`, and the
compiler emits the wiring that connects it to the board's ADC channel.
Re-plugging the thermistor changes `pin` and the generated route; it
never changes the HAL name the machine file is written against.

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
# One section per heater. Gains live here, not in the HAL file, so
# they can be retuned without regenerating. The section name is the
# tool's own id, uppercased (heater_ini_section — implemented, shared
# between HeaterHalMapper and ini_template_generator so the two can
# never name it differently) — NOT a LinuxCNC-style BED/EXT0
# abbreviation. Reads as "temperature control" generically, and is
# unique by construction for multiple heaters/extruders since
# tools[].id already has to be.
[<HEATER_SECTION>]           # e.g. [HEATER_BED], [HEATER_EXTRUDER]
PID_PONM  = <pid_on_measurement ? 1 : 0>  # not yet a Tool field — defaults to 1
PID_DIR   = 0                 # 0 = heating (raise output to raise PV)
PID_KP    = <parameters.pid_kp>
PID_KI    = <parameters.pid_ki>
PID_KD    = <parameters.pid_kd>
PID_SPMIN = <parameters.min_temp>
PID_SPMAX = <parameters.max_temp>
PID_CVMIN = 0.0
PID_CVMAX = <parameters.max_power>
```

`SPMAX` is the real safety bound: the PID cannot be commanded above it,
so a UI bug cannot ask for 400 °C. `CVMAX` caps duty cycle — lower it
for an undersized bed MOSFET.

machine.hal
```hal
# Component: <id>
# ------------------------------------------------------------------
# CONTROL LOOP — control: pid
# ------------------------------------------------------------------
# PIDcontroller ships with Remora and is the loop the reference
# printer uses. On a machine without it, LinuxCNC's built-in `pid`
# works the same way with different pin names (command/feedback/output
# instead of SP/PV/CV) — pick one and keep every heater consistent.
loadrt PIDcontroller names=PID-<id>
addf PID-<id>.compute servo-thread

setp PID-<id>.pOnM      [<HEATER_SECTION>]PID_PONM
setp PID-<id>.direction [<HEATER_SECTION>]PID_DIR
setp PID-<id>.KP        [<HEATER_SECTION>]PID_KP
setp PID-<id>.KI        [<HEATER_SECTION>]PID_KI
setp PID-<id>.KD        [<HEATER_SECTION>]PID_KD
setp PID-<id>.SPmin     [<HEATER_SECTION>]PID_SPMIN
setp PID-<id>.SPmax     [<HEATER_SECTION>]PID_SPMAX
setp PID-<id>.CVmin     [<HEATER_SECTION>]PID_CVMIN
setp PID-<id>.CVmax     [<HEATER_SECTION>]PID_CVMAX

# auto: hold the loop in manual until the link is up, so a dead MCU
# cannot leave the output latched at its last value.
net remora-status  => PID-<id>.auto
net <id>-SP        => PID-<id>.SP     # setpoint, from the UI
net <sensor.id>-PV => PID-<id>.PV     # reading, from the MCU
net <id>-heater-SP <= PID-<id>.CV     # duty cycle, to the MCU

# ------------------------------------------------------------------
# CONTROL LOOP — control: watermark (bang-bang)
# ------------------------------------------------------------------
# comp.out is a HAL BIT — <id>-heater-SP is routed straight into
# remora.SP.N, a FLOAT duty-cycle channel. Linking a bit pin to a
# float pin is a HAL load-time type error, so the bit is converted
# through conv_bit_float + scale before it reaches the exported
# signal, landing "on" at <parameters.max_power> percent (matching
# the PID branch's own CVmax convention).
loadrt comp names=comp-<id>
loadrt conv_bit_float names=conv-<id>
loadrt scale names=duty-<id>
addf comp-<id> servo-thread
addf conv-<id> servo-thread
addf duty-<id> servo-thread
setp comp-<id>.hyst <parameters.hysteresis>
setp duty-<id>.gain <parameters.max_power || 100.0>

net <sensor.id>-PV    => comp-<id>.in0
net <id>-SP           => comp-<id>.in1
net <id>-heat-bit     comp-<id>.out => conv-<id>.in
net <id>-heat-frac    conv-<id>.out => duty-<id>.in
net <id>-heater-SP <= duty-<id>.out

# ------------------------------------------------------------------
# HARDWARE-AGNOSTIC SIGNAL EXPORTS
# ------------------------------------------------------------------
# The MCU router binds these (README.md § 5):
#   <id>-heater-SP   -> heater_pin   (analog on class B, binary on class A)
#   <sensor.id>-PV   <- the sensor's pin
#   <fan.id>-SP      -> the referenced fan's pin
```

**Where the PWM lives decides what is valid.** On class B (Remora,
EtherCAT) the board owns the PWM: the PID's 0–100 % `CV` goes out as a
number (`remora.SP.N`) and everything works. On class A the router has
only a binary pin, so `control: pid` needs a `pwmgen` stage
(`analog_spindle.md` § 3) — without one, emit `E_PID_WITHOUT_PWM` and
tell the user to switch to `watermark`.

A parallel port also has **no ADC**, so a heater cannot be read at all
on a parport-only machine: `E_NO_ANALOG_INPUT`.

webgui_connections.hal
```hal
# UI Bindings for <id> — pin names carry the id suffix (§ 2). The
# generated catalog at the top of machine.hal lists this machine's
# exact names.

# Setpoint: the UI writes it, the loop reads it.
net <id>-SP <= webgui.target-temperature<suffix>

# Reading: ONE pin, named after the sensor. A heater does not own a
# second copy of its reading — it carries its sensor, so both the
# heater tool and the sensor entity resolve to `webgui.<sensor.id>`.
# (The app enforces this: a sensor a heater claims is never built as a
# separate entity — see TemperatureService.preload_hal_pins.)
net <sensor.id>-PV => webgui.<sensor.id>

# --- IF fan != null ---
net <fan.id>-SP <= webgui.<fan.id>
```

## 4. ROUTING NOTES

| Signal | Direction | Bound from |
|---|---|---|
| `<id>-heater-SP` | out | `heater_pin` |
| `<sensor.id>-PV` | in (analog) | `temperature_sensors[].pin` |
| `<fan.id>-SP` | out | the referenced `fans[].pin` |

**The sensor route has two halves**, because the reading has two
consumers — the control loop and the UI — and the UI's pin is named
after the sensor id, not the MCU pin (§ 2):

```hal
# 1. MCU -> signal. The router resolves temperature_sensors[].pin
#    ("PA1") against its MCU and emits that MCU's analog-input form.
#    Remora, from machine_config/example/ender3/3Dprinter.hal:
net <sensor.id>-PV <= remora.PV.<N>

# 2. Signal -> UI. One writer, two readers: the loop (heater.md § 3)
#    and the webgui pin, which is named for the sensor's id.
net <sensor.id>-PV => webgui.<sensor.id>
```

Never emit `net ... => webgui.<pin_id>` — `webgui.PA1` is not a pin the
component exposes. `E_SENSOR_PIN_AS_HAL_NAME` if a generator does.

Validation specific to heaters:

* `E_UNKNOWN_SENSOR` — `tools[].sensor` names no declared sensor.
* `E_SENSOR_SHARED` — two heaters name the same sensor. Each loop needs
  its own reading; sharing one silently couples them.
* `E_TEMP_RANGE` — `min_temp >= max_temp`.
* `E_NO_ANALOG_INPUT` — the sensor pin resolves to an MCU with no ADC
  (any parallel port).
* `E_PID_WITHOUT_PWM` — `control: pid` whose `heater_pin` resolves to a
  binary-only output with no `pwmgen` stage.
* `W_SLOW_SENSOR` — the sensor resolves to a class C MCU: the loop
  would run on poll-rate-stale data (`mcu_usb_arduino.md` § 4).
* `W_NO_RUNAWAY_GUARD` — neither `SPMAX` nor an independent cutout is
  set. `PID_SPMAX` bounds the *setpoint*; it does not catch a shorted
  SSR or a detached thermistor. A machine that can start a fire wants a
  `wcomp` on the reading gating the output as well.
