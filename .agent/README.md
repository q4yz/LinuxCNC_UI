# `.agent/` — Agent & Contributor Documentation

This directory holds the contracts and rules that govern the
per-domain router pattern, the repository agent guide, and the
hub-and-spoke context model used by the agents.

| Path | Audience | Purpose |
|------|----------|---------|
| [.agent/context/hub.md](.agent/context/hub.md) | AI agents | **Primary entry point.** Repository map + spoke navigation. Start here. |
| [.agent/context/VISION.md](.agent/context/VISION.md) | AI agents | Project goals, philosophy, what we are not building. |
| [.agent/context/ARCHITECTURE.md](.agent/context/ARCHITECTURE.md) | AI agents | Technical structure: the three-process backend split, the frontend layout, the event bus, safety watchdogs. |
| [.agent/context/BACKEND_LAYERS.md](.agent/context/BACKEND_LAYERS.md) | Backend module authors | Canonical Router → Service → DTO → Mapper → Storage pattern with worked examples and module cheat-sheet. |
| [.agent/context/LESSONS_LEARNED.md](.agent/context/LESSONS_LEARNED.md) | AI agents | Past mistakes and tripwires (Pinia store ids, eager imports, venv cache, the jog watchdog). |
| [.agent/AGENT.md](.agent/AGENT.md) | All AI agents | Repository agent guide. Stack, structure, typing discipline, backend + frontend conventions, quality and scope rules. |
| [.agent/HANDOFF_TEMPLATE.md](.agent/HANDOFF_TEMPLATE.md) | Issue resolvers | Required PR description format. |
| [.agent/TEST.md](.agent/TEST.md) | CI / orchestrator | The bash script the orchestrator runs to verify every edit. Do not run it yourself. |
| [.agent/STATE.md](.agent/STATE.md) | All contributors | Frontend/backend operational notes (base-thread split, event bus, camera/macros domain details). |
| [.agent/HANDOFF.md](.agent/HANDOFF.md) | AI agents | Agent-maintained log of past work, plus the current technical-debt list (§ 2). Optional — safe to delete. |
| [.agent/contracts/backend-router.md](.agent/contracts/backend-router.md) | Backend authors | Canonical per-domain router contract, one per app. |
| [.agent/contracts/settings-module.md](.agent/contracts/settings-module.md) | Module authors | Settings endpoints, storage layout, atomic-write contract. |

> **No frontend module contract.** There is no dynamic frontend
> module registry — components are imported directly where they're
> used (see [.agent/context/ARCHITECTURE.md](.agent/context/ARCHITECTURE.md) § 2). A
> `contracts/frontend-module.md` from an earlier architecture was
> deleted along with that registry; if you see a stale link to it
> anywhere, it's a leftover to fix, not a file to go looking for.

See also `MODULE_SYSTEM_ROADMAP.md` at the repo root for the
broader historical module-system plan (not present in the current
working tree).
