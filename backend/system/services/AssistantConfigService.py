"""The in-app assistant's settings: the Anthropic API key and the model.

Kept in ``backend/data/assistant.json`` (owner-only), **not** in the UI
settings: those are readable through the agent's own tools, and the key
must never reach the agent or a browser. The API only ever reports
whether a key is set and its last four characters.
``ANTHROPIC_API_KEY`` in the environment is used when no key is stored.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

logger = logging.getLogger("backend.system.assistant_config")

CONFIG_FILE = Path(__file__).resolve().parents[2] / "data" / "assistant.json"

#: Models the operator can pick (current generation); the first is the default.
MODELS: tuple[tuple[str, str], ...] = (
    ("claude-opus-5-5", "Claude Opus 5.5 (recommended)"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5 (faster, cheaper)"),
    ("claude-haiku-5-5", "Claude Haiku 5.5 (fastest, cheapest)"),
    ("claude-fable-5-2", "Claude Fable 5.2 (most capable, most expensive)"),
)
DEFAULT_MODEL = MODELS[0][0]
#: Thinking depth (``output_config.effort``); chat answers do well at medium.
EFFORTS = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"


@dataclass(frozen=True)
class AssistantConfig:
    api_key: str
    model: str
    effort: str
    #: Where the key comes from: "stored", "environment" or "" (none).
    key_source: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def key_hint(self) -> str:
        return f"…{self.api_key[-4:]}" if len(self.api_key) >= 8 else ""


class AssistantConfigService:
    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self._path = path
        self._lock = Lock()

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {k: str(v) for k, v in data.items() if isinstance(v, (str, int, float))} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._path)

    def get(self) -> AssistantConfig:
        data = self._read()
        stored = data.get("api_key", "").strip()
        env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        model = data.get("model", DEFAULT_MODEL)
        effort = data.get("effort", DEFAULT_EFFORT)
        return AssistantConfig(
            api_key=stored or env,
            model=model if model in dict(MODELS) else DEFAULT_MODEL,
            effort=effort if effort in EFFORTS else DEFAULT_EFFORT,
            key_source="stored" if stored else "environment" if env else "",
        )

    def update(self, *, api_key: str | None = None, model: str | None = None, effort: str | None = None) -> AssistantConfig:
        """``api_key=""`` removes the stored key. ``ValueError`` on an unknown model / effort."""
        if model is not None and model not in dict(MODELS):
            raise ValueError(f"unknown model {model!r}")
        if effort is not None and effort not in EFFORTS:
            raise ValueError(f"unknown effort {effort!r}")
        with self._lock:
            data = self._read()
            if api_key is not None:
                if api_key.strip():
                    data["api_key"] = api_key.strip()
                else:
                    data.pop("api_key", None)
            if model is not None:
                data["model"] = model
            if effort is not None:
                data["effort"] = effort
            self._write(data)
        logger.info("Assistant settings changed (key %s, model %s)", "set" if data.get("api_key") else "not stored", data.get("model"))
        return self.get()


_service = AssistantConfigService()


def get_assistant_config_service() -> AssistantConfigService:
    return _service


__all__ = ["DEFAULT_MODEL", "EFFORTS", "MODELS", "AssistantConfig", "AssistantConfigService", "get_assistant_config_service"]
