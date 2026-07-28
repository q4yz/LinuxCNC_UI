// Machineconfig module manifest. Mirrors
// ``backend/modules/machineconfig/module.py`` so the registry surfaces
// the same metadata. The sidebar entry reuses the legacy ``config``
// slot so it still routes to ``ConfigView``. See
// ``.agent/STATE.md`` § 9 (active modules table).

export default {
  id: "machineconfig",
  title: "Machine Config",
  version: "0.1.0",
  description:
    "Profiles editor, compiler selection, staged/active viewer, deployment.",
  sidebar: { id: "config", label: "Machine Config", order: 60 },
  settingsPanel: true,
};