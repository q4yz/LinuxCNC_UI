"""Every backend route reaches its service through nginx.

``deploy/nginx/linuxcnc-ui-routes.conf`` is the one routing table for a
real installation and the Docker image (both ``include`` it). A new
system-service route that the table does not send to :8001 falls through
to ``/api`` → :8000 and 404s on the machine — the bug that broke
``/api/v1/settings`` on an updated Pi. This test resolves every real
route of both apps the way nginx does and checks the port, and keeps the
Vite dev proxy and the install scripts in step with the same file.

Routes come from ``backend/dump_openapi.py`` in a subprocess per app (the
two apps cannot be imported into one interpreter).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

REPO = Path(__file__).resolve().parents[3]
ROUTES_FILE = REPO / "deploy" / "nginx" / "linuxcnc-ui-routes.conf"

SYSTEM, MACHINE = 8001, 8000

Location = Tuple[str, str, Optional[int]]  # (modifier, pattern, upstream port or None = static)


def _locations() -> List[Location]:
    text = re.sub(r"#[^\n]*", "", ROUTES_FILE.read_text(encoding="utf-8"))
    out: List[Location] = []
    for match in re.finditer(r"location\s+(=|~\*|~|\^~)?\s*(\S+)\s*\{([^}]*)\}", text):
        modifier, pattern, body = match.group(1) or "", match.group(2), match.group(3)
        port = re.search(r"proxy_pass\s+http://127\.0\.0\.1:(\d+)", body)
        out.append((modifier, pattern, int(port.group(1)) if port else None))
    return out


def resolve(path: str, locations: List[Location]) -> Optional[int]:
    """nginx location selection: ``=`` exact, else the longest prefix
    (final when ``^~``), else the first matching regex in order, else
    that longest prefix."""
    for modifier, pattern, port in locations:
        if modifier == "=" and path == pattern:
            return port
    prefixes = [
        (pattern, modifier, port)
        for modifier, pattern, port in locations
        if modifier in ("", "^~") and path.startswith(pattern)
    ]
    longest = max(prefixes, key=lambda p: len(p[0]), default=None)
    if longest and longest[1] == "^~":
        return longest[2]
    for modifier, pattern, port in locations:
        if modifier.startswith("~"):
            flags = re.IGNORECASE if modifier == "~*" else 0
            if re.search(pattern, path, flags):
                return port
    return longest[2] if longest else None


def _api_paths(app: str, tmp_path: Path) -> List[str]:
    out = tmp_path / f"{app}.json"
    subprocess.run(
        [sys.executable, str(REPO / "backend" / "dump_openapi.py"), app, str(out)],
        check=True, capture_output=True, timeout=120,
    )
    paths = json.loads(out.read_text(encoding="utf-8"))["paths"]
    # Concrete request paths: {param} -> a sample segment.
    return sorted(re.sub(r"\{[^}]+\}", "sample", p) for p in paths if p.startswith("/api"))


@pytest.fixture(scope="module")
def locations() -> List[Location]:
    return _locations()


@pytest.fixture(scope="module")
def api_paths(tmp_path_factory) -> Dict[str, List[str]]:
    tmp = tmp_path_factory.mktemp("openapi")
    return {"system": _api_paths("system", tmp), "machine": _api_paths("machine", tmp)}


def test_every_system_service_route_goes_to_8001(locations, api_paths):
    wrong = {p: resolve(p, locations) for p in api_paths["system"] if resolve(p, locations) != SYSTEM}
    assert api_paths["system"], "no system routes found"
    assert not wrong, (
        "system-service routes nginx would send elsewhere (add a location to "
        f"deploy/nginx/linuxcnc-ui-routes.conf and the vite DEV_PROXY): {wrong}"
    )


def test_every_machine_backend_route_goes_to_8000(locations, api_paths):
    wrong = {p: resolve(p, locations) for p in api_paths["machine"] if resolve(p, locations) != MACHINE}
    assert api_paths["machine"], "no machine routes found"
    assert not wrong, f"machine-backend routes nginx would send elsewhere: {wrong}"


def test_websocket_and_spa_routing(locations):
    assert resolve("/ws/telemetry", locations) == MACHINE
    assert resolve("/", locations) is None  # static SPA
    assert resolve("/files/anything", locations) is None


def test_vite_dev_proxy_matches_the_nginx_table(locations):
    """Dev must route like production, or a route works in dev and 404s on the Pi."""
    vite = (REPO / "frontend" / "vite.config.mjs").read_text(encoding="utf-8")
    table = vite[vite.index("const DEV_PROXY"): vite.index("};", vite.index("const DEV_PROXY"))]
    dev_system = set(re.findall(r"'(/[^']+)':\s*\{\s*target:\s*SYSTEM_TARGET", table))
    nginx_system = {pattern for modifier, pattern, port in locations if modifier == "" and port == SYSTEM}
    assert dev_system == nginx_system


def test_installs_include_the_shared_routes_file():
    configure = (REPO / "scripts" / "configure_nginx.sh").read_text(encoding="utf-8")
    assert configure.count("include $ROUTES_FILE;") == 2, "both server blocks (HTTP + HTTPS) must include it"
    assert "nginx -t" in configure, "validate before restarting nginx"

    install = (REPO / "install.sh").read_text(encoding="utf-8")
    assert "scripts/configure_nginx.sh" in install
    assert "location /api" not in install, "routes must not be duplicated inline again"

    docker = (REPO / "docker" / "nginx.conf").read_text(encoding="utf-8")
    assert "include /app/deploy/nginx/linuxcnc-ui-routes.conf;" in docker
    assert "COPY deploy/nginx deploy/nginx" in (REPO / "Dockerfile").read_text(encoding="utf-8")

    update = (REPO / "scripts" / "update.sh").read_text(encoding="utf-8")
    assert "linuxcnc-ui-routes.conf" in update, "updates must flag a site that does not include the file"


def test_the_resolver_follows_nginx_precedence():
    table: List[Location] = [
        ("", "/", None),
        ("~", r"^/api/v1/modules/macros/[^/]+/start$", MACHINE),
        ("", "/api/v1/modules/macros", SYSTEM),
        ("", "/api", MACHINE),
    ]
    assert resolve("/api/v1/modules/macros/probe/start", table) == MACHINE  # regex beats prefix
    assert resolve("/api/v1/modules/macros/probe", table) == SYSTEM
    assert resolve("/api/v1/other", table) == MACHINE
