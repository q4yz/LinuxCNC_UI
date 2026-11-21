# Assistant tools (MCP)

LinuxCNC UI serves an [MCP](https://modelcontextprotocol.io) server at
`/mcp` (system service, port 8001; through nginx on the UI's own address).
An MCP client — an AI assistant — gets the machine as tools.

## Connecting

Streamable HTTP, no login:

```
http://<machine address>/mcp
```

For example, with Claude Code: `claude mcp add --transport http linuxcnc http://<machine address>/mcp`.

## What the assistant can do

The tools are generated from the two backends' OpenAPI schemas — there is no
separate tool list to maintain. An operation becomes a tool when its
permission's level for the **agent** role is `allow` (see
[Permissions](permissions.md)): reading everything (state, temperatures,
I/O, programs, profiles, calibrations, logs) and engaging the E-stop.

Operations the agent may only use after the operator confirms (`confirm`:
homing, MDI, running programs, heaters, outputs, calibrations, file changes)
are not offered yet; that comes with the confirmation flow. Operations
denied to the agent (configuration, HAL editing, updates, settings, users)
are never offered.

Machine tools (`machine_*`) are only there while LinuxCNC runs; system tools
(`system_*`) always are.

## How it is limited

Every tool call goes back through the REST API carrying the agent's token
(`backend/data/agent.token`, created on first start), so the backend gives it
the **agent** role and its permission check refuses anything else (403) — even
a call to an operation the MCP server would not offer. Connecting to `/mcp`
therefore never gives more than the agent's rights.

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
