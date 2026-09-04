"""Per-module canonical settings router factory.

The previous module-registry implementation mounted a four-endpoint
settings router for every :class:`PluggableModule` it discovered.
After the consolidation this responsibility moved to
:mod:`backend.main` — :func:`build_module_settings_router` exposes
the same router so ``main.py`` can wire it under
``/api/v1/modules/<id>/settings`` exactly once per id.

Endpoints exposed:

* ``GET  /``       — full payload (defaults merged with persisted)
* ``GET  /{key}``  — single value, ``404`` if missing
* ``PUT  /``       — bulk replace, returns the merged payload
* ``PUT  /{key}``  — single-key upsert, returns the merged payload

The factory takes a :class:`core.settings_store.SettingsStore` so
the router owns no persistence state of its own — every read /
write is forwarded to the store, which is the same instance the
lifespan manager constructed in ``main.py``.
"""
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Body, HTTPException

from core.settings_store import SettingsStore


def build_module_settings_router(settings: SettingsStore) -> APIRouter:
    """Return the canonical four-endpoint settings router.

    The router is mounted under
    ``/api/v1/modules/<id>/settings`` by :mod:`backend.main`.
    """
    router = APIRouter()

    @router.get(
        "",
        summary="Read all settings for this module",
        description=(
            "Returns the persisted settings merged with the "
            "module's Pydantic defaults. Missing keys are filled "
            "in from the defaults so a fresh checkout returns a "
            "complete payload."
        ),
    )
    def read_all() -> Dict[str, object]:
        return settings.read_all()

    @router.get(
        "/{key}",
        summary="Read a single settings key",
        description=(
            "Returns the value associated with ``key`` or ``404`` "
            "if the key has never been set."
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
            "Persists the supplied payload atomically (tmp + "
            "os.replace) and returns the merged result."
        ),
    )
    def write_all(payload: Dict[str, object]) -> Dict[str, object]:
        return settings.write_all(payload)

    @router.put(
        "/{key}",
        summary="Upsert a single settings key",
        description=(
            "Accepts a JSON body of any shape and stores it under "
            "``{key}``. Merges with the existing payload, persists "
            "the result, and returns the merged payload."
        ),
    )
    def write_one(
        key: str,
        value: object = Body(...),
    ) -> Dict[str, object]:
        return settings.write_key(key, value)

    return router


__all__ = ["build_module_settings_router"]
