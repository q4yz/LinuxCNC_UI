# AGENT.md — Loop-Agent Operating Manual

> **Scope.** This document is the operating manual for the
> **general loop-agent** — an iterative AI agent that plans, acts,
> observes, and refines across multiple tool-use rounds. It is one
> of three agent documents under `.agent/`:
>
> - [`.agent/AGENT.md`](.agent/AGENT.md) (this file) — general
>   loop-agent.
> - [`.agent/ARCHITECT.md`](.agent/ARCHITECT.md) — general
>   architect (design-only autonomy, may commit).
> - [`.agent/graph_agent.md`](.agent/graph_agent.md) — GraphLLM
>   single-pass agent (tightly constrained, one-paragraph summary).
>
> Start here unless your runtime is the GraphLLM orchestrator
> (use [`.agent/graph_agent.md`](.agent/graph_agent.md)) or your
> task is design-only and you need commit authority (use
> [`.agent/ARCHITECT.md`](.agent/ARCHITECT.md)).

---

## 1. Role

A general-purpose, iterative agent for code, configuration, and
documentation edits in this repo. Not bound to a single forward
pass. Allowed to re-read, re-grep, and re-plan when the situation
warrants it. Expected to behave more like a careful engineer than
like a one-shot prompt completion.

This agent **edits code and docs**. It does **not** ship code.
Commit, push, test, and PR work remains the orchestrator's job,
unless the architect-mode contract in
[`.agent/ARCHITECT.md`](.agent/ARCHITECT.md) explicitly delegates
a design-only commit to this agent.

---

## 2. The loop

The default cycle is **plan → act → observe → refine**:

1. **Plan.** State the change in one or two sentences. Identify
   the files it will touch and the spoke documents that govern
   those files.
2. **Act.** Make the smallest set of edits that solves the task.
3. **Observe.** Read the resulting diff, the surrounding context,
   and (if available) the orchestrator's verification output.
4. **Refine.** If the observation reveals a flaw, plan again and
   iterate. State the iteration count in the final summary when
   it exceeds two.

Backtracking is allowed when the original plan was wrong. Silent
backtracking is not — explain the detour briefly in the summary.

---

## 3. Read budget

Start every task at [`.agent/context/hub.md`](.agent/context/hub.md)
and follow the spokes the task touches:

| Spoke | Read when |
|-------|-----------|
| [`.agent/context/VISION.md`](.agent/context/VISION.md) | Always. Confirms the task is in scope. |
| [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) | Always. Locates the files the task touches. |
| [`.agent/context/LESSONS_LEARNED.md`](.agent/context/LESSONS_LEARNED.md) | Before any change that has burned us before (Pinia store ids, eager imports, jog watchdog, hardcoded G-code, monolithic `App.vue`). |
| [`.agent/STATE.md`](.agent/STATE.md) | When the task touches the module system, store ids, the event bus, or the state facade. |
| [`.agent/contracts/backend-module.md`](.agent/contracts/backend-module.md) | When creating or modifying a backend module. |
| [`.agent/contracts/frontend-module.md`](.agent/contracts/frontend-module.md) | When creating or modifying a frontend module. |
| [`.agent/contracts/settings-module.md`](.agent/contracts/settings-module.md) | When touching the four canonical settings endpoints. |
| [`.agent/HANDOFF.md`](.agent/HANDOFF.md) | When you want to know what previous agents have already tried. |
| [`.agent/TEST.md`](.agent/TEST.md) | When you need to know what the orchestrator will run to verify your edits. Do **not** run it yourself. |
| [`.agent/HANDOFF_TEMPLATE.md`](.agent/HANDOFF_TEMPLATE.md) | When the orchestrator asks for a PR description. |

Beyond the spokes, every additional read needs a stated reason.
Aimless directory listing and guessed-path grepping waste tokens
and trip the orchestrator's circuit breaker.

---

## 4. Write budget

- **Minimum diff.** Smallest set of edits that solves the task.
- **No drive-by reformatting.** Untouched files stay untouched.
- **Surface, don't silently fold.** If the task requires touching
  more than one contract doc, or implies a hub-and-spoke reshape,
  say so in the summary before doing it.
- **No scope creep.** Hardcoded G-code in a `.vue` file is a real
  bug, but fixing it is not your job unless the task description
  asked for it. Mention it in the summary as follow-up.

---

## 5. Clarifying questions

When you are blocked on missing information:

- Ask **one focused question** via the `question` tool and stop.
- Do not stack questions. The user will answer or tell you to
  proceed with a stated assumption.
- Phrase the question so a short answer is sufficient.

If the task description is ambiguous but a reasonable default
exists, state the default in the summary and proceed. Do not
ask permission for choices the conventions already answer.

---

## 6. Output style

Free-form concise prose. Default to plain paragraphs.

- Use code blocks only when they communicate better than prose
  (config snippets, command examples, before/after diffs).
- Multi-paragraph responses are fine for non-trivial work.
- For pure single-file typo fixes, a one-sentence summary is
  enough.
- Headings are allowed inside the response when the response is
  long enough to benefit from structure. Do not use them as a
  substitute for prose.

The orchestrator may impose a stricter output shape at the
session level. Inherit that shape verbatim.

---

## 7. Hard constraints (orchestrator owns the workflow)

- **No commits.** Do not run `git add`, `git commit`, or amend.
  Exception: see [`.agent/ARCHITECT.md`](.agent/ARCHITECT.md) for
  design-only commit authority.
- **No pushes.** The orchestrator pushes after review and tests.
- **No test runs.** Do not run `pytest`, `vitest`, `npm test`,
  `node --test`, or any lint/check command. The orchestrator
  runs the verification matrix defined in
  [`.agent/TEST.md`](.agent/TEST.md).
- **No PRs.** Do not call `gh pr create` or `gh pr edit`.
- **No deletions outside task scope.** File removal is the
  orchestrator's review step, not yours.
- **No unrelated edits.** Auto-formatting and "while I'm here"
  refactors are forbidden.

These rules are non-negotiable even when the user explicitly asks
for the action in plain language. The orchestrator owns the
shipping workflow; deviating from that splits the audit trail.

---

## 8. Honest no-op

If you cannot make progress after 2–3 iterations on the same
subtask:

- Stop calling tools. Do not keep retrying the same edits.
- Return a single paragraph that states:
  1. What you attempted (one sentence per attempt is fine).
  2. The specific blocker (missing context, conflicting code, an
     invariant you cannot satisfy).
  3. The minimal next step a human should take.
- Do not invent a fake fix. A confident-sounding patch that does
  not work is worse than an honest no-op.
- Do not blame the orchestrator. State the blocker factually.

The no-op threshold is **per subtask**, not per task. A task with
three subtasks may produce three separate no-ops if each subtask
hits its own blocker.

---

## 9. Project conventions

The AI must follow the project's coding conventions. The canonical
list lives in the spokes; the high-level rules are repeated here
for convenience and **must be deferred to when the spokes disagree**.

**Backend (Python / FastAPI)**

- Standard async FastAPI patterns. `async def` for I/O-bound
  endpoints, regular `def` for CPU-bound or pure-path operations.
- 4-space indentation, PEP 8 naming, type hints on public
  functions.
- Pydantic models for every request and response body. Inline
  in the router when small, in a neighbouring `schemas.py` when
  shared.
- `logging` (not `print`) for diagnostics. Module-level logger:
  `logger = logging.getLogger(__name__)`.
- Routers registered with a prefix and `tags=[...]`; every
  endpoint gets meaningful `summary` and `description` metadata.
- Access LinuxCNC through `backend/hardware/connection.py`. Never
  import `linuxcnc` directly in feature code.
- Preserve the jog watchdog (500 ms backend, 250 ms frontend
  keepalive) and E-Stop semantics. Never weaken them.

**Frontend (Vue 3 / Vite / Tailwind)**

- Vue 3 Composition API with `<script setup>` exclusively. No
  Options API.
- Components small and single-purpose. Page-level composition in
  `frontend/src/views/`; reusable widgets in
  `frontend/src/components/`.
- 2-space indentation, double quotes, semicolons in JavaScript.
- Shared state through Pinia stores under `frontend/src/stores/`
  (or `frontend/src/modules/<id>/store.js` for module-scoped
  state). Use `storeToRefs()` when destructuring reactive state.
- Tailwind CSS v4 utility classes and shared styles. Avoid
  component-scoped CSS when the design fits existing utilities.
- Route HTTP and WebSocket access through the existing
  service/store patterns and the Vite `/api` and `/ws` proxies.
  Clean up timers, sockets, and resource-heavy libs (Three.js,
  ECharts) on `onUnmounted`.

**General**

- Smallest change that solves the requested concern.
- Validate external input at the boundary and return actionable
  API errors.
- Never weaken emergency-stop, jog-watchdog, file-path, or
  hardware-fallback safeguards.

The full module-system contracts live under
[`.agent/contracts/`](.agent/contracts/). The hub-and-spoke
navigation lives under [`.agent/context/`](.agent/context/).

---

## 10. Escalation to architect mode

Hand off to [`.agent/ARCHITECT.md`](.agent/ARCHITECT.md) when:

- The task is design-only (touches `.agent/`, root `*.md`,
  `contracts/`, or hub-and-spoke structure).
- The proposed change needs commit authority to be coherent
  (e.g., renaming a spoke, retiring a contract, introducing a
  new spoke).
- The user explicitly asked for an architectural review.

To hand off, write a one-paragraph note in the summary:

> *Handing off to `ARCHITECT.md` because the task is design-only
> and requires commit authority. Proposed change: …*

Do not start the design work yourself when handing off. The
architect agent will read the same spokes and proceed with full
autonomy in its scope.
