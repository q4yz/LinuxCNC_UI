## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below. 
**Component ID Format:** `[component_prefix]_[identifier]`

**Expected Syntax:**
```cfg
[spindle_digital identifier]
protocol: string // "vfdmod" (RS485) or "ethercat"
max_rpm: integer // Maximum allowable RPM
min_rpm: integer // Minimum allowable RPM
```

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "tools": [
    {
      "id": "spindle_digital",
      "name": "Spindle (Digital)",
      "type": "spindle_digital",
      "protocol": "RS485",
      "min_rpm": { "type": "float", "value": "<parsed_value>" },
      "max_rpm": { "type": "float", "value": "<parsed_value>" }
    }
  ]
}
```
## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[SPINDLE_<spindle_number>]
MAX_FORWARD_VELOCITY = <max_rpm>
MIN_FORWARD_VELOCITY = <min_rpm>

[TRAJ]
SPINDLES = <count of spindle tools>
```

vfd.ini — a third artifact next to the INI and HAL. `vfdmod` reads it
for the serial settings and the VFD's Modbus register map; the register
numbers are drive-specific (see the vfdmod project's per-VFD examples).
```ini
[common]
address = 1
port = /dev/ttyUSB0
baud = 9600
parity = none
databits = 8
stopbits = 1

[rpmIn]
address = 0x700C   # drive-specific: actual speed register
multiplier = 1
divider = 1

[rpmOut]
address = 0x2001   # drive-specific: speed command register
multiplier = 1
divider = 1
```

machine.hal
```hal
# Component: <id>
# -W blocks until vfdmod's pins exist, so the nets below cannot race
# the serial handshake.
loadusr -W vfdmod vfd.ini
```
webgui_connections.hal
```hal
# ==========================================================
# UNIVERSAL DIGITAL SPINDLE LOGIC & UI
# ==========================================================
# These nets connect LinuxCNC's core spindle logic to the Web GUI.
# They apply regardless of the underlying digital protocol.

# Web GUI Override
setp halui.spindle.0.override.direct-value true
setp halui.spindle.0.override.scale 0.01
net spindle-override webgui.override => halui.spindle.0.override.counts

# Standard UI state feedback
net spindle-forward  spindle.0.forward => webgui.spindle-forward
net spindle-reverse  spindle.0.reverse => webgui.spindle-reverse
net spindle-speed-out => webgui.rpm-out


# ==========================================================
# HARDWARE DRIVER BINDING 
# ==========================================================
# AGENT INSTRUCTION: Inject the correct block below based on the <protocol>.

# --- IF protocol == "vfdmod" ---
net spindle-forward  => vfdmod.control.run-forward
net spindle-reverse  => vfdmod.control.run-reverse
net spindle-speed-cmd spindle.0.speed-out => vfdmod.control.rpm-in
net spindle-speed-out <= vfdmod.spindle.rpm-out => spindle.0.speed-in

net backend-is-connected  vfdmod.rs485.is-connected => webgui.is-connected
net backend-error-count   vfdmod.rs485.error-count  => webgui.error-count
net backend-last-error    vfdmod.rs485.last-error   => webgui.last-error
```