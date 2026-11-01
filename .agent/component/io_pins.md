# Component: I/O pins (`[output_pin NAME]`, `[input_pin NAME]`) and fan control

> **Implemented status:** Klipper's syntax. Code: `IoPinHalMapper`,
> `IoPinWebguiMapper` (HAL), `IoService` + `/api/v1/modules/io` (machine
> backend), the dashboard's I/O card (`IoPanel.vue`). Fans reuse
> `FansService`'s `webgui.<id>` pin. Tests: `test_io_pins.py`,
> `test_io_service.py`, `test-io-panel.ts`.

## 1. INGESTION (Hand-Written CFG)

```cfg
[output_pin case_light]
pin: PB0
value: 0             // (Optional) start value: 0 or scale (switched), 0 ... scale (pwm)
shutdown_value: 0    // (Optional) only 0 — every pin falls back to Low, never configurable

[output_pin dimmable_light]
pin: PB1
pwm: True            // (Optional) default False
cycle_time: 0.010    // (Optional) PWM period in s, default 0.100 -> "Period us"
scale: 100           // (Optional) the UI's full value, default 1

[input_pin my_button]
pin: ^PA0
rising_ngc:          // (Optional) G-code lines run on the rising edge
    (MSG, Button pressed)
falling_ngc:         // (Optional) ... on the falling edge
    (MSG, Button released)

[input_pin door_switch]
pin: PA1
rising_halpin_set: case_light, 1       // (Optional) <output_pin>, <value> — one per line
falling_halpin_set:
    case_light, 0
    dimmable_light, 40
```

`*_halpin_set` is the realtime alternative to `*_ngc`: pure HAL, no MDI,
so it also works while a program runs. It may only target the profile's
own `[output_pin]`s (`E_IO_TARGET`) — the only signals the compiler owns,
so it never becomes a second writer — with 0 / 1 (switched) or
0 ... scale (PWM).

The name is the id: `webgui.<name>`, HAL signals `<name>-out` / `-SP` /
`-in`. It must not repeat a fan / tool / sensor id (`E_IO_ID_CONFLICT`).
Indented `#` lines inside the G-code are dropped. The G-code is LinuxCNC's
(`M117` is Klipper's; use `(MSG, ...)`).

## 2. hardware.json

`output_pins: [{id, pin, pwm, value, shutdown_value, cycle_time, scale}]`,
`input_pins: [{id, pin, rising_ngc, falling_ngc}]`, declaration order.

## 3. COMPILATION

machine.hal:

```hal
net case_light-out => remora.output.00                  # switched: Digital Pin
loadrt scale names=dimmable_light-scale                 # pwm: 0 ... scale -> 0 ... 100 %
setp dimmable_light-scale.gain 1                        # 100 / scale
net dimmable_light-SP <= dimmable_light-scale.out
net dimmable_light-SP => remora.SP.1                    # PWM module, "Period us": cycle_time
net my_button-in remora.input.00                        # Digital Pin input
loadrt not names=my_button-released                     # only with falling_ngc
net my_button-in => my_button-released.in
```

A targeted output is latched (`OutputLatchHalMapper`, last event wins):

```hal
loadrt edge names=case_light-ui-edge,door_switch-rising-edge,door_switch-falling-edge
loadrt mux2 names=case_light-set0,case_light-set1,case_light-set2
setp case_light-ui-edge.both 1                       # every UI toggle is an event
setp door_switch-falling-edge.in-edge 0
net door_switch-in => door_switch-rising-edge.in
net door_switch-rising <= door_switch-rising-edge.out
net case_light-ui-pulse <= case_light-ui-edge.out => case_light-set0.sel
net case_light-latched => case_light-set0.in0         # fed back: holds the value
net case_light-x0 <= case_light-set0.out
net door_switch-rising => case_light-set1.sel
setp case_light-set1.in1 1
net case_light-x0 => case_light-set1.in0
net case_light-x1 <= case_light-set1.out
net door_switch-falling => case_light-set2.sel
setp case_light-set2.in1 0
net case_light-x1 => case_light-set2.in0
net case_light-latched <= case_light-set2.out
setp case_light-on.in0 0.5                           # switched: latched > 0.5
net case_light-latched => case_light-on.in1
net case_light-out <= case_light-on.out
```

A PWM target feeds `<id>-latched` into its `scale` instead.

webgui_connections.hal:

```hal
net case_light-out <= webgui.case_light            # not targeted
# targeted (latched): the UI writes the value, toggles -set, reads -state
net case_light-ui-value webgui.case_light => case_light-set0.in1
net case_light-ui-set webgui.case_light-set => case_light-ui-edge.in
net case_light-latched => webgui.case_light-state
net dimmable_light-value webgui.dimmable_light => dimmable_light-scale.in
net my_button-in => webgui.my_button
net my_button-in => halui.mdi-command-00                               # rising_ngc
net my_button-released my_button-released.out => halui.mdi-command-01  # falling_ngc
```

machine.ini: `[HALUI] MDI_COMMAND = o<my_button_rising> call` per edge
(that order is the `mdi-command-NN` numbering, `mdi_commands()`), and
`SUBROUTINE_PATH` gains `:subroutines` — `configs/subroutines/
<id>_<edge>.ngc` hold the G-code. halui runs an MDI command only while
the machine is on and no program runs.

On a CAN node a switched output is a Digital Pin, a PWM output a node
`"PWM"` (counts towards the node's 4) with `"Safe Duty": 0`.

## 4. RUNTIME / UI

`GET /api/v1/modules/io` -> fans (%), outputs (pwm, scale, value),
inputs (on / off); `PUT /api/v1/modules/io/{id}` `{value}` sets a fan
(0 ... 100 %, clamped), a PWM output (0 ... scale) or a switched output
(0 / 1). Outputs start at their `value` once the webgui component is up.
The dashboard's I/O card: a slider per fan and PWM output, a toggle per
switched output, a lamp per input.
