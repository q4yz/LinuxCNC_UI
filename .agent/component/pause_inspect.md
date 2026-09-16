> **Implemented status:** Machine-level safety feature, not a `.cfg`
> component — no `[pause_inspect]` section, no `hardware.json` key,
> no per-machine configuration at all (beyond hand-tuning the lift
> distance, § 3). It exists purely as a backend service surface plus
> an unconditional HAL binding, same split as E-stop:
>
> * `ProgramService.pause_inspect()`/`resume_program()`
>   (`backend/machine/services/ProgramService.py`) drive
>   `webgui.inspect-z-lift`/`webgui.inspect-spindle-inhibit` as plain
>   0/1 toggles through a `PauseInspectPin` container
>   (`backend/common/dtos/PauseInspect.py`), the same
>   `ReadWriteDynamicHalPin.set_value()` mechanism `StateService.
>   activate_estop()` uses for `webgui.estop`. `pause_inspect()` is a
>   separate, explicit operator action layered on top of a plain
>   `pause_program()` (`POST /pause`) — Pause alone only issues
>   `AUTO_PAUSE`, it does not touch the spindle or the tool position.
>   `resume_program()` is `async`: it releases the spindle inhibit
>   first and waits 2.5 s for the spindle to spin back up to speed
>   before retracting the Z lift (0.5 s), then dispatches
>   `AUTO_RESUME` — so the tool never re-enters the cut before the
>   spindle is at speed. The router endpoints (`POST /pause_inspect`,
>   `POST /resume`, `backend/machine/routers/program.py`) are `async`
>   and `await` it, exactly like `POST /estop/activate`.
> * `PauseInspectWebguiMapper` (`backend/system/services/halcompiler/
>   components/PauseInspectWebguiMapper.py`) unconditionally seeds
>   `webgui_connections.hal` (via `render_webgui_connections`, gated
>   on the same "is this a real machine payload" `estop` presence
>   check `EstopWebguiMapper` uses — every real `hardware.json` has
>   both) with the § 3 HAL below. No `machine.hal` contribution at
>   all — everything here is a `webgui_connections.hal`-only binding,
>   the operator-hand-editable file, since there is nothing
>   hardware-specific about it (unlike a spindle or heater, it needs
>   no physical pin).
>
> `preload_hal_pins()` must run before `HalPin.initialize_component()`
> at startup (`backend/machine/main.py`, both the mock-startup and
> `__main__` boot paths) — mirrors `tool_service`/`sensor_service`/
> `state_service`/`fans_service`. `_pause_inspect_pins()` also
> lazily initializes the pin container on first use if that boot
> sequence was somehow skipped (mirrors `StateService.get_halpins()`),
> so a fresh `ProgramService()` instance never raises `AttributeError`.

## 1. Why no `.cfg` ingestion

Unlike every other component in this directory, Pause & Inspect has
no hand-written config syntax and no `hardware.json` representation.
It is not something an operator's machine *has* or *lacks* — every
machine with a Z axis gets it (`[machine]` compilation only accepts
`kinematics: cartesian`, so every compiled machine has one). The only
per-machine tuning knob is the Z lift distance, and that lives as a
hand-editable `setp` in the generated `webgui_connections.hal` itself
(§ 3), not as a `.cfg` field — the same "operator hand-edits survive
regenerate" contract every `webgui_connections.hal` binding already
has.

## 2. UI ABSTRACTION (hardware.json)

None. `render_webgui_connections` reads no dedicated key for this
component — it fires whenever `payload.get("estop")` is a dict, same
gate as `EstopWebguiMapper`.

## 3. COMPILATION (HAL)

No `machine.ini` section, no `machine.hal` contribution.

webgui_connections.hal
```hal
# Pause & Inspect (external offsets & spindle inhibit)
net inspect-spindle-inhibit webgui.inspect-spindle-inhibit => motion.spindle-inhibit

# Enable the Z eoffset stage. 1 count = eoffset-scale machine units
# (mm) of lift — webgui.inspect-z-lift only ever carries 0/1, so this
# scale IS the lift distance. Tune by hand-editing this line; hand
# edits to webgui_connections.hal survive every regenerate.
setp axis.z.eoffset-enable 1
setp axis.z.eoffset-scale 1.0

# Safety: clear the offset the instant the machine loses enable (an
# E-stop, or anything else that drops iocontrol.0.user-enable-out) —
# wired from the native iocontrol pin directly, not [estop]'s optional
# estop-out signal (EstopHalMapper), since that only exists when the
# operator declared [estop].out_pin. A dangling net on a machine
# without one would fail to load; iocontrol.0.user-enable-out is
# always present.
net inspect-eoffset-clear <= iocontrol.0.user-enable-out
net inspect-eoffset-clear => axis.z.eoffset-clear

net inspect-z-lift webgui.inspect-z-lift => axis.z.eoffset-counts
```

## 4. Runtime sequencing

`pause_inspect()` (`POST /pause_inspect`) sets both pins `True`
together — engage the inhibit and the lift in the same call, order
does not matter going in (`motion.spindle-inhibit` takes effect
immediately either way).

`resume_program()` (`POST /resume`) reverses them asymmetrically,
because coming back out is not symmetric with going in:

1. `inspect-spindle-inhibit` -> `False` (spindle starts spinning up)
2. wait 2.5 s (spindle reaches speed)
3. `inspect-z-lift` -> `False` (Z retracts back into the cut)
4. wait 0.5 s (Z settles)
5. dispatch `AUTO_RESUME`

Calling `resume_program()` when `pause_inspect()` was never engaged
is a safe no-op on both pins (already `False`) — it still waits the
full 3 s and dispatches `AUTO_RESUME`, same as a plain resume would.

## 5. Signal names

`inspect-spindle-inhibit`, `inspect-z-lift`, `inspect-eoffset-clear`
are new — reserved here for any future component that needs to touch
`axis.z.eoffset-*` or `motion.spindle-inhibit`, so a second feature
never double-drives the same eoffset stage a machine only has one of.
