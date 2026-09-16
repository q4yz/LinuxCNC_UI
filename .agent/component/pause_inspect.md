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
>   all — everything here is a `webgui_connections.hal`-only binding.
>   `webgui_connections.hal` is regenerated from scratch on every
>   `generate_machine_templates` call (`services/machinetemplates/
>   generator.py`'s own module docstring — no longer preserved across
>   a regenerate), so a fix here reaches every existing machine the
>   next time it's (re)generated, not just new ones.
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
(§ 3), not as a `.cfg` field — but a hand-tune there does **not**
survive a regenerate (`webgui_connections.hal` is rewritten from
scratch every time, per `generate_machine_templates`'s own module
docstring), so it has to be re-applied after every regenerate.

## 2. UI ABSTRACTION (hardware.json)

None. `render_webgui_connections` reads no dedicated key for this
component — it fires whenever `payload.get("estop")` is a dict, same
gate as `EstopWebguiMapper`.

## 3. COMPILATION (INI & HAL)

machine.ini — `[AXIS_Z]` gets one extra key beyond the usual
`MAX_VELOCITY`/`MAX_ACCELERATION`/limits every axis has
(`ini_template_generator.py`'s `_render_axis_section`, gated on
`axis.letter == "Z"`):
```ini
[AXIS_Z]
MAX_VELOCITY = <...>
MAX_ACCELERATION = <...>
MIN_LIMIT = <...>
MAX_LIMIT = <...>
OFFSET_AV_RATIO = 0.2
```
Without it the eoffset wiring below is inert, not broken — LinuxCNC's
own default is 0, meaning zero velocity/accel budget is reserved for
external-offset motion, so `eoffset-counts` can be set to anything and
the axis simply never moves. No error, no warning, just a Z lift that
silently does nothing — manually verified against a real machine, and
`0.2` (20% of Z's own envelope reserved for the lift) is the verified
value that actually moves it.

`PauseInspectWebguiMapper.to_lines()` takes no arguments — see the
mapper's own module docstring for the full reasoning behind each
fix:

* **Spindle inhibit is per-spindle, not global.** There is no
  `motion.spindle-inhibit` pin — a real `halcmd show` confirms it is
  `spindle.N.inhibit`, indexed the same way every other spindle pin
  in this compiler already is (`DigitalSpindleHalMapper`'s
  `spindle.{n}.speed-out`/`.forward`/`.at-speed`). This mapper has no
  visibility into which spindle(s) a machine declares, so it targets
  `spindle.0.inhibit` — correct for the single-spindle case, an
  honest gap on a genuine multi-spindle machine.
* **`axis.z.eoffset-counts` is `s32`, `webgui.inspect-z-lift` is
  `bit`.** Linking them directly is a HAL load-time type mismatch —
  the same class of error `HeaterHalMapper`'s watermark branch already
  routes around (`comp.out` `bit` -> a `float` duty-cycle channel,
  `.agent/component/heater.md` § 3) via `conv_bit_float`. This uses
  the sibling `conv_bit_s32` the same way.
* **`axis.z.eoffset-clear`'s source had the wrong polarity.** An
  earlier version wired it from `estop-out`/`iocontrol.0.
  user-enable-out` (`EstopHalMapper`) — that pin is TRUE while the
  machine is powered on and healthy, FALSE on E-stop, the *opposite*
  of what "clear the lift on E-stop" needs. Wired that way,
  `eoffset-clear` was asserted continuously during normal operation,
  crushing the lift back to 0 every servo cycle before it could ever
  take effect — a real bug, manually verified on a real machine, not
  a hypothetical. `halui.estop.is-activated` (a standard `halui` pin,
  always present) is TRUE only while E-stop actually is active — the
  correct polarity, and unlike `estop-out` it needs no branching on
  whether `[estop].out_pin` is declared.

webgui_connections.hal:
```hal
# Pause & Inspect (external offsets & spindle inhibit)
net inspect-spindle-inhibit webgui.inspect-spindle-inhibit => spindle.0.inhibit

# Enable the Z eoffset stage. 1 count = eoffset-scale machine units
# (mm) of lift — webgui.inspect-z-lift only ever carries 0/1 (see the
# conv_bit_s32 stage below), so this scale IS the lift distance. Tune
# by hand-editing this line — NOT preserved across a regenerate (every
# file `generate_machine_templates` writes is rewritten from scratch),
# so re-apply after every regenerate. Needs [AXIS_Z] OFFSET_AV_RATIO
# > 0 (machine.ini) to actually move the axis at all.
setp axis.z.eoffset-enable 1
setp axis.z.eoffset-scale 1.0

# Safety: clear the offset while E-stop is actually active.
# halui.estop.is-activated (TRUE only during E-stop) — NOT
# iocontrol.0.user-enable-out / estop-out (TRUE while healthy, the
# opposite polarity — see module docstring for the bug this replaced).
net estop-is-active halui.estop.is-activated => axis.z.eoffset-clear

# webgui.inspect-z-lift (bit) -> axis.z.eoffset-counts (s32).
loadrt conv_bit_s32 names=inspect-z-lift-conv
addf inspect-z-lift-conv servo-thread
net inspect-z-lift-bit webgui.inspect-z-lift => inspect-z-lift-conv.in
net inspect-z-lift-s32 inspect-z-lift-conv.out => axis.z.eoffset-counts
```

## 4. Runtime sequencing

`pause_inspect()` (`POST /pause_inspect`) sets both pins `True`
together — engage the inhibit and the lift in the same call, order
does not matter going in (`spindle.0.inhibit` takes effect immediately
either way).

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

`inspect-spindle-inhibit`, `inspect-z-lift-bit`, `inspect-z-lift-s32`,
and `estop-is-active` are new — reserved here for any future
component that needs to touch `axis.z.eoffset-*`, `spindle.N.inhibit`,
or `halui.estop.is-activated`, so a second feature never double-drives
the same eoffset stage a machine only has one of. `spindle.N.inhibit`
is not new — every other `DigitalSpindleHalMapper` net already targets
`spindle.{n}.*`; this is just the first thing outside that mapper to
touch it. `estop-out` (`.agent/component/README.md` § 5, `estop.md`)
is no longer touched by this component at all (see § 3's polarity fix).
