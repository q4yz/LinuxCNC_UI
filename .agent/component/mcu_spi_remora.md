## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `mcu <identifier>`

**Expected Syntax:**
```cfg
[mcu <identifier>]
    type: string // Must be "remora-spi"
    board: string // Firmware target, e.g. "BIGTREETECH OCTOPUS" / "SKR v1.4"
    spi_clk_div: integer // (Optional) SPI clock divider, default 64
    chip: string // (Optional) "stm32" | "lpc17xx" — selects the component variant
    servo_period: integer // (Optional) ns per servo cycle, default 1000000
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

```json
{"mcus": [{
  "id": "mcu_<identifier>",
  "type": "remora-spi",
  "ui_group": "Controllers",
  "capability_class": "B",
  "is_remora": true,
  "parameters": {
    "board": { "type": "string", "value": "<parsed_value>" },
    "spi_clk_div": { "type": "integer", "value": "<parsed_value || 64>" },
    "chip": { "type": "string", "value": "<parsed_value || 'stm32'>" },
    "servo_period": { "type": "integer", "value": "<parsed_value || 1000000>" }
  },
  "computed": {
    "component": { "type": "string", "formula": "chip == 'lpc17xx' ? 'remora_lpc' : 'remora-spi'" },
    "joint_count": { "type": "integer", "formula": "count(joints where joint.mcu_id == this.id)" },
    "firmware_config": { "type": "object", "formula": "see § 4 — the board-side config.txt" }
  }
}]}
```

The repo's own example machine is this shape —
`machine_config/machines/example/configs/hardware.json` carries
`"hal_type": "remora"`, `"connection": "remora-spi"`, `"is_remora": true`.

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
# Optional per-joint tuning, emit only when the cfg supplies them:
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

### Joint pins → `config.txt`, nothing in HAL

```json
{
  "Thread": { "Base": { "Frequency": 40000 }, "Servo": { "Frequency": 1000 } },
  "Modules": [
    {
      "Thread": "Base", "Type": "Stepper",
      "Comment": "<joints.id>",
      "Joint Number": <joints.joint_number>,
      "Step Pin": "<pin_id of step_pin>",
      "Direction Pin": "<'!' if invert else ''><pin_id of dir_pin>",
      "Enable Pin": "<'!' if invert else ''><pin_id of enable_pin>"
    }
  ]
}
```

### Digital input (endstop, probe, filament sensor) → `remora.input.NN`

The board exposes inputs as an indexed, **zero-padded two-digit** bank.
The router assigns the index in declaration order:

```hal
# Auto-Routed: <axes.id> home switch <- <mcu_id> pin <pin_id> (input <NN>)
net <axes.id>-home-sw remora.input.<NN> => joint.<n>.home-sw-in joint.<n>.neg-lim-sw-in
```

```json
{ "Thread": "Servo", "Type": "DigitalPin", "Comment": "<axes.id> home",
  "Pin": "<'^' if pullup else ''><pin_id>", "Mode": "Input", "Data Bit": <NN> }
```

Inversion is a firmware-side flag on the pin string, not a HAL `-not`
twin — put the `!` in `config.txt`.

### Analog / PWM output (heater, fan, laser) → `remora.SP.N`

`SP` = setpoint. The board owns the PWM, so a PID's 0–100 % output is
sent as a number and never needs a `pwmgen`:

```hal
# Auto-Routed: <owner.id> <field> -> <mcu_id> pin <pin_id> (SP <N>)
net <owner.id>-heater-SP => remora.SP.<N>
```

### Analog input (thermistor) → `remora.PV.N`

`PV` = process variable:

```hal
# Auto-Routed: <sensor.id> <- <mcu_id> pin <pin_id> (PV <N>)
net <sensor.id>-PV <= remora.PV.<N>
```

### Skew

Because HAL sees an **index** while `config.txt` names the **port**,
the two files must come from one allocation pass. Regenerating either
alone silently mis-wires the machine: `E_FIRMWARE_HAL_SKEW`. Record the
allocation in `hardware.json` (`mcus[].computed.firmware_config`) so
the skew is detectable.

`~` (pull-down) has no `DigitalPin` equivalent on most targets →
`E_MODIFIER_UNSUPPORTED`.
