// Frontend manifest for the machineconfig module (issue #41).
//
// Mirrors ``backend/modules/machineconfig/module.py`` so the frontend
// registry surfaces the same metadata to the rest of the app. The
// module contributes a sidebar entry that reuses the legacy config
// slot so the sidebar still lands in ``ConfigView`` while showing the
// new ``Machine Config`` label, plus a Settings tab so operators can
// tune ``require_confirm_flash`` / ``auto_readonly_after_stage`` /
// ``default_compiler_id`` from the existing settings surface.
//
// The store id is namespaced under the ``module_`` prefix per
// ``.agent/contracts/frontend-module.md`` § 5 — the lint script
// ``frontend/scripts/check-store-ids.mjs`` enforces this.

export default {
  id: "machineconfig",
  title: "Machine Config",
  version: "0.1.0",
  description:
    "Profiles editor, compiler selection, staged/active viewer, deployment.",
  sidebar: { id: "config", label: "Machine Config", order: 60 },
  settingsPanel: true,
};