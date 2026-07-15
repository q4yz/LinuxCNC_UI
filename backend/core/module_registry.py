"""
Module registry for auto-discovering hardware modules at startup.

The registry scans a Python package (default: ``backend.modules``) for
sub-packages, imports each, and asks it for a :class:`PluggableModule`
instance via a ``setup()`` factory. Each module is then:

1.  Hooked into the shared :class:`core.event_bus.EventBus` via
    :meth:`PluggableModule.register`.
2.  Mounted onto the FastAPI app under
    ``/api/v1/modules/{module_name}`` if it exposes an HTTP router.

The registry deliberately lives in :mod:`core` (not :mod:`routers`) so
that importing it does not pull in FastAPI at type-check time, while
still keeping every auto-discovery concern in one place.

The :class:`registry` singleton at module level is what
:func:`core.module_registry.registry` exposes to ``main.py``.
"""

import importlib
import logging
import pkgutil
from typing import Dict, Optional

from fastapi import FastAPI

from .event_bus import bus as default_bus
from .event_bus import EventBus
from .protocols import PluggableModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Discovers, loads, and wires up ``PluggableModule`` packages.

    Typical usage from FastAPI's lifespan manager::

        async def lifespan(app: FastAPI):
            registry.discover_and_load(app)
            ...
            yield
            registry.unload()

    Designed to be instantiated once and shared; a module-level
    :data:`registry` singleton is provided for convenience.
    """

    def __init__(self) -> None:
        # name -> PluggableModule instance
        self.modules: Dict[str, PluggableModule] = {}

    def discover_and_load(
        self,
        app: FastAPI,
        package_name: str = "modules",
        bus: Optional[EventBus] = None,
    ) -> None:
        """Scan ``package_name`` for sub-packages and register each module.

        For every sub-package found under ``package_name.__path__`` the
        registry dynamically imports it and looks for a ``setup()``
        factory. When ``setup()`` returns a
        :class:`PluggableModule`-shaped instance, the registry hands it
        to :meth:`_register_plugin` along with ``app``.

        Failures (missing ``setup``, import errors, etc.) are logged
        but never raised — a single broken module must not prevent the
        rest of the backend from starting.

        Args:
            app: The FastAPI application the module HTTP routers
                should be mounted onto.
            package_name: Dotted name of the package to scan. Defaults
                to ``"modules"``, which resolves to ``backend/modules``
                when the backend is run as the working directory.
            bus: Event bus instance to inject into modules. Falls back
                to the module-level ``bus`` singleton from
                :mod:`core.event_bus` when not supplied, which matches
                the rest of the codebase.
        """
        injected_bus = bus if bus is not None else default_bus

        try:
            module_pkg = importlib.import_module(package_name)
        except ImportError:
            logger.warning(
                "Package '%s' not found. No hardware modules loaded.",
                package_name,
            )
            return

        # Guard against namespace packages — they don't have a __path__.
        pkg_path = getattr(module_pkg, "__path__", None)
        if pkg_path is None:
            logger.warning(
                "Package '%s' has no __path__; nothing to scan.",
                package_name,
            )
            return

        for _, module_name, is_pkg in pkgutil.iter_modules(pkg_path):
            if not is_pkg:
                # Single-file modules aren't part of the protocol
                # contract — they wouldn't have a router package layout.
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
                plugin: PluggableModule = setup()
            except Exception as exc:  # noqa: BLE001 - intentional broad catch
                logger.error(
                    "Module %s.setup() raised: %s",
                    full_module_name,
                    exc,
                    exc_info=True,
                )
                continue

            self._register_plugin(app, plugin, injected_bus)

    def _register_plugin(
        self,
        app: FastAPI,
        plugin: PluggableModule,
        bus: EventBus,
    ) -> None:
        """Hook a single module into the event bus and FastAPI router.

        Steps:

        1.  Reject duplicate names so we never mount the same route
            prefix twice or feed two modules into the same event-bus
            subscription race.
        2.  Hand the module a reference to the event bus so it can
            subscribe to / publish topics.
        3.  If the module exposes a router, mount it under
            ``/api/v1/modules/{name}`` so all module-specific endpoints
            live under a single namespace.
        """
        module_name = getattr(plugin, "name", None)
        if not module_name or not isinstance(module_name, str):
            logger.error(
                "Module %r is missing a valid 'name' attribute. Skipping.",
                plugin,
            )
            return

        if module_name in self.modules:
            logger.error(
                "Module collision: '%s' is already registered.", module_name
            )
            return

        logger.info("Registering module: %s", module_name)

        # 1. Let the module hook into the event bus
        try:
            plugin.register(bus)
        except Exception as exc:  # noqa: BLE001 - intentional broad catch
            logger.error(
                "Module %s.register() raised: %s",
                module_name,
                exc,
                exc_info=True,
            )
            return

        # 2. Mount the module's HTTP routes, if any
        router = plugin.get_router()
        if router is not None:
            app.include_router(
                router,
                prefix=f"/api/v1/modules/{module_name}",
                tags=[f"modules:{module_name}"],
            )

        self.modules[module_name] = plugin

    def unload(self) -> None:
        """Drop all registered modules.

        Called from FastAPI's lifespan shutdown so subsequent restarts
        (for example under ``--reload``) don't accumulate stale
        references.
        """
        self.modules.clear()


# Singleton instance for the core system.
# ``main.py`` should ``from core.module_registry import registry`` and
# call ``registry.discover_and_load(app)`` from its lifespan manager.
registry = ModuleRegistry()
