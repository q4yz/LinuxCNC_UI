# Component: Temperature sensor (`[temperature_sensor NAME]`)

> **Implemented status:** parser (`MachineConfigParser._parse_temperature_sensor`),
> `hardware_json_generator`, `TemperatureSensorHalMapper` /
> `TemperatureSensorWebguiMapper`, the validator rules and
> `hal_pin_diagnostics` below. The runtime and the temperature plot
> needed no change: every `temperature_sensors[]` record no heater
> claims becomes a read-only `webgui.<id>` pin
> (`TemperatureService.preload_hal_pins`) and a line in the plot.
> Tests: `backend/system/tests/test_temperature_sensor_section.py`.
>
> Not yet: a CAN node's (toolhead's) MCU temperature — the node
> firmware has no "MCU Temperature" module.

A reading with no heater behind it — chamber, electronics bay, the
host's CPU, the board's MCU. A heater's own sensor still comes from the
heater section's `sensor_type` / `sensor_pin` (`heater.md`).

## 1. INGESTION (Hand-Written CFG)

```cfg
# A thermistor on a board pin
[temperature_sensor chamber]
sensor_type: Generic 3950    # a thermistor type with a known curve
sensor_pin: PF5              # or ebb:PF5 for a second MCU

# The host's CPU (Raspberry Pi, BTT CB1) — no pin
[temperature_sensor host]
sensor_type: temperature_host
thermal_zone: 2              # (optional) /sys/class/thermal zone; CB1: 2 = CPU, 0 = GPU

# The Remora board's own MCU — no pin
[temperature_sensor mcu]
sensor_type: temperature_mcu

# Any float HAL pin (has a dot) or existing signal (no dot)
[temperature_sensor probe]
sensor_type: hal
sensor_pin: mysensor.temp    # its component loaded in user.hal
```

* `NAME` is the id: lowercase, `^[a-z][a-z0-9_]*$` (`webgui.<NAME>`).
* `temperature_host` / `temperature_mcu` take no `sensor_pin`;
  `thermal_zone` only goes with `temperature_host`. One of each per
  machine.
* `hal`: the generator does not load the pin's component — load it in
  **`user.hal`**, the one HAL file a regenerate keeps (see § 3). A pin
  under `remora.*` is refused: those are PV slots the generator hands
  out to thermistors in turn, so any of them may already be taken.

## 2. hardware.json

Appended to `temperature_sensors[]` after the heaters' own sensors. The
pin-less kinds get the pin they read:

```json
{ "id": "chamber", "pin": "PF5",                  "type": "Generic 3950" },
{ "id": "host",    "pin": "rpi-monitor.cpu-temp", "type": "temperature_host", "thermal_zone": 2 },
{ "id": "mcu",     "pin": "mcu",                  "type": "temperature_mcu" },
{ "id": "probe",   "pin": "mysensor.temp",        "type": "hal" }
```

`temperature_mcu`'s `pin` is the Remora board's MCU id (the first
`remora-spi` MCU).

## 3. COMPILATION

Only for sensors no `tools[].sensor` references — a heater's sensor is
`HeaterHalMapper`'s.

machine.hal:

```hal
net chamber-PV <= remora.PV.<N>          # board thermistor: next free PV
loadusr -Wn rpi-monitor env RPI_MONITOR_TEMP_FILE=/sys/class/thermal/thermal_zone2/temp python3 /usr/local/bin/rpi-monitor 1.0
net host-PV <= rpi-monitor.cpu-temp      # temperature_host (no env without thermal_zone)
net mcu-PV <= remora.PV.<M>              # temperature_mcu: next free PV
```

config_<mcu>.txt: a `Temperature` module per board thermistor (a type
with a known curve, as for heaters) and, for `temperature_mcu`,
`{"Name": "mcu_temp", "Thread": "Servo", "Type": "MCU Temperature",
"Comment": "<id>", "PV[i]": <M>}` (Remora-m8p `modules/mcuTemp`).

webgui_connections.hal (runs after `user.hal`, so a `hal` pin may come
from a component loaded there):

```hal
net chamber-PV => webgui.chamber
net host-PV => webgui.host
net mcu-PV => webgui.mcu
net probe-PV <= mysensor.temp            # hal pin
net probe-PV => webgui.probe
net cpu-temp => webgui.probe_signal      # hal signal (no dot)
```

machine.ini loads `HALFILE = machine.hal`, `user.hal`, `custom.hal` in
that order. `user.hal` is seeded with a comment header on the first
generate and kept as it is on every regenerate.

## 4. VALIDATION

| Code / error | When |
|---|---|
| `MissingRequiredKeywordError` | `sensor_type` missing, or `sensor_pin` missing for a thermistor / `hal`. |
| `InvalidValueError` | a `sensor_pin` on `temperature_host` / `temperature_mcu`; `thermal_zone` on another type; a `hal` pin that is no HAL name. |
| `UndefinedMcuError` | a board pin's `mcu:` prefix names no `[mcu]`. |
| `DuplicateTemperatureSensorError` | `NAME` is a heater's own sensor id (`[heater_bed]` -> `bed`, `[extruder]` -> `extruder`). |
| `E_IO_ID_CONFLICT` | an `[output_pin]` / `[input_pin]` has the same name. |
| `E_MCU_TEMP_NO_REMORA` | `temperature_mcu` on a machine without a `remora-spi` MCU. |
| `E_MCU_TEMP_SHARED` / `E_HOST_TEMP_SHARED` | `temperature_mcu` / `temperature_host` declared twice. |
| `E_HAL_PIN_GENERATED` | a `hal` pin under `remora.*`. |
| `E_HAL_PIN_NO_COMPONENT` | a `hal` pin whose component nothing loads — not the generated `machine.hal`, not LinuxCNC itself (`motion`, `joint`, `iocontrol`, `halui`, ...), not `user.hal`. Checked after assembly. |
| `E_HAL_PIN_IN_USE` | a `hal` pin already on a signal in the generated `machine.hal`, in `user.hal`, or of another sensor. Checked after assembly. |
| `E_HEATER_HAL_SENSOR` | (hand-written hardware.json) a heater reads a sensor that is not a board thermistor. |
