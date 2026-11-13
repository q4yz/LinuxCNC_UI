# Fans and LEDs

## Fans

```ini
[fan]                       # the part fan: M106 / M107, the dashboard slider
pin: PA8
max_power: 1.0              # (optional) 0.0 … 1.0

[heater_fan hotend_fan]     # runs while the hotend is hot, not commandable
pin: PE5
heater: extruder
heater_temp: 50.0
```

`M106 P<0-255> [Q<fan>]` / `M106 S<0-255>` and `M107` drive the part fans, in declaration
order (`Q0` is the first).

## LEDs

```ini
[neopixel sb_leds]
pin: ebb:PD3
chain_count: 3
color_order: GRBW
initial_WHITE: 1.0
segments: 1, 2-3            # (optional) LED groups with one colour each
```

`SET_LED LED=sb_leds RED=1 GREEN=0.5 BLUE=0 [INDEX=2]` in the console or a macro; Marlin's
`M150 R255 U128 B0` in uploaded G-code is converted to the same. The LEDs card on the
dashboard sets colours by hand.
