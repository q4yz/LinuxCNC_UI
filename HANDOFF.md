### Resolution Summary
Deleted the legacy `/api/v1/file/*` routes from `backend/routers/machine.py` (the unused `file_router`, the `GcodeFile` / `ConfigFile` Pydantic models, the `GCODES_DIR` / `CNC_INI_DIR` constants, and the `os` / `UploadFile` / `File` imports that only supported them) and re-pointed the only remaining legacy frontend caller (`api.loadProgram`) to the consolidated `/api/v1/files/load_program` endpoint, which was added to the modern `backend/routers/files.py` router so the frontend "Load" action still functions end-to-end.

### Files Modified
- `backend/routers/machine.py`: Removed `file_router` (`/api/v1/file/*`), the legacy file/config endpoints (`load`, `list`, `upload`, `delete`, `load_program`, `configs`, `config/{filename}`), the `GCODES_DIR` / `CNC_INI_DIR` directory setup, and the `GcodeFile` / `ConfigFile` Pydantic models plus now-unused `os`, `UploadFile`, `File` imports. Module now exposes only `router` (`/api/v1/machine/*`) and `program_router` (`/api/v1/program/*`).
- `backend/routers/files.py`: Added `LoadProgramRequest` Pydantic model and `POST /api/v1/files/load_program` endpoint (ported from the removed `machine.file_router` `load_program` so the frontend "Load" button still resolves), wired via the standard `hardware.execute_sync_cmd` / `linuxcnc` accessors so the `linuxcnc_mock` fallback continues to work.
- `frontend/src/services/api.js`: Updated `loadProgram` from the legacy `/file/load_program` path to the modern `/files/load_program` path so the SPA calls only the consolidated `/api/v1/files/*` namespace.

### Architectural Decisions
- Followed `.agent/AGENT.md`: kept LinuxCNC access funnelled through `backend/hardware/connection.execute_sync_cmd` and the `linuxcnc` re-export (with `linuxcnc_mock` fallback) rather than importing the real `linuxcnc` module inside the file router.
- Preserved the modern Pydantic + `summary` / `description` metadata convention; the new endpoint mirrors the existing `files.py` style (4-space indent, double quotes, structured logging).
- Did not touch `/api/v1/program/*` or `/api/v1/config/*` — those routers were already correctly structured, and the issue scope was strictly the `/file/*` legacy split.
- Left a couple of intentionally unused imports (`time` for the placeholder `trigger_parser` mock delay, `from typing import List` in `files.py`) alone to honour the "smallest change that solves the requested concern" rule and avoid mixing in unrelated refactors.

### Testing Verification
- [x] Ran `python3 -m compileall -q backend` — produced no errors.
- [x] Ran `npm --prefix frontend run build` — completed successfully (`built in 3.24s`, 894 modules transformed).
- [x] Imported both routers in a smoke script and listed their registered routes — `machine.router` exposes 5 machine routes, `machine.program_router` exposes 5 program routes, and `files.router` exposes `GET /api/v1/files`, `POST /api/v1/files/upload`, `DELETE /api/v1/files/{filename}`, and the new `POST /api/v1/files/load_program`. No `/api/v1/file/*` paths remain.
- [ ] Manual browser exercise of the File manager "Load" button was not performed (no LinuxCNC runtime / mock instance available in this sandbox); the route is now actually mounted and serves the same backend operations as before.
