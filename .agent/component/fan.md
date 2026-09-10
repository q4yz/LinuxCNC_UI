> **Implemented status:** a fan a heater references compiles today —
> `HeaterHalMapper` (`heater.md` § 3) requests its pin as a plain
> `ANALOG_OUT`, routed through `RemoraRouterMapper` exactly like a
> heater's own output. There is no standalone `FanHalMapper` yet: with
> `kind`/`heater`/`max_power`/`off_below` absent from the real
> `fans[]` schema (this file's own § 2 gap), the `part`/`heater`/
> `controller` differentiation described in § 3 below is aspirational
> — every fan compiles as an unconditional passthrough, matching what
> `machine_config/example/ender3/3Dprinter.hal` actually does
> (`ext0-cooling-SP => remora.SP.2`, no `wcomp` gating).

## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below.
**Component ID Format:** `[fan_<identifier>]`, or the implicit
`[fan]` / `[heater_fan <name>]` / `[controller_fan <name>]` forms a
Klipper config uses.

**Expected Syntax:**
```cfg
[fan_<identifier>]
    pin: string // Output driving the fan (PWM-capable for variable speed)
    kind: string // "part" | "heater" | "controller" | "exhaust", default "part"
    heater: string // (kind: heater) id of the heater this fan follows
    max_power: float // (Optional) 0.0-1.0 duty ceiling, default 1.0
    off_below: float // (Optional) duty below which the fan is forced off, default 0.0
    shutdown_speed: float // (Optional) duty on estop/shutdown, default 0.0
    heater_temp: float // (kind: heater) turn on above this reading, default 50.0
```

**`kind` decides who drives the fan**, which is the only interesting
part of this component:

| kind | Driven by | Purpose |
|---|---|---|
| `part` | G-code / the UI slider | Cools the printed part. Freely commandable. |
| `heater` | the referenced heater's reading | Hot-end cooling. Must run whenever the block is hot — including after an estop. |
| `controller` | any joint being enabled | Stepper-driver cooling. |
| `exhaust` | the UI, or always-on | Enclosure / fume extraction. |

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "fans": [
    { "id": "fan_<identifier>", "pin": "<parsed_value>" }
  ]
}
```

The app's `fans[]` entries are deliberately thin — `id` and `pin` only,
as in the live example machine
(`{"id": "fan_heater_extruder_test", "pin": "PE3"}`). A fan surfaces in
the UI **through the heater that references it**, not on its own:
`HeaterMapper` turns `tools[].fan` into a FLOAT pin named after the
fan's id, so `fan_heater_extruder_test` becomes
`webgui.fan_heater_extruder_test`.

Consequences a compiler must respect:

* A fan that no heater references has **no UI surface**. That is fine
  for `controller` / `exhaust` fans (nothing should command them by
  hand), but a `part` fan needs a heater reference or a panel binding,
  else it is unreachable: `W_ORPHAN_FAN`.
* `kind`, `max_power`, `off_below` and friends have **nowhere to live**
  in the current `fans[]` schema. Either extend it, or bake the
  behaviour into the emitted HAL (the approach § 3 takes). Extending is
  preferable — the UI cannot show a limit it cannot read.
* The pin is FLOAT, not BIT: the UI expects a 0.0–1.0 (or 0–100) speed,
  so a fan on a binary-only output is a lie unless a PWM stage exists.

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
# A fan contributes no section of its own. Its duty ceiling belongs to
# whatever drives it — see [<HEATER_SECTION>]PID_CVMAX in heater.md.
```

machine.hal
```hal
# Component: <id>
# ------------------------------------------------------------------
# kind: part — commanded speed, clamped
# ------------------------------------------------------------------
loadrt limit1 names=limit-<id>
addf limit-<id> servo-thread
setp limit-<id>.min 0.0
setp limit-<id>.max <parameters.max_power>

net <id>-cmd => limit-<id>.in
net <id>-SP  <= limit-<id>.out

# ------------------------------------------------------------------
# kind: heater — follows the block temperature, NOT the setpoint
# ------------------------------------------------------------------
# Reading, not setpoint: after an estop the setpoint drops to 0 but
# the block is still 200 C and still needs cooling.
loadrt wcomp names=wcomp-<id>-hot
addf wcomp-<id>-hot servo-thread
setp wcomp-<id>-hot.min <parameters.heater_temp || 50.0>
setp wcomp-<id>-hot.max 999.0

net <heater.sensor.id>-PV => wcomp-<id>-hot.in
net <id>-on               <= wcomp-<id>-hot.out

loadrt conv_bit_float names=conv-<id>
addf conv-<id> servo-thread
net <id>-on => conv-<id>.in
net <id>-SP <= conv-<id>.out

# ------------------------------------------------------------------
# kind: controller — on whenever any joint is enabled
# ------------------------------------------------------------------
loadrt or2 names=or-<id>-any-joint
addf or-<id>-any-joint servo-thread
net j0enable => or-<id>-any-joint.in0
net j1enable => or-<id>-any-joint.in1
# ... chain more or2 instances for further joints ...

# ------------------------------------------------------------------
# HARDWARE-AGNOSTIC SIGNAL EXPORT
# ------------------------------------------------------------------
# The MCU router binds <id>-SP to the fan's pin. On class B the board
# owns the PWM (remora.SP.N takes the number directly); on class A the
# signal needs a pwmgen stage first, or the fan is on/off only.
```

The reference printer keeps this simple — the hot-end fan is just
another setpoint channel: `net ext0-cooling-SP => remora.SP.2`
(`machine_config/example/ender3/3Dprinter.hal`).

webgui_connections.hal
```hal
# UI Bindings for <id>
# Only when a heater references this fan — that reference is what
# creates the pin (§ 2).
net <id>-SP <= webgui.<id>
```

## 4. ROUTING NOTES

| Signal | Direction | Bound from |
|---|---|---|
| `<id>-SP` | out (float) | `fans[].pin` |

Validation specific to fans:

* `E_UNKNOWN_FAN` — a `tools[].fan` names no declared fan.
* `E_FAN_PIN_CONFLICT` — two fans share a pin, or a fan's pin is also a
  `heater_pin`. Worth calling out separately from the generic
  `E_PIN_CONFLICT`: the example machine has
  `fan_heater_extruder_test.pin == "PE3"` and
  `heater_extruder_test.heater_pin == "PE3"` — the same output driving
  both a heater and its own cooling fan, which cannot be right.
* `E_UNKNOWN_HEATER` — `kind: heater` references an undeclared heater.
* `W_ORPHAN_FAN` — a `part` fan no heater references and no panel
  binds: it exists in the config but nothing can turn it on.
* `W_BINARY_FAN` — the pin resolves to a binary-only output while the
  UI presents a speed slider. The fan will jump between off and full.
