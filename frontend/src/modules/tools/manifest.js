// Tools module manifest. Mirrors ``backend/modules/tools/module.py``.
// The panel lives in the dashboard grid — no sidebar entry, no
// Settings tab. The contract requires every manifest to declare the
// ``sidebar`` field so the manifest ships an empty entry that the
// registry filters out by ``id``.

export default {
  id: "tools",
  title: "Tools",
  version: "0.1.0",
  description:
    "Spindle and extruder MDI command surface with a mock tool list.",
  sidebar: {
    id: "",
    label: "",
    icon: "",
    order: 100,
  },
  settingsPanel: false,
};
