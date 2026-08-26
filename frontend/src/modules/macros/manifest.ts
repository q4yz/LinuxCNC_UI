// Frontend manifest for the macros module. Mirrors
// ``backend/modules/macros/module.py``.
//
// Macros live in two places in the UI:
//   1. The dashboard panel (``MacroPanel.vue``) — list + "Run" buttons so
//      operators can invoke them without leaving the dashboard.
//   2. The Machine Config "Macros" tab (``MacroManagerPanel.vue``) — full
//      CRUD: create, edit (inline CodeMirror modal), delete.
//
// The module deliberately omits a sidebar entry — the dashboard
// panel is the primary surface and the management tab lives inside
// ``EditorView.vue``. The contract requires every manifest to
// declare the field, so the manifest ships an empty entry that the
// registry filters out by ``id``.
// ``settingsPanel: true`` is a hint for the future Settings UI work; today
// the Machine Config tab already serves as the management surface.

interface SidebarEntry {
  id: string;
  label: string;
  icon: string;
  order: number;
}

interface MacrosManifest {
  id: string;
  title: string;
  version: string;
  description: string;
  sidebar: SidebarEntry;
  settingsPanel: boolean;
}

const manifest: MacrosManifest = {
  id: "macros",
  title: "Macros",
  version: "0.1.0",
  description:
    "User-defined .macro files; trigger static blocks via MDI, manage them from the Machine Config view.",
  sidebar: {
    id: "",
    label: "",
    icon: "",
    order: 100,
  },
  settingsPanel: true,
};

export default manifest;