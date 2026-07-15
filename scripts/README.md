# `scripts/`

Helper scripts for the LinuxCNC_UI repo.

## `minimax_local.py` — local MiniMax proxy

A small FastAPI server that gives this project (and your editor scripts) a
**stable local URL** for talking to the MiniMax M3 API:

```
http://127.0.0.1:8001/v1/chat/completions
```

### Why

The rest of this repo's toolchain (and most generic AI tooling) speak
OpenAI-style HTTP. This proxy:

- keeps the API key in one place (`.env`),
- exposes an OpenAI-compatible local URL,
- streams SSE when the caller asks for `stream: true`,
- uses **no extra dependencies** beyond what's already in
  [backend/requirements.txt](../backend/requirements.txt)
  (`fastapi`, `uvicorn`, `pydantic`, `python-dotenv`).

### Setup

```bash
# from the repo root
cp scripts/.env.example .env
# edit .env and paste your MINIMAX_API_KEY
```

### Run

```bash
# pick whichever python already has the backend venv (it has fastapi+uvicorn)
python ./scripts/minimax_local.py
# or activate the backend venv first:
#   source backend/venv/bin/activate     (Linux/macOS)
#   .\backend\venv\Scripts\activate     (Windows PowerShell)
```

You should see:

```
MiniMax local proxy listening on http://127.0.0.1:8001
Forwarding to upstream: https://api.minimaxi.chat/v1
```

### Quick test

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8001/v1/models \
  -H "Authorization: Bearer $MINIMAX_API_KEY"

curl http://127.0.0.1:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniMax-M3",
    "messages": [{"role":"user","content":"ping"}]
  }'
```

### Environment variables

| Variable           | Default                          | Notes                          |
|--------------------|----------------------------------|--------------------------------|
| `MINIMAX_API_KEY`  | *(none)*                         | **Required** for live calls.   |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.chat/v1`   | Verify against MiniMax docs.   |
| `MINIMAX_MODEL`    | `MiniMax-M3`                     | Default model when omitted.    |
| `MINIMAX_PORT`     | `8001`                           | Local port (avoid 8000/5173).  |
| `MINIMAX_HOST`     | `127.0.0.1`                      | Loopback by default.           |
| `MINIMAX_TIMEOUT`  | `60`                             | Seconds for upstream call.     |
| `MINIMAX_LOG_LEVEL`| `INFO`                           | Standard logging levels.       |

### Notes

- The upstream `MINIMAX_BASE_URL` is a sensible default — confirm it against
  your MiniMax dashboard before going to production.
- All calls stay on loopback unless you change `MINIMAX_HOST`. Do not expose
  this proxy directly to the internet without putting a real auth layer in
  front of it; it currently relies on the upstream key alone.