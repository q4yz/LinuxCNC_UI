## What this PR does

- Replaces the recursive Profiles Explorer tree with drill-down folder navigation, breadcrumbs, and a back button.
- Adds full-screen profile editing on file double-click through the parent `ConfigView`.
- Adds per-entry kebab actions for rename, move, and delete, plus a floating create dialog.
- Adds drag-and-drop profile uploads into the currently viewed directory, file-size labels, and individual profile downloads.
- Adds individual compiled-artifact downloads and a client-generated Download ZIP action.
- Adds a dedicated staged `remora.json` download control to the deployment panel.

## Files changed / added

- `backend/modules/machineconfig/router.py` — profile upload endpoint.
- `frontend/src/modules/machineconfig/services/api.js` — multipart upload API support.
- `frontend/src/modules/machineconfig/store.js` — profile upload action.
- `frontend/src/modules/machineconfig/components/ProfilesExplorer.vue` — drill-down explorer and requested interactions.
- `frontend/src/modules/machineconfig/components/CompiledOutputViewer.vue` — file and ZIP downloads.
- `frontend/src/modules/machineconfig/components/DeploymentPanel.vue` — `remora.json` download.
- `frontend/src/views/ConfigView.vue` — full-screen profile editor state and handoff.

## How it was tested

- `npm run build` from `frontend/` — passed (existing bundle-size and dynamic-import warnings only).
- `python3 -m pytest backend/tests/test_machineconfig_module.py` — 22 passed.

## Acceptance-criteria checklist

- [x] Folder clicks drill into immediate contents only.
- [x] Breadcrumbs and one-level back navigation are available.
- [x] Double-clicking a profile file mounts a full-screen editor and hides the normal layout.
- [x] Kebab menu provides Rename, Copy (Move), and Delete operations.
- [x] Floating + opens file/folder creation in the current directory.
- [x] Explorer accepts dropped files in the current directory and shows drag feedback.
- [x] Profile file sizes and individual downloads are shown.
- [x] Compiled files have individual downloads and a Download ZIP action.
- [x] Deployment controls can download staged `remora.json`.
