## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `[spindle_digital <identifier>]`

**Expected Syntax:**
```cfg
[spindle_digital <identifier>]
    protocol: string // Must be "ethercat" (see digital_spindle_rs485.md for "vfdmod")
    mcu: string // Which [mcu] block (type: ethercat) carries this drive
    slave: string // Slave id on that bus, e.g. "vfd0"
    mode: string // (Optional) "csv" (cyclic velocity) | "vl" (velocity mode), default "csv"
    max_rpm: integer // Maximum allowable RPM
    min_rpm: integer // Minimum allowable RPM
    rpm_scale: float // (Optional) drive units per RPM, default 1.0
    accel_time: float // (Optional) seconds 0 -> max_rpm, mirrors the VFD ramp
    spindle_number: integer // (Optional) LinuxCNC spindle index, default 0
```

Same `[spindle_digital]` block as the RS485 variant — `protocol`
selects which template compiles it. Keep the two ingestion grammars
identical so a machine can switch buses by editing one word.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "tools": [
    {
      "id": "spindle_digital_<identifier>",
      "name": "<identifier> (Digital)",
      "type": "spindle_digital",
      "protocol": "ethercat",
      "ui_group": "Tools",
      "spindle_number": { "type": "integer", "value": "<parsed_value || 0>" },
      "min_rpm": { "type": "float", "value": "<parsed_value>" },
      "max_rpm": { "type": "float", "value": "<parsed_value>" },
      "parameters": {
        "mcu": { "type": "string", "value": "<parsed_value>" },
        "slave": { "type": "string", "value": "<parsed_value>" },
        "mode": { "type": "string", "value": "<parsed_value || 'csv'>" },
        "rpm_scale": { "type": "float", "value": "<parsed_value || 1.0>" },
        "accel_time": { "type": "float", "value": "<parsed_value || 0.0>" }
      },
      "computed": {
        "hal_prefix": { "type": "string", "formula": "'lcec.' + mcu.master + '.' + slave" },
        "has_feedback": { "type": "boolean", "formula": "true" }
      }
    }
  ]
}
```

`type` stays `spindle_digital` — the UI treats RS485 and EtherCAT
spindles identically (the app's `SpindleDigitalPins` container backs
both). Only `protocol` differs, and only the HAL layer cares.

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[SPINDLE_<spindle_number>]
MAX_FORWARD_VELOCITY = <max_rpm>
MIN_FORWARD_VELOCITY = <min_rpm>

[TRAJ]
SPINDLES = <count of spindle tools>
```

ethercat-conf.xml — the spindle is one more slave on the bus declared
by `mcu_ethercat.md` § 3. Append, do not emit a second master:
```xml
<slave idx="<slave.position>" type="generic"
       vid="<slave.vendor_id>" pid="<slave.product_code>"
       configPdos="true" name="<parameters.slave>">
  <syncManager idx="2" dir="out">
    <pdo idx="1600">
      <pdoEntry idx="6040" subIdx="00" bitLen="16" halPin="cia-controlword" halType="u32"/>
      <pdoEntry idx="6042" subIdx="00" bitLen="16" halPin="vl-target-velocity" halType="s32"/>
    </pdo>
  </syncManager>
  <syncManager idx="3" dir="in">
    <pdo idx="1a00">
      <pdoEntry idx="6041" subIdx="00" bitLen="16" halPin="cia-statusword" halType="u32"/>
      <pdoEntry idx="6044" subIdx="00" bitLen="16" halPin="vl-velocity-actual" halType="s32"/>
    </pdo>
  </syncManager>
</slave>
```

machine.hal
```hal
# Component: <id>
# The lcec master itself is loaded once by mcu_ethercat.md § 3 —
# this block only adds the spindle's own wiring.

# Speed reference: RPM -> drive units.
loadrt scale names=scale-<id>-cmd
addf scale-<id>-cmd servo-thread
setp scale-<id>-cmd.gain <parameters.rpm_scale>

net spindle-speed-cmd spindle.<spindle_number>.speed-out => scale-<id>-cmd.in
net <id>-vel-cmd scale-<id>-cmd.out => <computed.hal_prefix>.vl-target-velocity

# Feedback: drive units -> RPM.
loadrt scale names=scale-<id>-fb
addf scale-<id>-fb servo-thread
setp scale-<id>-fb.gain <1.0 / parameters.rpm_scale>

net <id>-vel-fb-raw <computed.hal_prefix>.vl-velocity-actual => scale-<id>-fb.in
net spindle-speed-fb scale-<id>-fb.out => spindle.<spindle_number>.speed-in

# Run/direction. A VL-mode drive takes a signed velocity, so reverse is
# the sign of the setpoint; the controlword only gates run/stop.
net spindle-on spindle.<spindle_number>.on => <computed.hal_prefix>.cia-controlword

# At-speed: compare command against feedback inside a tolerance band.
loadrt near names=near-<id>-at-speed
addf near-<id>-at-speed servo-thread
setp near-<id>-at-speed.scale 1.02
setp near-<id>-at-speed.difference <min_rpm * 0.05>

net spindle-speed-cmd => near-<id>-at-speed.in1
net spindle-speed-fb  => near-<id>-at-speed.in2
net spindle-at-speed  near-<id>-at-speed.out => spindle.<spindle_number>.at-speed
```

> **VERIFY the drive's profile.** The `6042` / `6044` object pair is
> CiA402 *velocity mode*; many VFDs expose vendor-specific objects
> instead, and servo-style spindles use `csv` (`60ff` target velocity)
> with a full CiA402 state machine — in which case load `cia402` the
> way `mcu_ethercat.md` § 3 does and drive `cia402.N.velo-cmd` rather
> than writing the controlword directly. Check the drive's ESI/manual
> for the PDO map before generating, and confirm the resulting pin
> names with `halcmd show pin lcec*`.

webgui_connections.hal
```hal
# ==========================================================
# UNIVERSAL DIGITAL SPINDLE LOGIC & UI
# ==========================================================
# Identical to digital_spindle_rs485.md — the UI surface does not
# depend on the bus. Keep these two blocks in sync.

# Web GUI override
setp halui.spindle.0.override.direct-value true
setp halui.spindle.0.override.scale 0.01
net spindle-override webgui.override => halui.spindle.0.override.counts

# Standard UI state feedback
net spindle-forward  spindle.0.forward => webgui.spindle-forward
net spindle-reverse  spindle.0.reverse => webgui.spindle-reverse
net spindle-speed-fb => webgui.rpm-out
net spindle-speed-cmd => webgui.TargetRpm
net spindle-at-speed => webgui.spindle-at-speed

# ==========================================================
# ETHERCAT DRIVER HEALTH
# ==========================================================
# The RS485 template sources these from vfdmod.rs485.*; on EtherCAT the
# equivalents come from the master and the drive's statusword.
net backend-is-connected lcec.<master>.slaves-responding => webgui.is-connected
net backend-error-count  lcec.<master>.<slave>.error-count => webgui.error-count
net backend-last-error   <computed.hal_prefix>.cia-statusword => webgui.last-error
```

> **VERIFY the health pins.** `lcec.<master>.slaves-responding` and a
> per-slave `error-count` are master-dependent; some builds expose
> `lcec.<master>.link-up` or nothing at all. If the build has no error
> counter, hold `webgui.error-count` at 0 (`setp`) rather than leaving
> it unwired, so the UI reads "healthy" instead of "unknown".

## 4. ROUTING NOTES

This spindle declares **no pin strings** — it names a `slave`, and the
EtherCAT router (`mcu_ethercat.md` § 4) resolves everything through the
bus. Consequently:

* `E_PIN_ON_FIELDBUS_SPINDLE` — a `pwm_pin` / `enable_pin` /
  `direction_pin` on an EtherCAT spindle is a config error; those exist
  only on the analog variant.
* `E_UNKNOWN_SLAVE` — `parameters.slave` must match an
  `[ethercat_slave]` block whose `mcu` is `parameters.mcu`.
* `E_MCU_CLASS_MISMATCH` — `parameters.mcu` must be `type: ethercat`.
