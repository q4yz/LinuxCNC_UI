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
        manifest = ModuleManifest(id="demo", title="Demo")

        def on_load(self, ctx: ModuleContext) -> None:
            return None

        def on_unload(self) -> None:
            return None

        def get_router(self):
            return None

        # ``get_settings_model`` is part of the protocol as of Phase 2d
        # (see Issue #31 / module system extension). Modules that don't
        # ship a Pydantic defaults model return ``None`` — same shape
        # the registry's ``_resolve_settings_model`` accepts.
        def get_settings_model(self):
            return None

    assert isinstance(Stub(), PluggableModule)


def test_object_failing_protocol_is_rejected():
    """An object missing ``on_unload`` is not a PluggableModule."""

    class Broken:
        manifest = ModuleManifest(id="broken", title="Broken")

        def on_load(self, ctx):
            return None

        def get_router(self):
            return None

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
    from core.event_bus import EventBus
    from core.settings_store import SettingsStore

    bus = EventBus()
    store = SettingsStore(module_id="demo", data_root="/tmp")
    ctx = ModuleContext(module_id="demo", event_bus=bus, settings=store)
    assert ctx.module_id == "demo"
    assert ctx.event_bus is bus
    assert ctx.settings is store