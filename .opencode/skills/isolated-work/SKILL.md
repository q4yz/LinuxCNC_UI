---
name: isolated-work
description: Work in a separate git clone of the repository so the user's main working tree stays untouched. Use when the user invokes /delegate, asks to work in a scratch clone, or wants parallel work without colliding with their own edits. Sets up a scratch clone under D:\dev\linuxcnc-isolated, branches scratch/<short-desc> off ai_dev, does the work in isolation, commits, pushes, and opens a draft PR against ai_dev.
license: MIT
compatibility: opencode
metadata:
  audience: contributors
  workflow: scratch-clone
---

# How to use

This skill is loaded automatically when the user runs the `/delegate` slash command, or when the user explicitly asks to work in an isolated scratch clone. Do not load it for casual edits inside the main checkout — that work happens in `C:\Users\pc\IdeaProjects\LinuxCNC_UI` directly.

When loaded, follow the workflow below exactly. Every file read, every edit, every shell command runs inside the scratch clone via the `workdir` parameter. The main checkout is unreachable from this skill's perspective.

# Workflow

## 1. Resolve the scratch root

- Default: `D:\dev\linuxcnc-isolated`
- Override order: `--root <path>` flag > `LINUXCNC_SCRATCH_ROOT` env var > default
- Create the root with `New-Item -ItemType Directory -Force` if missing

## 2. Pick the scratch directory name

Pattern: `<branch-hint>-<YYYYMMDD-HHMM>` where:
- `branch-hint` is the issue number (`issue-50`), or `scratch` for ad-hoc work
- The timestamp uses the user's local time, hyphen-separated

Examples:
- `issue-50-20260811-1430`
- `scratch-20260811-1502`

## 3. Clone the repo

```
git clone <origin-url> <scratch-dir>
```

Get the URL with `git remote get-url origin` from the main checkout. Use a full clone (not `--no-local` and not `--depth 1`) so all branches are reachable.

## 4. Check out the base branch

```
git -C <scratch-dir> fetch origin ai_dev
git -C <scratch-dir> checkout ai_dev
```

Default base is `ai_dev`. Override with `--base <branch>`.

## 5. Create the work branch

```
git -C <scratch-dir> checkout -b scratch/<short-desc>
```

`<short-desc>` is a 2-5 word slug derived from the issue title (lowercase, hyphens, no special chars). Example: `fix-console-deprecation`.

## 6. Switch into the scratch clone

From this point on, **every** `read`, `edit`, `glob`, `grep`, `bash` call uses `workdir=<scratch-dir>`. Treat the main checkout as if it does not exist.

## 7. Do the work

- Read `.agent/AGENT.md` for stack and conventions
- Read `.agent/HANDOFF_TEMPLATE.md` for the PR description shape
- Read `.agent/STATE.md` for current-as-built module state
- Read `.agent/context/LESSONS_LEARNED.md` for past tripwires
- Follow the one-concern-per-change rule from `.agent/AGENT.md`
- Make the smallest change that solves the requested concern

## 8. Verify

If the change touches code, run the relevant subset of `.agent/TEST.md` inside the scratch clone. Do not run the full suite if the change is documentation-only — instead, document that no tests apply.

## 9. Commit

```
git add -A
git commit -m "scratch: <one-line summary>

- <bullet describing the change>
- <bullet describing the test or verification>
- <bullet naming any follow-ups>"
```

Single commit at the end. Do not amend, do not rebase, do not sign.

## 10. Push

```
git push -u origin scratch/<short-desc>
```

If push fails because the branch name already exists on remote, suffix with a counter (`scratch/fix-console-deprecation-2`) and retry once.

## 11. Open a draft PR against ai_dev

Try the GitHub CLI first:

```
gh pr create --draft --base ai_dev --head scratch/<short-desc> --title "scratch: <summary>" --body-file <handoff-body>
```

Where `<handoff-body>` is a temp file seeded from `.agent/HANDOFF_TEMPLATE.md` and filled with the issue context, files modified, and verification results.

If `gh` is not on PATH or the command fails, fall back to the GitHub MCP tool `mcp__github__create_pull_request` with:
- `owner: q4yz`
- `repo: LinuxCNC_UI`
- `head: scratch/<short-desc>`
- `base: ai_dev`
- `draft: true`
- `title`, `body` from the synthesized handoff

## 12. Surface the final report

Print a single block with:
- Scratch directory path
- Branch name
- Commit SHA (`git -C <scratch-dir> rev-parse HEAD`)
- PR URL
- List of files modified (`git -C <scratch-dir> show --stat HEAD`)
- Whether verification was run and its result

Then offer three next-step options the user can pick from:
1. **Review & merge** — open the PR URL, click "Ready for review", then merge after approval
2. **Cherry-pick locally** — `git -C <main-checkout> cherry-pick <sha>` to bring the commit onto `ai_dev` directly without a PR
3. **Discard** — `rm -rf <scratch-dir>` and `git push origin --delete scratch/<short-desc>`

# Hard rules

- Never run `git`, `read`, `edit`, or `bash` against `C:\Users\pc\IdeaProjects\LinuxCNC_UI` while this skill is loaded. The `workdir` parameter is mandatory.
- Never push to `main` or `ai_dev` directly. The branch is `scratch/<short-desc>`.
- Never open a non-draft PR. The user wants to review before merge.
- Never amend or force-push. If the commit is wrong, add a follow-up commit.
- Never run `.agent/TEST.md` from the main checkout — only from the scratch clone.
- If `gh` and the GitHub MCP both fail, surface the error verbatim and stop. Do not retry, do not fall back to a manual `git push` without telling the user.
