# Frontend & Backend — Operational Notes

This document used to describe a dynamic frontend module-registry
system (`frontend/src/modules/<id>/`, a `ModuleRegistry`, per-module
manifests, eager-import lint rules). **That system has been retired
and no longer exists in the codebase.** The frontend now imports
views and components directly where they're used — see
[`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) § 2 for
the current frontend layout, and
[`.agent/contracts/backend-router.md`](.agent/contracts/backend-router.md)
for the backend's per-app `_MODULE_DOMAINS` mount tables (the closest
remaining thing to a "module system," and it's a flat table, not a
registry).

What follows is the subset of the old content that is still true —
operational details worth keeping close at hand rather than
re-deriving from source every time — rewritten against the current
paths. Section numbers are not preserved from the old version; they
were an artifact of the retired numbering scheme.

---

## 1. Base-Thread Snapshot Store (servo ↔ base-thread split)

The dashboard reads two distinct transport streams from the backend:

* **Servo thread** — `GET /ws/telemetry`, 10 Hz WebSocket. Carries
  the time-critical fields the DRO / Estop / status panels need on
  every frame (`task_state`, `estop`, `position`, `interp_state`,
  `g5x_index`, `state`, `file`, `homed`, `errors`). Owned by the
  machine backend's WebSocket handler
  (`backend/machine/routers/ServoThreadRouter.py`).
* **Base thread** — `GET /api/v1/base-thread/snapshot`, 1 Hz REST
  round-trip. Carries the slow streams the dashboard polls anyway:
  `progress` (G-code line counters), `sensors` (temperature), `tools`
  (operator-facing tool list), `timestamp` (ISO-8601 UTC).

The base-thread store lives at `frontend/src/stores/baseThread.ts`.
It has three top-level refs (`progress`, `sensors`, `tools`) and
three actions (`refresh`, `start`, `stop`). See
[`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) § 2.4 for
why the split exists.

### 1.1 What lives on the WebSocket (servo thread) only

* `task_state`, `estop`, `task_mode`, `state`, `interp_state` —
  fast-changing task state.
* `position`, `actual_position`, `relative_position` — DRO axes
  at 10 Hz so the position display does not jitter.
* `g5x_index`, `homed`, `file`, `errors` — status / mode / file
  context.

### 1.2 What lives on the snapshot (base thread) only

* `progress` — G-code `current_line` / `motion_line` / `total_lines`.
* `sensors` — temperature sensor dict (keyed by sensor name).
* `tools` — operator-facing tool list with runtime state overlaid.
* `timestamp` — ISO-8601 UTC, lets the frontend detect a stalled
  poll.

### 1.3 Adding a new slow stream

```text
1. backend/machine/routers/BaseThreadRouter.py
   - Add a top-level field to ``BaseThreadSnapshotResponse``
     (backend/common/models/BaseThreadStateResponse.py).
   - Populate it in ``get_base_thread_snapshot()`` /
     ``BaseThreadService``.
2. ``npm run generate-api`` (regenerates the TS client — both
   backends must be running, see ARCHITECTURE.md § 1.4).
3. frontend/src/stores/baseThread.ts
   - Add a ref to the store state.
   - Add a defensive write inside ``refresh()`` mirroring the
     existing ``sensors`` / ``tools`` blocks.
4. Consumer component
   - ``const baseThread = useBaseThreadStore()``
   - ``const { newStream } = storeToRefs(baseThread)``
   - Watch with ``deep: true`` so the top-level reassignment
     propagates across component boundaries.
```

### 1.4 Gotchas (also see `LESSONS_LEARNED.md`)

* The poll-handle field on the `baseThread` store is a non-reactive
  property on the store instance — it starts `undefined`. The
  `start` / `stop` gates must use a truthy check, not a strict-null
  check, or the 1 Hz poll silently never starts on the second call.
* Consumers must read the snapshot via `storeToRefs(baseThread)` and
  watch with `deep: true` — a bare destructure loses reactivity on
  the store's top-level reassignment.
* `useBaseThreadStore().start()` is called once from `App.vue` at
  the top level of `<script setup>`. Do not call it again from a
  component's `onMounted` — that would stack intervals.

---

## 2. EventBus — Frozen Payload Contract

`frontend/src/core/event-bus.ts` enforces: every subscriber receives
a deep-cloned, deep-frozen copy of the payload. A buggy subscriber
mutating its copy throws in strict mode (ES modules are strict by
default) and the bus catches the throw, logs it, and continues to
the next subscriber.

`frontend/src/core/telemetry-bus.ts` is the opposite: it delivers by
reference so the high-frequency stream does not pay a clone cost per
tick. Subscribers to the telemetry bus must clone before storing.

---

## 3. State Facade

The `frontend/src/stores/stateFacade.ts` Pinia store is the facade
for raw LinuxCNC telemetry. The backend's WebSocket stream ships raw
integers (`task_state`, `interp_state`, `estop`, ...) to the
browser. The facade exposes those raw values verbatim **and** offers
a clean `systemState` string getter so widgets never have to do
integer math against the wire protocol.

The servo-thread store (`frontend/src/stores/servoThread.ts`) calls
`useStateFacadeStore().updateStatus({...})` on every `full_state` /
`delta` payload to keep the facade in sync. Before the first
telemetry frame arrives the facade renders its initial defaults,
which bias toward `ESTOP` — the UI must never claim the machine is
idle when it has no data yet.

---

## 4. Unsaved-Changes Guard

The editor store (`frontend/src/stores/editor.ts`) tracks
`pristineContent` as the last loaded or successfully saved snapshot
and exposes `isDirty`. Editor route leaves, same-component file
switches, and the editor Close action use the queue-based confirm
service in `frontend/src/core/confirm.ts`. `ModalConfirmHost.vue` is
mounted once in `App.vue`; feature code calls the Promise-based
`useConfirm()` API rather than native `window.confirm` dialogs.

---

## 5. Domain notes

Operational details about specific domains that are easy to
re-break because they aren't obvious from reading the code once:

**Camera** (`backend/machine/routers/camera.py`,
`frontend/src/components/camera/`) — USB-camera streams are proxied
through `ustreamer` (`/stream?id=/dev/videoN` → `MjpegProxy` →
`http://127.0.0.1:{port}/?action=stream`, because the browser can't
reach the backend's own localhost port from a different host).
IP-camera streams (`/stream?id=http://...&user=...&pwd=...`)
redirect with credentials in query parameters — Chrome strips
`user:pass@host` from cross-origin `Location` headers, but query
params pass through intact. RTSP URLs are rejected with a `503` and
a plain-English message (the proxy speaks HTTP/HTTPS only; RTSP
would need `ffmpeg`/`gst-launch`, out of scope today). Per-camera
operator preferences (rename / flip / mirror / hide-from-cycle)
persist via the `camera` module's settings store
(`backend/machine/data/modules/camera/settings.json`) and hydrate on
boot. `GET /status` returns `{running, active_id, ustreamer_url,
message}`; `message` is a single-line operator hint distinguishing
"ustreamer not installed" from "device unplugged" from "platform
unsupported" so the UI shows a dependency hint rather than a silent
broken image.

**Macros** (`backend/system/routers/macros.py` for CRUD,
`backend/machine/routers/macro_start.py` for execution,
`frontend/src/components/macros/`) — three kinds, selected via
`?kind=`: `.macro` (run via MDI), `.ngc` (LinuxCNC native, edit-only
from this UI), `mcode` (LinuxCNC `M100`-`M199` files under
`machine_config/m_codes/`, edit-only). `MacroManagerPanel.vue` and
`McodeManagerPanel.vue` are separate components rather than one
kind-switched panel.

**Machine config / templates** — see
[`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) § 7 for
the current template-generation pipeline
(`backend/system/services/machinetemplates/generator.py`) and the
`hardware.json` v2.1 schema. The old "compiler" concept described in
earlier revisions of this file has been removed.
