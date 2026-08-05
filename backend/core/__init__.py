"""Core package for the LinuxCNC UI backend.

The ``core`` package owns the cross-cutting infrastructure that the
rest of the codebase depends on: machine configuration parsing,
the event bus, the module registry, persistent settings, and the
Pydantic models that back them. Anything in here is permitted to
be imported by both the ``routers`` and ``services`` sub-packages
without introducing a cycle.
"""
