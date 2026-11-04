# Component: Temperature sensor (`[temperature_sensor NAME]`)

> **Implemented status:** parser (`MachineConfigParser._parse_temperature_sensor`),
> `hardware_json_generator`, `TemperatureSensorHalMapper` /
> `TemperatureSensorWebguiMapper`, validator rules below. The runtime and
> the temperature plot needed no change: every `temperature_sensors[]`
> record no heater claims already becomes a read-only `webgui.<id>` pin
> (`TemperatureService.preload_hal_pins`) and a line in the plot.
> Tests: `backend/system/tests/test_temperature_sensor_section.py`.
>
> Not yet: the MCU's own internal temperature (Remora has no firmware
> sensor type for it). Once a HAL pin carries it, it is just
> `sensor_type: hal`.

A reading with no heater behind it — chamber, electronics bay, the
host's CPU. A heater's own sensor still comes from the heater section's
`sensor_type` / `sensor_pin` (`heater.md`).

## 1. INGESTION (Hand-Written CFG)

```cfg
# A thermistor on a board pin
[temperature_sensor chamber]
sensor_type: Generic 3950    # a thermistor type with a known curve
sensor_pin: PF5              # or ebb:PF5 for a second MCU

# Any float HAL pin — e.g. the host's CPU temperature
[temperature_sensor host]
sensor_type: hal
sensor_pin: rpi-monitor.cpu-temp

# ... or an existing HAL signal (no dot)
[temperature_sensor host_signal]
sensor_type: hal
sensor_pin: cpu-temp
```

* `NAME` is the id: lowercase, `^[a-z][a-z0-9_]*$` (`webgui.<NAME>`).
* `sensor_type: hal` (any case) makes `sensor_pin` a HAL name. With a
  dot it is a **pin**, without one an existing **signal** — a HAL pin
  sits on one signal only, so a pin your own HAL already wires is given
  by its signal instead.
* The component behind a HAL pin is **not** loaded by the generator.
  Load it in your own HAL file, e.g. for the host CPU
  (Remora-m8p `LinuxCNC/Components/RPiMonitor`, Raspberry Pi and BTT CB1):

  ```hal
  loadusr -Wn rpi-monitor python3 /path/to/RPiMonitor/rpi_monitor.py 1.0
  ```

## 2. hardware.json

Appended to `temperature_sensors[]` after the heaters' own sensors:

```json
{ "id": "chamber",     "pin": "PF5",                  "type": "Generic 3950" },
{ "id": "host",        "pin": "rpi-monitor.cpu-temp", "type": "hal" },
{ "id": "host_signal", "pin": "cpu-temp",             "type": "hal" }
```

## 3. COMPILATION

Only for sensors no `tools[].sensor` references — a heater's sensor is
`HeaterHalMapper`'s.

machine.hal:

```hal
net chamber-PV <= remora.PV.<N>          # board pin: routed like a heater's sensor
net host-PV <= rpi-monitor.cpu-temp      # HAL pin
                                         # HAL signal: nothing here
```

A board thermistor also gets its `Temperature` module in
`config_<mcu>.txt` (only for a type with a known curve, as for heaters).

webgui_connections.hal:

```hal
net chamber-PV => webgui.chamber
net host-PV => webgui.host
net cpu-temp => webgui.host_signal
```

## 4. VALIDATION

| Code / error | When |
|---|---|
| `MissingRequiredKeywordError` | `sensor_type` or `sensor_pin` missing. |
| `InvalidValueError` | `sensor_type: hal` with a pin that is no HAL name. |
| `UndefinedMcuError` | a board pin's `mcu:` prefix names no `[mcu]`. |
| `DuplicateTemperatureSensorError` | `NAME` is a heater's own sensor id (`[heater_bed]` -> `bed`, `[extruder]` -> `extruder`). |
| `E_IO_ID_CONFLICT` | an `[output_pin]` / `[input_pin]` has the same name. |
| `E_HEATER_HAL_SENSOR` | (hand-written hardware.json) a heater reads a `type: hal` sensor — heaters read a board thermistor only so far. |

A `type: hal` pin is never checked as a board pin (no pin-conflict or
MCU checks).
