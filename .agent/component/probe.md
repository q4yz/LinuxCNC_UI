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
```

An empty `[probe]` block (no `pin` at all) is valid but contributes
nothing to `machine.hal` — same leniency as every other component,
just with no UI-only fallback behind it.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "probe": {
    "pin": "<parameters.pin | null>"
  }
}
```

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
