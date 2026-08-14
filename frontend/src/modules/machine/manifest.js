// Frontend manifest for the machine module. Mirrors
// ``backend/modules/machine/module.py``.
//
// The machine module is a hard dependency: it lives at the root of
// the dashboard rather than as a top-level nav entry. The contract
// requires every manifest to declare the ``sidebar`` field so the
// manifest ships an empty entry that the registry filters out by
// ``id``.

export default {
  id: "machine",
  title: "Machine",
  version: "0.1.0",
  description: "DRO, jogging, state, MDI, home.",
  sidebar: {
    id: "",
    label: "",
    icon: "",
    order: 100,
  },
  settingsPanel: true,
};
