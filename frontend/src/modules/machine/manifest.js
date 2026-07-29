// Frontend manifest for the machine module. Mirrors
// ``backend/modules/machine/module.py``. The ``sidebar`` field is
// intentionally omitted — machine lives at the root of the
// dashboard rather than as a top-level nav entry.

export default {
  id: "machine",
  title: "Machine",
  version: "0.1.0",
  description: "DRO, jogging, state, MDI, home.",
  settingsPanel: true,
};
