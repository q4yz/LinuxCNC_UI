# Configuration overview

The machine profile is a Klipper-style `.cfg`: `[section]` headers with `key: value` lines,
`#` or `;` comments (also at the end of a line). Most sections and keys mean what they mean in
Klipper, so a Klipper `printer.cfg` is a good start; keys this UI does not know are an error
(*Undefined keyword*), so typos do not go unnoticed.

| Section | Page |
|---------|------|
| `[mcu]`, `[mcu <name>]` | the board(s): `connection:` `remora-spi` (default), `remora-eth`, `remora-can` (a CAN node behind an SPI hub), `parallelport`, `vfd_rs485`, … |
| `[printer]` | kinematics (`cartesian`, `corexy`), velocity / acceleration limits |
| `[stepper_x]`, `[stepper_y]`, `[stepper_z]`, `[stepper_z1]`, … | {doc}`steppers` |
| `[extruder]`, `[heater_bed]`, `[heater_generic <name>]` | {doc}`heaters-extruder` |
| `[probe]`, `[tool_length_sensor]` | {doc}`probe` |
| `[z_tilt]`, `[bed_mesh]`, `[homing_override]` | {doc}`levelling` |
| `[fan]`, `[heater_fan <name>]`, `[neopixel <name>]` | {doc}`fans-leds` |
| `[output_pin <name>]`, `[input_pin <name>]`, `[temperature_sensor <name>]` | extra I/O |
| `[estop]` | the E-stop input (required) |

## Pins

A pin is `<mcu>:<pin>`; without a prefix it is on `[mcu]`. Prefixes:

- `!` — inverted (`!PB3`): an active-low enable, an NC switch, a reversed `dir_pin`.
- `^` — pull-up (`^PF3`), `~` — pull-down. Modifiers combine (`^!PC0`).

A pin used twice is an error, unless it is listed in `[duplicate_pin_override] pins:`.

## After a change

Generate the machine again (Config page) and restart LinuxCNC: the INI and HAL files are only
read at start.
