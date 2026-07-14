"""
minimax_local.py
================

A small FastAPI server that exposes a stable *local* URL for talking to the
MiniMax (M3) API. The intent is so that any tool in this repo (or your editor
scripts) can hit ``http://localhost:8001/v1/chat/completions`` without each
caller needing to know the upstream endpoint, key handling, or transport.

Why a local proxy?
------------------
- Single place to put the API key (read from .env, never logged).
- Lets the rest of the toolchain talk to an OpenAI-compatible local URL
  (``/v1/chat/completions``), so swapping the backend is one-line.
- Plays nicely with the rest of this project, which already runs FastAPI.

Run it:
    python scripts/minimax_local.py
    # or with overrides:
    MINIMAX_API_KEY=... MINIMAX_BASE_URL=https://api.minimaxi.chat \\
    MINIMAX_PORT=8001 python scripts/minimax_local.py

Endpoints exposed:
    GET  /health                  -> liveness + key presence check
    GET  /v1/models               -> passthrough to upstream
    POST /v1/chat/completions     -> OpenAI-compatible chat proxy
    POST /v1/chat/completions/stream -> SSE stream passthrough

NOTE: The upstream ``MINIMAX_BASE_URL`` is a placeholder. Confirm the correct
endpoint from your MiniMax dashboard before going to production.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Load .env from the repo root if present so users can drop the key there once.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))

# TODO: confirm this base URL against the MiniMax dashboard / docs.
DEFAULT_BASE_URL = "https://api.minimaxi.chat/v1"

API_KEY: Optional[str] = os.getenv("MINIMAX_API_KEY")
BASE_URL: str = os.getenv("MINIMAX_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
PORT: int = int(os.getenv("MINIMAX_PORT", "8001"))
HOST: str = os.getenv("MINIMAX_HOST", "127.0.0.1")
MODEL: str = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
REQUEST_TIMEOUT: float = float(os.getenv("MINIMAX_TIMEOUT", "60"))

logging.basicConfig(
    level=os.getenv("MINIMAX_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] minmax-local: %(message)s",
)
log = logging.getLogger("minimax_local")

app = FastAPI(
    title="MiniMax Local Proxy",
    version="0.1.0",
    description="Local passthrough to the MiniMax M3 API.",
)


# ---------------------------------------------------------------------------
# Schemas (OpenAI-compatible shape)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, gt=0)
    stream: Optional[bool] = False


# ---------------------------------------------------------------------------
# Upstream transport (stdlib only - no extra deps)
# ---------------------------------------------------------------------------

def _require_key() -> str:
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "MINIMAX_API_KEY is not set. Add it to your .env or environment "
                "before calling the proxy."
            ),
        )
    return API_KEY


def _upstream_headers(stream: bool = False) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_require_key()}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }


def _post_upstream(path: str, payload: Dict[str, Any], stream: bool) -> Any:
    """Blocking POST. For non-stream we return parsed JSON; for stream we
    return the raw urllib response so the caller can iterate it."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=_upstream_headers(stream=stream),
        method="POST",
    )
    log.info("POST %s model=%s stream=%s", url, payload.get("model"), stream)
    try:
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        log.error("upstream %s: %s", exc.code, body)
        raise HTTPException(status_code=exc.code, detail=body) from exc
    except urllib.error.URLError as exc:
        log.error("upstream connection error: %s", exc)
        raise HTTPException(status_code=502, detail=f"upstream unreachable: {exc}") from exc

    if stream:
        return resp  # caller iterates resp
    return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "upstream": BASE_URL,
        "model_default": MODEL,
        "api_key_present": bool(API_KEY),
    }


@app.get("/v1/models")
def list_models() -> Dict[str, Any]:
    return _post_upstream("/models", {}, stream=False)


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest) -> Any:
    payload = req.model_dump(exclude_none=True)
    payload.setdefault("model", MODEL)

    if payload.get("stream"):
        # Hand the raw upstream response back as SSE.
        resp = _post_upstream("/chat/completions", payload, stream=True)

        def iter_lines() -> AsyncIterator[bytes]:
            try:
                for raw in resp:
                    yield raw
            finally:
                resp.close()

        return StreamingResponse(iter_lines(), media_type="text/event-stream")

    body = _post_upstream("/chat/completions", payload, stream=False)
    return JSONResponse(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    if not API_KEY:
        log.warning(
            "MINIMAX_API_KEY is not set - the server will start but /v1/* "
            "calls will return 503 until a key is provided."
        )
    log.info("MiniMax local proxy listening on http://%s:%d", HOST, PORT)
    log.info("Forwarding to upstream: %s", BASE_URL)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")