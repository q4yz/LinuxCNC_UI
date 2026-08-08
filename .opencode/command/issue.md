---
description: Create a GitHub issue from the current conversation in the origin repository. Usage: /issue [optional title hint] [--dry-run]
agent: build
---

You create a GitHub issue in the project's origin repository from the conversation that preceded this command. The user invoking the command is the implicit confirmation — you do not block on a prompt, because in many agent contexts (server-side runners, automated workflows, the `question` tool denied) the user has no way to reply. The draft is shown inline so the user can review the content before it's submitted, and they can close the issue on GitHub if they don't want to keep it.

## Inputs

- `$ARGUMENTS` — optional short hint for the issue title. If empty, derive the title from the conversation summary.
- `--dry-run` — if present, run Steps 1–3 (resolve repo, synthesize draft, print draft) but do **not** call the GitHub MCP. The command exits with the draft visible and a note that no issue was opened.
- The conversation history is the primary source. Read the full thread, not just the last message.

## Workflow

Execute these steps in order. Do not skip steps.

### Step 1 — Resolve the target repository

The issue must land in the project's origin repo, not whatever fork or local clone happens to be on disk.

1. Run `git remote get-url origin` and parse the result.
2. Translate the URL into `owner/repo` form:
   - `https://github.com/q4yz/LinuxCNC_UI.git` → `q4yz/LinuxCNC_UI`
   - `git@github.com:q4yz/LinuxCNC_UI.git` → `q4yz/LinuxCNC_UI`
3. If the remote is not on `github.com`, halt with a one-line error: `Error: origin is not a GitHub repository. Halting.`
4. Print the resolved `owner/repo` once so it appears in the response next to the issue URL.

### Step 2 — Synthesize the issue

Read the full conversation and produce a structured issue draft:

- **Title** — one line, imperative mood, under 72 chars. If `$ARGUMENTS` (excluding `--dry-run`) is non-empty, use it as the title verbatim (trimmed); otherwise derive from the most recent unresolved question or requested action.
- **Body** — markdown with these sections in this order:
  1. `## Summary` — 2–4 sentences in prose. State the problem or request and the proposed direction.
  2. `## Context` — bullets capturing the relevant facts surfaced in the conversation (file paths, error messages, decisions, trade-offs). Quote short snippets verbatim; paraphrase long ones.
  3. `## Proposed approach` — if the conversation reached a plan, capture it as a numbered list. If not, write `TBD — discuss in issue`.
  4. `## Acceptance criteria` — bullets, each independently checkable. Empty section header is fine if the conversation didn't surface any.
  5. `## Notes` — anything else relevant (follow-ups, links, decisions deferred).

Do not invent facts that the conversation did not establish. If a section has no content, write `_(none)_` rather than omitting the header.

### Step 3 — Show the draft

Print the synthesized title and body to the conversation in a fenced markdown block, prefixed with a one-line header that names the target repo. This is the user's review surface — they see exactly what will be submitted. If `--dry-run` was passed, append `(dry run — no issue opened)` and stop here.

### Step 4 — Open the issue

Call the GitHub MCP to create the issue. The exact tool name depends on the MCP server in use; the canonical tool is `create_issue` (the GitHub MCP returns tools with the `mcp__github__` prefix in their identifiers, but the user-facing name is `create_issue`). Pass:

- `owner` — from Step 1
- `repo` — from Step 1
- `title` — from Step 2
- `body` — from Step 2

If the tool returns a URL or issue number, capture it. If the MCP returns an error, print the error verbatim and halt — do not retry.

### Step 5 — Print the result

Print the result block in this exact shape:

```
Issue opened: <url>
```

If `--dry-run` was used, replace with:

```
Dry run — no issue opened. Draft above is what would be submitted.
```

Follow the result with a short next-steps menu:

```
Next steps you can take:
- /issue-branch <number> to create a `issue-N-fix` branch and check it out.
- /issue-handoff <number> to seed `HANDOFF.md` with this issue's context.

(These commands exist if you have defined them; ignore if not.)
```

Do not auto-create the branch or HANDOFF.md — those are separate user actions.

## Constraints

- **Never open an issue in a fork.** Always use the resolved `origin` repo. If the user wants the issue elsewhere, they can edit the URL in GitHub after the issue is opened.
- **Never include secrets in the body.** If the conversation contained tokens, API keys, or passwords, redact them with `REDACTED` before opening.
- **Never invent commit references, file paths, or PR numbers.** Cite only what the conversation actually contains.
- **One concern per issue.** If the conversation covers multiple unrelated topics, open the issue for the dominant topic and add the rest to the `## Notes` section.

## Failure modes

- No git remote → print `Error: no git remote 'origin' configured. Halting.`
- Non-GitHub origin → print `Error: origin is not on github.com. Halting.`
- MCP tool missing → print `Error: GitHub MCP tool 'create_issue' not available. Check ~/.config/opencode/opencode.jsonc mcp.github is enabled.` and halt.
- MCP call fails for any reason → print the error verbatim and halt. Do not retry, do not fall back to a different tool.
