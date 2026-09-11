"""One heater/extruder tool's setpoint/reading/fan -> `webgui_connections.hal`.

The other half of `HeaterHalMapper`'s own deferred UI-bindings pass —
see `SpindleWebguiMapper` for why this is a separate file rather than
more `machine.hal` content. Pin names come straight from
`common/mappers/tools/HeaterMapper.py::from_dict_to_HeaterPins`:

* `webgui.target-temperature<suffix>`, `suffix = id.replace("heater", "")`
  — a **write**: the operator's target reaches `<id>-SP`, the signal
  `HeaterHalMapper`'s PID/watermark loop already reads as its `.SP`/
  `.in1` input but that nothing writes today (a real gap — the loop
  has no setpoint source at all without this line).
* `webgui.<sensor_id>` — a **read**: the sensor's `-PV` signal
  (already written by the MCU router) gains webgui as a second reader,
  same pin a heater and its sensor entity always share (`heater.md`
  § 2 — "one thermistor, one HAL pin, addressed the same way whether
  or not a heater claims it").

A heater's referenced fan (``tools[].fan``) does NOT get its binding
here — every ``kind: "part"`` fan (a real declared one, or a heater's
own auto-derived placeholder) is uniform now, so `FanWebguiMapper`
covers all of them the same way regardless of whether a heater
happens to reference one (`.agent/component/fan.md`).
"""

from __future__ import annotations

from typing import Any


class HeaterWebguiMapper:
    """`net` lines binding one heater's setpoint/reading onto `webgui.*`."""

    @staticmethod
    def to_lines(heater: dict[str, Any]) -> list[str]:
        heater_id = str(heater["id"])
        suffix = heater_id.replace("heater", "", 1)
        lines = [f"# Heater: {heater_id}"]

        lines.append(f"net {heater_id}-SP <= webgui.target-temperature{suffix}")

        sensor_id = heater.get("sensor")
        if sensor_id:
            lines.append(f"net {sensor_id}-PV => webgui.{sensor_id}")

        lines.append("")
        return lines


__all__ = ["HeaterWebguiMapper"]
