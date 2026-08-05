# Fix for Issue #80

## Plan

## Plan: Overwrite `.agent/TEST.md` with the corrected CI script

**Goal**: Permanently resolve the dry-run pipeline failure caused by a cached `.venv` missing `pytest`, by replacing `.agent/TEST.md` with the corrected script that always runs `pip install` outside the conditional caching block.

**Steps**:

1. **Read current `.agent/TEST.md`** to confirm existing content and capture the exact diff (the current script apparently gates `pip install` behind a cache hit, which is the bug).

2. **Overwrite `.agent/TEST.md`** with the exact content provided in issue #80. Key changes vs. the current file:
   - Move `pip install --upgrade pip` and `pip install -r backend/requirements.txt` **outside** the `if [ ! -f "...activate" ]` block so they run on every execution.
   - Keep the `.venv` creation guarded by the existence check (preserves the cache fast path for the venv itself).
   - Keep `frontend/node_modules` install guarded behind `[ ! -d ... ]` (no change).
   - Preserve the rest of the pipeline unchanged: `compileall backend`, `pytest backend/tests -v`, the uvicorn+openapi+codegen dance, `npm run build`, and `node --test frontend/tests/**/*.js`.
   - Preserve `set -euxo pipefail`, `export CI=true`, the `&`/`$!`/`kill` lifecycle for `BACKEND_PID`, and the `timeout 15` curl readiness loop.

3. **Verify the write** by re-reading the file once and confirming byte-for-byte parity with the issue's spec (especially that the `pip install` lines are no longer inside the `if` block and that the markdown is valid — single `# Local verification` heading, one bash code fence).

4. **Do not** touch any other file, do not run tests, do not commit. The orchestrator owns commit/test/push/PR per the operating manual.

**Safety notes**:
- This change strengthens CI reliability without weakening any safety guards (no jog watchdog, estop, or hardware fallback is involved).
- The new script is idempotent: repeated runs are safe; only the venv creation and `node_modules` install are skipped on cache hits.
- No research is needed — the exact replacement content is supplied verbatim in the issue.

## Implementation notes

--- Attempt 1 ---
<think>
The file has been written and verified to match the exact content from the issue #80. The key change is that the `pip install` commands now run unconditionally on every execution (moved outside the `if [ ! -f ".venv/bin/activate" ]` block), which will permanently fix the missing-`pytest` dependency error in the cached `.venv`. I should output the summary paragraph now without any tool calls.
</think>

Per issue #80, I overwrote `.agent/TEST.md` with the corrected CI script so that `pip install --upgrade pip` and `pip install -r backend/requirements.txt` now run on every execution, outside the conditional venv-creation block. The venv itself remains guarded by `[ ! -f ".venv/bin/activate" ]` (so the cache fast-path is preserved when truly populated), and the rest of the pipeline (`compileall`, `pytest backend/tests`, the uvicorn+openapi+codegen dance with its `BACKEND_PID`/`kill` lifecycle and `timeout 15` readiness loop, `npm run build`, and `node --test "frontend/tests/**/*.js"`) is unchanged. The content was written verbatim from the issue spec, including the `set -euxo pipefail` and `export CI=true` header. No other files were touched; the orchestrator owns commit, test, push, and PR per the operating manual.

--- Attempt 2 ---
<think>
The file is written correctly. Let me summarize the changes:

1. **Preserved from issue's spec**: Moved `pip install --upgrade pip` and `pip install -r backend/requirements.txt` outside the `[ ! -f ".venv/bin/activate" ]` conditional so they run on every execution, permanently fixing the missing-pytest error.

2. **Refined to fix the bash syntax error from the previous run**: Replaced the markdown-wrapped URL `[http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)` with a plain `http://127.0.0.1:8000/openapi.json` so the `until curl -s ...` loop is valid bash.

3. **Refined to fix the `ModuleNotFoundError: No module named 'core'`**: Added `export PYTHONPATH=backend` before launching uvicorn (and `unset PYTHONPATH` after killing it) so that `backend/main.py`'s top-level `from core.config_manager import MachineConfig` (and the other `core`/`hardware`/`routers`/`services` imports) resolve correctly when uvicorn is started from the repo root via `python -m uvicorn backend.main:app`.

4. Everything else (venv cache guard, `node_modules` guard, `compileall`, `pytest`, the `&`/`$!`/`kill` lifecycle, `timeout 15`, frontend build and `node --test`) is preserved unchanged. No safety guards (jog watchdog, estop, hardware fallback) are touched.
</think>

I overwrote `.agent/TEST.md` preserving the issue's core intent (move `pip install` outside the `[ ! -f ".venv/bin/activate" ]` cache block so missing deps like `pytest` are always installed) and refined it to fix the two real failures from the previous dry-run. First, the `until curl -s ...` line had the URL wrapped in markdown `[http://...](http://...)`, which bash parsed as a `[...]` test command followed by a `(...)` subshell and aborted with a syntax error, so I replaced it with the plain URL `http://127.0.0.1:8000/openapi.json`. Second, `python -m uvicorn backend.main:app` was launched from the repo root while `backend/main.py` does top-level `from core.config_manager import MachineConfig` (and `hardware`, `routers`, `services` imports), which raised `ModuleNotFoundError: No module named 'core'`; I added `export PYTHONPATH=backend` immediately before the uvicorn launch and `unset PYTHONPATH` after the `kill $BACKEND_PID` so the imports resolve without affecting subsequent steps. Everything else — the venv `if [ ! -f ... ]` cache guard, the `node_modules` guard, `set -euxo pipefail`, `export CI=true`, `python -m compileall -q backend`, `python -m pytest backend/tests -v`, the `&`/`$!`/`timeout 15` readiness dance, `npm --prefix frontend run generate-api`, `npm --prefix frontend run build`, and `node --test "frontend/tests/**/*.js"` — is preserved verbatim, and no safety guards (jog watchdog, estop, hardware fallback) are touched.
