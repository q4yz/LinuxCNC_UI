# Agent Handoff — State and Open Work

> **Optional, agent-maintained.** Safe to delete; ``test_doc_links``
> skips it when missing. Keep it **under ~150 lines**: current state,
> open debt, gotchas. Session narratives belong in commit messages —
> the pre-2026-10 history (entries 1.0–1.23) is in `git log -p
> .agent/HANDOFF.md`.

Last reviewed: **2026-10-11** (every item in § 2 re-checked against the code that day).

---

## 1. Current state

**Verification gate** ([`TEST.md`](.agent/TEST.md)) — all green on 2026-10-11:

| Suite | Result |
|---|---|
| `backend/machine` pytest | 400 passed |
| `backend/system` pytest | 680 passed, 2 skipped |
| `backend/common` pytest | 73 passed |
| `mypy .` (from `backend/`) | clean |
| frontend `vue-tsc --build` / `npm test` / `npm run build` | clean / 480 passed / ok |

The old "machine suite broken" (#118) and "56 frontend failures" (#117)
notes are obsolete — both suites pass.

**Architecture:** start at [`context/hub.md`](.agent/context/hub.md) and
[`context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md); backend layering
rules in [`context/BACKEND_LAYERS.md`](.agent/context/BACKEND_LAYERS.md).

- `backend/system` (:8001, systemd, always up), `backend/machine`
  (:8000), `backend/common` (shared library).
- **The machine backend is a HAL user component**, started *by LinuxCNC*
  from `postgui_call_list.hal` (`loadusr -W -n webgui … machine/main.py`)
  and stopped by LinuxCNC's `halcmd unload`. "Machine backend up" ⇔ "a
  LinuxCNC session of this UI is up". Nothing else starts it (#121 is
  answered by this design).

**Subsystems added in the 2026-10 sessions** (docs/tests are the reference):

- Central UI settings — one `backend/data/settings.json`, system service
  `/api/v1/settings` ([`contracts/settings-module.md`](.agent/contracts/settings-module.md)).
- System update — `scripts/update.sh` writes `backend/data/update_status.json`
  (via `scripts/update_status.py`); UI follows `GET /api/v1/system/update/status`
  (`stores/systemUpdate.ts`, `UpdateOverlay.vue`). API client is generated
  from `backend/dump_openapi.py` — **no temporary backends on :8000/:8001**.
  Two modes (`update.sh --mode commit|release`, `POST /system/update {mode}`):
  *commit* = git pull + build on the board (testing); *release* = check out the
  latest GitHub release tag + download the dist CI built for it
  (`scripts/fetch_release.py`, sha256 + `release.json` commit check) — no npm
  on 1 GB boards (CB1). CI's `release` job publishes the dist on `v*` tags;
  `install.sh --release` uses the same path. `GET /system/version` reports the
  latest release (`services/VersionService.py`, GitHub API, cached).
- One file record everywhere — `FileEntryResponse` / frontend `FileEntry`;
  every file selector uses `ui/FileDropZone.vue` (drag & drop, multi-file).
- LinuxCNC session lifecycle — `MachineLifecycleService`: one lock for
  start/stop/switch, zombie-safe pid probe, `state`
  (stopped/starting/running/stopping) and `owner` (`ui` = an INI under
  `machine_config/machines/`, `external` = anything else). Start refuses
  while an external session runs; **stop stops any session** (user decision).
- Machine-online UI — `useMachineOnline.ts` derives an `offlineReason`
  (stopped/starting/connecting/stopping/external/waiting/unresponsive/
  system-offline) from `/api/v1/health` (`linuxcnc_connected`,
  `shutting_down`) + the system service's session status.
- HAL compiler: `[tool_length_sensor]` OR-ed with `[probe]` into
  `motion.probe-input` (`component/probe.md`).
- Debug tab HAL pins: live values at 1 Hz for the pins on screen
  (`POST /api/v1/hal/pins/values`), and an oscilloscope
  (`components/debug/scope/`, lazy chunk) streaming up to 16 pins over
  `WS /ws/hal-scope` (`HalScopeService`, ≤ 1 kHz, 50 ms blocks). Dev
  pins move via `hardware/mock/MockDebugSignals.py`.

---

## 2. Open debt (verified 2026-10-11, most important first)

| # | Item | Where / what to do |
|---|---|---|
| 1 | **Cold-extrusion guard missing (safety).** An extruder's `j<n>enable` reaches hardware unconditionally; no `wcomp`/`and2` gate on temperature. | HAL compiler, `component/exturder.md` / `heater.md` |
| 2 | **nginx routing — fixed 2026-10-11, one manual step left per existing Pi.** Routes now live in the tracked `deploy/nginx/linuxcnc-ui-routes.conf`, included by the site `scripts/configure_nginx.sh` writes (install.sh, Docker), so updates apply new routes by reloading nginx; `test_nginx_routes.py` checks every backend route + the Vite proxy against it. An install from before must run `sudo bash scripts/configure_nginx.sh` once (`update.sh` warns in its log and the update toast). Not yet validated with a real `nginx -t`. | Pi (#114) |
| 3 | **Not yet verified on real hardware:** zombie-safe pid probe + session reaping, `owner` detection via `/proc/<pid>/cmdline`, HAL component `exit()` + `timeout_graceful_shutdown=3` during `halcmd unload`, the whole update status flow (`update.sh` was never run end to end after the rewrite). | Pi with LinuxCNC |
| 4 | Fan `shutdown_speed` ingested into `hardware.json`, never applied on estop (needs a shared "machine enabled" signal). | `component/fan.md` § 3 |
| 5 | `RemoraRouterMapper.base_fragment` reads the dead `mcus[].parameters` shape for `chip`/`spi_clk_div` — always stm32 / 64; LPC boards cannot be selected. | `halcompiler/mcus/RemoraRouterMapper.py` |
| 6 | #116 — `write_text()` without `newline="\n"` in `machinetemplates/generator.py` (8 sites) and `hardware_json_generator.py`: CRLF when generated on Windows. | trivial |
| 7 | Pin DTOs touch hardware: `ReadWriteDynamicHalPin.__post_init__` registers a HAL pin, so mappers building it have side effects and the DTOs cannot be frozen. Needs its own plan. | `common/dtos/pins/` |
| 8 | Frontend still calling the generated client directly: `stores/editor.ts`, `stores/cameraStore.ts`, `FileManager.vue` (upload path via facade, editor reads not). | facades |
| 9 | Class A (parport) heaters unsupported (`pwmgen`, no ADC); Remora `DIGITAL_OUT` not routed (documented); spindle manual-override triple not compiled. | component docs |
| 10 | #119 — mypy `disable_error_code` backlog (`return-value`, `arg-type`, `override`, …) in `backend/mypy.ini`. #111 — no ESLint config in `frontend/` yet. #113 — fragile `Stepper.section_name`. | |
| 11 | **Main JS bundle is ~2,085 kB — just under the PWA precache limit (2 MiB).** Anything bigger fails `npm run build` (CI and the update's rebuild). Lazy-load route views (3D viewer!) in the router. | `frontend/src/router`, `vite.config.mjs` |
| 12 | Observed once, re-verify: `hardware.json` uses the MERGE axis policy while `machine.ini` uses SPLIT; the extruder's `[AXIS_A]` got 0 limits. | `machineconfig/AxisBuilder.py` |

**Closed by now, close the GitHub issues after checking:** #117, #118
(suites green), #120 (PascalCase sweep done; `settings_store.py` removed),
#112 (machine.hal wiring is generated), #121 (see § 1).

**Policy:** `requirements-machine.txt` / `requirements-system.txt` are
deliberate placeholders — put a service-only dependency there, not in
the shared `requirements.txt`.

---

## 3. Gotchas worth knowing (learned the hard way)

- **Verify HAL output against the real reference files** in
  `machine_config/example/` (PrintNC-WEBGUI, ender3 `config.txt`), never
  generic advice — several "correct" shapes from docs/LLMs were wrong.
  Fragment-text unit tests do not catch HAL *load* errors.
- **HAL pin direction:** a value written by an MCU router (sensor reading
  `remora.PV.N`) is read by webgui → `ReadOnlyDynamicHalPin` (HAL_IN).
  Two HAL_OUT pins on one signal is a load-time crash.
- **Compiler-created pin sharing** (auto heater fan on the heater pin)
  must add its own `duplicate_pin_overrides` entry; the assembler never
  merges collisions silently.
- **`async` service methods must be awaited** by the router — a missing
  `await` silently does nothing (the old estop bug).
- **Never block the event loop:** NML/HAL calls that can wait go through
  `asyncio.to_thread`; `_cmd_lock` serialises commands. Telemetry, jog
  watchdog and health share the loop.
- **Jog watchdog is safety code:** fixed 500 ms constant, monotonic
  clock, no lifetime cap, every iteration guarded. Keep the frontend
  keep-alive (250 ms) well below it.
- **`machine.ini` `[DISPLAY]`:** keep the commented `#INTRO_GRAPHIC` /
  `#INTRO_TIME` lines (LinuxCNC parser quirk).
- **`webgui_connections.hal` is regenerated every time** (no preserve);
  generation refuses to override the machine selected as "main".
- **Frontend:** use `storeToRefs()`; call other stores inside actions,
  not at module scope; G-code literals live in `src/config/gcodes.ts`;
  never hardcode `localhost` (API base is relative / same host).
- **Windows dev checkout uses CRLF** (`core.autocrlf=true`); git stores
  LF. Edit tools must preserve line endings.

---

## 4. Maintainer notes

When a session ends: update § 1 if the architecture or the gate changed,
add/strike items in § 2 (verify against the code — don't copy prose
forward), and add a gotcha to § 3 only if it would have saved real time.
Open work that needs discussion belongs in a GitHub issue; this file
maps it.
