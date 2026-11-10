> **Implemented status:** `ProbeHalMapper` (`backend/system/services/
> halcompiler/components/ProbeHalMapper.py`) emits the § 3 wiring into
> `machine.hal` when `pin` is declared — and nothing at all when it
> isn't (including when `[probe]` is present but bare). Unlike
> `[estop]`, there is no "exactly one `[probe]`" requirement and no
> two-mapper split: a probe has no UI-only trigger to fall back to
> (`webgui_connections.hal` is untouched), and `motion.probe-input` is
> a core LinuxCNC motion pin, not something a class-B/C MCU router
> ever claims for its own link-health chain — so there is no MCU-class
> gating to speak of either. `services.machineconfig.
> hardware_json_generator.build_hardware_json` never raises for a
> missing `[probe]`; a machine with no touch probe simply omits the
> `probe` key from `hardware.json` altogether.

> **Tool-length sensor:** `[tool_length_sensor]` is a second,
> independent section with the same single optional `pin`. LinuxCNC
> has one probe input, so both switches are merged into
> `motion.probe-input` (§ 3). NC/NO is each pin's own `!`, so a probe
> and a tool setter may have opposite polarities.

## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for the block matching
the syntax below.
**Component ID Format:** `[probe]` — bare only, no named-instance
form (unlike `[heater_*]` / `[spindle *]`). At most one is meaningful
per machine (a second `[probe]` is a literal duplicate section,
already rejected for free by `configparser`'s own strict mode); zero
is equally valid — a machine with no touch probe never declares this
section at all.

**Expected Syntax:**
```cfg
[probe]
    pin: string // (Optional) the probe switch's digital input, e.g. "!par0:15"
    x_offset: float // (Optional) probe X minus nozzle X, mm, default 0 (Klipper's meaning)
    y_offset: float // (Optional) probe Y minus nozzle Y, mm, default 0
    z_offset: float // (Optional) nozzle height above the bed when the probe triggers, mm
```

The offsets are used by every probing routine (`services/Probing.py`):
the bed mesh's `mesh_min` / `mesh_max` are where the probe touches (the
nozzle goes `x_offset`, `y_offset` away), Z tilt's `points` are nozzle
positions (the fit uses where the probe touched), and a probed height
is the nozzle's Z at the trigger minus `z_offset`. With Z homed on the
probe, `z_offset` is Z at the trigger point (`position_endstop`; both
set and different is an `InvalidValueError`). `PROBE_CALIBRATE` measures
`z_offset` (below).

An empty `[probe]` block (no `pin` at all) is valid but contributes
nothing to `machine.hal` — same leniency as every other component,
just with no UI-only fallback behind it.

```cfg
[tool_length_sensor]
    pin: string // (Optional) the tool setter's digital input, e.g. "!par0:13"
```

Same rules as `[probe]`: bare section only, at most one, an empty
block contributes nothing.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "probe": {
    "pin": "<parameters.pin | null>",
    "x_offset": "<float, only when not 0>",
    "y_offset": "<float, only when not 0>",
    "z_offset": "<float, only when set>"
  }
}
```

```json
{
  "tool_length_sensor": {
    "pin": "<parameters.pin | null>"
  }
}
```

`tool_length_sensor` follows exactly the same presence rules as
`probe` below.

A top-level singleton object, same shape as `estop` — but genuinely
optional at the *object* level, not just per-field: `probe` is
**absent from the payload entirely** when the source `.cfg` declares
no `[probe]` section (`graph.probe is None`). A declared-but-bare
`[probe]` still serialises as the present, empty object `{}` (its one
field dropped by `exclude_none`), matching `estop`'s "present, empty
object" convention for that case — the two are only differentiated by
whether the section existed in the source at all.

## 3. COMPILATION (INI & HAL)

No `machine.ini` section — the probe has no tunable gains, nothing to
re-tune without regenerating HAL.

machine.hal
```hal
# Nothing at all when pin is unset — an empty [probe] block (or no
# [probe] section at all) contributes zero lines here.

# --- IF parameters.pin ---
# Grounded in the real reference machine, machine_config/example/
# PrintNC-WEBGUI/Machine.hal (line 93). motion.probe-input is a core
# LinuxCNC motion pin — no loadrt needed, and (unlike estop's
# iocontrol.0 chain) no MCU-class router ever claims it for its own
# purposes, so there is no gating to consider here.
net probe-in => motion.probe-input
net probe-in <= <pin>                         # <- pin (input)
```

When **both** `[probe]` and `[tool_length_sensor]` declare a pin,
either switch must trip the single probe input, so they are OR-ed:

```hal
loadrt or2 names=probe-or
addf probe-or servo-thread                    # input stage (order 0), before motion
net probe-in              => probe-or.in0
net tool-length-sensor-in => probe-or.in1
net probe-or-out probe-or.out => motion.probe-input
net probe-in              <= <probe pin>              # router half
net tool-length-sensor-in <= <tool_length_sensor pin> # router half
```

With only `[tool_length_sensor]` declared, it is wired straight to
`motion.probe-input` exactly like a lone probe
(`net tool-length-sensor-in => motion.probe-input`).

**Polarity (NC/NO)** is never handled by the OR: each pin's `!` is
resolved by the MCU router that binds its `PinRequest`, MCU-specific —
`parport.0.pin-NN-in-not`, `remora.input.NN.not`, or an explicit `not`
stage for `vfdmod`. The OR always sees "1 = triggered".

The two `net probe-in ...` lines are the component-owned half
(emitted directly by `ProbeHalMapper`) and the router-owned half
(emitted by whichever MCU router the pin targets, from the
`PinRequest` `ProbeHalMapper` registers) — same split-net pattern
every other component uses. They land as two separate statements in
the generated file rather than the reference's single combined line;
HAL's `net` command accumulates pins onto an existing signal across
statements, so the result is behaviourally identical.

## 4. Validation rules

* No cardinality rule — a missing `[probe]` is never an error, unlike
  `MissingEstopSectionError`.
* Duplicate `[probe]` — free, via `configparser`'s own strict
  duplicate-section rejection (`MalformedConfigError`).
* `pin` participates in every *generic* pin rule the same way any
  other component's pins do — `E_UNKNOWN_MCU`, `E_NO_DEFAULT_MCU`,
  `E_PIN_CONFLICT`, `E_MALFORMED_PIN` (`MachineValidator._parsed_pins()`
  folds the top-level `probe` singleton into the same walk every
  list-shaped component's pins go through, same as `estop`). It never
  drives motion, so `E_MOTION_ON_IO_MCU` never applies.

## 5. Signal names

Reuses the `DIGITAL_IN` `PinRole` `estop.md` § 5 introduced — no new
role needed. `probe-in` is the signal name, now listed alongside
`estop-out`/`estop-fault` in `.agent/component/README.md` § 5's
reserved "machine core" signal-name table.

## Z homed on the probe (Klipper's `probe:z_virtual_endstop`)

```cfg
[probe]
pin: !sb2209:PB6

[stepper_z]
endstop_pin: probe:z_virtual_endstop   # (the probe pin itself means the same)
position_endstop: 0                    # Z at the probe's trigger point
homing_speed: 5                        # (Optional) first approach, mm/s
second_homing_speed: 2.5               # (Optional) default homing_speed / 2
homing_retract_dist: 5                 # (Optional) back off between the two, default 5
```

Z homes with LinuxCNC's own homing, the probe as the Z home switch of
every Z joint. LinuxCNC aborts any non-probe move during which
`motion.probe-input` trips ("probe tripped during non-probe move"), its
own homing included, so the probe reaches `motion.probe-input` through a
gate that is closed while Z homes (`ProbeHalMapper._with_z_home`):

```hal
net probe-in => joint.2.home-sw-in
net probe-z-homing joint.2.homing => probe-z-homing-not.in
net probe-allowed probe-z-homing-not.out => probe-gate.in1
net probe-in => probe-gate.in0
net probe-gated probe-gate.out => motion.probe-input
```

The Z joints (`AxisBuilder._home_z_on_probe`): `HOME_SEARCH_VEL =
-homing_speed`, `HOME_LATCH_VEL = -second_homing_speed` (latch from the
same side), `HOME_OFFSET = position_endstop`, `HOME = position_endstop +
homing_retract_dist` (Z lifts off the bed after homing). A `G38.2`
search from an unhomed Z is not used: the soft limits refuse it ("Probe
move would exceed Z's negative limit").

`G28 Z` (in `[homing_override]`, MDI, a print's start G-code), the Home
Z and Home All buttons do this; a bare `G28` homes the other axes first
and Z last (X / Y must put the probe over the bed — `[homing_override]`
for a "move to the centre" first). `NO_FORCE_HOMING = 1` (that
move runs with Z unhomed); programs only start once everything is homed.
The probe may sit on a CAN node (`mcu_can_remora.md`).


## PROBE_ACCURACY

`PROBE_ACCURACY [SAMPLES=10] [SAMPLE_RETRACT_DIST=2] [PROBE_SPEED=5]`
(MDI, a macro line; `ProbeAccuracyService`): Klipper's repeatability test.
Probes the bed at the current X, Y `SAMPLES` times with relative moves
(`G91`, `G38.2 Z-<to the lowest Z>`, `G0 Z<retract>`, `G90`), Z homed.
Each sample is logged under DEBUG; the result under INFO: maximum,
minimum, range, average, median and (population) standard deviation.

## PROBE_CALIBRATE

Klipper's paper test for `z_offset` (MDI; `ProbeCalibrateService`), Z homed:

1. `PROBE_CALIBRATE [SPEED=5]` probes at the current X, Y, lifts 5 mm,
   moves the nozzle by `x_offset`, `y_offset` (over the spot the probe
   touched) and lowers it back to the trigger height. Bed mesh
   compensation is switched off for the test.
2. Lower the nozzle until a sheet of paper just drags: the Z jog, or
   `TESTZ Z=-0.1` (relative mm, up to ±5; `TESTZ Z=0.05` back up). Each
   `TESTZ` logs the `z_offset` the nozzle's height gives.
3. `ACCEPT` logs `z_offset = trigger Z - nozzle Z` under INFO, to put into
   the `.cfg` (`[probe] z_offset`) before generating the machine again;
   `ABORT` ends the test without a value.
