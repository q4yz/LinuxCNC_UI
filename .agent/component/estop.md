> **Implemented status:** `EstopHalMapper` (`backend/system/services/
> halcompiler/components/EstopHalMapper.py`) emits the § 3 UI pulse
> chain unconditionally on every machine — no hardware needed — plus
> the § 3 physical chain when `fault_pin`/`out_pin` are declared.
> Cardinality ("exactly one `[estop]`") is enforced by
> `services.machineconfig.hardware_json_generator.build_hardware_json`,
> not by the raw section parser — see that function's own docstring
> for why the boundary sits there (the same layer `MachineValidator`'s
> `E_NO_MCU` rule already uses for the analogous "machine has no MCU
> at all" case). The physical chain is skipped on a class-B MCU
> (Remora/EtherCAT) — that router's own `base_fragment()` already
> claims `iocontrol.0`'s enable chain for its SPI/EtherCAT link-health
> wiring; see § 3's "Physical chain" note. No `Digital Pin` **output**
> firmware module exists for Remora yet (`out_pin` on that class): no
> real reference `config.txt` shows one — an honest gap, not a
> fabricated shape, same class as `heater.md`'s missing thermistor
> module.

## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for the block matching
the syntax below.
**Component ID Format:** `[estop]` — bare only, no named-instance
form (unlike `[heater_*]` / `[spindle *]`). Exactly one is required
per machine; a second `[estop]` is a literal duplicate section,
already rejected for free by `configparser`'s own strict mode.

**Expected Syntax:**
```cfg
[estop]
    # --- Wiring: pins, exactly like every other component. Both
    # --- optional — an empty [estop] block is valid on its own. ---
    fault_pin: string // (Optional) physical E-stop loop's fault input
    out_pin: string // (Optional) mirrors LinuxCNC's own enable state out
```

An empty `[estop]` is a complete, valid, and common configuration —
it's what a UI-only machine (no physical E-stop hardware at all)
declares. The section's mere *presence* is what's required, not its
contents.

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "estop": {
    "fault_pin": "<parameters.fault_pin | null>",
    "out_pin": "<parameters.out_pin | null>"
  }
}
```

A top-level singleton object (not a list, not a `tools[]` entry) —
matches the cardinality: exactly one per machine. `build_hardware_json`
always emits it once `graph.estop` is set (which it must be —
`MissingEstopSectionError` otherwise); an empty `[estop]` block still
serialises as the present, empty object `{}`, never an absent key. An
absent key on a *hand-crafted* payload (this compiler's own older test
fixtures, or a hardware.json predating this feature) is tolerated at
the `HardwareJson` pydantic model layer (`estop: Estop | None = None`)
so those payloads still validate — only `build_hardware_json` itself
enforces the requirement on a freshly-parsed `.cfg`.

## 3. COMPILATION (INI & HAL)

No `machine.ini` section — E-stop has no tunable gains, nothing to
re-tune without regenerating HAL.

machine.hal
```hal
# --- UI pulse chain (unconditional — no hardware required) ---
#
# StateService.activate_estop() (backend/machine/services/
# StateService.py) just asserts webgui.estop True and leaves it
# there — a continuous level. halui.estop.activate needs a *rising
# edge* every time the operator presses the button, not a held
# level, so a oneshot turns the continuous UI signal into a pulse.
loadrt oneshot names=estop-pulse-generator
addf estop-pulse-generator servo-thread
setp estop-pulse-generator.width 0.1
net continuous-estop-in webgui.estop => estop-pulse-generator.in
net pulsed-estop-out estop-pulse-generator.out => halui.estop.activate

# --- IF parameters.fault_pin AND this pin's MCU is not class B ---
# Physical E-stop chain — grounded in the real reference machine,
# machine_config/example/PrintNC-WEBGUI/Machine.hal (lines 41-57).
# Skipped on Remora/EtherCAT: RemoraRouterMapper.base_fragment()
# already nets these same iocontrol.0 pins for its own SPI
# link-health chain — wiring estop_latch on top would double-drive
# them. The physical pin still routes (a real config.txt module);
# only this linkage is skipped.
loadrt estop_latch
addf estop-latch.0 servo-thread
net estop-fault => estop-latch.0.fault-in    # <- fault_pin (input)
net estop-reset <= iocontrol.0.user-request-enable
net estop-reset => estop-latch.0.reset
net estop-ext <= estop-latch.0.ok-out
net estop-ext => iocontrol.0.emc-enable-in

# --- IF parameters.out_pin AND this pin's MCU is not class B ---
net estop-out <= iocontrol.0.user-enable-out
net estop-out => <out_pin>                    # <- out_pin (output)
```

webgui_connections.hal
```hal
# Nothing here. webgui.estop is machine-core wiring (every generated
# machine needs it, regardless of what the operator hand-wires), so
# it lives in machine.hal via EstopHalMapper — not something an
# operator ever hand-wires per-machine the way a spindle VFD or a
# heater's fan is. See `pin_catalog.py`'s "EStopPin" entry for the
# read-only reference hint shown in machine.hal's own pin-reference
# appendix when a machine doesn't compile yet.
```

## 4. Validation rules

* `MissingEstopSectionError` — no `[estop]` section at all. Raised by
  `build_hardware_json`, not the parser (§ 1's cardinality note).
* Duplicate `[estop]` — free, via `configparser`'s own strict
  duplicate-section rejection (`MalformedConfigError`).
* `fault_pin`/`out_pin` participate in every *generic* pin rule the
  same way any other component's pins do — `E_UNKNOWN_MCU`,
  `E_NO_DEFAULT_MCU`, `E_PIN_CONFLICT`, `E_MALFORMED_PIN`
  (`MachineValidator._parsed_pins()` folds the top-level `estop`
  singleton into the same walk every list-shaped component's pins go
  through). Neither pin ever drives motion, so `E_MOTION_ON_IO_MCU`
  never applies to them.

## 5. Signal names

Two new generic `PinRole`s (`models/machineconfig/hal_fragment_models.py`)
back this component, reusable by any future component needing a plain
digital input/output that isn't an endstop:

| Role | Meaning | Parport | Remora |
|---|---|---|---|
| `DIGITAL_IN` | plain level read | `pin-NN-in`/`-in-not` | `remora.input.NN` + `"Digital Pin"`/`Mode: Input` (shares one bit-space with `ENDSTOP`) |
| `DIGITAL_OUT` | plain level write | `pin-NN-out` | no firmware module (honest gap — no real reference) |

`estop-out` / `estop-fault` are the "machine core" signal names
`.agent/component/README.md` § 5 already reserved for this component
before it existed.
