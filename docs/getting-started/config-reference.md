# Config reference

Every section and key the profile accepts, in the style of
[Klipper's Config Reference](https://www.klipper3d.org/Config_Reference.html): a key shown
`#commented` is optional and shows its default; a key without `#` is required. Sections that
mean the same as in Klipper use Klipper's names.

## Micro-controller

### [mcu]

The board (a Remora board on SPI, Ethernet, a CAN node, a VFD). One `[mcu]`; more as
`[mcu <name>]`, their pins prefixed `<name>:`.

```ini
[mcu]
#connection: remora-spi
#   How the host reaches the board: remora-spi, remora-eth, remora-can (a CAN node behind a
#   remora-spi hub), parallelport, vfd_rs485, ethercat, usb_arduino, dummy.
#board:
#   The board's name, for your information (e.g. BIGTREETECH OCTOPUS).
#interface:
#   The transport's device: the spidev path for remora-spi, socket:// for remora-eth, a
#   serial port for vfd_rs485.
#board_reset_pin:
#   A pin on the Remora board that resets it (remora-spi / remora-eth).
```

**Host side of an SPI link** (`remora-spi` only; case-sensitive, as the driver spells them):

```ini
#SPI_freq:
#   SPI clock in Hz, e.g. 1000000 (BTT CB1, Pi 5).
#SPI_clk_div: 64
#   Instead of SPI_freq: the bcm2835 clock divider (Pi 3 / 4).
#PRU_base_freq: 40000
#   The board's base thread in Hz; 20000 on a Manta M8P (STM32G0).
#spi_cs_pin:
#spi_cs_chip:
#   Chip select on a host GPIO and its gpiochip (the CB1 has none on the header), e.g. PC10.
#reset_pin:
#reset_chip:
#   A host GPIO that resets the board, e.g. PC12.
#sync_config: True
#   Put config_<mcu>.txt on the board's SD card at every LinuxCNC start.
```

**CAN** — on the hub (`remora-spi`):

```ini
#can_bitrate: 1000000
#can_status_bit: 15
#   LinuxCNC input bit that is 1 only while every mandatory node runs (E-stop chain).
```

— and on a node (`connection: remora-can`):

```ini
[mcu toolhead]
connection: remora-can
canbus_uuid:
#   The node's UUID, 12 hex digits, printed by the hub's debug console.
#can_node:
#   1 … 15; default the next free one in declaration order.
#can_hub:
#   The hub's MCU name; default the machine's only remora-spi MCU.
#mandatory: True
#   Losing the node means E-stop.
```

### [estop]

Required, may be empty (an E-stop in the UI only).

```ini
[estop]
#fault_pin:
#   Input of a physical E-stop loop.
#out_pin:
#   Output that follows LinuxCNC's enable state.
```

## Kinematics

### [machine]

Klipper's `[printer]`.

```ini
[machine]
#kinematics: cartesian
#   cartesian or corexy.
#max_velocity:
#max_accel:
#   mm/s, mm/s² — the X / Y defaults when a stepper has none.
#max_z_velocity:
#max_z_accel:
#minimum_cruise_ratio:
#square_corner_velocity:
#   Accepted for Klipper compatibility, no effect.
```

### [stepper]

One per motor: `[stepper_x]`, `[stepper_y]`, `[stepper_z]`; a second motor on an axis
`[stepper_y1]`, `[stepper_z1]`, … (it takes the first one's limits and homing keys unless it
has its own).

```ini
[stepper_x]
step_pin:
dir_pin:
#   ! reverses the axis.
#enable_pin:
microsteps:
rotation_distance:
#   mm per turn: per motor turn, or per output turn with gear_ratio.
#full_steps_per_rotation: 200
#   400 for a 0.9° motor.
#gear_ratio:
#   e.g. 50:17 (motor turns : output turns), chained 80:16, 3:1. Only with a gearbox.
#endstop_pin:
#   The home switch; probe:z_virtual_endstop homes Z on the probe.
#position_min: 0
position_max:
position_endstop:
#   Where the switch is.
#homing_speed: 10
#second_homing_speed:
#   The slow second touch; default homing_speed.
#homing_retract_dist: 5
#   After homing the axis moves this far off the switch.
#homing_positive_dir:
#   Home towards +; default from which end of travel position_endstop is at.
#deadband:
#pgain:
#   Remora position loop tuning of this joint.
```

Steps per mm: `microsteps × full_steps_per_rotation × gear_ratio / rotation_distance`.

### [tmc2209]

A TMC2209 driver on UART: `[tmc2209 stepper_x]`.

```ini
[tmc2209 stepper_x]
uart_pin:
run_current:
#hold_current:
#stealthchop_threshold:
#microsteps:
#interpolate:
#sense_resistor:
```

### [homing_override]

A homing routine: the Home buttons, `G28` and a program's start G-code run it.

```ini
[homing_override]
gcode:
#   G-code lines (indented). G28 X / Y / Z home those axes; it runs unhomed.
#axes: xyz
#   Axes whose home button runs it.
```

## Extruders and heaters

### [extruder]

A heater plus a motor — LinuxCNC's **A axis** (no E axis in LinuxCNC; uploads are converted).

```ini
[extruder]
step_pin:
dir_pin:
#enable_pin:
microsteps:
rotation_distance:
#full_steps_per_rotation: 200
#gear_ratio:
#nozzle_diameter:
#filament_diameter:
#min_extrude_temp: 170
#   No extruder move below this (the Remora "extruder" component stops it; homing is
#   ignored). 0 switches the guard off.
heater_pin:
sensor_type:
sensor_pin:
control:
#   pid or watermark.
#pid_Kp:
#pid_Ki:
#pid_Kd:
min_temp:
max_temp:
#   The highest target the heater accepts.
#max_power: 1.0
#   Duty ceiling, 0.0 … 1.0.
```

### [heater_bed]

```ini
[heater_bed]
heater_pin:
sensor_type:
sensor_pin:
control:
#pid_Kp:
#pid_Ki:
#pid_Kd:
min_temp:
max_temp:
#max_power: 1.0
```

### [heater_generic]

`[heater_generic chamber]` — the same keys as `[heater_bed]`.

### [temperature_sensor]

A temperature without a heater: `[temperature_sensor chamber]`.

```ini
[temperature_sensor chamber]
sensor_type:
#   A thermistor (Generic 3950, …), temperature_host (the host's CPU, no pin) or
#   temperature_mcu (the Remora board's MCU, no pin).
#sensor_pin:
#thermal_zone:
#   temperature_host: the /sys/class/thermal zone; CB1: 2 = CPU.
```

## Probes and levelling

### [probe]

```ini
[probe]
pin:
#x_offset: 0
#y_offset: 0
#   The probe relative to the nozzle, mm.
#z_offset:
#   The nozzle's height above the bed when the probe triggers — measure it with
#   PROBE_CALIBRATE. With Z homed on the probe it is Z at the trigger point.
```

### [tool_length_sensor]

A tool setter, wired together with the probe into LinuxCNC's one probe input.

```ini
[tool_length_sensor]
pin:
```

### [z_tilt]

```ini
[z_tilt]
z_positions:
#   X, Y of each Z motor's pivot, one per line, in [stepper_z], [stepper_z1], … order.
points:
#   Nozzle X, Y of each probe point, one per line.
#speed: 50
#horizontal_move_z: 5
#probe_speed: 5
#retries: 0
#retry_tolerance: 0
#max_adjust: 5
```

### [bed_mesh]

```ini
[bed_mesh]
#probe_count: 3, 3
#mesh_min:
#mesh_max:
#   Where the probe touches; default the X / Y travel.
#speed: 50
#horizontal_move_z: 5
#probe_speed: 5
#zero_reference_position:
#   X, Y where the mesh is 0; default raw heights.
```

## Fans, LEDs and I/O

### [fan]

The part fan (`M106` / `M107`, the I/O card).

```ini
[fan]
pin:
#max_power: 1.0
#shutdown_speed: 0
```

### [heater_fan]

Runs while its heater is hot; not commandable. `[heater_fan hotend_fan]`.

```ini
[heater_fan hotend_fan]
pin:
#heater: extruder
#heater_temp: 50.0
#fan_speed: 1.0
#max_power: 1.0
#shutdown_speed: 0
```

### [neopixel]

```ini
[neopixel leds]
pin:
#chain_count: 1
#color_order: GRB
#initial_RED: 0.0
#initial_GREEN: 0.0
#initial_BLUE: 0.0
#initial_WHITE: 0.0
#segments:
#   LED groups with one colour each, e.g. 1, 2-3; default the whole chain.
```

### [output_pin]

A switched or PWM output, shown on the I/O card: `[output_pin case_light]`.

```ini
[output_pin case_light]
pin:
#pwm: False
#value: 0
#scale: 1
#   The UI's full value (PWM).
#cycle_time: 0.100
#shutdown_value: 0
```

### [input_pin]

An input shown on the I/O card that can run G-code or set outputs on its edges.

```ini
[input_pin door]
pin:
#rising_ngc:
#falling_ngc:
#   G-code lines (indented) run on the edge.
#rising_halpin_set:
#falling_halpin_set:
#   <output_pin>, <value> lines — in HAL, also while a program runs.
```

### [duplicate_pin_override]

```ini
[duplicate_pin_override]
pins:
#   Pins that may be used by more than one section.
```
