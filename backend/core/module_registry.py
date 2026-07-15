"""
Registry-driven module discovery, boot, and shutdown.

ModuleRegistry scans the ``backend/modules/`` package for sub-packages
and instantiates each via a ``setup()`` factory. Each module is then:

1.  Bootstrapped with a :class:`core.protocols.ModuleContext`
    (event bus + per-module :class:`core.settings_store.SettingsStore`).
2.  Mounted onto the FastAPI app under
    ``/api/v1/modules/{id}`` if it exposes an HTTP router.
3.  Mounted onto the FastAPI app under
    ``/api/v1/modules/{id}/settings`` if it exposes a settings
    router.

The registry lives in :mod:`core` (not :mod:`routers`) so that
importing it does not pull in FastAPI at type-check time, while still
keeping every auto-discovery concern in one place.

The module-level :data:`registry` singleton is what
``backend/main.py`` invokes from its lifespan manager. The
:class:`registry <ModuleRegistry>` emits a single-line summary on
boot::

    registry: mounted=[a,b] skipped=0 missing=0

…which the acceptance criteria for Phase 2b/2c require for log-based
verifiability.
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from .event_bus import EventBus, bus as default_bus
from .protocols import ModuleContext, ModuleManifest, PluggableModule
from .settings_store import SettingsStore

logger = logging.getLogger(__name__)


# ``MODULES_ENABLED`` controls which module IDs are allowed to boot.
# Empty / unset means "mount everything discovered" — keeps the dev
# experience ergonomic without forcing operators to maintain a
# whitelist. Comma-separated values, e.g. ``MODULES_ENABLED=camera,
# temperature`` mounts only those two.
_MODULES_ENABLED_ENV = "MODULES_ENABLED"


def _parse_enabled() -> Optional[set]:
    """Return the ``MODULES_ENABLED`` whitelist, or ``None`` for "all".

    Returns ``None`` (not an empty set) when the env var is unset or
    empty, so callers can distinguish "no whitelist" from "whitelist
    is empty" (which would mount nothing).
    """
    raw = os.environ.get(_MODULES_ENABLED_ENV, "").strip()
    if not raw:
        return None
    return {token.strip() for token in raw.split(",") if token.strip()}


class ModuleRegistry:
    """Discovers, boots, and tears down :class:`PluggableModule` packages.

    Typical usage from FastAPI's lifespan manager::

        async def lifespan(app: FastAPI):
            registry.boot(app)
            yield
            registry.shutdown()

    Designed to be instantiated once and shared; a module-level
    :data:`registry` singleton is provided for convenience.
    """

    DEFAULT_PACKAGE = "modules"
    DEFAULT_DATA_ROOT = Path("data")

    def __init__(
        self,
        *,
        data_root: Optional[Path] = None,
    ) -> None:
        self.modules: Dict[str, PluggableModule] = {}
        self.manifests: Dict[str, ModuleManifest] = {}
        self._data_root = Path(data_root) if data_root else self.DEFAULT_DATA_ROOT
        # Track which modules we booted so shutdown walks them in
        # reverse order regardless of dict iteration order.
        self._boot_order: List[str] = []

    # ------------------------------------------------------------------ #
    # Discovery                                                          #
    # ------------------------------------------------------------------ #

    def discover(self, package_name: str = DEFAULT_PACKAGE) -> List[PluggableModule]:
        """Scan ``package_name`` for sub-packages and instantiate each.

        The scan walks ``package_name.__path__`` and treats every
        sub-package whose top-level ``setup()`` returns something
        ``isinstance(..., PluggableModule)`` as a candidate. Failures
        (missing ``setup``, import errors, ``setup()`` raising, the
        returned object failing the protocol check) are logged but
        never raised.

        Returns:
            The list of successfully constructed (but **not yet
            booted**) module instances.
        """
        try:
            module_pkg = importlib.import_module(package_name)
        except ImportError:
            logger.warning(
                "Package '%s' not found. No modules discovered.", package_name
            )
            return []

        pkg_path = getattr(module_pkg, "__path__", None)
        if pkg_path is None:
            logger.warning(
                "Package '%s' has no __path__; nothing to scan.", package_name
            )
            return []

        instances: List[PluggableModule] = []
        for _, module_name, is_pkg in pkgutil.iter_modules(pkg_path):
            if not is_pkg:
                # Single-file modules can't host the contract
                # (router + settings + setup() need a package layout).
                continue

            full_module_name = f"{package_name}.{module_name}"
            try:
                mod = importlib.import_module(full_module_name)
            except Exception as exc:  # noqa: BLE001 - intentional broad catch
                logger.error(
                    "Failed to import module %s: %s",
                    full_module_name,
                    exc,
                    exc_info=True,
                )
                continue

            setup = getattr(mod, "setup", None)
            if setup is None:
                logger.warning(
                    "Module %s missing 'setup' entrypoint. Skipping.",
                    full_module_name,
                )
                continue

            try:
                instance = setup()
            except Exception as exc:  # noqa: BLE001 - intentional broad catch
                logger.error(
                    "Module %s.setup() raised: %s",
                    full_module_name,
                    exc,
                    exc_info=True,
                )
                continue

            if not isinstance(instance, PluggableModule):
                logger.error(
                    "Module %s.setup() did not return a PluggableModule. Skipping.",
                    full_module_name,
                )
                continue

            instances.append(instance)

        return instances

    # ------------------------------------------------------------------ #
    # Boot / Shutdown                                                    #
    # ------------------------------------------------------------------ #

    def boot(
        self,
        app: FastAPI,
        *,
        bus: Optional[EventBus] = None,
        candidates: Optional[List[PluggableModule]] = None,
    ) -> None:
        """Discover, whitelist-filter, and boot every module.

        Steps, in order:

        1.  :meth:`discover` produces the raw candidate list (or use
            the one passed in via ``candidates``, handy for tests).
        2.  The ``MODULES_ENABLED`` env var filters the list. Unknown
            IDs are logged at WARNING but never abort the boot.
        3.  Each surviving module is wired into the FastAPI app and
            the event bus, and its :meth:`PluggableModule.on_load`
            hook is invoked.
        4.  A single-line summary is logged::

                registry: mounted=[a,b] skipped=1 missing=0

        ``missing`` counts requested IDs that weren't found among
        the discovered modules; ``skipped`` counts modules we found
        but didn't mount because they weren't on the whitelist.
        """
        injected_bus = bus if bus is not None else default_bus

        if candidates is None:
            candidates = self.discover()

        mounted_ids: List[str] = []
        skipped_ids: List[str] = []
        missing_ids: List[str] = []
        seen_ids: set = set()

        # Build the candidate map keyed by ``manifest.id`` so the
        # whitelist can address modules by their public identifier
        # (rather than the filesystem folder name).
        by_id: Dict[str, PluggableModule] = {}
        for instance in candidates:
            manifest = getattr(instance, "manifest", None)
            if not isinstance(manifest, ModuleManifest):
                logger.error(
                    "Module %r is missing a valid ModuleManifest. Skipping.",
                    instance,
                )
                continue
            mid = manifest.id
            if mid in by_id:
                logger.error("Module id collision: '%s' is duplicated. Skipping.", mid)
                continue
            by_id[mid] = instance

        whitelist = _parse_enabled()
        if whitelist is None:
            # No whitelist: mount everything discovered.
            to_mount = list(by_id.items())
        else:
            to_mount = []
            for mid in whitelist:
                if mid in by_id:
                    to_mount.append((mid, by_id[mid]))
            # Track what the operator asked for but we couldn't find.
            missing_ids = sorted(whitelist - by_id.keys())
            # Track what we discovered but the operator excluded.
            skipped_ids = sorted(by_id.keys() - whitelist)
            for missing in missing_ids:
                logger.warning("unknown module id '%s'", missing)

        for mid, instance in to_mount:
            if mid in seen_ids:
                logger.error("Module id collision during mount: '%s'. Skipping.", mid)
                continue
            seen_ids.add(mid)
            self._mount(app, injected_bus, mid, instance)
            mounted_ids.append(mid)

        # Summary log line: exactly one line so CI grep stays trivial.
        logger.info(
            "registry: mounted=%s skipped=%d missing=%d",
            mounted_ids,
            len(skipped_ids),
            len(missing_ids),
        )

        # Stash the boot order so shutdown is the exact reverse.
        self._boot_order = list(reversed(mounted_ids))

    def shutdown(self) -> None:
        """Unload every booted module in reverse registration order.

        Idempotent: calling :meth:`shutdown` twice is safe. After
        shutdown the registry can be booted again with a fresh
        candidate list (useful under ``--reload``).
        """
        for mid in self._boot_order:
            instance = self.modules.get(mid)
            if instance is None:
                continue
            try:
                instance.on_unload()
            except Exception as exc:  # noqa: BLE001 - intentional broad catch
                logger.error(
                    "Module %s.on_unload() raised: %s", mid, exc, exc_info=True
                )
        self.modules.clear()
        self.manifests.clear()
        self._boot_order.clear()

    # ------------------------------------------------------------------ #
    # Mount helpers                                                      #
    # ------------------------------------------------------------------ #

    def _mount(
        self,
        app: FastAPI,
        bus: EventBus,
        module_id: str,
        instance: PluggableModule,
    ) -> None:
        """Hook a single module into the event bus and FastAPI routers."""
        manifest = instance.manifest
        logger.info("Mounting module: %s (%s)", module_id, manifest.title)

        # 1. Settings store + ModuleContext (cheap, no I/O yet).
        settings = SettingsStore(
            module_id=module_id,
            data_root=self._data_root,
            defaults=None,
        )
        ctx = ModuleContext(
            module_id=module_id,
            event_bus=bus,
            settings=settings,
        )

        # 2. Run the module's on_load hook.
        try:
            instance.on_load(ctx)
        except Exception as exc:  # noqa: BLE001 - intentional broad catch
            logger.error(
                "Module %s.on_load() raised: %s. Skipping mount.",
                module_id,
                exc,
                exc_info=True,
            )
            return

        # 3. Mount the public router, if any.
        router = instance.get_router()
        if router is not None:
            app.include_router(
                router,
                prefix=f"/api/v1/modules/{module_id}",
                tags=[f"modules:{module_id}"],
            )

        # 4. Mount the canonical settings router. The four endpoints
        #    (GET/PUT bulk + GET/PUT key) are owned by the registry;
        #    modules just declare schemas on their manifest.
        settings_router = _build_default_settings_router(settings)
        app.include_router(
            settings_router,
            prefix=f"/api/v1/modules/{module_id}/settings",
            tags=[f"modules:{module_id}:settings"],
        )

        self.modules[module_id] = instance
        self.manifests[module_id] = manifest


# ---------------------------------------------------------------------- #
# Default settings router                                                 #
# ---------------------------------------------------------------------- #


def _build_default_settings_router(settings: SettingsStore) -> APIRouter:
    """Return the canonical four-endpoint settings router.

    The router exposes:

    * ``GET  /``       — full payload (defaults merged with persisted)
    * ``GET  /{key}``  — single value, ``404`` if missing
    * ``PUT  /``       — bulk replace, returns the merged payload
    * ``PUT  /{key}``  — single-key upsert, returns the merged payload
    """
    from fastapi import Body, HTTPException

    router = APIRouter()

    @router.get(
        "",
        summary="Read all settings for this module",
        description=(
            "Returns the persisted settings merged with the module's "
            "Pydantic defaults. Missing keys are filled in from the "
            "defaults so a fresh checkout returns a complete payload."
        ),
    )
    def read_all() -> Dict[str, object]:
        return settings.read_all()

    @router.get(
        "/{key}",
        summary="Read a single settings key",
        description=(
            "Returns the value associated with ``key`` or ``404`` if "
            "the key has never been set."
        ),
    )
    def read_one(key: str):
        data = settings.read_all()
        if key not in data:
            raise HTTPException(
                status_code=404,
                detail=f"Settings key '{key}' not found",
            )
        return {key: data[key]}

    @router.put(
        "",
        summary="Replace all settings for this module",
        description=(
            "Persists the supplied payload atomically (tmp + os.replace) "
            "and returns the merged result."
        ),
    )
    def write_all(payload: Dict[str, object]) -> Dict[str, object]:
        return settings.write_all(payload)

    @router.put(
        "/{key}",
        summary="Upsert a single settings key",
        description=(
            "Accepts a JSON body of any shape and stores it under "
            "``{key}``. Merges with the existing payload, persists the "
            "result, and returns the merged payload."
        ),
    )
    def write_one(
        key: str,
        value: object = Body(...),
    ) -> Dict[str, object]:
        # ``Body(...)`` tells FastAPI to read the request body as the
        # value (rather than expecting query parameters). The store
        # stores it verbatim.
        return settings.write_key(key, value)

    return router


# Module-level singleton consumed by ``backend/main.py``.
registry = ModuleRegistry()


__all__ = ["ModuleRegistry", "registry"]