// Camera frontend module entrypoint.
//
// The registry (``frontend/src/core/modules/registry.js``) imports this
// file via the lazy ``import.meta.glob('../modules/*/index.js', { eager: false })``
// and consumes the default export. ``onLoad`` runs synchronously at
// boot; long-running I/O must be scheduled by the module itself.
//
// ``CameraPanel`` is also re-exported as a named export so
// ``DashboardView.vue`` can import it via ``defineAsyncComponent`` and
// still tree-shake cleanly when the module is removed (Gotcha #1).

import manifest from './manifest.js'

const module = {
  manifest,
  // Mirroring ``manifest.sidebar`` keeps the registry's
  // ``record.sidebar = instance.sidebar ?? instance.manifest.sidebar``
  // line unambiguous; either form works but having both never hurts.
  sidebar: manifest.sidebar,
  onLoad(/* ctx */) {
    // No-op for v1. The dashboard loads ``CameraPanel`` lazily via
    // ``defineAsyncComponent``; this hook is the place to subscribe to
    // module events (e.g. ``camera.status``) once Phase 4 lands.
  },
  onUnload() {
    // Idempotent teardown placeholder. If the module later subscribes
    // to events or owns timers, clear them here.
  },
}

export default module
export { manifest }