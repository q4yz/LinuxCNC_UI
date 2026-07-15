"""
Pluggable module protocol for the hardware module registry.

This module defines the :class:`PluggableModule` protocol that every
hardware module (camera, temperature, spindle, VFD, ...) must satisfy to
participate in the auto-discovery performed by
:class:`core.module_registry.ModuleRegistry`.

A "module" is an isolated unit of functionality that may:

* subscribe to or publish events on the shared :class:`core.event_bus.EventBus`, and
* expose an optional HTTP surface as a FastAPI :class:`fastapi.APIRouter`.

The intent is to let new hardware be added by simply dropping a package
under ``backend/modules/`` and exposing a ``setup()`` factory — the
registry wires it up at startup without the module needing to know
about FastAPI, the event bus, or any other concrete service.
"""

from typing import Optional, Protocol

from fastapi import APIRouter

from .event_bus import EventBus


class PluggableModule(Protocol):
    """The interface every hardware module must implement.

    Instances are typically produced by a module-level ``setup()``
    factory that returns a concrete class implementing this surface.
    The registry treats the returned object as a black box that obeys
    these three members.
    """

    name: str
    """Unique identifier for the module (e.g. ``'camera'``, ``'temperature'``).

    Used as the namespace for HTTP routes (``/api/v1/modules/{name}/...``)
    and as the key in the registry's module map. Two modules sharing the
    same name will be rejected as a collision.
    """

    def register(self, bus: EventBus) -> None:
        """Hook the module into the shared EventBus.

        Called exactly once at startup, before the HTTP router (if any)
        is mounted. Modules should subscribe to topics of interest here.

        Implementations MUST be **lightweight and non-blocking**: do not
        open serial ports, start threads, or perform long-running I/O
        in this method. Anything that needs an event loop should be
        scheduled via FastAPI's lifespan and consume the bus from a
        background task instead.
        """
        ...

    def get_router(self) -> Optional[APIRouter]:
        """Return the module's HTTP router, if it exposes any.

        Returning ``None`` means the module is *internal*: it only
        interacts via the event bus or background work. Returning a
        router causes the registry to mount the routes at
        ``/api/v1/modules/{name}`` automatically.
        """
        ...
