## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `mcu <identifier>`

**Expected Syntax:**
```cfg
[mcu <identifier>]
    connection: string // Must be "ethercat"
    master: integer // (Optional) EtherCAT master index, default 0
    servo_period: integer // (Optional) ns per servo cycle, default 1000000
    config_file: string // (Optional) slave XML path, default "ethercat-conf.xml"

# One block per slave on the bus. Position is the physical order.
[ethercat_slave <slave_id>]
    mcu: string // Which [mcu] this slave sits on
    position: integer // Ring position, 0-based
    vendor_id: string // Hex, e.g. "0x00000002"
    product_code: string // Hex, e.g. "0x044c2c52"
    type: string // "servo" | "din" | "dout" | "ain" | "aout"
    mode: string // (servo only) "csp" | "csv" | "cst"
```

An EtherCAT drive is capability class B (`README.md` § 2): it closes
its own position loop from a cyclic setpoint. No `stepgen`, no
`base-thread`.

## 2. UI ABSTRACTION (hardware.json)

```json
{"mcus": [{
  "id": "mcu_<identifier>",
  "type": "ethercat",
  "ui_group": "Controllers",
  "capability_class": "B",
  "parameters": {
    "master": { "type": "integer", "value": "<parsed_value || 0>" },
    "servo_period": { "type": "integer", "value": "<parsed_value || 1000000>" },
    "config_file": { "type": "string", "value": "<parsed_value || 'ethercat-conf.xml'>" }
  },
  "slaves": [
    {
      "id": "<slave_id>",
      "position": { "type": "integer", "value": "<parsed_value>" },
      "vendor_id": { "type": "string", "value": "<parsed_value>" },
      "product_code": { "type": "string", "value": "<parsed_value>" },
      "type": { "type": "string", "value": "<parsed_value>" },
      "mode": { "type": "string", "value": "<parsed_value || 'csp'>" }
    }
  ],
  "computed": {
    "hal_prefix": { "type": "string", "formula": "'lcec.' + master + '.' + slave.id" }
  }
}]}
```

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[EMCMOT]
# Class B: servo thread only, no BASE_PERIOD.
SERVO_PERIOD = <parameters.servo_period>
```

ethercat-conf.xml — a third artifact alongside the INI and HAL. `lcec`
reads it to map slaves onto PDOs, and the HAL pin names below only
exist because this file named them.
```xml
<masters>
  <master idx="<parameters.master>" appTimePeriod="<parameters.servo_period>" refClockSyncCycles="1">
    <!-- one per slave, in ring order -->
    <slave idx="<slave.position>"
           type="generic"
           vid="<slave.vendor_id>"
           pid="<slave.product_code>"
           configPdos="true"
           name="<slave.id>">
      <!-- CiA402 servo: the standard cyclic-position PDO set -->
      <syncManager idx="2" dir="out">
        <pdo idx="1600">
          <pdoEntry idx="6040" subIdx="00" bitLen="16" halPin="cia-controlword" halType="u32"/>
          <pdoEntry idx="607a" subIdx="00" bitLen="32" halPin="target-position" halType="s32"/>
        </pdo>
      </syncManager>
      <syncManager idx="3" dir="in">
        <pdo idx="1a00">
          <pdoEntry idx="6041" subIdx="00" bitLen="16" halPin="cia-statusword" halType="u32"/>
          <pdoEntry idx="6064" subIdx="00" bitLen="32" halPin="actual-position" halType="s32"/>
        </pdo>
      </syncManager>
    </slave>
  </master>
</masters>
```

machine.hal
```hal
# Component: <id>
loadusr -W lcec_conf <parameters.config_file>
loadrt lcec
addf lcec.read-all  servo-thread
addf lcec.write-all servo-thread

# --- CiA402 state machine (one per servo slave) -------------------
# The drive must be walked through the CiA402 states before it accepts
# a setpoint. The cia402 component does that handshake.
loadrt cia402 count=<count of servo slaves>
addf cia402.0.read  servo-thread
addf cia402.0.write servo-thread

net <slave.id>-statusword  lcec.<master>.<slave.id>.cia-statusword  => cia402.<n>.statusword
net <slave.id>-controlword cia402.<n>.controlword => lcec.<master>.<slave.id>.cia-controlword
net <slave.id>-pos-fb-raw  lcec.<master>.<slave.id>.actual-position => cia402.<n>.pos-fb-raw
net <slave.id>-pos-cmd-raw cia402.<n>.pos-cmd-raw => lcec.<master>.<slave.id>.target-position

setp cia402.<n>.pos-scale <joints.computed.scale>
setp cia402.<n>.csp-mode 1

# --- Joint binding ------------------------------------------------
net <axes.id>-pos-cmd joint.<joints.joint_number>.motor-pos-cmd => cia402.<n>.pos-cmd
net <axes.id>-pos-fb  cia402.<n>.pos-fb => joint.<joints.joint_number>.motor-pos-fb
net <joints.id>-enable joint.<joints.joint_number>.amp-enable-out => cia402.<n>.enable
net <joints.id>-fault cia402.<n>.drv-fault => joint.<joints.joint_number>.amp-fault-in
```

webgui_connections.hal
```hal
# No UI Bindings required for the core EtherCAT link.
```

> **VERIFY against your `linuxcnc-ethercat` build.** `lcec` pin names
> are whatever the XML's `halPin=` attributes say — the names above are
> the conventional CiA402 set, not a guarantee. `cia402`'s own pin
> names (`pos-cmd`, `drv-fault`, `csp-mode`) also vary by version; some
> installs use the `lcec_cia402` variant instead. Confirm with
> `halcmd show pin lcec*` / `cia402*` before trusting generated output.

## 4. PIN ROUTER (Class B — position command)

Like Remora, joint `step_pin` / `dir_pin` **never** become HAL nets: an
EtherCAT drive has no step/dir at the LinuxCNC boundary. For a joint on
this MCU those fields are either unused or descriptive only, and a
`step_pin` pointing at an EtherCAT MCU should raise a warning
(`W_IGNORED_PIN`) rather than silently vanish.

I/O pins *do* route, because I/O slaves expose one HAL pin per channel.
The `<pin_id>` for this MCU is `<slave_id>.<channel>`:

```
^ec0:din1.din-3   ->  mcu ec0, slave "din1", channel "din-3", pullup
```

### Digital input (endstop, button, probe)

`lcec` gives each input pin a `-not` twin, same as parport:

```hal
# Auto-Routed: <axes.id> home switch <- <mcu_id> <slave>.<channel>
# invert == false:
net <axes.id>-home-sw <= lcec.<master>.<slave>.<channel>
# invert == true:
net <axes.id>-home-sw <= lcec.<master>.<slave>.<channel>-not
```

### Digital output (heater, fan, relay, lamp)

```hal
# Auto-Routed: <owner.id> <field> -> <mcu_id> <slave>.<channel>
net <owner.id>-<field> => lcec.<master>.<slave>.<channel>
```

`lcec` has no invert parameter on outputs. An inverted output needs a
`logic`/`not` component in between — emit it explicitly rather than
dropping the `!`:

```hal
loadrt not names=not-<owner.id>-<field>
addf not-<owner.id>-<field> servo-thread
net <owner.id>-<field>     => not-<owner.id>-<field>.in
net <owner.id>-<field>-inv not-<owner.id>-<field>.out => lcec.<master>.<slave>.<channel>
```

### Analog output (0–10 V spindle, see `digital_spindle.md`)

```hal
net <owner.id>-<field> => lcec.<master>.<slave>.<channel>
```

Pull-up / pull-down modifiers are a slave-side ESI setting, not a HAL
one → `E_MODIFIER_UNSUPPORTED` unless the compiler also writes the
slave's SDO configuration.
