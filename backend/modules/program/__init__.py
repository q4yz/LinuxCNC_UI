"""Program module package (issue #38 stub).

Per the Phase 3 plan in :file:`MODULE_SYSTEM_ROADMAP.md`, the program
lifecycle endpoints (``run``, ``stop``, ``pause``, ``resume``,
``parse``) will eventually live in their own module. Phase 3a
(issue #38) only moves them **out of** ``routers/machine.py`` — the
UI for the program module lands in a later round.

This package is the landing pad: it re-exports the program
endpoints verbatim from ``router.py`` so the registry can mount them
under ``/api/v1/modules/program`` today, and the dedicated UI can
follow later without churning the URL surface.

The endpoints are intentionally defined here rather than imported
from the legacy ``routers/machine.py`` because that file is being
deleted as part of this migration. Any operator who relied on the
old ``/api/v1/program/*`` URLs gets exactly the same response
shapes under ``/api/v1/modules/program/*`` — which is acceptable
for v1 because nothing in the codebase (or in the existing tests)
called those endpoints via the old URL yet.
"""
from .module import setup

__all__ = ["setup"]
