# Config

Your machine is described by one text file, the **profile** (`.cfg`). Its syntax mirrors
[Klipper's](https://www.klipper3d.org/Config_Reference.html): if you know a Klipper
`printer.cfg`, you know this file — sections in `[brackets]`, `key: value` lines, the same
section and key names wherever the meaning is the same.

```ini
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF12        # a comment
dir_pin: !PF11
```

- `#` or `;` start a comment, also at the end of a line.
- A key this UI does not know is an error (*Undefined keyword*) — a typo never goes unnoticed.
  Klipper keys that make no sense here are rejected the same way; a few harmless ones are
  accepted and ignored.
- Section names: `[machine]` (not Klipper's `[printer]`), `[stepper_x]`, `[extruder]`, … —
  every section and key is listed in the {doc}`config-reference`.

## [mcu] — the boards

Every machine has at least one **MCU**: the board that drives the motors and heaters (a
Manta M8P, an Octopus …) running Remora. `[mcu]` names how the host reaches it:

```ini
[mcu]
connection: remora-spi    # the board sits on SPI: a CB1 on the M8P, a Pi on the Octopus
```

More boards get a name — `[mcu toolhead]` for a CAN toolhead board, `[mcu ebb]`, … — and
their pins carry that name as prefix:

```ini
[mcu toolhead]
connection: remora-can
canbus_uuid: 0e0d81e4210c

[probe]
pin: !toolhead:PB6        # a pin on the toolhead board
```

## Pins

A pin is the board's own name for it (`PF12`), optionally with the MCU's name in front
(`toolhead:PB6`; without one it is on `[mcu]`) and modifiers:

| Modifier | Meaning | Example |
|----------|---------|---------|
| `!` | inverted: active-low enable, NC switch, reversed direction | `!PB3` |
| `^` | pull-up | `^PF3` |
| `~` | pull-down | `~PG9` |

Modifiers combine (`^!PC0`). A pin used twice is an error unless it is listed in
`[duplicate_pin_override]`.

## Start from an example

Copy a profile from {doc}`config-examples`, change the pins to your wiring, then generate the
machine: {doc}`compile`.
