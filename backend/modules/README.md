# `backend/modules/`

This directory is the **module discovery surface** for Phase 2b/2c
of the module system. Each sub-package is a self-contained feature
that gets plugged into the application at startup via
[`ModuleRegistry`](../core/module_registry.py).

A module is **any sub-package** that exposes a top-level `setup()`
factory returning a [`PluggableModule`](../core/protocols.py) instance.

See [`.agent/contracts/backend-module.md`](../../.agent/contracts/backend-module.md)
for the full contract.

While no modules are mounted, this directory is intentionally empty —
the application boots cleanly with zero modules and the registry logs
`registry: mounted=[] skipped=0 missing=0`.