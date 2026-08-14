"""Tests for the runtime-checkable PluggableModule protocol.

These tests validate the contract guarantees documented in
``.agent/contracts/backend-module.md``:

* The protocol is ``@runtime_checkable`` — duck-typed objects are
  accepted without inheritance.
* ``ModuleManifest`` is a Pydantic model and serialises to JSON.
* A bare stub class is recognised as a PluggableModule.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
    SidebarEntry,
)


class _StubManifest(BaseModel):
    pass


def test_protocol_is_runtime_checkable():
    """Duck-typed objects satisfy the protocol without inheriting."""

    class Stub:
        manifest = ModuleManifest(
            id="demo",
            title="Demo",
            sidebar=SidebarEntry(id="demo", label="Demo"),
        )

        def on_load(self, ctx: ModuleContext) -> None:
            return None

        def on_unload(self) -> None:
            return None

        def get_router(self):
            # The contract requires a non-null router; the stub
            # returns a minimal APIRouter to satisfy the type
            # check.
            from fastapi import APIRouter

            return APIRouter()

        # ``get_settings_model`` is part of the protocol and must
        # return a non-null :class:`BaseModel` (see
        # ``.agent/contracts/backend-module.md`` § 1).
        def get_settings_model(self):
            class _Empty(BaseModel):
                pass

            return _Empty()

    assert isinstance(Stub(), PluggableModule)


def test_object_failing_protocol_is_rejected():
    """An object missing ``on_unload`` is not a PluggableModule."""

    class Broken:
        manifest = ModuleManifest(
            id="broken",
            title="Broken",
            sidebar=SidebarEntry(id="broken", label="Broken"),
        )

        def on_load(self, ctx):
            return None

        def get_router(self):
            from fastapi import APIRouter

            return APIRouter()

        def get_settings_model(self):
            class _Empty(BaseModel):
                pass

            return _Empty()

    assert not isinstance(Broken(), PluggableModule)


def test_module_manifest_serialises_to_json():
    """Manifests round-trip through JSON without losing fields."""
    manifest = ModuleManifest(
        id="camera",
        title="Camera",
        version="1.2.3",
        description="Live video feed",
        sidebar=SidebarEntry(id="camera", label="Camera", order=20),
        settings_panel=True,
    )
    blob = manifest.model_dump_json()
    again = ModuleManifest.model_validate_json(blob)
    assert again == manifest


def test_module_context_carries_event_bus_and_settings():
    """ModuleContext is a plain dataclass wiring the bus + settings."""
    from fastapi import FastAPI

    from core.event_bus import EventBus
    from core.settings_store import SettingsStore

    bus = EventBus()
    store = SettingsStore(module_id="demo", data_root="/tmp")
    app = FastAPI()
    ctx = ModuleContext(module_id="demo", event_bus=bus, settings=store, app=app)
    assert ctx.module_id == "demo"
    assert ctx.event_bus is bus
    assert ctx.settings is store
    assert ctx.app is app