"""
Pluggable module protocol for the registry-driven module system.

This module defines the contract that every backend module must satisfy to
participate in the auto-discovery performed by
:class:`core.module_registry.ModuleRegistry`. The contract is the canonical
``PluggableModule`` Protocol documented in
``.agent/contracts/backend-module.md`` and referenced from the
``MODULE_SYSTEM_ROADMAP.md`` Phase 2b/2c work.

A *module* is an isolated unit of functionality that may:

* expose an HTTP surface via a FastAPI :class:`fastapi.APIRouter`,
* expose a settings HTTP surface managed by the per-module
  :class:`core.settings_store.SettingsStore`,
* subscribe to or publish events on the shared
  :class:`core.event_bus.EventBus`,
* run its own lifecycle (mount/unmount) via :meth:`PluggableModule.on_load`
  and :meth:`PluggableModule.on_unload`.

The contract is :func:`typing.runtime_checkable` so the registry can do
``isinstance(obj, PluggableModule)`` against duck-typed objects without
forcing module authors to inherit from a base class.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .event_bus import EventBus


class ModuleManifest(BaseModel):
    """Static metadata describing a discovered module.

    The manifest is what the registry surfaces to the rest of the system
    (frontend sidebar, settings page, OpenAPI tags) before any of the
    module's runtime hooks have been invoked. It is intentionally a
    pure data model so it can be serialized to JSON without pulling
    in any module-specific code.
    """

    id: str = Field(..., description="Unique module identifier (kebab/snake).")
    title: str = Field(..., description="Human-readable display name.")
    version: str = Field(default="0.0.0", description="Semantic-ish version string.")
    description: str = Field(default="", description="One-line description.")
    sidebar: Optional["SidebarEntry"] = Field(
        default=None,
        description="Optional sidebar entry the module contributes.",
    )
    settings_panel: bool = Field(
        default=False,
        description="Whether this module contributes a Settings tab.",
    )


class SidebarEntry(BaseModel):
    """Single sidebar entry a module contributes.

    Modules may add entries to the application sidebar without owning
    the entire layout. The frontend registry merges these entries with
    the static built-in navigation list.
    """

    id: str = Field(..., description="Stable route identifier (must be unique app-wide).")
    label: str = Field(..., description="Display label rendered in the sidebar.")
    icon: str = Field(default="", description="Optional SVG/HTML icon string.")
    order: int = Field(
        default=100,
        description="Sort weight. Lower numbers appear earlier in the sidebar.",
    )


@dataclass
class ModuleContext:
    """Runtime context handed to a module during :meth:`PluggableModule.on_load`.

    The context is the single object a module receives at boot. It owns
    references to the shared services (event bus, settings store) plus
    the module's own identifier so it can build module-scoped namespaces
    without inspecting globals.
    """

    module_id: str
    event_bus: EventBus
    settings: "SettingsStore"
    # Optional extra slots modules can populate to share data with the
    # frontend registry. Kept open so we don't churn the protocol every
    # time the contract grows.
    extras: Dict[str, Any] = field(default_factory=dict)


# Forward reference: ``ModuleContext`` references ``SettingsStore``, but the
# store lives in :mod:`core.settings_store` which in turn imports the
# ``ModuleManifest`` model. We resolve the cycle lazily inside the registry
# instead of importing here. ``SettingsStore`` is type-checked by name only
# so static analyzers accept the forward reference.
SettingsStore = Any  # type: ignore[assignment]


@runtime_checkable
class PluggableModule(Protocol):
    """The interface every backend module must implement.

    Modules are typically produced by a module-level ``setup()`` factory
    (or any other constructor) and handed to
    :meth:`ModuleRegistry.discover`. The registry treats the returned
    object as a black box that obeys these members.

    The contract deliberately keeps the surface small so module authors
    can opt in incrementally: a module that only wants to ship
    background work can implement :meth:`on_load` and skip the rest.
    """

    manifest: ModuleManifest
    """Static metadata. Required — the registry reads this to populate
    sidebar entries, settings tabs, and OpenAPI tags without invoking
    the module's hooks."""

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the module.

        Called exactly once at startup, after the module has been
        constructed and registered with the registry, but before any
        router has been mounted. Implementations should:

        * subscribe to event-bus topics of interest,
        * open hardware handles / serial ports,
        * schedule background tasks on the running event loop.

        Must be **non-blocking**: long-running I/O must be scheduled
        via FastAPI's lifespan or :func:`asyncio.create_task`, not
        performed synchronously.
        """
        ...

    def on_unload(self) -> None:
        """Tear the module down.

        Called exactly once during shutdown, in reverse registration
        order so a module's dependents unload first. Implementations
        must release hardware handles, cancel background tasks, and
        unsubscribe from the event bus. Must be idempotent: the
        registry may call it more than once under ``--reload``.
        """
        ...

    def get_router(self) -> Optional[APIRouter]:
        """Return the module's HTTP router, if any.

        Returning ``None`` marks the module as *internal*: it only
        interacts via the event bus and/or background work. Returning
        a router causes the registry to mount the routes under
        ``/api/v1/modules/{id}``.

        Settings endpoints are **not** part of this router: the
        registry always mounts a canonical four-endpoint settings
        surface (``GET/PUT`` bulk, ``GET/PUT`` per-key) at
        ``/api/v1/modules/{id}/settings`` backed by
        :class:`core.settings_store.SettingsStore`. Modules that want
        extra settings-related endpoints should add them to the router
        returned here, optionally under a sub-prefix.
        """
        ...

    def get_settings_model(self) -> Optional[BaseModel]:
        """Return a Pydantic defaults instance, if any.

        The registry constructs a per-module :class:`SettingsStore`
        and passes the returned model as the ``defaults`` argument.
        ``None`` means the module has no Pydantic schema and the store
        stores arbitrary JSON (current behaviour for modules without
        a schema).

        The method is **optional**. Modules that don't need typed
        defaults can omit it. The registry uses :func:`getattr` and
        tolerates ``AttributeError`` so older module code keeps
        working unchanged.
        """
        ...


ModuleFactory = Callable[[], PluggableModule]
"""Callable that produces a :class:`PluggableModule` instance.

Modules traditionally expose a ``setup()`` factory function at the
package level so the registry can defer construction until the
:class:`ModuleContext` is available. The factory pattern keeps import
side effects minimal: importing the package must not start threads or
open hardware.
"""


# Re-exported for callers that want to type-check manifests in one go.
__all__ = [
    "ModuleManifest",
    "SidebarEntry",
    "ModuleContext",
    "PluggableModule",
    "ModuleFactory",
]