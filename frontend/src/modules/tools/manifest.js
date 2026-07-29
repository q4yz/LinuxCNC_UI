// Tools module manifest. Mirrors ``backend/modules/tools/module.py``.
// The panel lives in the dashboard grid — no sidebar entry, no
// Settings tab. See ``.agent/STATE.md`` § 9.

export default {
  id: "tools",
  title: "Tools",
  version: "0.1.0",
  description:
    "Spindle and extruder MDI command surface with a mock tool list.",
  settingsPanel: false,
};