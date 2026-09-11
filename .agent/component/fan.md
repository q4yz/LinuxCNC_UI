> **Implemented status:** Both fan `kind`s from § 1 are implemented,
> ingested via Klipper's own real section names — `[fan]`/
> `[fan_generic ...]` for `kind: "part"`, `[heater_fan <name>]` for
> `kind: "heater"` — not a synthetic `kind:` sub-field on one generic
> section, matching the real Klipper config reference this file used
> to only aspire to. `FanHalMapper` (`backend/system/services/
> halcompiler/components/FanHalMapper.py`) gives every `part` fan its
> own direct pin route unconditionally (no heater reference needed —
> `W_ORPHAN_FAN` below is now moot, superseded by this) and wires a
> `heater`-kind fan's `wcomp`/`conv_bit_float`/`scale` chain exactly
> as sketched. `FanWebguiMapper` binds every `part` fan's UI trigger
> in `webgui_connections.hal`; a `heater`-kind fan gets none at all.
> **Two real, still-open gaps, not silently papered over:**
> `shutdown_speed` is ingested as data all the way to `hardware.json`
> but not yet wired into an estop-triggered HAL switchover (§ 3's own
> note explains why: it needs a machine-wide "is this machine actually
> enabled" signal this compiler doesn't export uniformly across MCU
> classes yet). And **no machine-runtime code registers a standalone
> `[fan]`'s own `webgui.<id>` pin** — only a heater's *own* nested fan
> field does (`HeaterMapper.py::from_dict_to_HeaterPins`); "gcode
> defines the speed" for a genuinely standalone fan needs a small
> `FanPin`/`FanMapper`/`FanService` on the machine-backend side, which
> does not exist yet. `webgui_connections.hal`'s binding is real HAL
> text either way — it's just that nothing on the Python side answers
> it for a fan no heater references, today.

## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for the two distinct
Klipper section shapes below — they are not variants of one syntax,
they are two different sections with two different control models.

**Component ID Format:** `[fan]` / `[fan_generic <identifier>]` for a
`part` fan; `[heater_fan <identifier>]` (bare `[heater_fan]` accepted
too, for consistency with every other component here) for a `heater`
fan.

**Expected Syntax:**
```cfg
[fan]
    pin: string // Output driving the fan (PWM-capable for variable speed)
    max_power: float // (Optional) 0.0-1.0 duty ceiling, default 1.0
    shutdown_speed: float // (Optional) duty on estop/shutdown, default 0.0
    # --- Every other real Klipper [fan] keyword is accepted and
    # --- ignored: this compiler assumes a plain two-pin fan (no
    # --- tachometer wire at all) at a fixed PWM cycle.
    # enable_pin / cycle_time / hardware_pwm / off_below /
    # tachometer_pin / tachometer_ppr / tachometer_poll_interval /
    # kick_start_time

[heater_fan <identifier>]
    pin: string // Output driving the fan
    heater: string // (Optional) heater section this follows, default "extruder"
    heater_temp: float // (Optional) turn on above this reading, default 50.0
    fan_speed: float // (Optional) 0.0-1.0 speed once triggered, default 1.0
    max_power: float // (Optional) 0.0-1.0 duty ceiling, default 1.0
    shutdown_speed: float // (Optional) duty on estop/shutdown, default 0.0
    # --- Same ignored-keyword set as [fan] above.
```

**Control model — the only interesting part of this component:**

| Section | kind | Driven by | Purpose |
|---|---|---|---|
| `[fan]` / `[fan_generic ...]` | `part` | G-code / the UI slider | Cools the printed part. Freely commandable. |
| `[heater_fan <name>]` | `heater` | the referenced heater's reading | Hot-end/heatbreak cooling. Runs whenever the block is hot — including after an estop (it reads the *reading*, not the setpoint, which drops to 0 immediately). Never operator-commandable. |

A heater's own `heater_pin` also gets an *auto-derived* `kind: "part"`
placeholder fan sharing that exact pin — real hardware fact (one
physical output can't independently drive two logical signals), not
an operator mistake, see § 4's `W_FAN_SHARES_HEATER_PIN`.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "fans": [
    { "id": "fan", "pin": "PA8", "kind": "part",
      "max_power": 1.0, "shutdown_speed": 0.0 },
    { "id": "heater_fan_heatbreak_cooling_fan", "pin": "PA9", "kind": "heater",
      "heater": "heater_extruder", "heater_temp": 50.0, "fan_speed": 1.0 }
  ]
}
```

One list, one discriminator (`kind`), so `tools[].fan` cross-reference
validation stays a single mechanism regardless of which section shape
produced the record — a `heater`-kind fan is simply never referenced
that way. `heater` resolves the *raw* Klipper heater section name
(`"extruder"`, `"heater_bed"`, ...) to this compiler's own canonical
tool id (`"heater_extruder"`) — `hardware_json_generator._heater_id`,
the exact same resolution every other heater cross-reference already
goes through.

A `part` fan surfaces in the UI unconditionally now (its own direct
pin route + its own `webgui_connections.hal` binding) — it does not
need a heater to reference it the way an earlier draft of this file
required. A `heater`-kind fan has no UI surface at all, deliberately:
nothing should be able to command it by hand.

## 3. COMPILATION (INI & HAL)

machine.ini
```ini
# A fan contributes no section of its own. Its duty ceiling belongs to
# whatever drives it — see [<HEATER_SECTION>]PID_CVMAX in heater.md.
```

machine.hal
```hal
# ------------------------------------------------------------------
# kind: part — a plain direct pin route, nothing else
# ------------------------------------------------------------------
# The write side (webgui.<id> => <id>-SP) lives in
# webgui_connections.hal, not here (FanWebguiMapper) — this mapper
# only ever contributes the PinRequest so the MCU router can bind the
# physical pin. On class B (Remora) the board owns the PWM directly
# (remora.SP.N takes the duty number as-is); on class A the signal
# would need a pwmgen stage first, or the fan is on/off only — not
# yet implemented for class A.

# ------------------------------------------------------------------
# kind: heater — follows the block temperature, NOT the setpoint
# ------------------------------------------------------------------
# Reading, not setpoint: after an estop the setpoint drops to 0 but
# the block is still 200 C and still needs cooling. Skipped entirely
# (an honest gap, no crash) when the referenced heater declares no
# sensor — nothing to gate on.
loadrt wcomp names=wcomp-<id>
addf wcomp-<id> servo-thread
setp wcomp-<id>.min <parameters.heater_temp || 50.0>
setp wcomp-<id>.max 999.0

net <heater.sensor.id>-PV => wcomp-<id>.in
net <id>-on               <= wcomp-<id>.out

loadrt conv_bit_float names=conv-<id>
addf conv-<id> servo-thread
net <id>-on => conv-<id>.in
net <id>-on-frac <= conv-<id>.out

loadrt scale names=scale-<id>
addf scale-<id> servo-thread
# fan_speed (0.0-1.0, Klipper's own unit) -> percent (this compiler's
# own remora.SP.N convention — heater.md's PID CVmax / the watermark
# branch's scale.gain both default to 100.0 the same way).
setp scale-<id>.gain <parameters.fan_speed || 1.0> * 100
net <id>-on-frac => scale-<id>.in
net <id>-SP      <= scale-<id>.out

# ------------------------------------------------------------------
# HARDWARE-AGNOSTIC SIGNAL EXPORT
# ------------------------------------------------------------------
# Both kinds emit the same PinRequest shape (ANALOG_OUT, signal
# "<id>-SP") — the MCU router doesn't know or care which kind wrote
# the signal, only that it needs a physical pin.
```

The reference printer keeps `kind: heater` simpler than this compiler
now does — the hot-end fan there is just another setpoint channel with
no temperature gating at all: `net ext0-cooling-SP => remora.SP.2`
(`machine_config/example/ender3/3Dprinter.hal`). That machine's fan is
a `part`-shaped wiring even though it cools the hot end; a real
`[heater_fan]` section (Klipper's own automatic-cooling concept) is a
different, additional case this file now covers.

**`shutdown_speed` — ingested, not yet wired.** Both kinds carry it
through to `hardware.json`, but nothing switches the fan to that duty
on an estop today. The natural mechanism (a `mux2` selecting between
the commanded value and `shutdown_speed`, gated on
`iocontrol.0.user-enable-out`) is straightforward per-fan, but every
fan doing it independently would each net a fresh reader off
`iocontrol.0.user-enable-out` — safe (HAL allows any number of
readers on one source pin) but wants a single shared "is the machine
enabled" export so N fans don't each reinvent the same `not` stage. No
such shared, cross-MCU-class export exists in this compiler yet
(`EstopHalMapper`'s own physical chain reads `iocontrol.0.
user-enable-out` directly too, but only conditionally, per-MCU-class —
see `estop.md`). Next concrete step, not a fabricated one.

webgui_connections.hal
```hal
# UI Bindings for <id> — only for kind: "part". A kind: "heater" fan
# gets nothing here at all (FanWebguiMapper is never called for one).
net <id>-SP <= webgui.<id>
```

Skipped even for a `part` fan when its pin is in
`duplicate_pin_overrides` (the heater/fan-shares-a-pin case
`hardware_json_generator` auto-populates, or an operator's own
explicit entry) — `HalAssembler` renames that fan's signal onto
whatever else already claims the pin, so a standalone binding here
would reference a signal `machine.hal` never actually uses.

## 4. ROUTING NOTES

| Signal | Direction | Bound from |
|---|---|---|
| `<id>-SP` | out (float) | `fans[].pin`, either kind |

Validation specific to fans:

* `E_UNKNOWN_FAN` — a `tools[].fan` names no declared fan.
* `E_UNKNOWN_HEATER` — a `kind: "heater"` fan's `heater` resolves to
  no declared tool. Implemented (`MachineValidator._check_references`,
  and the pydantic `HardwareJson` model's own cross-reference pass).
* `E_PIN_CONFLICT` (generic) — two fans share a pin, or a fan's pin is
  also a `heater_pin`; the one documented, deliberate exception is the
  heater/fan auto-sharing case immediately below.
* `W_FAN_SHARES_HEATER_PIN` — the generator-created placeholder fan
  sharing its own heater's `heater_pin`; real, but the compiler's own
  doing, not the operator's. `build_hardware_json` auto-adds that pin
  to `duplicate_pin_overrides` so `HalAssembler` collapses the
  heater's PID output and the placeholder fan onto one signal, one
  `config.txt` `"PWM"` module — see `mcu_spi_remora.md`.
* ~~`W_ORPHAN_FAN`~~ — moot now: every `part` fan gets its own direct
  route and webgui binding unconditionally, heater reference or not.
* `W_BINARY_FAN` — not yet implemented (needs pin-type introspection
  this compiler doesn't do yet): the pin resolves to a binary-only
  output while the UI presents a speed slider.
