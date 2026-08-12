# Lessons Learned

A running log of mistakes, near-misses, and irreversible truths
the team has paid for. Each entry is ordered newest-first so the
freshest thinking is at the top. New entries should be added at the
**top** of the appropriate section, not the bottom.

## 1. Module system

### 1.1 Eager glob imports pull excluded modules into the bundle

**Symptom.** The `MODULES_ENABLED` whitelist had no effect on the
frontend production bundle; every module's JS shipped even when
excluded.

**Root cause.** The original glob used `{ eager: true }`, so every
file matched by `import.meta.glob` was imported synchronously at
module-init time. The whitelist filter never ran because the JS
had already been pulled in.

**Fix.** `import.meta.glob(...)` everywhere with `{ eager: false }`.
The whitelist now actually prunes the bundle.

**Tripwire.** `frontend/src/core/modules/registry.js` carries a
tripwire comment: changing the glob to `eager: true` is a
regression; the union of "mounted ids" and "skipped ids" should
always equal the union of "all module ids".

### 1.2 Pinia store ids must be `module_<id>`, not `<id>`

**Symptom.** A module's Pinia store collided with the legacy
top-level `machine` / `console` stores, silently shadowing them
and breaking the dashboard.

**Root cause.** Naive `defineStore('machine', ...)` inside a module
folder; the runtime id was the same as the legacy monolith.

**Fix.** Pattern: `const STORE_ID = 'module_' + manifest.id;
defineStore(STORE_ID, ...)`. The lint script
`frontend/scripts/check-store-ids.mjs` enforces the
`^module_[a-z][a-z0-9_]+$` regex against every module store id.

**Tripwire.** Never hardcode a Pinia store id as a literal string
inside a module. Always build it from `manifest.id` so the lint
can reason about it.

### 1.3 `activePinia` boot-timing race

**Symptom.** Module stores crashed at app startup with
`Cannot read properties of undefined (reading 'has')` from inside
Pinia.

**Root cause.** `onLoad` hooks tried to call `useXxxStore()` before
`app.use(pinia)` had wired up the active Pinia instance. The
relative ordering of `main.js` and the import glob was fragile.

**Fix.** Module stores are lazy. The first `useXxxStore()` call
must come from a component, not from `onLoad`. The module's polling
loops / WebSocket handlers start when the panel mounts, not when
the registry boots.

### 1.4 Empty `modules/` folder must still build

**Symptom.** With no modules mounted, `npm run build` failed.

**Root cause.** Vite's glob collapses to `{}` when the directory
is empty, but a downstream consumer expected an array.

**Fix.** All consumers tolerate empty results. The registry logs
`mounted=[] skipped=0 missing=0` and the build succeeds.

### 1.5 Snapshots vs lazy shims

**Symptom.** A round-trip refactor of the temperature module wiped
the rolling chart history; the polled array was re-created on
every component mount.

**Root cause.** The component held the array in local `ref`s
instead of reading from the Pinia store.

**Fix.** Store-owned `reactive` containers; the component reads
through `storeToRefs`. The store outlives the mount/unmount/remount
cycle, so the chart history survives.

## 2. Frontend discipline

### 2.7 Never hand-roll HTTP calls when a generated OpenAPI service exists

**Symptom.** The tools store initially shipped with a local
`postJson` helper plus raw `fetch()` calls for every backend route
(`GET /tools`, `POST /spindle`, `POST /extruder`,
`POST /tools/{id}/target`). Same shape was duplicated in
`TemperaturePanel.vue` for the per-sensor target endpoint. The two
surfaces drift independently — a backend field rename silently
breaks the hand-written `fetch` while the generated client tracks
it via `npm run generate-api`.

**Root cause.** The generated `ModulesToolsService` (and its
peers under `frontend/generated/api/services/`) sits next to the
store, but the store's author reached for the familiar `fetch`
shape because every other module file already had a similar
helper. There was no tripwire so the regression stayed invisible.

**Fix.** Every backend module endpoint has a generated
counterpart under
`frontend/generated/api/services/Modules<Name>Service.ts`. Module
stores import the service and call its static methods; errors
flow through `describeError` from `core/error-format.js` so the
console store sees the same envelope shape as every other
module. The temperature module is mid-migration —
`TemperaturePanel.vue:37` still has raw `fetch` for the per-sensor
target endpoint; the store layer already consumes via
`useBaseThreadStore()`. Same lesson applies there.

**One exception.** `frontend/src/core/modules/settings.js` is
deliberately hand-rolled `fetch` (per its own header comment § 2)
so module stores keep working when `generated/api/` is stale —
e.g. a fresh checkout before `npm run generate-api` has run. The
exception is the **settings** endpoint, not the data endpoints.

**Tripwire.** No `fetch(...)` call in a module store file. The
template is `test-tools-module.mjs`:
- `assert.doesNotMatch(text, /\bfetch\s*\(/);`
- `assert.doesNotMatch(text, /\bpostJson\s*\(/);`
- `assert.doesNotMatch(text, /\/api\/v1\/modules\/<id>\//);`
- `assert.match(text, /import\s+\{[^}]*Modules<Name>Service[^}]*\}\s+from\s+["'][^"']*generated\/api\/services\/Modules<Name>Service/);`

Add the same guard to every module's `test-<id>-module.mjs` so a
future regression is caught before merge.

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

**See also.** `frontend/src/stores/baseThread.js` header comment
§ GOTCHAS, `.agent/STATE.md` § 12.6.

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

**See also.** `frontend/src/modules/temperature/store.js`,
`frontend/src/modules/tools/toolStore.js`, `frontend/src/stores/baseThread.js`
header comment § GOTCHAS.

### 2.1 No hardcoded G-code in components

**Symptom.** Reviewers found `M3 S{speed}` and `G10 L20 P0`
string literals scattered across `.vue` files.

**Root cause.** Each author built their own helper.

**Fix.** All G-code construction lives in
`frontend/src/config/gcodes.js`. Export helper functions like
`generateSetOffset(axis, value)`; consumers import the helper,
never the G-code string.

### 2.2 No monolithic `App.vue`

**Symptom.** `App.vue` grew to 400+ lines and held the WebSocket
subscription, the route map, the module switcher, and the active
print widget.

**Root cause.** "I'll just put this here for now, refactor later."
Later never came.

**Fix.** `App.vue` is a layout wrapper. It renders the sidebar and
the active view via `<router-view>` plus the module-owned override.
Any logic > 5 lines belongs in a component or a store.

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

### 3.1 No endpoints in `main.py`

**Symptom.** A refactor of the WebSocket telemetry loop broke
three unrelated endpoints because they were inlined into `main.py`.

**Root cause.** "Just one quick endpoint" became five.

**Fix.** Every endpoint lives in a router under `backend/routers/`
(legacy) or `backend/modules/<id>/router.py` (post-migration).
`main.py` only includes the routers and runs the lifespan.

### 3.2 Hardware calls go through the singleton `connection`

**Symptom.** A developer on a Windows laptop could not run the
test suite because `import linuxcnc` failed.

**Root cause.** Feature code imported `linuxcnc` directly.

**Fix.** `backend/hardware/connection.py` is the only place that
imports `linuxcnc`. It falls back to `linuxcnc_mock.py` on
`ImportError`. Feature code calls `execute_sync_cmd(...)` on the
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

The order that worked:

1. **camera** — self-contained, no shared state, no telemetry,
   easy nullable test.
2. **temperature** — shared mock state but simulation stays in
   `core/`; main risk is the polling loop.
3. **machine** (axis) — largest, safety-critical keep-alive /
   watchdog, owns the WebSocket subscription, drives every other
   module.
4. **program** — `program_router` in `routers/machine.py`; simple
   once machine is done.
5. **files, system, config, compiler** — backend-only or low-
   coupling; migrated one at a time.
6. **telemetry refactor** (Phase 4) — decouple WebSocket from
   machine module's Pinia store.

If you reverse the order, the migration costs roughly 3× because
the machine module's WebSocket + watchdog is the dependency root
for nearly every other module.

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

- `DebugPanel.vue` polls `JSON.parse(JSON.stringify(useMachineStore()))`
  every 3 seconds. Motivates Phase 4 (event-bus subscriptions).
- `CameraPanel.vue` uses raw `<img src>` because the stream is
  MJPEG, not typed JSON. Stays raw after migration.
- Legacy `backend/main.py` imports flat routers **and** boots the
  registry. Removing a module after migration must not remove the
  legacy `include_router` until the consumer has migrated.
- `MODULES_ENABLED` whitelist is "soft" on frontend (console.warn)
  and "hard warning log" on backend. Consider aligning.
- The watchdog hard-caps its own lifetime at 10 minutes per loop.
  Bounds the impact of a buggy loop in CI/test environments.
- Multi-machine, remote access, and time-series DB logging are
  out of scope for the current vision.
