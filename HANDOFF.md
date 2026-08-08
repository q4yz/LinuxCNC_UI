### Resolution Summary
Adds a frontend toast notification channel wired into the console store, and a backend duplicate-stepper-pin validation that surfaces a structured error envelope through the compile endpoint. The compile flow now toasts the operator the moment a profile fails validation.

### Files Modified
- `backend/modules/machineconfig/parser.py`: Added `DuplicateStepperPinError` class, `kind`/`line`/`to_dict()` on the `ConfigValidationError` family, and the post-parse `_validate_stepper_pins` walk that enforces the new rule.
- `backend/modules/machineconfig/router.py`: Added a module-owned `register_exception_handlers(app)` helper plus a `ConfigValidationError` exception handler that returns the structured `{"error": {section, key, line, message, kind}}` envelope; reordered the compile endpoint's `try/except` so `ConfigValidationError` flows through the handler (it inherits from `ValueError`, which would otherwise swallow the structured response).
- `backend/modules/machineconfig/module.py`: Calls `register_exception_handlers(ctx.app)` from `on_load` so the handler is registered as soon as the FastAPI app is available.
- `backend/core/protocols.py` + `backend/core/module_registry.py`: Added `app: Optional[FastAPI]` to `ModuleContext` and pass the live app reference at mount time.
- `frontend/src/core/toast.js`: New Pinia store exposing `useToast()` with `success` / `info` / `warn` / `error`; auto-dismiss 5 s for success/info, persistent for warn/error; `durationMs` override supported; colour palette exported as `TOAST_TYPE_STYLES`.
- `frontend/src/components/ToastContainer.vue`: New `<ToastContainer>` component, fixed top-right, Tailwind palette consistent with `bg-gray-800` / `border-gray-700`. Owns auto-dismiss timers and `onBeforeUnmount` cleanup so HMR cannot leak callbacks.
- `frontend/src/App.vue`: Mounts `<ToastContainer />` alongside the existing router-view shell.
- `frontend/src/stores/console.js`: `error` / `info` / `warning` / `debug` / `success` now accept an optional `opts: { popup?: boolean, title?: string, durationMs?: number }`; default `popup=false` keeps every existing call site working unchanged. The toast channel is reached via a dynamic import to avoid the cross-store Pinia ordering trap documented in `.agent/LESSONS_LEARNED.md` § 2.4.
- `frontend/src/modules/machineconfig/store.js`: Updated `describeError` to read the new structured error envelope first (then the legacy `detail` string and finally `error.message`); the `compile` action now invokes `console.error(message, { popup: true, title: 'Compile failed' })` so the operator sees the failure without hunting in the console panel.
- `backend/tests/test_machineconfig_parser.py`: +6 tests — four per-pin-key (`step_pin` / `dir_pin` / `enable_pin` / `endstop_pin`) duplicates, plus a `ConfigValidationError` subclass check and a regression guard for legitimate multi-motor Y.
- `backend/tests/test_machineconfig_module.py`: +1 integration test using the issue's example config — `[stepper_x]` / `[stepper_y]` / `[stepper_z]` sharing `PG0` / `PG1` / `!PF15` produces a 400 response with the documented `{section, key, line, message, kind}` envelope.
- `frontend/tests/test-console-features.mjs`: +5 tests — three toast-store contract tests (method surface, auto-dismiss vs. persistence, palette / container wiring) and two console-store popup tests (forwarding to the toast layer, backward-compatible default). Existing `debug(text)` regex loosened to `debug\s*\(\s*text` so the new optional `opts` parameter does not break the static-structural contract.

### Architectural Decisions
- **Module-owned exception handler, not a global registration.** The `ConfigValidationError` family belongs to the machineconfig parser, so the handler lives in `modules/machineconfig/router.py` and is registered from `on_load`. The legacy flat routers stay untouched.
- **`ModuleContext.app` is the wiring channel.** Adding `app: Optional[FastAPI]` to the dataclass is the smallest possible contract change — it preserves the existing `module_id` / `event_bus` / `settings` / `extras` fields and stays optional so the legacy test-only `isolated_machine_config` fixture (which never passes an app) still works.
- **Dynamic import in `console.js`.** Importing the toast store at module-init time would pull it into the console's evaluation cycle; the dynamic import inside `_emitToast` keeps the dependency one-way and lets the console still boot when the toast layer is absent (e.g. tests that mock Pinia).
- **`ConfigValidationError` is a `ValueError`.** The compile endpoint's existing `except ValueError` clause now has an explicit `except ConfigValidationError` ahead of it — reordering the existing branches would silently swallow the new structured response. The contract is documented inline so a future refactor cannot regress it.
- **Static-structural frontend tests.** Pinia is not drivable from bare `node --test` (see `.agent/LESSONS_LEARNED.md` § 5.2); the new toast/popup tests assert on the contract surface via regex. Dynamic regressions are caught by the Vite build step in CI.

### Testing Verification
- [x] Ran local test suite / build checks
- Backend: `python -m compileall -q backend && python -m pytest backend/tests` → 324 passed (including 4 new parser tests for the duplicate-pin rule, 1 regression guard, and 1 compile-endpoint integration test using the user's example config).
- Frontend: `npm --prefix frontend run build` → ✓ built (only pre-existing `INEFFECTIVE_DYNAMIC_IMPORT` warnings about `EditorView` static imports remain).
- Frontend: `node --test frontend/tests/**/*.mjs` → 103 passed (5 new tests for toast composable + console-store popup option).
- API codegen: `node frontend/scripts/generate-api.mjs` against the live backend → schema regenerated, no breakage.
