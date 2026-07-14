### Resolution Summary
Refactored `JogControls.vue` to delegate all jogging network calls to the Pinia `machine` store (`jogContinuous` / `jogStop`), removing the component's private Axios client and parallel keepalive timer so the global state (via `machineStore.jogIntervals`) is now the single source of truth for which axes are actively jogging.

### Files Modified
- `frontend/src/components/JogControls.vue`: Removed `axios` import, the local `API_BASE` / `http` client, the local `activeAxes` ref, and the local 250 ms `heartbeatInterval`. The component now obtains the machine store via `useMachineStore()`, derives `jogIntervals` through `storeToRefs`, and dispatches `machineStore.jogContinuous(axis, velocity)` for start events and `machineStore.jogStop(axis)` for stop / window-blur / unmount cleanup.

### Architectural Decisions
- Reused the store's existing `jogContinuous` / `jogStop` actions, which already send the initial `POST /machine/jog` start, register a per-axis `setInterval(... , 250)` keepalive ping via `api.jogKeepalive`, and tear both down on stop. No new store API was introduced because the keepalive cadence is encapsulated inside `jogContinuous`, satisfying the requirement that the 250 ms watchdog heartbeat still fires through the store.
- Kept UI-only state (`sliderPos`, `jogSpeed`, `MAX_JOG_SPEED`, `KEY_BINDINGS`, the typing-in-field guard, and the keyboard / touch event wiring) inside the component because they are presentation concerns and are not relevant to machine state.
- Followed the AGENT.md guidance by using `<script setup>`, 2-space indentation, double quotes, and `storeToRefs` when destructuring the reactive `jogIntervals` map. Multiple-axis concurrent jogging is preserved by iterating the store's active interval keys during `stopAllJogging`.
- Made the smallest change possible — the component's template, button bindings, and event listeners are untouched, so the visual layout and user interaction model are unchanged.

### Testing Verification
- [x] Ran local test suite / build checks
- [x] Installed backend Python dependencies (`python3 -m pip install --break-system-packages -r backend/requirements.txt`) — the sandbox lacks `python3-venv`, so system pip was used; all packages installed successfully.
- [x] Ran `python -m compileall -q backend` successfully (no errors).
- [x] Ran `npm --prefix frontend run build` successfully; the Vite production build emits `dist/index.html`, `dist/assets/index-BF8tWr7l.css`, and `dist/assets/index-DchaI395.js` without any compilation errors (only a pre-existing chunk-size advisory that is unrelated to this change).