# Assistant tools (MCP)

LinuxCNC UI serves an [MCP](https://modelcontextprotocol.io) server at
`/mcp` (system service, port 8001; through nginx on the UI's own address).
An MCP client — an AI assistant — gets the machine as tools.

## The in-app assistant

The assistant panel on the right of the UI answers with Claude once an
Anthropic API key is set in **Settings → Assistant** (model and effort there
too; Claude Opus 5.5 at medium effort by default). The key is kept on the
machine in `backend/data/assistant.json` (owner-only, never shown again, never
sent to a browser, not in the UI settings the agent could read);
`ANTHROPIC_API_KEY` in the system service's environment works too. The
machine needs internet access to reach the Anthropic API, and usage is billed
to the key's account.

The in-app assistant uses exactly the tools, role and approvals described
below — it runs the same catalog as `/mcp`, inside the system service. Its
actions show up as the same approval cards. Conversations live in the system
service's memory (a restart forgets them); refusals fall back to another model
server-side.

## Connecting

**Settings → Assistant** shows this machine's MCP address, whether the server
is offering tools right now, and ready-to-copy setup for Claude Code, Claude
Desktop and other clients. The address is Streamable HTTP, no login:

```
http://<machine address>/mcp
```

- Claude Code: `claude mcp add --transport http linuxcnc http://<machine address>/mcp`
- Claude Desktop (Settings → Developer → Edit Config; needs Node.js):
  `{"mcpServers": {"linuxcnc": {"command": "npx", "args": ["-y", "mcp-remote", "http://<machine address>/mcp", "--allow-http"]}}}`

The switch **Let the assistant ask to run actions** (same tab,
`assistant.allow_actions`, on by default) turns the action tools off: the
assistant then only reads and can engage the E-stop.

## What the assistant can do

The tools are generated from the two backends' OpenAPI schemas — there is no
separate tool list to maintain. An operation becomes a tool when its
permission's level for the **agent** role is `allow` (see
[Permissions](permissions.md)): reading everything (state, temperatures,
I/O, programs, profiles, calibrations, logs) and engaging the E-stop.

Operations the agent may only use after the operator confirms (`confirm`:
homing, MDI, running programs, heaters, outputs, calibrations, file changes)
are offered too, but each call **waits for you**: the assistant panel unfolds
with a card showing what the assistant wants to do and the exact request
(method, path, arguments). **Approve** runs it once, as shown; **Deny** (with an
optional reason) tells the assistant no. Unanswered requests expire after two
minutes. Every decision is written to the console. Operations denied to the
agent (configuration, HAL editing, updates, settings, users) are never offered.

Machine tools (`machine_*`) are only there while LinuxCNC runs; system tools
(`system_*`) always are.

## How it is limited

Every tool call goes back through the REST API carrying the agent's token
(`backend/data/agent.token`, created on first start), so the backend gives it
the **agent** role and its permission check refuses anything else (403) — even
a call to an operation the MCP server would not offer. An approved action
carries a signed, single-use approval of exactly that request (method, path,
query and body); the backend refuses it for any other request, a second time,
or after 30 s. Approving needs the `agent.approve` permission, which the agent
role never has. Connecting to `/mcp` therefore never gives more than the
agent's rights.

## Shaping the tools

All in the route definitions (they end up in the OpenAPI schema):

- the route's permission (`backend/common/core/permissions.py`) decides
  whether the agent sees it;
- `summary` and `description` are the tool's description; parameters and the
  request body are its arguments;
- `openapi_extra={"x-mcp": False}` hides a route that is not useful as a tool
  (the OctoPrint emulation for slicers, schema-only routes);
- `deprecated=True` routes and routes that neither take nor return JSON / text
  (uploads, video streams) are left out — declare a route's real media type.
