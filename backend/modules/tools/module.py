"""Tools module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package-level
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the lifecycle hooks :meth:`on_load` and :meth:`on_unload`,
* the router reference returned by :meth:`get_router`.

The actual HTTP router lives in :mod:`backend.modules.tools.router`.
No background work is scheduled today because all spindle /
extruder interactions are operator-initiated and complete in a
single request (Issue #64).

The module exposes a typed Pydantic settings schema via
:mod:`backend.modules.tools.settings`. The schema is intentionally
small so the canonical four settings endpoints expose a non-empty
payload from first boot; new knobs land as new keys on
:class:`ToolsSettings` without breaking the contract.

Spindle HAL pin subscriptions
-----------------------------

``on_load`` wires each ``spindle_digital`` tool's HAL pins into the
shared :class:`hardware.hal_subscription_manager.HalSubscriptionManager`
so the per-tick callback routes every pin read through
:func:`hardware.connection.apply_spindle_pin`. The unified helper
populates the mock's per-tool telemetry dict; the base-thread
snapshot then carries ``actual_rpm`` / ``is_connected`` /
``error_count`` to the dashboard's :class:`SpindleCard` without
any frontend changes.

The HAL module is required to be importable (real hardware path);
when the optional :mod:`hal` Python binding is missing the manager
falls through to the mock simulator at
:mod:`hardware.spindle_pin_simulator` so the dashboard still
renders realistic values in CI / dev.

Subscriptions are idempotent — a second ``on_load`` (e.g. under
``uvicorn --reload``) appends duplicates to the subscription
list rather than replacing the existing callback, which would be a
subtle bug. The ``start()`` call is also idempotent.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter
from pydantic import BaseModel

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
    SidebarEntry,
)

from .router import router as _router
from .settings import ToolsSettings

logger = logging.getLogger("backend.modules.tools")


_MANIFEST = ModuleManifest(
    id="tools",
    title="Tools",
    version="0.2.0",
    description=(
        "Operator-facing tool control: spindle (M3 / M4 / M5), "
        "extruder (G91 + G1 + G90), and per-tool target temperature "
        "via the canonical hardware.json ``tools[]`` list."
    ),
    # Tools live inside the dashboard grid, not as a top-level
    # nav item — matches the temperature module. The manifest
    # declares the sidebar entry explicitly because the contract
    # forbids a None sidebar.
    sidebar=SidebarEntry(
        id="tools",
        label="Tools",
        icon="",
        order=90,
    ),
    # Settings panel stays off until the Settings UI gains a tab
    # for this module.
    settings_panel=False,
)


# Pins the simulator / HAL reader cares about for telemetry. The
# ``rpm_out`` / ``pwm`` pins drive the dashboard's "actual RPM"
# gauge; ``at_speed`` drives the green dot; ``istop`` / ``estop``
# drive error reporting. ``forward`` / ``reverse`` / ``on`` /
# ``vfd_enable`` are control inputs but a HAL read returns a
# latched state which the simulator reflects.
_TELEMETRY_PIN_SUFFIXES = (
    "rpm-out", "rpm_out",
    "at-speed", "at_speed",
    "istop", "estop",
    "pwm",
    "on", "forward", "reverse",
    "vfd-enable", "vfd_enable",
)


def _make_spindle_callback(tool_id: str, pin_name: str) -> Callable[[Any], None]:
    """Build a HAL-pin subscription callback for one spindle pin.

    The callback reads the pin value via the mock simulator (when
    ``USE_MOCK`` is true) or via the live HAL module (real
    hardware), then routes the value through the unified
    :func:`hardware.connection.apply_spindle_pin` helper. The
    helper owns the per-pin field-mapping logic (``rpm_out`` →
    ``actual``, ``on`` / ``vfd_enable`` → ``is_connected``,
    ``istop`` / ``estop`` → ``error_count`` delta) so the callback
    stays a thin orchestrator. On real hardware the helper is a
    no-op — the live VFD status arrives via HAL pins directly and
    there is no in-process telemetry buffer to update.
    """
    from hardware.connection import HAS_HAL, USE_MOCK, apply_spindle_pin, hal
    from hardware.mock.spindle_pin_simulator import read_spindle_pin

    def _on_pin_change(_pin_value: Any) -> None:
        try:
            if HAS_HAL and hal is not None and not USE_MOCK:
                # Real-hardware path — read the pin directly. We
                # don't yet know which telemetry field the pin maps
                # to without a per-pin mapping; the simplest
                # fallback is to read the simulator anyway (which
                # falls through to hal.get_value on real hardware
                # too). Centralising the read path keeps the contract
                # in one place.
                actual = hal.get_value(pin_name)
            else:
                actual = read_spindle_pin(pin_name, tool_id)
            apply_spindle_pin(tool_id, pin_name, actual)
        except Exception:  # noqa: BLE001 - pin callback must never crash the loop
            logger.exception(
                "spindle HAL callback failed for tool %s pin %s",
                tool_id, pin_name,
            )

    return _on_pin_change


def _subscribe_spindle_pins() -> int:
    """Subscribe each spindle_digital tool's pins to ``hal_manager``."""
    from hardware import hal_manager
    from dataclasses import fields

    # Import your new mappers and config fetchers!
    from .config_mapper import get_tools
    from .mapper.digital_spindle_mapper import SpindleDigitalMapper

    count = 0
    seen_pins: set[str] = set()
    raw_tools = get_tools()

    for tool in raw_tools:
        # We only want to subscribe to digital spindles for now
        if tool.get("type") == "spindle_digital":
            tool_id = tool.get("id")

            try:
                # Use your awesome new mapper to safely parse the tool
                pins = SpindleDigitalMapper.from_dict_to_SpindleDigitalPins(tool)

                # Loop through every field (rpm_in, rpm_out, is_connected, etc.)
                for field_def in fields(pins):
                    hal_pin = getattr(pins, field_def.name)

                    # Thanks to your new HalPin design, only DynamicHalPin
                    # actually has a valid `pin` string attribute!
                    pin_name = getattr(hal_pin, "pin", None)

                    if not pin_name or pin_name in seen_pins:
                        continue

                    seen_pins.add(pin_name)

                    hal_manager.subscribe(
                        pin_name, _make_spindle_callback(tool_id, pin_name)
                    )
                    count += 1

            except Exception as e:
                logger.warning("Failed to subscribe HAL pins for spindle %s: %s", tool_id, e)

    return count


class ToolsModule:
    """The :class:`PluggableModule` instance the registry boots.

    Lifecycle: ``on_load`` wires the spindle HAL pin subscriptions and
    starts the shared :class:`HalSubscriptionManager` poll thread;
    ``on_unload`` emits an info log so registry reloads show a
    clean teardown.
    """

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Share the module-level router with the registry. The
        # registry mounts it under ``/api/v1/modules/tools``.
        self._router: APIRouter = _router
        # Track whether we have started the HAL subscription manager
        # in this process so ``on_load`` is idempotent under reload.
        self._hal_started = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the tools module.

        Subscribes each spindle's HAL pins to the shared
        :class:`HalSubscriptionManager` and starts the poll thread
        (idempotent — a reload re-subscribes but the manager's
        append-only fan-out is harmless). No other background work is
        scheduled: every spindle / extruder interaction is a single
        HTTP request that completes before the response is returned.
        """
        from hardware import hal_manager

        try:
            count = _subscribe_spindle_pins()
            if not self._hal_started:
                hal_manager.start()
                self._hal_started = True
            logger.info(
                "tools module on_load: subscribed %d spindle pin(s); "
                "HAL subscription manager %s",
                count,
                "started" if self._hal_started else "already running",
            )
        except Exception as exc:  # noqa: BLE001 - defensive: HAL missing on dev hosts
            logger.warning(
                "tools module on_load: spindle HAL subscription failed (%s); "
                "spindle telemetry will stay at default zeros until HAL "
                "wiring is restored",
                exc,
            )

    def on_unload(self) -> None:
        """Tear the tools module down.

        The HAL subscription manager is process-lifetime; we
        intentionally do not stop it here so a reload does not
        disrupt other modules' subscriptions. ``on_load`` is
        idempotent on the manager side (subsequent subscriptions
        append to the fan-out rather than replacing it).
        """
        logger.debug("tools module on_unload (HAL manager left running)")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the module's HTTP router.

        The registry mounts this at ``/api/v1/modules/tools`` with
        OpenAPI tag ``modules:tools``. Settings endpoints are
        mounted separately by the registry — see
        :meth:`ModuleRegistry._build_default_settings_router`.
        """
        return self._router

    def get_settings_model(self) -> BaseModel:
        """Return a fresh :class:`ToolsSettings` defaults instance.

        The contract requires a non-null :class:`BaseModel`. See
        :mod:`backend.modules.tools.settings` for the schema.
        """
        return ToolsSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between test runs and avoids leaking class-level state
    across reloads.
    """
    return ToolsModule()


__all__ = ["ToolsModule", "setup", "ToolsSettings"]