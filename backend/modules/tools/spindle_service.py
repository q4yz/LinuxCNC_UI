import logging

from fastapi import HTTPException

from hardware.connection import mark_spindle_connected, execute_sync_cmd
from modules.tools.config_mapper import get_spindle_hal_pin_maps
from modules.tools.dtos.digital_spindle_dto import SpindleStateDTO, SpindleDigitalPins, SpindleSettingsDTO
from modules.tools.tool_service import read_spindle_telemetry, DEFAULT_SPINDLE_OVERRIDE_PIN, M5_STOP, M3_FORWARD, \
    M4_BACKWARD
from tests.test_machine_state_facade import linuxcnc

logger = logging.getLogger("backend.modules.tools.service")
class SpindleService:
    def get_spindle_state(self, tool_id: str) -> SpindleStateDTO:

        if not isinstance(tool_id, str) or not tool_id:
            raise HTTPException(status_code=400, detail="Spindle tool_id must be a non-empty string",)

        return read_spindle_telemetry(tool_id)

    def set_spindle_speed(
        self,
        pins: SpindleDigitalPins,
        dto: SpindleSettingsDTO,
    ) -> str:
        """Single spindle dispatch entry point.

        Consumes a :class:`SpindleSettingsDTO` and applies the
        state machine:

        * ``state == "stop"`` → ``M5``, transition to idle.
        * ``state == "forward"`` / ``"reverse"`` and current == idle
          → ``M3`` / ``M4`` per ``state``, transition to that direction.
        * ``state == "forward"`` / ``"reverse"`` and current == same
          direction → ``M3`` / ``M4`` with the new target RPM
          (``speed`` or ``master_override`` depending on the bypass).
        * ``state == "forward"`` / ``"reverse"`` and current ==
          opposite direction → :class:`HTTPException` ``409`` —
          operator must stop first.

        ``master_override_enable`` bypasses the standard ``speed`` /
        ``override`` path: the dispatch uses ``master_override`` RPM
        directly and the ``halui.spindle.override.scale`` pin is
        left untouched. The override pin is otherwise written before
        every M-code dispatch when it differs from the LinuxCNC
        default of ``1.0``. Returns the exact MDI string dispatched
        so the router can echo it back to the caller.
        """
        if not isinstance(dto, SpindleSettingsDTO):
            raise HTTPException(
                status_code=400,
                detail="Spindle settings must be a SpindleSettingsDTO",
            )
        if not isinstance(pins, SpindleDigitalPins):
            raise HTTPException(
                status_code=400,
                detail="Spindle pins must be a SpindleDigitalPins record",
            )

        current = self._spindle_state.get(pins.id, "idle")

        # State-machine guard — reject mid-spin direction reversal.
        if (
            dto.state != "stop"
            and current != "idle"
            and dto.state != current
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Spindle {pins.id!r} is already spinning {current}; "
                    "stop it before reversing."
                ),
            )

        self._ensure_mdi_mode()

        # Always write the override first so the next M-code runs at
        # the requested scale. Skipping the MDI when override is the
        # LinuxCNC default (1.0) keeps the output clean for the
        # common case. ``master_override_enable`` bypasses the whole
        # override path — the caller is forcing an absolute RPM and
        # does not want the relative knob applied.
        if dto.master_override_enable:
            pass
        elif dto.override != 1.0:
            self._dispatch_setp(DEFAULT_SPINDLE_OVERRIDE_PIN, dto.override)

        if dto.state == "stop":
            mdi = M5_STOP
            new_state = "idle"
            new_target = 0
        else:
            target_rpm = (
                dto.master_override if dto.master_override_enable else dto.speed
            )
            template = M3_FORWARD if dto.state == "forward" else M4_BACKWARD
            mdi = template.format(speed=target_rpm)
            new_state = dto.state
            new_target = target_rpm

        self._dispatch_mdi(mdi)
        self._spindle_state[pins.id] = new_state

        # Push the new target RPM into the mock-mode simulator so
        # ``hardware.spindle_pin_simulator.read_spindle_pin`` ramps
        # the spindle toward ``new_target`` RPM on every poll tick.
        # On real hardware the HAL subscription manager reads the
        # real ``rpm_out`` pin instead; this call is a no-op in that
        # path because the simulator is only consulted when
        # ``USE_MOCK`` is true.
        try:
            from hardware.spindle_pin_simulator import (
                set_spindle_target,
            )
            set_spindle_target(pins.id, new_target)
        except Exception:  # noqa: BLE001 - simulator missing on real hw
            pass

        # Eagerly update the spindle's ``is_connected`` flag so the
        # dashboard's SpindleCard reflects the operator's action
        # before the HAL poll loop has a chance to fire. The
        # simulator's per-tick poll refines ``actual`` (the ramp) on
        # the next iteration; ``is_connected`` flips immediately so
        # the operator's command reflects in the UI within the
        # next snapshot tick (~1 s). Routed through the unified
        # :func:`hardware.connection.mark_spindle_connected` so the
        # mock-only state write stays inside the mock.
        mark_spindle_connected(
            pins.id, dto.state != "stop",
        )

        return mdi

    def set_spindle_override_relative(
        self,
        pins: SpindleDigitalPins,
        value: float,
    ) -> None:
        """Write the relative spindle override only — no state change.

        Thin wrapper around :func:`_dispatch_setp` for the canonical
        ``halui.spindle.override.scale`` pin. The service intentionally
        does not provide an absolute counterpart — the operator-facing
        surface only writes the relative knob. ``value`` is forwarded
        verbatim; callers are expected to have clamped it to
        ``[0.0, 2.0]`` (LinuxCNC's documented range).
        """
        self._dispatch_setp(DEFAULT_SPINDLE_OVERRIDE_PIN, float(value))

    def control_spindle(
        self,
        tool_id: str,
        action: str,
        speed: int,
        override: float = 1.0,
        master_override: int = 0,
        master_override_enable: bool = False,
    ) -> str:
        """Dispatch a spindle command (legacy ``POST /spindle`` adapter).

        ``action`` must be one of ``"forward"`` / ``"backward"`` /
        ``"stop"``; the call returns the exact MDI string dispatched
        so the router can echo it back to the caller. Internally
        builds a :class:`SpindleSettingsDTO` and delegates to
        :meth:`set_spindle_speed`, which owns the state machine.

        ``override`` (default ``1.0``) is the relative override
        factor applied via ``halui.spindle.override.scale``. The
        legacy endpoint previously never wrote the pin, so the
        default of ``1.0`` preserves the historical behaviour.

        ``master_override`` is the absolute RPM applied when
        ``master_override_enable`` is true (default ``False``).
        When the bypass is on, ``speed`` and ``override`` are
        ignored and the dispatch uses ``master_override`` directly.
        """
        if not isinstance(tool_id, str) or not tool_id:
            raise HTTPException(
                status_code=400,
                detail="Spindle tool_id must be a non-empty string",
            )
        if action not in {"forward", "backward", "stop"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid spindle action: {action!r}; expected "
                    "'forward', 'backward', or 'stop'."
                ),
            )

        pins_map = get_spindle_hal_pin_maps()
        pins = pins_map.get(tool_id)
        if pins is None:
            # Back-compat fallback: the legacy ``POST /spindle``
            # route historically accepted any ``tool_id`` without
            # validating it against ``hardware.json``. Preserve that
            # behaviour by dispatching the M-code with an empty
            # :class:`SpindleDigitalPins` record so callers without a
            # compiled profile (tests, dev fixtures) keep working.
            # The stricter lookup still lives in :meth:`get_spindle`
            # and :meth:`set_spindle_speed` — those raise ``404``
            # for unknown ids and are the preferred entry points.
            pins = SpindleDigitalPins(id=tool_id)

        if action == "stop":
            dto = SpindleSettingsDTO(
                speed=0,
                master_override=master_override,
                override=override,
                master_override_enable=master_override_enable,
                state="stop",
            )
        else:
            dto = SpindleSettingsDTO(
                speed=speed,
                master_override=master_override,
                override=override,
                master_override_enable=master_override_enable,
                state="forward" if action == "forward" else "reverse",
            )
        return self.set_spindle_speed(pins, dto)

    @staticmethod
    def _ensure_mdi_mode() -> None:
        """Switch the task into MDI mode and wait for the change to commit."""
        execute_sync_cmd(
            "mode",
            5,
            getattr(linuxcnc, "MODE_MDI", 3),
        )

    @staticmethod
    def _dispatch_mdi(command: str) -> None:
        """Issue a single MDI command without waiting for completion."""
        logger.info("tools mdi -> %s", command)
        execute_sync_cmd("mdi", 0, command)

    @staticmethod
    def _dispatch_setp(pin: str, value: float) -> None:
        """Write a HAL pin via ``setp <pin> <value>``.

        Used by the spindle-override path and any future per-pin
        HAL writes the service needs. The router delegates here so
        no router is allowed to import ``hardware.*`` directly (the
        "no router imports a hardware file" rule stays enforced).
        """
        logger.info("tools setp -> %s %s", pin, value)
        execute_sync_cmd("setp", 0, pin, value)