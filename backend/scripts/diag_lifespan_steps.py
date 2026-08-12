"""Read-only SIGILL diagnostic for the machineconfig boot path.

The Linux debian machine's lifespan crashes with SIGILL right after the
``INFO:backend.main:Starting LinuxCNC background tasks...`` log line
but before any subsequent module mount messages reach stdout. SIGILL
is a kernel-level signal that Python cannot catch via ``try/except``
(only ``Exception`` subclasses are caught; ``BaseException`` / signals
are not). The diagnostic therefore runs narrow probes one at a time
with line-buffered stdout and no broad except:

* If a probe raises a Python ``Exception``, the script logs
  ``FAILED: <name>: <exc>`` and moves to the next probe.
* If a probe triggers SIGILL, the Python process is killed by the
  kernel before any line can be printed for it. The **last line on
  stdout** identifies the probe that killed the process.

Output is deliberately redundant (``print`` writes the line and
``sys.stdout.flush()`` after every probe) so terminal buffering
cannot hide the result. The script exits 0 if every probe passes,
1 on the first Python-level failure, or is killed by SIGILL
(returncode reported as -4 / 132 by the shell).

Probes execute in the order they would be exercised at lifespan boot:

1. ``import pydantic_core`` — pydantic_core Rust .so loads at all.
2. ``HardwareJson.model_rebuild(force=True)`` — full schema recompile
   on the v2 model. **Prime suspect** for SIGILL via pydantic_core:
   forces a recompile of the forward-referenced ``mcus`` list,
   exercises pydantic_core's compile path differently than lazy
   first-use.
3. ``from modules.machineconfig.module import setup`` + ``setup()`` —
   machineconfig module on_load cycle without FastAPI boot.
4. ``KlipperToLinuxCNCCompiler()`` and ``.id`` — the concrete
   compiler class that registers in the global registry.
5. ``from main import app; len(app.openapi())`` — full OpenAPI
   schema, the endpoint the codegen script fetches.
6. ``from modules.camera.module import setup`` + ``setup()`` —
   camera-module init chain (``router`` → ``detection`` →
   ``settings``). On hosts whose OpenCV wheel ABI mismatches the
   local CPU / glibc, mapping the .so emits SIGILL at module-init.
   This is the regression net introduced after the eager
   ``import cv2 as _cv2`` at :mod:`modules.camera.router:55` was
   deleted.

Run from the repo root via the companion ``scripts/run_diag_lifespan.sh``
wrapper which sets a 30-second timeout.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Make the backend/ root importable regardless of where the script
# is invoked from. The probes use absolute imports
# (``from modules.machineconfig...``) that resolve against this path.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _banner(label: str) -> None:
    print(f"\n========== {label} ==========", flush=True)


def _run(label: str, fn) -> bool:
    """Invoke ``fn`` and report its outcome.

    Returns ``True`` on success, ``False`` if a Python exception was
    raised. The function deliberately does NOT catch
    :class:`BaseException` — SIGILL/SIGSEGV propagate to the kernel
    so the caller can see ``last log line == killed probe``.
    """
    print(f"START: {label}", flush=True)
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - intentional narrow catch
        print(f"FAILED: {label}: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.stdout.flush()
        return False
    print(f"OK: {label}", flush=True)
    sys.stdout.flush()
    return True


def _probe_pydantic_core() -> None:
    import pydantic_core  # noqa: F401 - import-only probe


def _probe_model_rebuild() -> None:
    from modules.machineconfig.models.hardware_json_models import (
        HardwareJson,
    )

    HardwareJson.model_rebuild(force=True)


def _probe_machineconfig_module() -> None:
    from modules.machineconfig.module import setup as machineconfig_setup

    instance = machineconfig_setup()
    # Touch each attribute the lifespan probes (manifest id, get_router)
    # so a SIGILL inside any of them shows up under this probe rather
    # than masquerading as something later.
    _ = instance.manifest.id
    _ = callable(instance.get_router)


def _probe_compiler_discovery() -> None:
    from modules.machineconfig.compilers.klipper_linuxcnc import (
        KlipperToLinuxCNCCompiler,
    )

    compiler = KlipperToLinuxCNCCompiler()
    _ = compiler.id
    _ = compiler.title


def _probe_openapi_schema() -> None:
    from main import app

    schema = app.openapi()
    paths = len(schema.get("paths", {}))
    schemas = len(schema.get("components", {}).get("schemas", {}))
    if paths == 0:
        raise RuntimeError(
            "OpenAPI schema generated with 0 paths — partial generation"
        )
    print(f"  paths={paths} components={schemas}", flush=True)


def _probe_camera_module() -> None:
    """Trigger ``modules.camera.module.setup()``.

    The camera module is the third-party ``opencv-python-headless``
    consumer. On hosts where the prebuilt OpenCV wheel's native ABI
    is incompatible with the local CPU / glibc baseline, mapping the
    .so at module-init time emits SIGILL — a kernel signal Python's
    ``try/except`` cannot catch, which silently kills the FastAPI
    lifespan before the OpenAPI canary fires.

    The earlier probe chain covered the pydantic_core / machineconfig
    / compiler / OpenAPI surface but not the camera module. This
    probe is the regression net for that class of failure: importing
    :mod:`modules.camera.module` here goes through the same import
    chain (``from .module import setup`` → :mod:`modules.camera.router`
    → :mod:`modules.camera.detection`) and surfaces any kernel-level
    SIGILL as an exit code 132 here rather than as an opaque lifespan
    crash in :func:`registry.boot`.

    The eager ``import cv2 as _cv2`` previously living at the top of
    :mod:`modules.camera.router` has been removed; this probe is the
    protection against reintroduction.
    """
    from modules.camera.module import setup as camera_setup

    instance = camera_setup()
    _ = instance.manifest.id
    _ = callable(instance.get_router)


PROBES: list[tuple[str, callable]] = [
    ("1_pydantic_core_import", _probe_pydantic_core),
    ("2_hardware_json_model_rebuild_force", _probe_model_rebuild),
    ("3_machineconfig_module_setup", _probe_machineconfig_module),
    ("4_compiler_discovery", _probe_compiler_discovery),
    ("5_openapi_schema_generation", _probe_openapi_schema),
    ("6_camera_module_setup", _probe_camera_module),
]


def main() -> int:
    print("LinuxCNC_UI lifespan SIGILL diagnostic", flush=True)
    print(f"Python: {sys.executable} ({sys.version.split()[0]})", flush=True)
    print(f"Platform: {sys.platform}", flush=True)

    failures = 0
    for label, probe in PROBES:
        _banner(label)
        if not _run(label, probe):
            failures += 1
            # Continue past Python-level failures so the operator
            # gets a complete failure list. SIGILL/SIGSEGV are not
            # caught (no BaseException) and abort the process
            # before this point — that's exactly the signal we want.
            continue

    _banner("summary")
    total = len(PROBES)
    if failures == 0:
        print(f"all {total} probes passed", flush=True)
        return 0
    print(f"{failures}/{total} probes failed", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
