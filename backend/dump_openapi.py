"""Write one backend app's OpenAPI schema to a file — no server, no port.

    python backend/dump_openapi.py machine <out.json>
    python backend/dump_openapi.py system  <out.json>

Imports ``backend/<app>/main.py`` and calls ``app.openapi()``. The
lifespan never runs, so nothing is bound to :8000/:8001 and no HAL
pins, camera supervisor or machine process are started. The update
(``rebuild_ui.sh``) uses this instead of booting temporary backends on
the real ports, which made the UI believe the system was back up.

One app per process: both apps have their own top-level ``main``,
``routers`` and ``services`` modules, which would collide in one
interpreter.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APPS = ("machine", "system")


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in APPS:
        print(f"usage: {argv[0]} {{{'|'.join(APPS)}}} <out.json>", file=sys.stderr)
        return 2
    app_dir = Path(__file__).resolve().parent / argv[1]
    out = Path(argv[2]).resolve()

    # Same import context as `uvicorn main:app` run from the app folder.
    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))
    import main as app_main  # noqa: E402  (path set up above)

    spec = app_main.app.openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec), encoding="utf-8")
    print(f"[dump_openapi] {argv[1]}: {len(spec.get('paths', {}))} paths -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
