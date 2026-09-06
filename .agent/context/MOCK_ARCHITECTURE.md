# Mock Architecture

The mock layer lives under `backend/common/hardware/mock/`. It is the
fallback the `hardware.Connection` module picks when the real
`linuxcnc` C extension is unavailable (typically: any Windows
dev host). The FastAPI app must boot and every test must run
without LinuxCNC installed, so the mock has to be a faithful
substitute for the production NML + HAL surface.

> **Read this before editing anything under `backend/common/hardware/mock/`.** The
> layered split below is load-bearing — feature code talks to the
> facades, facades talk to the `HalMock` + `StateMachineMock`
> singletons, those singletons own the lifecycle. Skipping a layer
> (e.g., writing to the central pin dict directly) breaks both
> mock and production.

---

## 1. Why the mock exists

* **Windows development hosts.** `linuxcnc` and `hal` ship as C
  extensions; importing them on Windows raises `ImportError`. The
  `Connection` module catches that and substitutes the mock
  facades so every other piece of feature code is OS-agnostic.
* **Integration tests.** The mock's `update()` tick is synchronous
  and instantaneous, so test assertions can read the state
  machine right after the action without race conditions.
* **Operator demos.** A laptop without a LinuxCNC install can run
  the dashboard and exercise every UI flow against the mock.

The mock is **not** an emulator. It simulates the wire contract —
NML state transitions, HAL pin values, error channels — but it does
not simulate servo-period timing, SPI latency, or HAL realtime
thread semantics. Tests that depend on those belong in the bench
test rig against real LinuxCNC, not in the mock test surface.

---

## 2. Layered structure

```
                        ┌──────────────────────┐
   feature code  ──────► │  HalModuleFacade     │  ← what feature code touches
                        │  LinuxcncModuleFacade│
                        └─────────┬────────────┘
                                  │ translates get_value / set_p / setp / component() / command()
                                  ▼
                        ┌──────────────────────┐
                        │     HalMock          │  ← central pin registry
                        │     ("Muscle")       │     iterates components on every set/get
                        │  + StateMachineMock  │  ← NML state ("Brain")
                        │     ("Brain")        │     owns task_state, estop, interp_state,
                        │                      │     axes, errors, error-channel queue
                        └─────────┬────────────┘
                                  │ broadcasts writes; ticks update() every 100 ms
                                  ▼
                        ┌──────────────────────┐
                        │   MockComponent      │  ← per-feature subclasses
                        │   subclasses         │     MockHeater, MockSpindleDigital,
                        │                      │     MockSensor, MockExtruder,
                        │                      │     MockEStopComponent, …
                        └──────────────────────┘
```

* **Top (facades)** — `HalModuleFacade` and `LinuxcncModuleFacade`
  in `backend/common/hardware/mock/facade/`. These are drop-in replacements for
  the real `hal` and `linuxcnc` Python modules. They are what
  `hardware.Connection` exposes to feature code.
* **Middle (singletons)** — `HalMock` (pin registry) and
  `StateMachineMock` (NML state). Constructed once by
  `LinuxCNCMock.__init__` and reused for the process lifetime.
* **Bottom (per-feature)** — `MockComponent` subclasses in
  `backend/common/hardware/mock/tools/` (and a few directly under `backend/common/hardware/mock/`
  for the always-on ones). Each owns a slice of the pin namespace.

The `LinuxCNCMock` top-level singleton in `backend/common/hardware/mock/LinuxCNCMock.py`
wires the three layers together and exposes `hal`, `linuxcnc`, and
the two raw singletons (`internal_hal`, `internal_state`) for tests
that need to introspect or seed state.

---

## 3. Pin write propagation

A typical pin write (e.g., `webgui.estop = 1` from the
`EStopPin.set_value(True)` path) walks this chain:

```
ReadWriteDynamicHalPin.set_value(1)
   └─► HalPin._comp_instance["estop"] = 1
         └─► MockComponent.__setitem__            (facade.MockHalComponent)
               └─► HalMock.set_pin("webgui.estop", 1)
                     └─► for each registered component:
                           component.set_pin("webgui.estop", 1)
                           └─► first to return True wins
                                 └─► e.g. MockEStopComponent
                                       └─► state_machine.trigger_estop()
                                             └─► StateMachineMock
                                                   ├─ self.estop = 1
                                                   ├─ self.task_state = STATE_ESTOP
                                                   └─ self.interp_state = INTERP_IDLE
```

The `HalMock.set_pin` broadcast is `O(N)` over registered
components. `MockComponent.set_pin` returns `False` for any pin
it does not own, so the broadcast terminates at the first
match. Order of registration does not affect correctness — the
**owner** of the pin is the only component expected to return
`True`.

Reads follow the same pattern in reverse: `HalMock.get_pin`
iterates registered components and returns the first non-`None`
value from `component.read_pin(...)`.

---

## 4. Adding a new mock component

Step by step, regardless of whether the component is **always-on**
or **tool-derived** (see § 5):

1. **Pick the layer.** Per-feature components subclass
   `MockComponent` from `backend/common/hardware/mock/tools/MockComponent.py`.
   The base class defines four overridable hooks:
   `read_pin`, `set_pin`, `execute_mdi`, `update`. The default
   implementations are no-ops returning `None` / `False`.

2. **Set a stable `id`.** `HalMock.register_component` dedups by
   `getattr(component, "id", None)`. A second registration with
   the same `id` replaces the first (logged at INFO). Always-on
   components use a literal id (e.g. `"estop"`); tool-derived
   components use the tool id from `hardware.json`.

3. **Build a `_pin_map` if you own multiple pins.** Map the full
   HAL pin name (`webgui.foo`) to the internal attribute that
   holds its value. Look it up in `read_pin` / `set_pin` and
   return `None` / `False` for anything outside the map.

4. **Implement `update` only if you have physics.** A passive
   sensor with no ramp-up leaves `update` as a no-op. A heater
   that ramps toward its target writes to its own internal
   attribute. Never mutate `state_machine` from inside `update`
   unless the contract requires it (e.g. axis limits triggering
   ESTOP, which is currently commented out — see the docstring
   on `StateMachineMock.update`).

5. **Register.** Always-on: add a line to
   `LinuxCNCMock.__init__`. Tool-derived: extend
   `MockToolFactory.create` to recognise your tool type.

6. **Add a test** under `backend/machine/tests/test_mock_<name>.py` that
   builds a `StateMachineMock`, instantiates the component,
   registers it on a fresh `HalMock`, and exercises the
   `set_pin` / `read_pin` / `update` contract.

---

## 5. Always-on vs tool-derived

The mock splits components into two lifetime classes. **Pick the
right one** — the wrong choice leaks state across tests or causes
tools to appear before a hardware.json has been reseeded.

| Lifetime | Where it lives | When registered | When torn down |
|----------|---------------|-----------------|----------------|
| **Always-on** | `backend/common/hardware/mock/MockEStopComponent.py` (and any future core safety component) | `LinuxCNCMock.__init__` | Never — exists for the process lifetime |
| **Tool-derived** | `backend/common/hardware/mock/tools/MockHeater.py`, `MockExtruder.py`, `MockSensor.py`, `MockSpindleDigital.py` | `MockToolFactory.create(payload_record)` inside `LinuxCNCMock.register_hardware` | Cleared by `reset_simulator_state()` between tests |

**Always-on** components are reserved for things that are not
operator-configurable and that a service can rely on at any tick.
The only member today is `MockEStopComponent` (subscribes to
`webgui.estop`); future additions would be overcurrent trips,
door-switch interlocks, or any other safety-critical signal that
must exist before any tool has been loaded.

**Tool-derived** components come from `payload["tools"]` in the
project's `hardware.json`. A typical test starts with
`reset_simulator_state()` (clears `mock_system.internal_hal._components`),
then calls `reseed_from_hardware_json()` to populate the tool list
for that test. If your component belongs to that lifecycle, route
it through `MockToolFactory`.

**Failure mode of the wrong choice.** An always-on component
placed in `tools/` is registered only after a hardware.json reseed
— tests that don't reseed will see a missing pin and fail with
`MOCK HAL: Writing to unassigned pin 'webgui.foo'`. A tool-derived
component placed in `LinuxCNCMock.__init__` will be present even
when the operator's hardware.json has no matching tool, leaking
state across reseeds.

---

## 6. Edge-triggered pins

The mock does **not** run a real-time thread. A pin write is
processed instantly inside `HalMock.set_pin` — there is no servo
period to cross, no realtime-vs-userspace gap, no race between
Python and a HAL kernel module.

This matters for pins that the real machine relies on edge
detection. The canonical example is `halui.estop.activate`: the
real `halui` component samples the pin each servo period and fires
`task.set_state(STATE_ESTOP)` on the **rising edge only**. The
mock's `MockEStopComponent` short-circuits that wire and calls
`state_machine.trigger_estop()` on **any truthy write**.

The 0 -> 1 dance performed by `EStopPin` (the pin wrapper in
`backend/common/dtos/EStopDto.py`) is what preserves the operator-visible
contract: each button press produces a 0-write followed by a
1-write across a 2 ms sleep. In the mock, both writes are
processed instantly by the same thread, so the net effect is one
ESTOP trigger per press — same as the real machine.

If a future pin requires true edge detection (e.g. a pulse
counter that needs to ignore repeated writes within a window),
implement it inside the subclass with a `_last_value` field and
return `True` only on transitions. Do not try to model realtime
thread semantics at the mock layer — the mock is synchronous.

---

## 7. Test helpers

`backend/common/hardware/mock/test_helpers/mock_helpers.py` exposes the
shortcuts used by integration tests. Use them in this order of
preference:

| Helper | Use when |
|--------|---------|
| `reseed_from_hardware_json(path=None)` | Test needs the full tool set from the default machine's `hardware.json` (resolved via `domain_file_services.paths.default_machine_hardware_json`, or a fixture path). Loads every tool-derived component. |
| `seed_temperature(sensor_id, actual, target=0)` | Test needs a temperature reading on a specific sensor without waiting for the heater ramp. Registers a fresh `MockHeater` on the fly. |
| `seed_spindle(spindle_id, actual_rpm, is_connected, error_count)` | Test needs spindle telemetry without waiting for VFD spool-up. Registers a fresh `MockSpindleDigital` on the fly. |
| `force_hal_pin(pin_name, value)` | Test needs to drive an arbitrary HAL pin directly. Bypasses the broadcast — only useful for pins whose owners don't validate writes. |
| `set_mock_task_state(state)` | Test needs the NML state machine in a specific task_state without going through the action path. |
| `reset_simulator_state()` | Pytest fixture that clears all registered components. Call before each test that registers its own. |
| `reset_program_state()` / `reset_error_history()` / `push_mock_error(...)` | Test needs the program lifecycle or error channel in a specific shape. |

These helpers are **test-only**. Do not import them from feature
code; the production runtime never needs to seed state.

---

## 8. Anti-patterns

* **Don't bypass the facades.** Calling `HalMock.set_pin` directly
  from feature code skips the `HalPin._comp_instance.__setitem__`
  layer and the `webgui.<name>` prefix; the pin name ends up wrong
  and the registered components see nothing.
* **Don't write to the central pin dict directly.** `HalMock`
  has no public `set_pin` accessors other than the broadcast;
  the broadcast is the contract. Tests that need to seed a value
  use `force_hal_pin` (which itself goes through the broadcast).
* **Don't add `update`-time side effects on `state_machine`.** The
  commented-out limit-switch code in `StateMachineMock.update`
  shows the historical pattern and is disabled because every
  integration test would then need to clear the limit-switch
  pins before each assertion. If a future feature genuinely
  needs that wiring, do it inside a dedicated `MockComponent`
  subclass's `update` — never inside `StateMachineMock.update`.
* **Don't register always-on components conditionally.** Either
  `LinuxCNCMock.__init__` registers `MockEStopComponent` or it
  doesn't — there is no `if some_feature_flag:`. Tests rely on
  the E-Stop pin existing on every mock boot.
