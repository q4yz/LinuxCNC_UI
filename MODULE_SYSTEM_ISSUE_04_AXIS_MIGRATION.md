# Issue #4 — Migrate `machine` (axis, state, jog, MDI, home) into the module system

> **Status:** not started
> **Tracks:** [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) Phase 3a
> **Companion:** [`MODULE_SYSTEM_EVALUATION.md`](MODULE_SYSTEM_EVALUATION.md) § 4
> **Scope:** the **machine** module — DRO, jog, state, mode, home,
> MDI, set-position, WCS selector, E-STOP, Power. Excludes the program
  lifecycle endpoints (run/stop/pause/resume/parse), which are a
  separate module tracked under Phase 3 (`program`).
> **Risk class:** highest — see § 4 of the evaluation.
> **Depends on:** Issues #02 and #03 (camera + temperature) to establish
> the migration pattern.

---

## 1. Problem

The machine feature is the most fragmented in the codebase and the
only one with safety-critical concerns:

- `backend/routers/machine.py` (~200 lines): `POST /state`, `POST /mode`,
  `POST /home`, `POST /mdi`, `POST /temperature`, and a nested
  `program_router` (run/stop/pause/resume/parse).
- `backend/routers/jog.py` (~165 lines): `POST /jog`,
  `POST /jog/keepalive`, `POST /jog/stop` plus the **500 ms safety
  watchdog** background task.
- `backend/hardware/linuxcnc_mock.py` (~440 lines): jog simulation
  thread, jog state (`jogging_axis`, `jogging_velocity`, `jog_thread`,
  `jog_stop_event`), and the `command.jog(...)` mock.
- `backend/routers/websocket.py` (~200 lines): the WebSocket transport
  (Phase 4 will refactor; this issue keeps it as-is).
- `frontend/src/stores/machine.js` (~400 lines): the **monolithic** store
  — WebSocket client, reconnect, delta merge, all status state, all
  jog actions, all home/state/mode actions, the `temperatureHistory`
  snapshot loop (already extracted by Issue #03), and console
  integration.
- `frontend/src/components/DroPanel.vue` (~230 lines): E-STOP/Power
  banner, DRO X/Y/Z readouts, WCS selector, home-all, per-axis home,
  set-position modal.
- `frontend/src/components/JogControls.vue` (~165 lines): 6-button
  jog grid, slider, keyboard bindings (ArrowKeys, PageUp/Down), window
  blur handler.
- `frontend/src/views/DashboardView.vue` (~70 lines): hard-imports all
  panels (camera, temperature, DRO, jog).

The safety-critical bit is the **500 ms keep-alive watchdog** in
`jog.py`: if a UI bug leaks a continuous jog, the watchdog halts the
axis within 500 ms. This must keep working.

---

## 2. Goals

1. Move all axis/state/MDI/home/jog endpoints into
   `backend/modules/machine/`.
2. Move the WebSocket subscription into the machine module's frontend
   Pinia store.
3. Split the monolithic `stores/machine.js` so machine concerns live
   in `frontend/src/modules/machine/store.js` and other consumers
   (legacy) get a thin shim.
4. Keep the **safety watchdog** running and equivalent.
5. Validate the nullable-module guarantee: deleting
   `backend/modules/machine/` and `frontend/src/modules/machine/` boots
   the app with zero errors and zero axis/machine functionality.

---

## 3. Non-Goals

- The program lifecycle endpoints (`/program/run`, `/stop`, `/pause`,
  `/resume`, `/parse`) — tracked separately under the `program`
  module (Phase 3). This issue extracts them from
  `routers/machine.py` into a separate module folder but does **not**
  implement their UI in this round.
- WebSocket transport refactor (Phase 4). For this issue the WebSocket
  remains in `routers/websocket.py` as legacy; the machine module's
  Pinia store subscribes to it.
- Form-from-schema settings UI.
- Mock simulation (stays in `backend/hardware/linuxcnc_mock.py`).

---

## 4. Tasks

### 4.1 Backend

- [ ] Create `backend/modules/machine/__init__.py` re-exporting
      `setup()`.
- [ ] Create `backend/modules/machine/module.py`:

      ```python
      from fastapi import APIRouter
      from core.protocols import (
          ModuleManifest, ModuleContext, PluggableModule,
      )
      from .router import router as _router
      from .settings import MachineSettings

      class MachineModule:
          manifest = ModuleManifest(
              id="machine",
              title="Machine",
              version="0.1.0",
              description="DRO, jogging, state, MDI, home.",
              settings_panel=True,
          )

          def on_load(self, ctx: ModuleContext) -> None:
              # Start the jog safety watchdog as an asyncio task.
              # The watchdog lives in this module because it shares
              # module-private state (`_active_jogs`) with the
              # /jog, /jog/keepalive, /jog/stop endpoints.
              from .jog_watchdog import start_watchdog
              start_watchdog()
              ...

          def on_unload(self) -> None:
              from .jog_watchdog import stop_watchdog
              stop_watchdog()
              ...

          def get_router(self) -> APIRouter:
              return _router

      def setup() -> PluggableModule:
          return MachineModule()
      ```

- [ ] Create `backend/modules/machine/router.py` — move the contents of
      `backend/routers/machine.py` minus the `set_temperature`
      endpoint and minus the `program_router` (those move to the
      temperature module Issue #03 and the program module Phase 3
      respectively). Includes:
      - `POST /state` (`StateCommand`)
      - `POST /mode` (`ModeCommand`)
      - `POST /home` (`HomeCommand`)
      - `POST /mdi` (`MdiCommand`)
- [ ] Create `backend/modules/machine/jog.py` — move the contents of
      `backend/routers/jog.py` minus the `jog_watchdog` function. The
      watchdog moves to `jog_watchdog.py` (next bullet). The module-
      private `_active_jogs` dict + `active_jogs_lock` move with it.
- [ ] Create `backend/modules/machine/jog_watchdog.py`:

      ```python
      """Background watchdog for continuous jog safety.

      Mirrors the existing 500 ms keep-alive window from
      backend/routers/jog.py. The watchdog reads
      :data:`backend.modules.machine.jog._active_jogs` (module-private
      to this package) and force-stops any axis whose last-ping
      timestamp is older than :data:`WATCHDOG_TIMEOUT_S`.
      """

      import asyncio
      import time
      import logging

      from hardware import execute_sync_cmd, linuxcnc

      logger = logging.getLogger(__name__)

      WATCHDOG_TIMEOUT_S = 0.5
      _task: asyncio.Task | None = None

      async def _loop():
          from . import jog  # local import to avoid circular
          while True:
              await asyncio.sleep(0.1)
              now = time.time()
              expired = []
              with jog._active_jogs_lock:
                  expired = [
                      axis for axis, t in jog._active_jogs.items()
                      if now - t > WATCHDOG_TIMEOUT_S
                  ]
                  for axis in expired:
                      del jog._active_jogs[axis]
              for axis in expired:
                  logger.warning("SAFETY WATCHDOG: missed keep-alive on axis %s", axis)
                  try:
                      execute_sync_cmd(
                          "jog", 0,
                          getattr(linuxcnc, "JOG_STOP", 0), True, axis,
                      )
                  except Exception:
                      logger.exception("Watchdog stop failed for axis %s", axis)

      def start_watchdog():
          global _task
          if _task is None or _task.done():
              _task = asyncio.create_task(_loop())

      def stop_watchdog():
          global _task
          if _task is not None:
              _task.cancel()
              _task = None
      ```

- [ ] Create `backend/modules/machine/settings.py`:

      ```python
      from pydantic import BaseModel, Field

      class MachineSettings(BaseModel):
          jog_watchdog_timeout_ms: int = Field(default=500, ge=100, le=5000)
          default_jog_velocity: float = Field(default=500.0, ge=1.0)
          keepalive_interval_ms: int = Field(default=250, ge=50, le=2000)
          estop_disables_power: bool = Field(default=True)
      ```

      Note: `jog_watchdog_timeout_ms` is consumed by the watchdog at
      startup — the watchdog reads
      `ctx.settings.read_key("jog_watchdog_timeout_ms")` once when it
      starts (the value is settable at runtime via PUT /settings; the
      watchdog only re-reads it on a restart, which is acceptable for
      v1).

- [ ] Update `backend/modules/machine/jog_watchdog.py` to honor
      `WATCHDOG_TIMEOUT_MS` from settings on startup.
- [ ] Update `backend/routers/machine.py`:
  - Remove the `state`, `mode`, `home`, `mdi`, `temperature`, and
    `program_router` endpoints.
  - The file is removed entirely after the migration.
- [ ] Update `backend/routers/jog.py`:
  - Remove all endpoints and the watchdog.
  - The file is removed entirely after the migration.
- [ ] Update `backend/main.py`:
  - Remove `from routers import machine, jog`.
  - Remove `app.include_router(machine.router)`,
    `app.include_router(machine.program_router)`,
    `app.include_router(jog.router)`.
  - The registry's `boot()` picks up `modules/machine/` automatically.
- [ ] Tests:
  - `test_machine_router.py` — `/api/v1/modules/machine/state` accepts
    `StateCommand` and rejects unknown states with 400.
  - `test_jog_watchdog.py` — start a continuous jog, do NOT ping,
    assert `_stop_axis` is called within 600 ms.
  - `test_jog_keepalive.py` — start a continuous jog, ping every
    100 ms, assert the axis keeps moving for 2 seconds without
    forced stop.
  - `test_machine_null.py` — boot with `modules/machine/` removed
    yields `mounted=['camera','temperature']` (or whatever is left).

### 4.2 Frontend

- [ ] Create `frontend/src/modules/machine/index.js`:

      ```js
      import manifest from "./manifest.js";
      import DroPanel from "./components/DroPanel.vue";
      import JogControls from "./components/JogControls.vue";
      import { useMachineStore } from "./store.js";

      export default {
        manifest,
        onLoad(ctx) {
          // The machine module owns the WebSocket subscription.
          const store = useMachineStore(ctx.id);
          store.connect();
        },
        onUnload() {
          const store = useMachineStore(ctx.id);
          store.disconnect();
        },
      };
      ```

- [ ] Create `frontend/src/modules/machine/manifest.js`:

      ```js
      export default {
        id: "machine",
        title: "Machine",
        version: "0.1.0",
        description: "DRO, jogging, state, MDI, home.",
        settingsPanel: true,
        // No sidebar entry — the machine dashboard lives at the root.
      };
      ```

- [ ] Create `frontend/src/modules/machine/store.js`. This replaces
      the bulk of `stores/machine.js`. Sketch:

      ```js
      import { defineStore } from "pinia";
      import { ref, reactive } from "vue";
      import {
        ModuleMachineService,
      } from "../../../generated/api/services/ModuleMachineService";
      import { useConsoleStore } from "../../stores/console";

      const AXIS_NAMES = ["X", "Y", "Z"];
      const HOME_ALL = -1;

      export const useMachineStore = defineStore("module_machine", () => {
        const connectionStatus = ref("disconnected");
        const status = reactive({
          task_state: 1, estop: 1, task_mode: 1,
          position: [...], actual_position: [...], relative_position: [...],
          state: 1, file: "", homed: [0, 0, 0],
          interp_state: 1, current_line: 0, g5x_index: 1,
        });
        const errors = ref([]);
        const jogIntervals = reactive({});
        let socket = null;

        // … actions: connect, disconnect, toggleEstop, togglePower,
        //            jog, jogContinuous, jogStop, homeAxis, homeAll,
        //            setPosition, setCoordinateSystem …

        return { connectionStatus, status, errors, jogIntervals,
                 connect, disconnect, toggleEstop, togglePower,
                 jog, jogContinuous, jogStop, homeAxis, homeAll,
                 setPosition, setCoordinateSystem };
      });
      ```

      **The store id MUST be `'module_machine'` per Gotcha #2.**

- [ ] Move `frontend/src/components/DroPanel.vue` →
      `frontend/src/modules/machine/components/DroPanel.vue`. Replace
      `useMachineStore` import with
      `import { useMachineStore } from '../store.js'`. Replace
      `MachineStateService.*` calls with `ModuleMachineService.*`.
- [ ] Move `frontend/src/components/JogControls.vue` →
      `frontend/src/modules/machine/components/JogControls.vue`. Same
      import migrations. **Critical:** the `onBeforeUnmount` handler
      must still call `stopAllJogging` to release any in-flight jog
      when the component is destroyed (e.g. when the user navigates
      away). The unmount fires for `v-if`-hidden components, but
      verify with a manual test.
- [ ] Update `frontend/src/views/DashboardView.vue` to lazy-load both
      panels:

      ```js
      const DroPanel = defineAsyncComponent(
        () => import('../modules/machine/components/DroPanel.vue')
      );
      const JogControls = defineAsyncComponent(
        () => import('../modules/machine/components/JogControls.vue')
      );
      ```

      Render a placeholder for each when the module is absent:

      ```vue
      <DroPanel v-if="mounted.machine" />
      <div v-else class="bg-gray-800 rounded-lg p-6 text-gray-500">
        Machine module not mounted.
      </div>
      ```

- [ ] Replace `frontend/src/stores/machine.js` with a thin shim:

      ```js
      // Legacy re-export shim. New code should import from the
      // machine module directly:
      //   import { useMachineStore } from '../modules/machine/store.js'
      //
      // This shim exists only until every consumer migrates.
      export { useMachineStore } from '../modules/machine/store.js';
      ```

      …and remove the legacy monolithic implementation. The shim
      approach ensures consumers like `DebugPanel.vue`,
      `ConsolePanel.vue`, and any pre-migration panels keep working
      without code change. The shim can be deleted in a follow-up
      issue once the last consumer migrates.

- [ ] Update `frontend/src/App.vue`:
  - Remove the `useMachineStore().connect()` call (the machine
    module's `onLoad` handles it now). Keep a fallback `connect()`
    call **only if** `MODULES_ENABLED` excludes `machine`, so that
    legacy code paths still see telemetry. In practice: if the
    machine module is mounted, the registry runs `onLoad` which
    calls `connect`; if not, no telemetry.
- [ ] Tests:
  - `tests/machine-store.spec.js` — `useMachineStore().jogIntervals`
    populates on `jogContinuous` and empties on `jogStop`.
  - `tests/dro-panel.spec.js` — clicking E-STOP calls
    `ModuleMachineService.setMachineState({ state: 'estop' })`.
  - `tests/jog-watchdog-e2e.spec.js` — start a continuous jog, do
    not ping, observe `_stop_axis` called within 600 ms.
  - `tests/machine-null.spec.js` — removing the module folder builds
    and renders placeholder cards.

### 4.3 Docs

- [ ] Update [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) § 9
      status table — mark Phase 3a ✅ Done.
- [ ] Append the migration log to
      [`MODULE_SYSTEM_EVALUATION.md`](MODULE_SYSTEM_EVALUATION.md) § 4
      describing deviations from the audit's plan.
- [ ] Add `backend/modules/machine/README.md` documenting:
  - The 500 ms keep-alive watchdog contract.
  - The `set_temperature` endpoint's relocation to the temperature
    module.
  - The migration path for the `program_router` endpoints (Phase 3).

---

## 5. Acceptance Criteria

A CI run on a clean checkout must demonstrate **all six**:

1. `start_dev.sh` boots with `MODULES_ENABLED` empty. Backend logs
   `registry: mounted=['camera','temperature','machine']`. The
   dashboard renders DRO, jog, temperature, camera panels as before.
2. **Jog safety regression test.** Start a continuous jog via the UI
   (or a synthetic WebSocket message). Do NOT ping for 600 ms. The
   watchdog halts the axis within 500 ms; the backend logs the
   "SAFETY WATCHDOG: missed keep-alive" line. The DRO stops
   advancing.
3. **Jog keep-alive happy path.** Start a continuous jog. Ping every
   250 ms. The jog continues for 5 seconds without forced stop.
4. **Settings persistence.** `curl -X PUT -d '{"default_jog_velocity": 250}'`
   to `/api/v1/modules/machine/settings` persists and survives a
   restart. New jogs use the new default velocity.
5. **Nullability.** Remove `backend/modules/machine/` and
   `frontend/src/modules/machine/`, re-run `start_dev.sh`, visit
   `/settings` and the dashboard. Backend boots with the remaining
   modules (`['camera','temperature']`); the dashboard shows
   placeholder cards in the DRO and jog slots; no error logs.
6. `npm run build` succeeds with both folders deleted.

---

## 6. Risks

1. **Watchdog state isolation.** The watchdog reads
   `_active_jogs` from the module's `jog.py`. If a developer reorders
   module imports, the watchdog might start before the module is
   fully initialized. Mitigation: start the watchdog from `on_load`,
   not from a module-level side effect.
2. **Watchdog hot-reload.** Under `uvicorn --reload`, `on_unload` may
   fire while a jog is in flight. The watchdog's stop should be
   idempotent — the existing implementation cancels the asyncio task
   but does not stop in-flight axes. Mitigation: add a
   `_active_jogs.clear()` step in `stop_watchdog()` so the next boot
   starts fresh.
3. **Double WebSocket subscription.** If both the module's `onLoad`
   and the legacy `App.vue` `connect()` fire, the store tries to open
   two sockets. Mitigation: the module's `connect()` is idempotent
   (existing guard) and `App.vue`'s call is removed in § 4.2.
4. **`<img>` cache-buster on the camera URL changes.** Cross-cutting;
   see Issue #02 § 6.
5. **Jog keyboard bindings leak across views.** If the user navigates
   to a view that does not contain `<JogControls>` while a jog is in
   flight, the `onBeforeUnmount` handler calls `stopAllJogging`. But
   if the component is hidden via `v-if`, `onBeforeUnmount` still
   fires (Vue 3 destroys hidden `v-if` components). Verify with a
   manual test.
6. **Pinia store ID collision.** The legacy `useMachineStore` uses
   `'machine'`. The new store uses `'module_machine'`. No collision,
   but the legacy shim re-exports the new store under the old import
   path — ensure consumers do not pass `id` parameter where the
   legacy signature did not.
7. **Two routers still share a prefix.** `routers/machine.py` defines
   both `router` (state/mode/home/mdi/temperature) and `program_router`
   (run/stop/pause/resume/parse). After migration:
   - `state` → machine module ✅
   - `temperature` → temperature module ✅
   - `program_router` → program module (Phase 3, **not in this issue**)
     but must be moved out of `routers/machine.py` so the file can be
     deleted. Decision: create a stub `modules/program/__init__.py` and
     `modules/program/router.py` that re-hosts the program endpoints
     **without** yet moving the UI. This unblocks deletion of
     `routers/machine.py`.

---

## 7. Out of Scope

- The program lifecycle UI (Phase 3 — `program` module's Vue
  components).
- WebSocket transport refactor (Phase 4).
- Form-from-schema settings UI.
- The `console.js` store move to `core/stores/console.js` — that
  refactor is shared with Issue #02.

---

## 8. References

- [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) § 4, § 6, § 12.
- [`MODULE_SYSTEM_EVALUATION.md`](MODULE_SYSTEM_EVALUATION.md) § 4
  (axis audit), § 5 (cross-cutting pitfalls).
- [`backend/routers/jog.py`](backend/routers/jog.py) — the watchdog.
- [`backend/routers/machine.py`](backend/routers/machine.py) — the
  endpoints to move.
- [`backend/hardware/linuxcnc_mock.py`](backend/hardware/linuxcnc_mock.py)
  — the jog simulation thread.
- [`frontend/src/stores/machine.js`](frontend/src/stores/machine.js) —
  the monolithic store to split.
- [`frontend/src/components/DroPanel.vue`](frontend/src/components/DroPanel.vue) —
  the DRO panel to move.
- [`frontend/src/components/JogControls.vue`](frontend/src/components/JogControls.vue) —
  the jog controls to move.
- [`backend/core/event_bus.py`](backend/core/event_bus.py) — for the
  event-bus topics the machine module will publish on (Phase 4
  groundwork).