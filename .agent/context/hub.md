# Hub — Repository Entry Point for AI Agents

This is the **primary entry point** for any AI agent working on
this codebase. Read this file first, then follow the spokes to
the documents you need for your task. Do not browse the
repository directly; the spokes already encode the curated
context you need.

> **Note for human readers.** This file is for AI agents. If you
> are a human developer, start at [`README.md`](README.md) for
> the run/build/contribute guide.

---

## 1. Repository map

```
LinuxCNC_UI/
├── README.md                  # Human developer entry point
│
├── .agent/                    # AI agent contracts + working memory
│   ├── context/               # Hub-and-spoke docs (AI agent entry point)
│   │   ├── hub.md             # This file — AI agent entry point
│   │   ├── VISION.md          # Project goals + philosophy
│   │   ├── ARCHITECTURE.md    # Technical structure + module registry graph
│   │   └── LESSONS_LEARNED.md # Past mistakes and pitfall tripwires
│   ├── AGENT.md               # Operating manual for the AI agent
│   ├── TEST.md                # Bash script the orchestrator runs to verify edits
│   ├── STATE.md               # Current as-built state of the module system
│   ├── README.md              # Index of the .agent/ folder
│   ├── HANDOFF_TEMPLATE.md    # PR description template
│   ├── HANDOFF.md             # Agent-maintained handoff log (optional — see § 2.2)
│   ├── contracts/             # Backend + frontend + settings module contracts
│   │   ├── backend-module.md
│   │   ├── frontend-module.md
│   │   └── settings-module.md
│   └── doc/                   # Offline LinuxCNC reference docs
│       └── linuxcnc_docs.htlm # Rendered reference (legacy filename extension)
│
├── backend/                   # FastAPI app
│   ├── main.py                # App + lifespan + router includes
│   ├── core/                  # Hardware-agnostic: models, event bus, registry
│   ├── hardware/              # Hardware abstraction (real linuxcnc + mock)
│   ├── modules/               # Pluggable feature modules (camera, machine, …)
│   ├── routers/               # Legacy flat routers
│   ├── services/              # Cross-module service objects
│   └── tests/                 # pytest: 240+ tests
│
├── frontend/                  # Vue 3 SPA
│   ├── src/
│   │   ├── core/              # Cross-module: registry, event-bus, settings
│   │   ├── modules/           # Self-contained feature modules
│   │   ├── components/        # Legacy / shared widgets
│   │   ├── views/             # Route components
│   │   ├── stores/            # Legacy top-level Pinia stores
│   │   ├── router/            # Vue Router config
│   │   ├── config/            # Centralized G-code constants + helpers
│   │   ├── services/          # Generated OpenAPI client + helpers
│   │   └── generated/api/     # OpenAPI-generated services (gitignored)
│   ├── tests/                 # node --test: 98+ static-structural tests
│   └── package.json
│
├── scripts/                   # Dev utilities (minimax_local proxy, etc.)
├── cnc_ini/                   # Operator-supplied axis INI files
├── gcodes/                    # Operator-supplied G-code examples
├── nc_files/                  # Uploaded G-code lives here
├── machine_config/            # SSOT for machine.cfg + profiles / staged / active
└── backend/requirements.txt   # Backend-only Python deps (see backend/README.md)
                                # NOTE: there is no top-level requirements.txt; do
                                # not expect one to exist.

> **Note on the ``HANDOFF.md`` entry.** `.agent/HANDOFF.md` is the
> agent-maintained handoff log created by previous agents. It is
> **optional** — the orchestrator's structural test treats it as
> optional, so the file may be deleted without breaking the build.
> When present, the agent should read it before diving into code
> so it does not redo work that has already been attempted.
```

## 2. Spokes — read what your task needs

### 2.1 Always read

These two files describe the project at the level an AI agent
needs before editing any code.

| Spoke | What it tells you |
|-------|-------------------|
| [`.agent/context/VISION.md`](.agent/context/VISION.md) | Why the project exists, what it optimizes for, what it is not. Use this to push back on requests that violate the philosophy. |
| [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) | Backend + frontend layout, the module registry graph, the event bus, the state facade, the safety watchdog. Use this to find the right file to edit. |

### 2.2 Read when relevant

| Spoke | When to read it |
|-------|-----------------|
| [`.agent/context/LESSONS_LEARNED.md`](.agent/context/LESSONS_LEARNED.md) | Before you do anything that has burned us before: Pinia store ids, eager imports, venv cache, the jog watchdog, hardcoded G-code, monolithic `App.vue`. The tripwires are the most valuable content. |
| [`.agent/HANDOFF.md`](.agent/HANDOFF.md) | When you want to know what previous agents have already tried, completed, or abandoned. Optional — if the file is missing, this entry silently skips. |
| [`.agent/STATE.md`](.agent/STATE.md) | When you need to know the **current** state of the module system (active modules, store id rules, nullable-module guarantee, migration window). Source of truth for the as-built system. |
| [`.agent/contracts/backend-module.md`](.agent/contracts/backend-module.md) | When you are creating or modifying a backend module. |
| [`.agent/contracts/frontend-module.md`](.agent/contracts/frontend-module.md) | When you are creating or modifying a frontend module. |
| [`.agent/contracts/settings-module.md`](.agent/contracts/settings-module.md) | When you are touching the four canonical settings endpoints. |
| [`.agent/AGENT.md`](.agent/AGENT.md) | When you need a reminder of the operating manual (no commits, no tests, no PRs, one-paragraph summary, honest no-op). |
| [`.agent/TEST.md`](.agent/TEST.md) | When you need to know what the orchestrator will run to verify your edits. Do **not** run it yourself. |
| [`.agent/HANDOFF_TEMPLATE.md`](.agent/HANDOFF_TEMPLATE.md) | When the orchestrator asks for a PR description. |
| `MODULE_SYSTEM_ROADMAP.md` (root) | When you are picking up a ticket that says "Phase 4" or "Phase 5" or higher. Not present in the working tree. |
| [`README.md`](README.md) | When the task is about the run/build/contribute experience for humans. |

### 2.3 Do not read

These exist for historical context; the relevant content has been
migrated to the spokes above. Skim only if a spoke explicitly
points you at them.

| File | Why it's superseded |
|------|---------------------|
| Archived `AI_INSTRUCTIONS.md` / `archived_notes.md` | Deleted; content migrated to `VISION.md`, `ARCHITECTURE.md`, and `LESSONS_LEARNED.md`. |
| `MODULE_SYSTEM_EVALUATION.md` (root) | Original module design notes; the canonical state is in `.agent/STATE.md`. Not present in the working tree. |
| `PROJECT_ARCHITECTURE.md` (root) | Original architecture draft; the canonical version is `ARCHITECTURE.md`. Not present in the working tree. |
| `HANDOFF.md` (root) | Cross-team handoff content was integrated into `VISION.md`. Not present in the working tree. |
| `MODULE_SYSTEM_ROADMAP.md` (root) | Module design backlog supersedes by per-section references in the spokes. Not present in the working tree. |

## 3. How to navigate

1. **Read the one-paragraph summary at the top of
   [`.agent/context/VISION.md`](.agent/context/VISION.md)** to
   confirm the task is in scope.
2. **Skim the relevant section of
   [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md)**
   to find the file(s) the task touches.
3. **Check
   [`.agent/context/LESSONS_LEARNED.md`](.agent/context/LESSONS_LEARNED.md)**
   for any past mistake that matches the proposed approach.
4. **If the task is a module change**, read the matching contract
   in [`.agent/contracts/`](.agent/contracts/).
5. **Write the minimum code change**, then stop and reply with
   one paragraph. The orchestrator runs
   [`.agent/TEST.md`](.agent/TEST.md) after your edit.

## 4. Anti-patterns (load-bearing reminders)

- **Do not commit, push, run tests, or open PRs.** The
  orchestrator owns the workflow.
- **Do not browse the repo.** Read the spokes; they are the
  curated context.
- **Do not write code for a request that violates
  [`.agent/context/VISION.md`](.agent/context/VISION.md).**
  Push back in the summary paragraph instead.
- **Do not invent a fix.** If you are stuck after 2-3 attempts,
  return the honest no-op (see
  [`.agent/AGENT.md`](.agent/AGENT.md)).

---

**If you only have time to read three files, read these:**

1. [`.agent/context/VISION.md`](.agent/context/VISION.md) — the why.
2. [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) — the where.
3. [`.agent/context/LESSONS_LEARNED.md`](.agent/context/LESSONS_LEARNED.md) — the don't.
