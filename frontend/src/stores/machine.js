// Legacy shim — re-exports the machine module's Pinia store under
// the historical import path. New code should import from the
// module directly:
//
//   import { useMachineStore } from '../modules/machine/store.js'
//
// This shim exists only until every consumer migrates. The original
// monolithic implementation that owned the WebSocket subscription
// and every machine action was extracted into
// ``frontend/src/modules/machine/store.js`` as part of issue #38;
// the components still importing from ``../stores/machine``
// (``DebugPanel.vue``, ``ConsolePanel.vue``, ``GCodeViewer.vue``,
// ``UpdateManager.vue``) keep working without code change because
// Pinia stores are singletons keyed by id.

export { useMachineStore, useMachineRefs } from '../modules/machine/store.js';
export { default } from '../modules/machine/store.js';
