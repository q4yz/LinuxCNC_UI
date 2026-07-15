# `.agent/` — Agent & Contributor Documentation

This directory holds the contracts and rules that govern the
pluggable-module system plus the original AI constraints that
backed the rest of the project.

| Path | Audience | Purpose |
|------|----------|---------|
| [`AGENT.md`](AGENT.md) | All contributors | Repository-wide conventions, layer responsibilities, quality rules. |
| [`AI_INSTRUCTIONS.md`](AI_INSTRUCTIONS.md) | AI agents | Stack constraints, modularity rules, telemetry & safety guidance. |
| [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md) | Issue resolvers | Required PR description format. |
| [`TEST.md`](TEST.md) | CI / contributors | Build + test commands. |
| [`contracts/backend-module.md`](contracts/backend-module.md) | Backend module authors | Canonical `PluggableModule` Protocol. |
| [`contracts/frontend-module.md`](contracts/frontend-module.md) | Frontend module authors | Canonical `FrontendModule` interface. |
| [`contracts/settings-module.md`](contracts/settings-module.md) | Module authors | Settings endpoints, storage layout, atomic-write contract. |

See also [`MODULE_SYSTEM_ROADMAP.md`](../MODULE_SYSTEM_ROADMAP.md) at the
repo root for the broader Phase 2b/2c/2d plan.