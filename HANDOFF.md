### Resolution Summary
Added the standard `.agent/` configuration directory with repository-specific architecture, style, dependency installation, verification, and PR handoff guidance for the FastAPI/Vue monorepo.

### Files Modified
- `.agent/AGENT.md`: Documents backend, frontend, formatting, safety, and scope conventions tailored to the repository.
- `.agent/TEST.md`: Provides sequential dependency installation and build verification commands for the Python and Node.js stacks.
- `.agent/HANDOFF_TEMPLATE.md`: Adds the exact handoff template requested by the issue.
- `HANDOFF.md`: Records the implementation and verification details for this PR.

### Architectural Decisions
- Reused the existing `AI_INSTRUCTIONS.md` guidance and current manifests/source conventions as the basis for the agent rules, while documenting the installed Tailwind CSS v4 stack.
- Used Python byte-compilation and a production Vite build as the required checks because the repository does not currently define a formal automated test or lint suite.

### Testing Verification
- [x] Ran local test suite / build checks
- [x] Installed backend, root, and frontend dependencies using the commands in `.agent/TEST.md`.
- [x] Ran `python -m compileall -q backend` successfully.
- [x] Ran `npm --prefix frontend run build` successfully.
