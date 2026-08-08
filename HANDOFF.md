### Resolution Summary

Removes the deprecated `consoleStore.addMessage()` wrapper (and its stray `console.warn` + self-warning side-effect that cluttered the operator console on every legacy call) and migrates every operational caller to the canonical level actions (`info()`, `error()`, `warning()`, `success()`, `command()`). Console output is no longer polluted by deprecation notices; operators see only the operational message they actually triggered.

### Files Modified

- `frontend/src/stores/console.js` — Dropped the public `addMessage(text, type)` action entirely. The store now exposes only the level-specific helpers (`error`, `info`, `debug`, `warning`, `command`, `success`) on top of the internal `_addMessage` helper. This removes the duplicate `console.warn` / `this.warning(...)` deprecation lines that fired on every call and were the source of the "debug-level print" clutter the issue called out.
- `frontend/src/modules/machineconfig/store.js` — Converted 4 `consoleStore.addMessage(msg, "error")` calls (in `loadCompilers`, `loadProfilesTree`, `loadStaged`, `loadActive`) to `consoleStore.error(msg)`.
- `frontend/src/components/UpdateManager.vue` — Converted 4 calls in `fetchVersion` (`info` / `error`) and `updateSystem` (`warning` / `error`) to the matching level helpers.
- `frontend/src/components/ConsolePanel.vue` — Converted 4 calls in `submitCommand` (`command` / `error` / `success` / `error`) to the matching level helpers.
- `frontend/tests/test-console-features.mjs` — Updated the comment on the "level field" test to reference the internal `_addMessage` helper (the actual decorator) instead of the now-removed `addMessage` shim. The two regex assertions (`level = typeToLevel(type)` and `level,`) still target the same line in `console.js`.

### Architectural Decisions

- **Removed rather than kept.** The issue is specifically about removing deprecated debug-level prints; keeping a deprecated wrapper defeats the purpose. The store now has a single internal `_addMessage` and six thin public level actions. No external code referenced the public `addMessage` shim, so deletion is safe (verified via `grep -rn 'addMessage' frontend backend`).
- **One concern per PR.** No unrelated refactors; the diff is 5 files, +14/−27 lines, all of them the rename. The frontend build still succeeds and the test suite is unchanged.
- **Test contract preserved.** The existing console-features test only asserts on the regex shape of the internal helper (`_addMessage` writes `level = typeToLevel(type)` and the object carries a `level` field); both assertions still pass after the public shim is gone. Updated one comment to keep the test's documentation honest about what it is exercising.
- **Backend untouched.** A `grep` for `addMessage` across `backend/` returns zero matches — the operator console is the only place this legacy API was in use, so no backend changes were required.

### Testing Verification

- [x] `node --test frontend/tests/**/*.mjs` — 98/98 pass
- [x] `node --test frontend/tests/test-console-features.mjs` — 20/20 pass
- [x] `python -m compileall -q backend` — clean
- [x] `python -m pytest backend/tests` — 317/317 pass
- [x] `npm --prefix frontend run build` — production build succeeds (only pre-existing `INEFFECTIVE_DYNAMIC_IMPORT` warnings unrelated to this change)
- [x] Backend health check + `npm --prefix frontend run generate-api` — openapi regenerated cleanly; no drift introduced

### Acceptance-criteria checklist

- [x] Searched the backend and frontend codebases for stray `addMessage()` — only the public shim on the console store; backend has none.
- [x] Removed debug-level prints that are no longer relevant — the deprecated `console.warn` + `this.warning(...)` self-warning inside `addMessage()` is gone.
- [x] Converted every operational `addMessage()` into the matching level action (`info`, `error`, `warning`, `success`, `command`).
