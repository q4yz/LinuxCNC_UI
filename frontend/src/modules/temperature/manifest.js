// Frontend manifest for the temperature module.
//
// Mirrors the backend ModuleManifest so the frontend registry can
// surface the same metadata to the rest of the app. ``settingsPanel:
// true`` causes the settings view to render a Temperature tab.
//
// We intentionally omit the ``sidebar`` field — temperature lives in
// the dashboard grid, not as a top-level nav entry.

export default {
  id: "temperature",
  title: "Temperature",
  version: "0.1.0",
  description: "Heater target / actual sensor monitoring.",
  settingsPanel: true,
};
