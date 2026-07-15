# `frontend/src/modules/`

This directory is the **frontend module discovery surface** mirrored
from `backend/modules/`. Each sub-folder contributes a default export
shaped like [`FrontendModule`](../../core/modules/protocols.js) so
the [`FrontendRegistry`](../../core/modules/registry.js) can wire it
into the application at startup.

See [`.agent/contracts/frontend-module.md`](../../../.agent/contracts/frontend-module.md)
for the full contract.

While no modules are mounted, this directory is intentionally empty —
`npm run build` still succeeds (zero errors, zero warnings) and the
registry logs `[registry] mounted=[] skipped=0 missing=0`.