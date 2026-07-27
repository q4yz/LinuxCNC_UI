// Manifest for the tools frontend module.
//
// Mirrors ``backend/modules/tools/module.py``'s ``ModuleManifest``
// so the frontend registry can surface the same metadata. Issue
// #64 ships the spindle / extruder controls as an in-dashboard
// panel — no sidebar entry, no Settings tab.

export default {
  id: "tools",
  title: "Tools",
  version: "0.1.0",
  description:
    "Spindle and extruder MDI command surface with a mock tool list.",
  // ``sidebar`` is intentionally omitted — the panel lives in
  // the dashboard grid, mirroring the temperature module's layout.
  settingsPanel: false,
};