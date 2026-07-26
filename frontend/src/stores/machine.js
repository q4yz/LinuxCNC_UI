// Legacy public re-export shim. New machine code should import from
// ``../modules/machine/store.js`` directly. Shell components use the
// optional ``machine-compat.js`` adapter so deleting the module folder
// still leaves a buildable, inert application.
//
// This file intentionally remains a direct re-export for third-party
// consumers while the migration window is open.
export { useMachineStore, useMachineRefs } from '../modules/machine/store.js';
export { default } from '../modules/machine/store.js';
