"""One fan entry (`fans[]`) -> :class:`HalFragment` (`.agent/component/fan.md`).

Two fan `kind`s, matching Klipper's own two section types — mutually
exclusive control models, never both on the same fan:

* **`"part"`** (`[fan]` / `[fan_generic ...]`, plus a heater's own
  auto-derived placeholder sharing its `heater_pin`). Operator/G-code
  commandable. Gets its own direct pin route unconditionally — the
  writer side (`webgui.<id>` -> `<id>-SP`) lives in
  `webgui_connections.hal` via `FanWebguiMapper`, this mapper only
  ever emits the `PinRequest` so the router can bind the physical pin.

* **`"heater"`** (`[heater_fan <name>]`). Never operator/G-code
  commandable — the HAL wires it straight off the referenced heater's
  own sensor reading: a `wcomp` (window comparator) turns "block
  temperature > heater_temp" into a bit, `conv_bit_float` + `scale`
  turn that bit into 0 or `fan_speed` (as a percent, matching every
  other `remora.SP.N` channel's own 0-100 convention — heater.md's PID
  `CVmax`/watermark's `scale.gain` both default to 100.0 the same
  way). No `webgui_connections.hal` entry at all: nothing should be
  able to command it by hand. An honest gap, not a crash, when the
  referenced heater has no sensor to gate on — there is nothing to
  read a temperature from.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import (
    SERVO_THREAD,
    Addf,
    HalFragment,
    PinRequest,
    PinRole,
)

#: Klipper's own default for a `[heater_fan]`'s trigger temperature.
_DEFAULT_HEATER_TEMP = 50.0
#: Klipper's own default fan_speed (0.0-1.0) once triggered.
_DEFAULT_FAN_SPEED = 1.0
#: `remora.SP.N` channels are 0-100 (percent) by this compiler's own
#: convention — matches heater.md's PID `CVmax`/watermark `scale.gain`
#: defaults (both 100.0) — not Klipper's own 0.0-1.0 `fan_speed` units.
_FAN_SPEED_TO_PERCENT = 100.0


class FanHalMapper:
    """The `fans[]` component — direct pin route (`part`) or a
    temperature-gated one (`heater`)."""

    @staticmethod
    def to_fragment(
        fan: dict[str, Any],
        heaters_by_id: dict[str, dict[str, Any]],
        sensors_by_id: dict[str, dict[str, Any]],
    ) -> HalFragment:
        pin = fan.get("pin")
        if not pin:
            return HalFragment()

        if fan.get("kind") == "heater":
            return FanHalMapper._heater_fragment(fan, pin, heaters_by_id, sensors_by_id)
        return FanHalMapper._part_fragment(fan, pin)

    # -- kind: part ---------------------------------------------------- #

    @staticmethod
    def _part_fragment(fan: dict[str, Any], pin: str) -> HalFragment:
        fan_id = str(fan["id"])
        return HalFragment(
            requests=[
                PinRequest(
                    signal=f"{fan_id}-SP",
                    role=PinRole.ANALOG_OUT,
                    pin=PinStringMapper.from_string(pin),
                    owner=fan_id,
                )
            ]
        )

    # -- kind: heater ---------------------------------------------------- #

    @staticmethod
    def _heater_fragment(
        fan: dict[str, Any],
        pin: str,
        heaters_by_id: dict[str, dict[str, Any]],
        sensors_by_id: dict[str, dict[str, Any]],
    ) -> HalFragment:
        fan_id = str(fan["id"])
        heater = heaters_by_id.get(str(fan.get("heater") or ""))
        sensor_id = heater.get("sensor") if heater else None
        if not sensor_id or sensor_id not in sensors_by_id:
            # Honest gap: nothing to gate the fan on. The referenced
            # heater declares no sensor (or the reference itself is
            # unresolved — E_UNKNOWN_HEATER is the validator's job,
            # not this mapper's, which trusts a validated payload).
            return HalFragment()

        heater_temp = fan.get("heater_temp", _DEFAULT_HEATER_TEMP)
        fan_speed = fan.get("fan_speed", _DEFAULT_FAN_SPEED)
        wcomp = f"wcomp-{fan_id}"
        conv = f"conv-{fan_id}"
        scale = f"scale-{fan_id}"

        fragment = HalFragment(
            loadrt=[
                f"loadrt wcomp names={wcomp}",
                f"loadrt conv_bit_float names={conv}",
                f"loadrt scale names={scale}",
            ],
            addf=[
                Addf(wcomp, SERVO_THREAD, order=1),
                Addf(conv, SERVO_THREAD, order=1),
                Addf(scale, SERVO_THREAD, order=1),
            ],
            setp=[
                f"setp {wcomp}.min {heater_temp}",
                f"setp {wcomp}.max 999.0",
                f"setp {scale}.gain {fan_speed * _FAN_SPEED_TO_PERCENT}",
            ],
            nets=[
                # Reads the same `<sensor>-PV` signal the heater's own
                # PID/watermark loop already reads (HeaterHalMapper) —
                # HAL allows any number of readers on one signal, so
                # this is just another consumer, never a second writer.
                f"net {sensor_id}-PV => {wcomp}.in",
                f"net {fan_id}-on <= {wcomp}.out",
                f"net {fan_id}-on => {conv}.in",
                f"net {fan_id}-on-frac <= {conv}.out",
                f"net {fan_id}-on-frac => {scale}.in",
                f"net {fan_id}-SP <= {scale}.out",
            ],
            requests=[
                PinRequest(
                    signal=f"{fan_id}-SP",
                    role=PinRole.ANALOG_OUT,
                    pin=PinStringMapper.from_string(pin),
                    owner=fan_id,
                )
            ],
        )
        return fragment


__all__ = ["FanHalMapper"]
