# Lessons Learned

A running log of mistakes, near-misses, and irreversible truths
the team has paid for. Each entry is ordered newest-first so the
freshest thinking is at the top. New entries should be added at the
**top** of the appropriate section, not the bottom.

## 1. Module system (retired — history only)

> **This entire system no longer exists.** There was once a dynamic
> frontend module registry (`frontend/src/modules/<id>/`, an eager
> `import.meta.glob` registry, a `module_<id>` Pinia store-id
> convention, a `MODULES_ENABLED` whitelist, `check-no-lazy-imports.mjs`
> / `check-store-ids.mjs` lint scripts). It has been fully removed;
> the frontend now imports views/components directly (see
> [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) § 2). None of
> the fixes below apply to the current codebase — they are kept as
> **general lessons** (the failure mode can recur in a different
> shape) not as **current instructions**.

### 1.1 A "lazy module disabled at build time" path hides missing dependencies

**Symptom.** A previous revision made frontend modules lazy-loaded
so a whitelist could prune the production bundle. The lazy glob hid
module dependencies: deleting a module folder left the build green
because nothing referenced the deleted path statically.

**General lesson.** If a future feature needs conditional inclusion
(a build-time flag, an optional integration), prefer a pattern where
removing the thing being conditioned on breaks the build loudly —
static imports, not a glob that silently returns fewer entries.

### 1.2 A local naming convention prevented store-id collisions

**Symptom.** A module-scoped Pinia store collided with a top-level
store of the same id, silently shadowing it and breaking the
dashboard.

**General lesson.** When two independent parts of the codebase can
both register something under a shared namespace (store ids, event
names, settings keys), a naming convention plus a lint check is
cheap insurance. There is no module-scoped Pinia namespace to
protect today, but the same risk exists wherever two stores could
plausibly pick the same id — check `frontend/src/stores/` for
existing names before adding a new one.

### 1.3 `activePinia` boot-timing race

**Symptom.** An early revision had feature stores constructed
lazily on first `useXxxStore()` call, but the lazy path raced with
the Pinia 3.x boot order.

**General lesson.** `main.ts` calls `app.use(pinia)` before mounting
the app; anything that calls `useXxxStore()` outside of a component
setup or a store action should confirm it runs after that call, not
before.

### 1.4 (retired) Empty module directory had to still build

Historical only — there is no `frontend/src/modules/` directory to
be empty or non-empty. No current equivalent.

### 1.5 Snapshots vs lazy shims

**Symptom.** A round-trip refactor of the temperature panel wiped
the rolling chart history; the polled array was re-created on every
component mount.

**Root cause.** The component held the array in a local `ref`
instead of reading from the Pinia store.

**Fix — still current.** Store-owned `reactive` containers
(`frontend/src/stores/temperatureStore.ts`); the component reads
through `storeToRefs`. The store outlives the mount/unmount/remount
cycle, so the chart history survives.

## 2. Frontend discipline

### 2.7 Never hand-roll HTTP calls when a generated OpenAPI service exists

**Symptom.** A domain store shipped with a local `postJson` helper
plus raw `fetch()` calls for every backend route instead of the
generated client. A backend field rename silently breaks the
hand-written `fetch` while the generated client tracks it via
`npm run generate-api`.

**Fix — still current.** Every backend module endpoint has a
generated counterpart under
`frontend/generated/api/services/Modules<Name>Service.ts` (e.g.
`ModulesToolsService.ts`, `ModulesTemperatureService.ts` — see
`frontend/generated/api/services/` for the full list, one per
module id plus a `*SettingsService.ts` per module for the settings
endpoints). Domain stores under `frontend/src/stores/` should
import the service and call its static methods rather than
hand-rolling `fetch`.

**One exception.** `frontend/src/core/settings/createModuleSettings.ts`
is deliberately hand-rolled `fetch` so callers keep working when
`generated/api/` is stale — e.g. a fresh checkout before
`npm run generate-api` has run. The exception is the **settings**
endpoint, not the data endpoints.

**Tripwire.** No `fetch(...)` call in a store file outside of
`createModuleSettings.ts`. `frontend/tests/test-tools-module.ts`
is the closest thing to an automated guard today — it asserts the
tools store consumes `useBaseThreadStore()` rather than its own
polling/fetch, and it does not currently regex-ban a stray `fetch(`
call directly, so a new hand-rolled `fetch` in a different store
would not be caught automatically. Treat this as a code-review
check until a dedicated lint exists (see `.agent/HANDOFF.md` § 2).

### 2.5 Strict-null idempotency gate silently disables the poll

**Symptom.** The `baseThread` store's `start()` was called at app
mount from `App.vue`, but the 1 Hz REST poll never fired. The
WebSocket telemetry worked, but the temperature sensor dict and
tool list stayed empty indefinitely. No error was logged.

**Root cause.** The action used a strict-null check on its
non-state handle:

```js
start() {
  if (this._pollHandle !== null) return;   // BUG
  this._pollHandle = setInterval(...);
}
```

`_pollHandle` is a non-state property on the Pinia store
instance, so it starts as `undefined`. The expression
`undefined !== null` evaluates to `true`, and the function
returned early on the first call — never scheduling the
`setInterval`. The companion test asserted the broken check
(`/if\s*\(\s*this\._pollHandle\s*!==\s*null\s*\)\s*return/`) so it
"protected" the bug instead of catching it.

**Fix.** Use a truthy check that catches both `undefined` and
`null`:

```js
start() {
  if (this._pollHandle) return;        // catches undefined AND null
  this._pollHandle = setInterval(...);
}
stop() {
  if (!this._pollHandle) return;       // symmetric
  clearInterval(this._pollHandle);
  this._pollHandle = null;
}
```

The companion test was updated to match the truthy check AND
gained an `assert.doesNotMatch` that explicitly forbids the
broken strict-null pattern, so the regression cannot be
reintroduced silently.

**Tripwire.** Any idempotency gate on a non-state property must
use a truthy check (`if (this.handle)`) or the loose-null check
(`if (this.handle != null)`). Strict-null (`!== null` / `=== null`)
silently breaks on the first call when the property has never
been set.

**See also.** `frontend/src/stores/baseThread.ts`,
`.agent/STATE.md` § 1.4.

### 2.6 Cross-module reactivity needs `deep: true` and a sync ingest

**Symptom.** A consumer module's `watch(() => baseThread.sensors, ...)`
never fired when the baseThread store's `refresh()` action updated
the `sensors` ref via `this.sensors = next`. The UI rendered the
empty state indefinitely.

**Root cause.** Pinia OPTIONS-API state is wrapped in `reactive()`
and exposed via the store proxy. Top-level reassignment
(`this.sensors = next`) inside an action triggers reactivity for
the *owning* store, but the rebroadcast through `storeToRefs` and
across module boundaries intermittently misses the trigger. The
default `deep: false` watcher only fires on reference change, and
the timing of the proxy read in a sibling module can see the
new value already without firing the side effect.

**Fix.** Two changes:

1. Pull the current value synchronously at setup time so the
   panel renders populated on the first frame, regardless of
   whether the first 1 Hz tick has landed:

```js
const baseThread = useBaseThreadStore();
ingest(baseThread.sensors);            // sync initial pull
stopSensorWatch = watch(
  () => baseThread.sensors,
  (next) => { if (next) ingest(next); },
  { immediate: true, deep: true },     // deep: true for cross-module
);
```

2. Always pass `deep: true` for any cross-module watcher over a
   baseThread snapshot field. The payload is small (a handful of
   sensor / tool rows) so the deep-traversal cost is negligible.

**See also.** `frontend/src/stores/temperatureStore.ts`,
`frontend/src/stores/toolsStore.ts`, `.agent/STATE.md` § 1.4.

### 2.1 No hardcoded G-code in components

**Symptom.** Reviewers found `M3 S{speed}` and `G10 L20 P0`
string literals scattered across `.vue` files.

**Root cause.** Each author built their own helper.

**Fix.** All G-code construction lives in
`frontend/src/config/gcodes.ts`. Export helper functions like
`generateSetOffset(axis, value)`; consumers import the helper,
never the G-code string.

### 2.2 No monolithic `App.vue`

**Symptom.** `App.vue` grew to 400+ lines and held the WebSocket
subscription, the route map, and the active print widget.

**Root cause.** "I'll just put this here for now, refactor later."
Later never came.

**Fix.** `App.vue` is a layout wrapper. It renders the sidebar and
the active view via `<router-view>` (the static route table in
`frontend/src/router/index.ts` — see `ARCHITECTURE.md` § 2.2). Any
logic > 5 lines belongs in a component or a store.

### 2.3 `storeToRefs()` is mandatory when destructuring

**Symptom.** A widget stopped updating when the underlying state
changed.

**Root cause.** The component destructured Pinia state with plain
ES destructuring: `const { droX } = useMachineStore()`. This
captured the value at destructuring time, losing reactivity.

**Fix.** Always `const { droX } = storeToRefs(useMachineStore())`.

### 2.4 Cross-store calls belong inside actions

**Symptom.** Adding a `useConsoleStore()` import at the top of a
Pinia store file broke the other store's initialization.

**Root cause.** Circular import: store A imports store B at module
scope; store B imports store A at module scope; Pinia evaluates
both before the dependency graph is settled.

**Fix.** Cross-store dependencies are resolved inside the action
method, not at module scope. The action runs at call time when
both stores are guaranteed initialized.

### 2.5 `console.log` is forbidden in production code

**Symptom.** Operators reading the console store saw raw
`console.log` lines mixed with structured messages.

**Root cause.** Some `console.log` survives in places because the
author wanted a quick debug line.

**Fix.** Use `consoleStore.debug(...)` (or the appropriate level).
The store forwards to the persistent logger and the operator UI
filter chips both see it.

## 3. Backend discipline

### 3.5 Use the `HalPin` subclass architecture instead of writing HAL from services

**Symptom.** A first cut of the critical E-Stop endpoint reached
for a generic `write_hal_pin()` helper in `hardware.Connection` and
called it directly from `StateService.activate_estop()`. The helper
did the right thing internally — `hal.setp` with a 2 ms sleep and a
0 → 1 rising-edge dance — but the policy was inlined into the
service: the service imported `time`, knew about servo periods, and
owned the edge-generation sequence.

**Root cause.** The codebase already has a typed HAL-pin OOP
hierarchy under `backend/common/dtos/pins/`: `HalPin` (ABC, generic
over `T`), `UnconnectedHalPin`, `StaticHalPin`,
`ReadOnlyDynamicHalPin`, `ReadWriteDynamicHalPin`, plus domain
wrappers like `EStopPin` (`backend/common/dtos/EStopDto.py`). Services
hold `self._foo: HalPin = UnconnectedHalPin()` typed properties
and swap in the real pin in `preload_hal_pins()`, called once at
boot right before `HalPin.initialize_component()`. The pattern is
already established by `ToolsService`, `TemperatureService`, and
the per-tool / per-sensor mappers. Reaching for a free-floating
helper bypasses it.

**Fix.** Domain-specific behaviour — edge generation, debouncing,
pulse shaping, safety interlocks — belongs in a small `HalPin`
subclass. The service stays a thin facade over `set_value()` /
`get_value()`:

```python
def __init__(self):
    self._Estop: HalPin = UnconnectedHalPin()

def preload_hal_pins(self):
    self._Estop = EStopPin(
        "estop",
        ReadWriteDynamicHalPin("estop", HalDataType.BIT, ""),
    )

def activate_estop(self) -> None:
    try:
        self._Estop.set_value(True)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"HAL unreachable — cannot set webgui.estop: {e}",
        )
```

The `webgui.estop` pin is created automatically by
`HalPin.initialize_component()` (component name comes from
`HalPin._component_name = "webgui"`) and routed to
`halui.estop.activate` via the project's hand-written HAL file.
The rising-edge dance lives inside `EStopPin`, never inside the
HTTP service. No `time.sleep` in a service file, no `hal.setp` in
a service file, no edge policy leaking into HTTP code.

**Bootstrap order matters.** `preload_hal_pins()` only *queues*
pins in `HalPin._pending_pins`; the actual HAL pins are created
when `HalPin.initialize_component()` is called. The machine
backend's boot sequence (`backend/machine/main.py`) must therefore
run every `*.preload_hal_pins()` before the single
`HalPin.initialize_component()` call. Reversing the order — or
splitting `initialize_component()` across multiple call sites —
leaves the HAL component locked with zero pins, and the service's
typed `HalPin` properties silently stay `UnconnectedHalPin()` for
the lifetime of the process.

**Tripwire.** A backend service file must not call `hal.setp`,
`hal.set_p`, or `Connection.write_hal_pin` directly. All HAL writes
must go through a `HalPin` subclass property assigned by a
`preload_hal_pins()` method — a scan of every file under
`backend/machine/services/` (excluding `backend/common/dtos/pins/`)
for those names, outside `preload_hal_pins()` or
`initialize_component()`, is the manual check today (no automated
guard yet — see `.agent/HANDOFF.md` § 2). It pairs with the "no
endpoints in `main.py`" lesson (§ 3.1) and the "hardware calls go
through the singleton `connection`" lesson (§ 3.2); both reject the
same anti-pattern from a different angle.

### 3.1 No endpoints in `main.py`

**Symptom.** A refactor of the WebSocket telemetry loop broke
three unrelated endpoints because they were inlined into `main.py`.

**Root cause.** "Just one quick endpoint" became five.

**Fix.** Every endpoint lives in a router under
`backend/<app>/routers/`. Per-domain routers are mounted directly
from `backend/<app>/routers/<id>.py` in that app's own
`main.py:_MODULE_DOMAINS` (see `.agent/contracts/backend-router.md`).
Neither `backend/machine/main.py` nor `backend/system/main.py`
declares endpoints directly — each only includes its routers and
runs its own lifespan.

### 3.2 Hardware calls go through the singleton `connection`

**Symptom.** A developer on a Windows laptop could not run the
test suite because `import linuxcnc` failed.

**Root cause.** Feature code imported `linuxcnc` directly.

**Fix.** `backend/common/hardware/Connection.py` is the only place
that imports `linuxcnc`. It falls back to `backend/common/hardware/mock/`
on `ImportError`. Feature code calls `execute_sync_cmd(...)` on the
connection.

### 3.3 The jog watchdog is a contract, not a config

**Symptom.** A test that pinged the keep-alive at 100 ms passed
locally but the machine still ran away on the shop floor.

**Root cause.** The watchdog timeout was being read mid-flight
from settings, so a `PUT /settings` value could extend the
window above the documented 500 ms.

**Fix.** The watchdog reads its timeout **once** at startup, from
the persisted settings. Mid-flight changes take effect on the
next backend restart. The 500 ms default is the contract; the
explicit `// 500 ms keep-alive watchdog` comment is the tripwire.

### 3.4 Atomic file writes for settings

**Symptom.** A crash mid-write left a half-written
`modules/<id>/settings.json` and the next boot read a corrupt
JSON file.

**Root cause.** `open(path, 'w').write(content)` is not atomic.

**Fix.** `tempfile.mkstemp` + `fsync` + `os.replace`. The previous
file stays intact until the new one is fully flushed.

## 4. Module migration order

### 4.1 Camera module does not own capture

The previous implementation kept a background thread with an OpenCV
``VideoCapture`` open on every active camera. The fragility of that
loop (Windows C++ exceptions on locked hardware, ``opencv-python``
wheels emitting SIGILL on mismatched ABIs, ``cv2.imencode`` paying
a numpy round-trip per frame) and the cost of supporting per-frame
``jpeg_quality`` / ``target_fps`` knobs pushed the streaming concern
out of the backend.

The camera module is now a thin layer on top of ``ustreamer`` — a
pure-C MJPEG/HTTP server that already powers every 3D-printer
camera panel on the planet (OctoPrint, Mainsail, Fluidd). Each
detected ``/dev/videoN`` device gets its own ``ustreamer``
subprocess bound to ``http://127.0.0.1:{8080+index}/?action=stream``;
the backend ``/stream`` endpoint is a 302 redirect to that URL.

**Tripwire.** Do NOT reintroduce ``cv2`` into
``backend/machine/routers/camera.py`` (or any sibling under
`backend/`). The `UstreamerSupervisor` owns the only process
boundary the camera needs; any new capture code in the backend is
the regression vector that brings SIGILL back. If a future feature
needs per-frame processing (e.g. an on-screen reticle), do it in
``ustreamer``'s user-facing overlays or in a separate frontend
canvas — never in Python.

### 4.2 Dependency diagnostics for external binaries

When a backend feature depends on an external binary (``ustreamer``
today; could be ``ffmpeg`` / ``gst-launch-1.0`` / ``mjpg_streamer``
tomorrow), wire a single-line ``message`` field through the status
endpoint so operators can distinguish:

* "dependency missing" — the binary is not on ``$PATH``;
* "device unplugged" — ``/dev/videoN`` is absent;
* "platform unsupported" — ``sys.platform`` is not Linux;
* "child crashed" — the subprocess exited non-zero.

Generic 503s look like camera bugs. A plain-English hint
("ustreamer is not installed on this host. Run 'sudo apt install
ustreamer' on the LinuxCNC controller.") makes the operator's next
step obvious and removes the "is this a hardware problem?" guess.
The CameraViewer renders ``streamMessage`` verbatim with an amber
"Camera unavailable" panel; the CameraSettings panel surfaces the
same string in its empty-state row; and the camera store emits a
single console-store row per distinct diagnostic value so the
operator console does not go quiet during a sustained outage.

### 4.3 Migration order (historical — the module-to-flat-router migration)

This predates the current architecture (it describes the order used
when the old `PluggableModule` system was flattened into per-domain
routers, and later when the frontend module registry was retired
entirely). Kept because the general lesson still holds: migrate the
highest-fan-in dependency first.

The order that worked:

1. **camera** — self-contained, no shared state, no telemetry,
   easy to migrate in isolation.
2. **temperature** — shared mock state but simulation stays in
   the hardware mock layer; main risk is the polling loop.
3. **machine / axis** — largest, safety-critical keep-alive /
   watchdog, owns the WebSocket subscription, drives nearly every
   other domain.
4. **program** — simple once machine is done.
5. **files, system, config, machine-config generation** — low-
   coupling; migrated one at a time.
6. **telemetry refactor** — decouple the WebSocket from any single
   domain's store (this became the servo-thread / base-thread
   split, see `ARCHITECTURE.md` § 2.4).

If you reverse the order, the migration costs roughly 3× because
the machine domain's WebSocket + watchdog is the dependency root
for nearly everything else.

## 5. Test discipline

### 5.1 The test suite is the contract, not the documentation

**Symptom.** A refactor "according to the docs" broke 12 tests
across 5 files because the docs and the tests had drifted apart.

**Root cause.** The regex tests in `frontend/tests/*.mjs` look for
specific string shapes in the source. When the source changes
shape (renaming a symbol, switching from `console.log` to
`consoleStore.debug`, dropping a Vue prop), the tests fail loudly.
The docs say "the test suite is the contract" — the tests reflect
the new contract, and the docs follow.

**Lesson.** When the source changes shape, update the tests in
the same commit. Don't leave the docs lying.

### 5.2 `node --test` cannot drive Pinia

**Symptom.** Attempting to invoke a Pinia store at test time
crashed with `Cannot read properties of undefined (reading '_s')`.

**Root cause.** `node --test` runs without the Vite runtime, so
`activePinia` is never set.

**Fix.** The frontend tests are **static-structural** — they read
files and assert on regex patterns. The dynamic / type-level
regressions are caught by `npm run build` (which runs through
Vite) and the manual smoke test.

### 5.3 Playwright is out of scope for CI

**Symptom.** A "full e2e" dream-list item keeps reappearing.

**Root cause.** Maintaining a Playwright suite against a real
LinuxCNC box is its own project.

**Fix.** The CI surface is: `npm --test` + `pytest` + `npm run
build` + `python -m compileall`. End-to-end checks live in the
manual smoke checklist, not the CI matrix.

## 6. AI agent / orchestrator boundaries

### 6.1 The agent runs tests, the orchestrator owns the result

**Symptom.** An AI agent ran `pytest` after every edit, taking
~30 s per cycle. The orchestrator's deterministic test runner
already does this.

**Root cause.** The agent's instruction file did not say "don't
run tests; the orchestrator does."

**Fix.** `.agent/AGENT.md` is the repository agent guide; the
no-commits / no-tests / no-PRs rules for the in-repo agent role
are enforced by the orchestrator out-of-repo. The agent writes
code and a summary; the orchestrator handles commit, push, test,
and PR.

### 6.2 The "honest no-op"

**Symptom.** An AI agent invented a plausible-looking patch to
hide a missing dependency instead of asking.

**Root cause.** The agent prefers "useful" over "honest."

**Fix.** The "honest no-op" rule is enforced by the orchestrator
out-of-repo: state the attempts, state the blocker, state the next
human step. A credible fake fix is worse than a real "blocked."

### 6.3 The venv cache trap

**Symptom.** A subsequent run after an interrupted `python3 -m
venv .venv` found the empty `.venv` folder, skipped the rebuild,
and crashed when `.venv/bin/activate` did not exist.

**Root cause.** `.gitignore`d folders survive `git clean -fd`; a
naïve `[ ! -d ".venv" ]` cache check cannot tell the difference
between a complete and a partial venv.

**Fix.** Check the activation file, not the directory:
`[ ! -f ".venv/bin/activate" ]`. On miss, `rm -rf .venv` first so
the rebuild is self-healing.

### 6.4 Multi-cycle agents saturate the circuit breaker

**Symptom.** An agent that explored for 30+ tool calls before
writing any code tripped the orchestrator's circuit breaker.

**Root cause.** The agent treated the orchestrator's budget as
unbounded.

**Fix.** `.agent/AGENT.md` sets the conventions and quality/scope
rules; the read/write budget and circuit-breaker thresholds are
enforced by the orchestrator out-of-repo. The anti-patterns
remain: read minimum, write minimum, do not browse, do not hedge.

## 7. Hot debris (known limitations to track)

See [`.agent/HANDOFF.md`](.agent/HANDOFF.md) § 2 for the maintained
technical-debt list (the two-backend split, typing-discipline
tooling gaps, pre-existing test failures, etc.). The items below are
smaller/older observations not worth a full HANDOFF.md entry:

- `DebugPanel.vue` polls `JSON.parse(JSON.stringify(useMachineStore()))`
  every 3 seconds rather than subscribing to the event bus.
- `CameraViewer.vue` uses a raw `<img src>` because the stream is
  MJPEG, not typed JSON. This is expected to stay raw.
- The jog watchdog hard-caps its own lifetime at 10 minutes per
  loop. Bounds the impact of a buggy loop in CI/test environments.
- Multi-machine, remote access, and time-series DB logging are
  out of scope for the current vision (see `VISION.md`).
