# Hub — Repository Entry Point for AI Agents

This is the **primary entry point** for any AI agent working on
this codebase. Read this file first, then follow the spokes to
the documents you need for your task. Do not browse the
repository directly; the spokes already encode the curated
context you need.

> **Note for human readers.** This file is for AI agents. If you
> are a human developer, start at [README.md](README.md) for
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
│   │   ├── ARCHITECTURE.md    # Technical structure: the 3-process backend split + frontend layout
│   │   ├── BACKEND_LAYERS.md  # Canonical Router → Service → DTO → Mapper → Storage pattern
│   │   └── LESSONS_LEARNED.md # Past mistakes and pitfall tripwires
│   ├── AGENT.md               # Repository agent guide (stack, typing rules, conventions, quality/scope)
│   ├── TEST.md                # Bash script the orchestrator runs to verify edits
│   ├── STATE.md               # Frontend/backend operational notes (base-thread split, event bus, domain gotchas)
│   ├── README.md              # Index of the .agent/ folder
│   ├── HANDOFF_TEMPLATE.md    # PR description template
│   ├── HANDOFF.md             # Agent-maintained log + current technical-debt list (optional — see § 2.2)
│   ├── contracts/              # Backend router + settings module contracts
│   │   ├── backend-router.md  # Per-domain router contract, one per app
│   │   └── settings-module.md # Per-module settings endpoints contract
│   └── doc/                   # Offline LinuxCNC reference docs
│       └── linuxcnc_docs.htlm # Rendered reference (note the unusual .htlm extension — not a typo to "fix" blindly, check what generated it first)
│
├── backend/
│   ├── common/                 # Shared library — settings store, event bus, DTOs, domain
│   │                           # file services, hardware abstraction. Imported by both
│   │                           # apps below; never runs by itself.
│   ├── machine/                 # Machine backend (FastAPI, port 8000) — telemetry, NML,
│   │                           # jogging, program execution, tools/temperature/camera.
│   ├── system/                  # System service (FastAPI, port 8001, always running) —
│   │                           # machine-config templates, program uploads, macro CRUD,
│   │                           # version/update, LinuxCNC process lifecycle.
│   ├── requirements.txt        # Shared dependency set (one venv for both apps)
│   ├── requirements-machine.txt
│   └── requirements-system.txt
│
├── frontend/                   # Vue 3 + TypeScript SPA — no dynamic module registry;
│   ├── src/
│   │   ├── core/                # Cross-cutting: event-bus, settings, toast, telemetry-bus
│   │   ├── components/          # Reusable panels, organized by domain subfolder
│   │   ├── views/                # Route-level page components
│   │   ├── stores/                # Pinia stores, one (or a few) per domain
│   │   ├── router/                # Vue Router config
│   │   ├── config/                # Centralized G-code constants + helpers
│   │   ├── ui/                    # Shared design-system primitives (BaseButton, Drawer, ...)
│   │   └── generated/api/         # OpenAPI-generated client (gitignored)
│   ├── tests/                    # node --test: static-structural tests
│   └── package.json
│
├── scripts/                   # Dev utilities
├── nc_files/                  # Uploaded G-code lives here
├── machine_config/            # SSOT for machine.cfg profiles + generated machine templates + active
└── start_network.sh           # Repo-root script every generated machine.ini's [APPLICATIONS] references
```

> **Note on the ``HANDOFF.md`` entry.** `.agent/HANDOFF.md` is the
> agent-maintained handoff log created by previous agents. It is
> **optional** — the orchestrator's structural test treats it as
> optional, so the file may be deleted without breaking the build.
> When present, the agent should read it before diving into code
> so it does not redo work that has already been attempted.

## 2. Spokes — read what your task needs

### 2.1 Always read

These two files describe the project at the level an AI agent
needs before editing any code.

| Spoke | What it tells you |
|-------|-------------------|
| [.agent/context/VISION.md](.agent/context/VISION.md) | Why the project exists, what it optimizes for, what it is not. Use this to push back on requests that violate the philosophy. |
| [.agent/context/ARCHITECTURE.md](.agent/context/ARCHITECTURE.md) | The 3-process backend split (`common` / `machine` / `system`), which module id lives in which app, the frontend layout, the event bus, the state facade, the safety watchdog. Use this to find the right file to edit. |
| [.agent/context/BACKEND_LAYERS.md](.agent/context/BACKEND_LAYERS.md) | Canonical Router → Service → DTO → Mapper → Storage pattern with a worked example and the module cheat-sheet. Read before touching any backend module. |
| [.agent/context/MOCK_ARCHITECTURE.md](.agent/context/MOCK_ARCHITECTURE.md) | Mock HAL + NML layer under `backend/common/hardware/mock/`. Read before adding a new mock component, when the real-vs-mock seam is unclear, or when debugging a pin write that "should" propagate. |
| [.agent/AGENT.md](.agent/AGENT.md) | The typing discipline (no bare `dict` in Python, no `any` in TypeScript) applies to every edit, not just the file you're told to read. |

### 2.2 Read when relevant

| Spoke | When to read it |
|-------|-----------------|
| [.agent/context/LESSONS_LEARNED.md](.agent/context/LESSONS_LEARNED.md) | Before you do anything that has burned us before: Pinia store ids, eager imports, venv cache, the jog watchdog, hardcoded G-code, monolithic `App.vue`. The tripwires are the most valuable content. |
| [.agent/HANDOFF.md](.agent/HANDOFF.md) | When you want to know what previous agents have already tried, completed, or abandoned — **and** for the current technical-debt list (§ 2). Optional — if the file is missing, this entry silently skips. |
| [.agent/STATE.md](.agent/STATE.md) | Operational details for specific domains (base-thread/servo-thread split, event bus contract, camera/macros gotchas) that are easy to re-break. |
| [.agent/contracts/backend-router.md](.agent/contracts/backend-router.md) | When you are creating or modifying a backend per-domain router in either app. |
| [.agent/contracts/settings-module.md](.agent/contracts/settings-module.md) | When you are touching the four canonical settings endpoints. |
| [.agent/TEST.md](.agent/TEST.md) | When you need to know what the orchestrator will run to verify your edits. Do **not** run it yourself. |
| [.agent/HANDOFF_TEMPLATE.md](.agent/HANDOFF_TEMPLATE.md) | When the orchestrator asks for a PR description. |
| [README.md](README.md) | When the task is about the run/build/contribute experience for humans. |

## 3. How to navigate

1. **Read the one-paragraph summary at the top of
   [.agent/context/VISION.md](.agent/context/VISION.md)** to
   confirm the task is in scope.
2. **Skim the relevant section of
   [.agent/context/ARCHITECTURE.md](.agent/context/ARCHITECTURE.md)**
   to find which app and which file(s) the task touches.
3. **If the task touches the backend**, read
   [.agent/context/BACKEND_LAYERS.md](.agent/context/BACKEND_LAYERS.md)
   to learn the canonical Router → Service → DTO → Mapper → Storage
   pattern before editing anything.
4. **Check
   [.agent/context/LESSONS_LEARNED.md](.agent/context/LESSONS_LEARNED.md)**
   for any past mistake that matches the proposed approach.
5. **If the task is a module change**, read
   [.agent/contracts/backend-router.md](.agent/contracts/backend-router.md).
6. **Write the minimum code change**, following the typing
   discipline in [.agent/AGENT.md](.agent/AGENT.md), then stop and
   reply with one paragraph. The orchestrator runs
   [.agent/TEST.md](.agent/TEST.md) after your edit.

## 4. Anti-patterns (load-bearing reminders)

- **Do not commit, push, run tests, or open PRs.** The
  orchestrator owns the workflow.
- **Do not browse the repo.** Read the spokes; they are the
  curated context.
- **Do not write code for a request that violates
  [.agent/context/VISION.md](.agent/context/VISION.md).**
  Push back in the summary paragraph instead.
- **Do not invent a fix.** If you are stuck after 2-3 attempts,
  return the honest no-op (see
  [.agent/AGENT.md](.agent/AGENT.md)).
- **Do not add a bare `dict` (Python) or `any` (TypeScript).** See
  the typing discipline in [.agent/AGENT.md](.agent/AGENT.md).

---

**If you only have time to read three files, read these:**

1. [.agent/context/VISION.md](.agent/context/VISION.md) — the why.
2. [.agent/context/ARCHITECTURE.md](.agent/context/ARCHITECTURE.md) — the where.
3. [.agent/context/LESSONS_LEARNED.md](.agent/context/LESSONS_LEARNED.md) — the don't.

**If the task is backend code, also read:**

4. [.agent/context/BACKEND_LAYERS.md](.agent/context/BACKEND_LAYERS.md) — the layered pattern (Router / Service / DTO / Mapper / Storage).
