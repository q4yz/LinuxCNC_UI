> **Implemented status:** Two mappers split the § 3 HAL, matching the
> two things `[estop]` can affect:
>
> * `EstopWebguiMapper` (`backend/system/services/halcompiler/
>   components/EstopWebguiMapper.py`) unconditionally seeds
>   `webgui_connections.hal` (via `render_webgui_connections`) with a
>   plain `webgui.estop => halui.estop.activate` passthrough net — no
>   hardware needed, present on every machine. This is what makes an
>   empty `[estop]` block useful on its own for a UI-only machine.
>   `StateService.activate_estop()` (`backend/machine/services/
>   StateService.py`) generates the rising edge itself now — assert
>   `True`, hold ~50 ms, reset to `False` — rather than relying on a
>   HAL-side `oneshot` to turn a held level into a pulse; that turned
>   out not to be as simple as it sounds (a held level plus a HAL-side
>   reset has its own edge cases a Python-owned pulse doesn't). The
>   router endpoint (`POST /estop/activate`,
>   `backend/machine/routers/state.py`) is `async` and `await`s it.
> * `EstopHalMapper` (`backend/system/services/halcompiler/
>   components/EstopHalMapper.py`) emits the § 3 physical chain into
>   `machine.hal` when `fault_pin`/`out_pin` are declared — and
>   nothing at all when they aren't.
>
> Cardinality ("exactly one `[estop]`") is enforced by
> `services.machineconfig.hardware_json_generator.build_hardware_json`,
> not by the raw section parser — see that function's own docstring
> for why the boundary sits there (the same layer `MachineValidator`'s
> `E_NO_MCU` rule already uses for the analogous "machine has no MCU
> at all" case). The physical chain is skipped on a class-B MCU
> (Remora/EtherCAT) — that router's own `base_fragment()` already
> claims `iocontrol.0`'s enable chain for its SPI/EtherCAT link-health
> wiring; see § 3's "Physical chain" note. There `out_pin` joins the
> board's own `user-enable-out` signal (one HAL pin, one signal) and
> becomes a `Digital Pin` **output** module (`remora.output.NN`, the
> Remora-m8p fork's verified shape) with `Safe State: Low`: the physical
> level while LinuxCNC is disconnected is always Low — inverted pin or
> not (the firmware does not invert it), never configurable. The machine
> must be safe at Low.

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
# Nothing at all when fault_pin and out_pin are both unset — an
# empty [estop] block contributes zero lines here. EstopHalMapper
# only ever emits the physical chain below, per declared pin.

# --- IF parameters.fault_pin AND this pin's MCU is not class B ---
# Physical E-stop chain — grounded in the real reference machine,
# machine_config/example/PrintNC-WEBGUI/Machine.hal (lines 41-57).
# Not emitted here on Remora: RemoraRouterMapper.base_fragment()
# owns these iocontrol.0 pins for its SPI link-health chain, so when
# the fault_pin is read through that board (HalAssembler flags
# `_estop_fault`) it builds the latch itself, ANDing link + fault:
#   net user-request-enable <= iocontrol.0.user-request-enable => remora.SPI-reset estop-latch.0.reset
#   net remora-status <= remora.SPI-status => estop-latch.0.ok-in
#   net estop-fault => estop-latch.0.fault-in
#   net estop-ext <= estop-latch.0.ok-out => iocontrol.0.emc-enable-in
# Typical use: a relay / optocoupler on the motor supply when the
# physical E-stop cuts motor power but not the board's logic power.
# Relay coil on the motor supply, NO contact from the input to GND,
# `fault_pin: ^PG11`: power OK pulls the pin low (no fault); power
# lost — or a broken wire — lets the pull-up read high = fault.
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
# --- IF parameters.out_pin on a Remora board (class B) ---
net user-enable-out => remora.output.NN       # + config.txt "Digital Pin" Mode Output, Safe State Low
```

webgui_connections.hal
```hal
# UI trigger — unconditional, present the moment [estop] exists at
# all (even empty). webgui.estop is already a clean 0 -> 1 -> 0 edge
# by the time HAL sees it: StateService.activate_estop() generates
# the pulse itself (assert True, hold ~50 ms, reset False) rather
# than leaving edge generation to a HAL-side oneshot, so this is a
# plain passthrough — no different in kind from a spindle's
# TargetRpm binding.
# Estop
net estop-activate webgui.estop => halui.estop.activate
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

Two new generic `PinRole`s (`models/machineconfig/HalFragmentModels.py`)
back this component, reusable by any future component needing a plain
digital input/output that isn't an endstop:

| Role | Meaning | Parport | Remora |
|---|---|---|---|
| `DIGITAL_IN` | plain level read | `pin-NN-in`/`-in-not` | `remora.input.NN` + `"Digital Pin"`/`Mode: Input` (shares one bit-space with `ENDSTOP`) |
| `DIGITAL_OUT` | plain level write | `pin-NN-out` | `remora.output.NN` + `"Digital Pin"`/`Mode: Output`, own bit-space, `Safe State: Low` always (+ `Invert` for `!pin`) |

`estop-out` / `estop-fault` are the "machine core" signal names
`.agent/component/README.md` § 5 already reserved for this component
before it existed.
