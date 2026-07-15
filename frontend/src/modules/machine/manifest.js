// Frontend manifest for the machine module.
//
// Mirrors ``backend/modules/machine/module.py`` so the frontend
// registry surfaces the same metadata to the rest of the app.
// ``settingsPanel: true`` causes the Settings view to render a
// "Machine" tab (currently showing a placeholder until the settings
// UI lands in Phase 5).
//
// We intentionally omit the ``sidebar`` field — machine lives at
// the root of the dashboard rather than as a top-level nav entry,
// matching the historical behaviour of the dashboard composition
// in ``DashboardView.vue``.

export default {
  id: "machine",
  title: "Machine",
  version: "0.1.0",
  description: "DRO, jogging, state, MDI, home.",
  settingsPanel: true,
};
