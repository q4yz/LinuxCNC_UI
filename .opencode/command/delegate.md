---
description: Delegate a task to an isolated scratch clone. Opens a GitHub issue on q4yz/LinuxCNC_UI, clones the repo to D:\dev\linuxcnc-isolated, branches scratch/<short-desc> off ai_dev, does the work there, commits, pushes, and opens a draft PR against ai_dev. Refuses if the main working tree is dirty. Usage: /delegate [title hint] [--no-issue] [--base <branch>] [--root <path>] [--dry-run]
agent: build
---

# How to use

`/delegate` is the entry point for handing a task to an isolated worker. The conversation so far becomes the issue body; a fresh `git clone` becomes the work environment; a draft PR against `ai_dev` becomes the deliverable. Your main checkout (`C:\Users\pc\IdeaProjects\LinuxCNC_UI`) is never touched.

Typical flow:

```
/delegate "fix console deprecation warning"
```

This:
1. Refuses if the main checkout has uncommitted changes
2. Opens a GitHub issue summarizing the conversation
3. Clones the repo to `D:\dev\linuxcnc-isolated\issue-<N>-<timestamp>\`
4. Branches `scratch/<short-desc>` off `ai_dev`
5. Loads the `isolated-work` skill — the rest of the conversation runs in the scratch clone
6. Commits, pushes, and opens a **draft** PR against `ai_dev`
7. Prints the scratch path, commit SHA, and PR URL

Flags:

- `--no-issue` — skip the GitHub issue step. Use for throwaway exploration.
- `--base <branch>` — branch off `main` (or any other branch) instead of `ai_dev`. Default: `ai_dev`.
- `--root <path>` — override the scratch root. Default: `D:\dev\linuxcnc-isolated`. Override via env: `LINUXCNC_SCRATCH_ROOT`.
- `--dry-run` — synthesize the issue draft and clone the repo, but stop before the work begins. Lets you sanity-check the path and base branch before any commits land.

When the delegated work finishes, you have three options:

1. **Review & merge** — open the PR URL in GitHub, click "Ready for review", merge after approval
2. **Cherry-pick locally** — `git -C C:\Users\pc\IdeaProjects\LinuxCNC_UI cherry-pick <sha>` to bring the single commit onto `ai_dev` without going through the PR
3. **Discard** — `rm -rf <scratch-dir>` and `git push origin --delete scratch/<short-desc>`

---

# Workflow

You are the wrapper for the `isolated-work` skill. Execute these steps in order. Do not skip the clean-tree gate; do not auto-merge; do not touch the main checkout after the gate passes.

## 1. Parse arguments

`$ARGUMENTS` may contain:
- Free-text title hint (everything that is not a flag)
- Zero or more flags: `--no-issue`, `--base <branch>`, `--root <path>`, `--dry-run`

Trim the title hint. If empty, derive one from the conversation summary — pick the most recent unresolved request or question and condense it to under 72 chars in imperative mood.

## 2. Resolve the target repository

```
git remote get-url origin
```

Translate to `owner/repo`:
- `https://github.com/q4yz/LinuxCNC_UI.git` → `q4yz/LinuxCNC_UI`
- `git@github.com:q4yz/LinuxCNC_UI.git` → `q4yz/LinuxCNC_UI`

If the remote is not on `github.com`, halt with: `Error: origin is not a GitHub repository. Halting.`

Print the resolved `owner/repo` once so it appears next to the issue URL in the output.

## 3. Clean-tree gate

```
git -C C:\Users\pc\IdeaProjects\LinuxCNC_UI status --porcelain
```

If the output is non-empty, halt with:

```
Error: main checkout is dirty. /delegate refuses to run while uncommitted changes exist.

Dirty files:
<list>

Fix one of:
  - git -C C:\Users\pc\IdeaProjects\LinuxCNC_UI add -A && git commit -m "..."
  - git -C C:\Users\pc\IdeaProjects\LinuxCNC_UI stash push -m "..."
  - git -C C:\Users\pc\IdeaProjects\LinuxCNC_UI restore <file>   # to discard
```

Do not proceed. Do not open the issue. The user must resolve the dirty state first.

## 4. Synthesize the issue (unless `--no-issue`)

Read the full conversation history, not just the last message. Produce a structured draft with these sections, in this order:

1. `## Summary` — 2–4 sentences in prose. State the problem or request and the proposed direction.
2. `## Context` — bullets capturing the relevant facts surfaced in the conversation (file paths, error messages, decisions, trade-offs). Quote short snippets verbatim; paraphrase long ones.
3. `## Proposed approach` — if the conversation reached a plan, capture it as a numbered list. If not, write `TBD — discuss in issue`.
4. `## Acceptance criteria` — bullets, each independently checkable.
5. `## Notes` — anything else relevant (follow-ups, links, decisions deferred).

Title: use `$ARGUMENTS` (excluding flags) verbatim if non-empty, else derive from the most recent unresolved request.

Print the synthesized title and body to the conversation in a fenced markdown block prefixed with the resolved repo:

```
Issue for q4yz/LinuxCNC_UI:

# <title>

<body>
```

If `--no-issue` was passed, skip Steps 5 and the issue-related parts of Step 6. Continue from Step 6 with `issue_number=null`.

If `--dry-run` was passed, append `(dry run — no issue opened, no scratch clone created yet)` and stop here.

## 5. Open the issue

Call `mcp__github__create_issue` with:
- `owner: q4yz`
- `repo: LinuxCNC_UI`
- `title: <title>`
- `body: <body>`

Capture the returned issue number and URL.

If the MCP returns an error, print it verbatim and halt. Do not retry.

## 6. Hand off to the skill

Call:

```
skill({ name: "isolated-work" })
```

Pass the following context in the conversation turn so the skill picks it up:

- `issue_number: <N>` (or `null` if `--no-issue`)
- `issue_url: <url>` (or `null`)
- `title_hint: <title>`
- `base: ai_dev` (or the value of `--base`)
- `root: D:\dev\linuxcnc-isolated` (or the value of `--root` / `LINUXCNC_SCRATCH_ROOT`)
- `dry_run: false` (or `true` if `--dry-run` was passed)
- `short_desc: <slug>` — derived from the title: lowercase, alphanumerics + hyphens, 2-5 words

The skill takes over from here. The rest of the conversation runs in the scratch clone. Do not return to the main checkout. Do not call `git`, `read`, `edit`, or `bash` against `C:\Users\pc\IdeaProjects\LinuxCNC_UI` — the skill forbids it.

## 7. Print the final report

When the skill returns, print a result block in this shape:

```
Delegation complete.

  Scratch dir: D:\dev\linuxcnc-isolated\<name>
  Branch:      scratch/<short-desc>
  Commit:      <sha>
  PR:          <url>  (draft, base=ai_dev)
  Files:       <count>

Next steps:
  1. Review & merge  — open the PR URL, click "Ready for review", merge after approval
  2. Cherry-pick     — git -C C:\Users\pc\IdeaProjects\LinuxCNC_UI cherry-pick <sha>
  3. Discard         — rm -rf <scratch-dir> && git push origin --delete scratch/<short-desc>
```

If the skill reports an error (push failed, PR creation failed, etc.), surface it verbatim. Do not attempt recovery — the user decides what to do.

# Hard rules

- The clean-tree gate is non-negotiable. Refuse and exit if the main checkout is dirty.
- Never open an issue in a fork. The target is always `q4yz/LinuxCNC_UI` from `origin`.
- Never include secrets in the issue body or PR body. Redact with `REDACTED`.
- Never invent commit references, file paths, or PR numbers in the issue body. Cite only what the conversation actually contains.
- One concern per issue. If the conversation covers multiple unrelated topics, open the issue for the dominant topic and add the rest to `## Notes`.
- Never merge the PR yourself. The user clicks the button in GitHub.
- Never auto-run `.agent/TEST.md` from the main checkout. The skill runs it inside the scratch clone if applicable.
