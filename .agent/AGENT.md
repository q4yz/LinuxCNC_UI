# Repository Agent Guide

This guide has two parts. The first half is the **GraphLLM agent operating manual** — the rules any AI agent must follow when working on this repo. The second half is the **project conventions** that govern what the AI may write.

---

## Part 1 — GraphLLM Agent Operating Manual

### Core Constraints

- **No commits.** The orchestrator owns the commit graph. Do not run `git add`, `git commit`, or amend anything.
- **No pushes.** The orchestrator pushes the working branch only after it has been reviewed and tests have passed.
- **No test runs.** Do not execute `pytest`, `vitest`, `npm test`, `node --test`, or any other test/lint/check command. The orchestrator runs them deterministically via `.agent/TEST.md`.
- **No PRs.** Do not call `gh pr create`, `gh pr edit`, or interact with any code-hosting CLI. The orchestrator opens the PR.
- **No file deletions outside the task scope.** Removing files is part of the orchestrator's review, not yours.
- **Mutate only the files the task describes.** Side edits to unrelated files (auto-formatting, "while I'm here" refactors) are forbidden.

### Workflow

1. Read the **minimum** set of files needed to understand the request — usually the file(s) named in the task plus one or two callers. Do not browse the repo.
2. Write the **minimum** code that solves the task. Prefer the smallest possible diff.
3. Reply with exactly **one paragraph** of natural language summary. The paragraph must contain **no tool calls**, no code blocks, no markdown headings. It states what changed, why, and any follow-up the human should be aware of.
4. Stop. The orchestrator handles commit, test, push, and PR.

### Anti-patterns (circuit breakers)

- **Do not browse endlessly.** Repeated `list_dir`, `grep_search`, or `read_file` calls on guessed paths will trip the orchestrator's circuit breaker.
- **Do not read directories aimlessly.** Only read a file when you know specifically why you need its contents.
- **Do not re-explore after every change.** A single forward pass is expected; backtracking means the plan was wrong.
- **Do not spawn subagents for simple lookups.** Reserve subagents for tasks that genuinely need them.
- **Do not hedge.** If you need more information, ask one focused question via the question tool and stop.

### Refinement Mode (PR feedback)

When the orchestrator hands you PR review comments:

- **Address every comment directly.** Every reviewer bullet needs a corresponding code change or a written justification in your summary paragraph.
- **Do not silently ignore comments.** If you disagree with a reviewer, say so explicitly in the summary and explain why the current code is correct.
- **Do not over-rewrite.** Tweak only what the review asked for. Do not reformat untouched files.
- **One round, one paragraph.** Return the updated diff plus the single-paragraph summary listing each addressed comment.

### Giving Up — The Honest No-Op

If you cannot make progress after a small number of attempts (typically 2–3):

- **Stop calling tools.** Do not keep retrying the same edits.
- **Return a single-paragraph honest no-op** that states:
  1. What you attempted.
  2. The specific blocker (missing context, conflicting code, an invariant you cannot satisfy, etc.).
  3. The minimal next step a human should take (e.g., "clarify which file owns the config write path").
- **Do not invent a fake fix.** A confident-sounding patch that does not actually work is worse than an honest no-op.
- **Do not blame the orchestrator.** State the blockers factually.

### Project Conventions (enforced by the AI)

When the AI writes code in this repo, it must follow these conventions.

**Backend (Python / FastAPI)**

- Follow standard async FastAPI patterns. Use `async def` for I/O-bound endpoints, regular `def` for CPU-bound or pure-path operations.
- Use 4-space indentation, PEP 8 naming, and type hints on public functions.
- Use Pydantic models for every request and response body. Define them inline in the router when small, or in a `schemas.py` neighbour when shared.
- Use `logging` (not `print`) for diagnostics. Use the module-level logger pattern: `logger = logging.getLogger(__name__)`.
- Register routers with a prefix and `tags=[...]`; give every endpoint meaningful `summary` and `description` metadata.
- Access LinuxCNC through `backend/hardware/connection.py` so the mock stays compatible. Do not import `linuxcnc` directly in feature code.
- Preserve the jog watchdog (500 ms backend) and frontend keepalive (~250 ms) safety semantics. Never weaken these.

**Frontend (Vue 3 / Vite / Tailwind)**

- Use the Vue 3 Composition API with `<script setup>` exclusively. No Options API.
- Keep components small and single-purpose. Page-level composition lives in `frontend/src/views/`; reusable widgets live in `frontend/src/components/`.
- Use 2-space indentation, double quotes, and semicolons in JavaScript to match the existing source.
- Access shared state through Pinia stores under `frontend/src/stores/` (or `frontend/src/modules/<id>/store.js` for module-scoped state). Use `storeToRefs()` when destructuring reactive state.
- Style with Tailwind CSS v4 utility classes and existing shared styles. Avoid component-scoped CSS when the design can be expressed with existing utilities.
- Route HTTP and WebSocket access through the existing service/store patterns and the Vite `/api` and `/ws` proxies. Always clean up timers, sockets, and resource-heavy libs (Three.js, ECharts) on `onUnmounted`.

**General**

- Make the smallest change that solves the requested concern. Do not mix in unrelated refactors or touch generated build output.
- Validate external input at the boundary and return actionable API errors.
- Never weaken emergency-stop, jog-watchdog, file-path, or hardware-fallback safeguards.
- Refer to `.agent/contracts/` for module-system contracts and to `MODULE_SYSTEM_ROADMAP.md` for the broader migration plan.

### Context source of truth

The AI agent's curated context is the **hub-and-spoke** document set
under `.agent/context/`. Start every task at
[`.agent/context/hub.md`](.agent/context/hub.md) and follow the spokes
(`VISION.md`, `ARCHITECTURE.md`, `LESSONS_LEARNED.md`) to the
documents you need. The legacy `AI_INSTRUCTIONS.md` and
`archived_notes.md` files were deleted; do not reference them.