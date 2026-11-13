# Config examples

:::{admonition} Placeholder
:class: warning
Complete, tested profiles for the supported boards are to be added: BTT Manta M8P + CB1
with an EBB toolhead board, BTT Octopus + Raspberry Pi.
:::

## BTT Octopus, Cartesian printer

A complete profile (the generator's own test profile): three axes, an extruder, a bed, two
fans. Pins are the Octopus's; adjust `position_max` to your machine.

```ini
[mcu]
connection: remora-spi
board: BIGTREETECH OCTOPUS
board_reset_pin: PC14

[estop]

[machine]
kinematics: cartesian
max_velocity: 300
max_accel: 3000
max_z_velocity: 5
max_z_accel: 100

[stepper_x]
step_pin: PF11
dir_pin: PG3
enable_pin: !PG5
microsteps: 16
rotation_distance: 40
endstop_pin: PG6
position_endstop: 0
position_max: 200
homing_speed: 50

[tmc2209 stepper_x]
uart_pin: PC6
run_current: 0.600
stealthchop_threshold: 999999

[stepper_y]
step_pin: PG4
dir_pin: PC1
enable_pin: !PA0
microsteps: 16
rotation_distance: 40
endstop_pin: PG9
position_endstop: 0
position_max: 200
homing_speed: 50

[tmc2209 stepper_y]
uart_pin: PC7
run_current: 0.600
stealthchop_threshold: 999999

[stepper_z]
step_pin: PF9
dir_pin: PF10
enable_pin: !PG2
microsteps: 16
rotation_distance: 8
endstop_pin: PG10
position_endstop: 0
position_max: 200
homing_speed: 10

[tmc2209 stepper_z]
uart_pin: PF2
run_current: 0.600
stealthchop_threshold: 999999

[extruder]
step_pin: PC13
dir_pin: PF0
enable_pin: !PF1
microsteps: 16
rotation_distance: 33.500
nozzle_diameter: 0.400
filament_diameter: 1.750
heater_pin: PA2
sensor_type: Generic 3950
sensor_pin: PF4
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 250

[tmc2209 extruder]
uart_pin: PE4
run_current: 0.300
stealthchop_threshold: 999999

[heater_fan]
pin: PA8
heater: extruder

[fan]
pin: PE5

[heater_bed]
heater_pin: PA1
sensor_type: Generic 3950
sensor_pin: PF3
control: watermark
min_temp: 0
max_temp: 130
```

## Snippets

**Z homed on a probe on a CAN toolhead board**

```ini
[mcu toolhead]
connection: remora-can
canbus_uuid: 0e0d81e4210c

[probe]
pin: !toolhead:PB6
x_offset: -25
y_offset: 10
z_offset: 1.2

[stepper_z]
endstop_pin: probe:z_virtual_endstop
# … (no position_endstop: z_offset is the trigger height)

[homing_override]
gcode:
    G91
    G0 Z5
    G90
    G28 X
    G28 Y
    G53 G0 X100 Y100
    G28 Z
```

**Manta M8P on a CB1 (SPI host keys)**

```ini
[mcu]
connection: remora-spi
SPI_freq: 1000000
spi_cs_pin: PC10
PRU_base_freq: 20000
```

*(placeholder: the CB1's spidev `interface` and `reset_pin`)*

**CPU temperature of the host**

```ini
[temperature_sensor host]
sensor_type: temperature_host
thermal_zone: 2
```
