#!/usr/bin/env python3
"""Record the progress of a system update for the UI.

Called by ``scripts/update.sh`` at every step; the system service
serves the file at ``GET /api/v1/system/update/status`` and the update
screen polls it. ``done`` is written only as the very last step — after
the services were restarted and answered a health check — so the UI
never finishes early.

    update_status.py <state> <phase> [message]

    state: running | done | failed
    phase: free text shown on the update screen (pull, dependencies, ...)

Environment (set by the system service when it launches the update):
    UPDATE_STATUS_FILE   where to write (default backend/data/update_status.json)
    UPDATE_RUN_ID        id of this update run ("manual" when run by hand)

Standard library only — it runs while the backend services are down.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_FILE = PROJECT_ROOT / "backend" / "data" / "update_status.json"
LOG_FILE = PROJECT_ROOT / "update.log"
STATES = ("running", "done", "failed")
LOG_TAIL_LINES = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _log_tail() -> str:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL_LINES:])


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".update_status-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in STATES:
        print(f"usage: {argv[0]} {{{'|'.join(STATES)}}} <phase> [message]", file=sys.stderr)
        return 2
    state, phase = argv[1], argv[2]
    message = argv[3] if len(argv) > 3 else ""
    path = Path(os.environ.get("UPDATE_STATUS_FILE") or DEFAULT_STATUS_FILE)
    run_id = os.environ.get("UPDATE_RUN_ID") or "manual"

    previous = _read(path)
    same_run = previous.get("run_id") == run_id
    payload = {
        "run_id": run_id,
        "state": state,
        "phase": phase,
        "message": message,
        "started_at": previous.get("started_at") if same_run else _now(),
        "updated_at": _now(),
        "finished_at": _now() if state != "running" else None,
        "commit_before": previous.get("commit_before") if same_run else _commit(),
        "commit_after": _commit() if state == "done" else None,
        "log_tail": _log_tail() if state == "failed" else "",
    }
    _write(path, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
