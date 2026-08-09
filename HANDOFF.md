### Resolution Summary

Issue #103: introduced a global Emergency Stop header that is
rendered at the very top of the application shell and cannot be
hidden by scrolling or any overlapping modal. The button delegates
to the machine store's existing `toggleEstop` action so the
backend E-Stop API endpoint is hit with no duplicated logic.

### Files Modified

- `frontend/src/components/EStopHeader.vue` *(new)*: Vue 3
  `<script setup>` component. Sticky (`top-0`), high z-index
  (`z-[100]`, above every `z-50` modal in the app), large red
  octagonal-style STOP button. Reads `isEstop` via `storeToRefs`
  and renders ACTIVE / Clear state chips. Uses the compatibility
  adapter (`stores/machine-compat.js`) so the shell still renders
  when the machine module is not mounted.
- `frontend/src/App.vue`: restructured the layout root from a
  single-row flex into a flex column. `EStopHeader` sits above a
  `flex flex-1 overflow-hidden` row that holds the sidebar and
  `<main>`. No new endpoints, no new Pinia stores, no
  module-folder surgery.
- `frontend/tests/test-estop-header.mjs` *(new)*: 12
  static-structural assertions covering the component's API
  contract (compat import, `storeToRefs`, `toggleEstop`
  delegation, sticky / z-index, iconography, data-testid hooks)
  plus the App.vue wiring (import, render order, column
  layout). Total frontend suite: **110 / 110 pass** (was 98).

### Architectural Decisions

- **Layout wrapper, not `<Teleport>`.** `App.vue` already wraps
  the whole app in `h-screen overflow-hidden`, so adding a sticky
  header above the sidebar is the smallest change that satisfies
  the "must not be hidden by scrolling or overlapping elements"
  requirement. `<Teleport to="body">` would have worked but adds
  complexity for no safety benefit given the existing layout.
- **Reuse `toggleEstop`.** The machine store already exposes a
  canonical action that posts
  `POST /api/v1/modules/machine/state` with
  `{state: "estop"}` or `{state: "estop_reset"}` and surfaces the
  result through the console store. Reusing it keeps the button
  trivially testable and prevents drift between the two
  E-Stop entry points (DroPanel + header).
- **`z-[100]`, not `z-50`.** Every existing modal in the app
  uses `z-50` (editor overlay, update manager, panel dialogs).
  Picking a higher value with Tailwind's arbitrary-value syntax
  guarantees the E-Stop is reachable even when the operator has
  an editor modal open mid-print — a non-obvious safety gap.
- **Compat adapter for state.** Following
  `.agent/STATE.md § 7` (nullable-module guarantee), the header
  imports `useMachineStore` from `stores/machine-compat.js`. When
  the machine module is excluded the adapter supplies a no-op
  fallback so the header still renders without breaking the
  shell.
- **Iconography.** Standard E-Stop: 80-96 px red circular button
  with a bold white "STOP" label, a 4 px red-800 ring, an
  `aria-label`, and an ACTIVE / Clear state chip. No SVG custom
  artwork — matches the conventions already in
  `DroPanel.vue` (red / gray contrast) and keeps the bundle lean.

### Testing Verification

- [x] Ran local test suite / build checks
- [x] `node --test frontend/tests/**/*.mjs` → **110 / 110 pass**
  (12 new, 98 pre-existing)
- [x] `npm run build` → succeeded in 3.51 s, EStopHeader chunk
  baked into `index-*.js` (verified `estop-header`,
  `estop-button`, `estop-state-*`, `Emergency Stop`,
  `toggleEstop` all present in the bundle)
- [x] `python -m compileall -q backend` → clean
- [x] `python -m pytest backend/tests -v` → **317 / 317 pass**

### Acceptance Criteria Checklist

- [x] Create a global E-Stop header component.
  `frontend/src/components/EStopHeader.vue` ships a `<header>`
  element with a `<button>` and state chips, rendered
  unconditionally from `App.vue`.
- [x] Apply CSS `position: sticky; top: 0;` and a high z-index
  via the layout wrapper so it cannot be hidden. Header uses
  `sticky top-0 z-[100]`, sits above the sidebar (`z-10`) and
  every modal in the app (`z-50`), and lives outside the
  `<main class="overflow-y-auto">` scrollable region.
- [x] The button correctly triggers the backend E-Stop API
  endpoint. Click → `store.toggleEstop()` →
  `ModulesMachineService.setMachineState({ state: "estop" })` →
  `POST /api/v1/modules/machine/state`. The endpoint
  (`backend/modules/machine/router.py::set_state`) was already in
  place; this PR adds the missing UI surface.
- [x] The button styling clearly indicates its critical
  function. 80–96 px red circular button with a bold white
  "STOP" label, a 4 px red-800 ring, ACTIVE / Clear state chips,
  and `aria-label="Emergency Stop"` for assistive tech.
