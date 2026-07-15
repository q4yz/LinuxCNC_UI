# `frontend/generated/` — auto-generated, never committed

Everything under this directory is produced by tooling and must not be edited by hand.
It is matched by `frontend/generated/` in the root `.gitignore`.

## What lives here

| Path                | Tool                              | Command                     |
|---------------------|-----------------------------------|-----------------------------|
| `api/`              | `openapi-typescript-codegen`      | `npm run generate-api`      |
| `.openapi-cache/`   | `scripts/generate-api.mjs`        | (side effect of the above)  |

The `api/` client is regenerated from the running FastAPI backend's `/openapi.json`
schema, so service methods and TypeScript types always match the live backend.

## First-time checkout / CI / fresh container

After cloning or in a CI step that builds the frontend, run:

```bash
npm --prefix frontend install
npm --prefix frontend run generate-api   # produces frontend/generated/api/
npm --prefix frontend run build          # or `npm --prefix frontend run dev`
```

If a build complains about a missing `generated/api/` directory, you forgot the
generation step — never hand-write files here.

## Why it's outside `src/`

Keeping generated artifacts under a top-level `generated/` directory (rather than
inside `src/`) makes the contract obvious:

- Anything under `src/` is hand-written.
- Anything under `generated/` is tool-produced.

It also keeps generated/regenerated diffs out of normal PR review, eliminating
hundreds of lines of whitespace churn that the OpenAPI generator produces on
every backend schema tweak.
