// Frontend manifest for the temperature module.
//
// Mirrors the backend ModuleManifest so the frontend registry can
// surface the same metadata to the rest of the app. ``settingsPanel:
// true`` causes the settings view to render a Temperature tab.
//
// The temperature module does not contribute a sidebar entry — it
// lives inside the dashboard grid, not as a top-level nav item —
// but the contract requires every module to declare the field, so
// the manifest ships an empty entry that the registry filters out
// by ``id``.

export default {
  id: "temperature",
  title: "Temperature",
  version: "0.1.0",
  description: "Heater target / actual sensor monitoring.",
  sidebar: {
    id: "",
    label: "",
    icon: "",
    order: 100,
  },
  settingsPanel: true,
};
