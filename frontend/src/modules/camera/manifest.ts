// Manifest for the camera frontend module.
//
// Mirrors ``backend/modules/camera/module.py``'s ``ModuleManifest``.
// The registry (``frontend/src/core/modules/registry.js``) reads this
// before calling ``onLoad`` so the sidebar / settings tabs can render
// without invoking the module's runtime hooks.
//
// Field reference lives in
// ``.agent/contracts/frontend-module.md`` § 2.
//
// Why a dedicated file instead of an inline object?
//   * Easier to grep "camera" -> manifest in code review.
//   * Same pattern as ``backend/modules/camera/module.py`` — manifest
//     is data, not behaviour, so it lives in its own file.
//   * Keeps ``index.js`` focused on lifecycle wiring.

// Inline SVG icon — a simple video-camera glyph used in the sidebar.
// Kept small and self-contained so the registry can ship it via
// ``v-html`` without an extra round-trip.
const cameraIcon =
  '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" ' +
  'd="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />' +
  '</svg>'

export default {
  id: 'camera',
  title: 'Camera',
  version: '0.1.0',
  description: 'Live USB webcam MJPEG stream.',
  // ``order: 50`` floats the camera sidebar entry above the built-in
  // items (which all default to ``order: 100``) so users can find it
  // without scrolling. Tweak if more dashboard-bound modules appear.
  sidebar: {
    id: 'camera',
    label: 'Camera',
    icon: cameraIcon,
    order: 50,
  },
  settingsPanel: true,
}