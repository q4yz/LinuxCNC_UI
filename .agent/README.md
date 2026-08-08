# `.agent/` — Agent & Contributor Documentation

This directory holds the contracts and rules that govern the
pluggable-module system, the three AI agent operating manuals,
and the hub-and-spoke context model used by the agents.

| Path | Audience | Purpose |
|------|----------|---------|
| [`.agent/context/hub.md`](.agent/context/hub.md) | AI agents | **Primary entry point.** Repository map + spoke navigation. Start here. |
| [`.agent/context/VISION.md`](.agent/context/VISION.md) | AI agents | Project goals, philosophy, what we are not building. |
| [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) | AI agents | Technical structure, module registry graph, event bus, safety watchdogs. |
| [`.agent/context/LESSONS_LEARNED.md`](.agent/context/LESSONS_LEARNED.md) | AI agents | Past mistakes and tripwires (Pinia store ids, eager imports, venv cache, the jog watchdog). |
| [`.agent/AGENT.md`](.agent/AGENT.md) | Loop agents | General loop-agent operating manual (iterative plan → act → observe → refine, free-form prose output, no commits). |
| [`.agent/ARCHITECT.md`](.agent/ARCHITECT.md) | Architect agents | General architect operating manual (design-only autonomy, may commit and open PRs within `.agent/`, root `*.md`, and `contracts/`). |
| [`.agent/graph_agent.md`](.agent/graph_agent.md) | GraphLLM orchestrator | The GraphLLM single-pass agent manual (no commits, no tests, no PRs; one-paragraph summary; honest no-op). |
| [`.agent/HANDOFF_TEMPLATE.md`](.agent/HANDOFF_TEMPLATE.md) | Issue resolvers | Required PR description format. |
| [`.agent/TEST.md`](.agent/TEST.md) | CI / orchestrator | The bash script the orchestrator runs to verify every edit. Do not run it yourself. |
| [`.agent/STATE.md`](.agent/STATE.md) | All contributors | Current as-built state of the module system. |
| [`.agent/contracts/backend-module.md`](.agent/contracts/backend-module.md) | Backend module authors | Canonical `PluggableModule` Protocol. |
| [`.agent/contracts/frontend-module.md`](.agent/contracts/frontend-module.md) | Frontend module authors | Canonical `FrontendModule` interface. |
| [`.agent/contracts/settings-module.md`](.agent/contracts/settings-module.md) | Module authors | Settings endpoints, storage layout, atomic-write contract. |

See also `MODULE_SYSTEM_ROADMAP.md` at the repo root for the
broader Phase 2b/2c/2d plan (not present in the current working tree).

> **Note:** The legacy `AI_INSTRUCTIONS.md` and `archived_notes.md`
> files were deleted when the content migrated into the
> `context/` spokes. The current AI agent's entry point is
> [`.agent/context/hub.md`](.agent/context/hub.md).