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

**Fix.** `.agent/AGENT.md` Part 1 explicitly forbids committing,
pushing, running tests, and opening PRs. The agent writes code
and a one-paragraph summary; the orchestrator handles the rest.

### 6.2 The "honest no-op"

**Symptom.** An AI agent invented a plausible-looking patch to
hide a missing dependency instead of asking.

**Root cause.** The agent prefers "useful" over "honest."

**Fix.** The "giving up" rule in `.agent/AGENT.md` codifies the
honest no-op: state the attempts, state the blocker, state the
next human step. A credible fake fix is worse than a real
"blocked."

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

**Fix.** `.agent/AGENT.md` Part 1 codifies the anti-patterns:
read minimum, write minimum, do not browse, do not hedge.

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
