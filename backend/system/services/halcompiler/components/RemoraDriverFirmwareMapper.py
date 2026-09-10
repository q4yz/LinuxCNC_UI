"""TMC2209 UART tuning -> a `config.txt` firmware module, per joint.

Firmware-only, like a joint's own `Stepgen` module
(`RemoraStepperHalMapper`) — TMC2209 UART configuration never touches
`machine.hal` at all. `machine_config/example/ender3/config.txt` is
the ground truth for every key here (verified against real, working
firmware, not generic Remora documentation):

```json
{
  "Name": "driver_stepper_x",
  "Thread": "On load",
  "Type": "TMC2209",
  "Comment": "X - Joint 0 TMC driver",
  "RX pin": "PC_6",
  "RSense": 0.11,
  "Current": 800,
  "Microsteps": 16,
  "Stealth chop": "on",
  "Stall sensitivity": 0
}
```

Two things worth flagging explicitly, because they contradict generic
Remora advice that doesn't hold for this actual firmware target:

* `"Stealth chop"` is the **string** `"on"`/`"off"`, not a JSON
  boolean — matches the reference file exactly.
* Only `"RX pin"` is present — no `"TX pin"`, no `"Address"`. This
  project's Remora build shares one UART pin for TX/RX (a common
  single-wire TMC2209 wiring) and doesn't use Modbus-style addressing.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper, RemoraFirmwarePinMapper
from models.machineconfig.hal_fragment_models import FirmwareModuleRequest, HalFragment

#: `driver.sense_resistor`'s documented fallback — the value every
#: module in the reference config uses (a common TMC2209 breakout's
#: sense resistor), not yet a field a profile can override.
_DEFAULT_RSENSE = 0.11
#: `driver.run_current` is ingested in Klipper's native unit — amps
#: (`run_current: 0.8` in a `.cfg`). The reference config's `"Current"`
#: is milliamps (`800`), Remora's own convention — this is the one
#: unit conversion in this file; verify against real hardware before
#: trusting it on a machine you haven't tested.
_AMPS_TO_MILLIAMPS = 1000
_DEFAULT_RUN_CURRENT_A = 0.8
#: `"Stall sensitivity"` has no schema field yet (not ingested from
#: any `.cfg` key) — every module in the reference config uses this.
_DEFAULT_STALL_SENSITIVITY = 0


class RemoraDriverFirmwareMapper:
    """One `TMC2209` firmware module per joint whose driver has a UART pin."""

    @staticmethod
    def to_fragment(joints: list[dict[str, Any]], drivers_by_id: dict[str, dict[str, Any]]) -> HalFragment:
        fragment = HalFragment()
        for joint in joints:
            driver_id = joint.get("driver")
            if not driver_id:
                continue
            driver = drivers_by_id.get(driver_id)
            if driver is None or driver.get("type") != "TMC2209":
                continue
            uart_pin = driver.get("uart_pin")
            if not uart_pin:
                continue

            joint_id = str(joint["id"])
            parsed = PinStringMapper.from_string(uart_pin)
            run_current_a = driver.get("run_current")
            if run_current_a is None:
                run_current_a = _DEFAULT_RUN_CURRENT_A

            module = {
                "Name": f"driver_{joint_id}",
                "Thread": "On load",
                "Type": "TMC2209",
                "Comment": f"{joint_id} TMC driver",
                "RX pin": RemoraFirmwarePinMapper.to_firmware_pin(parsed.pin_id),
                "RSense": driver.get("sense_resistor", _DEFAULT_RSENSE),
                "Current": round(run_current_a * _AMPS_TO_MILLIAMPS),
                "Microsteps": driver.get("microsteps", 16),
                "Stealth chop": "on" if driver.get("stealthchop_threshold") else "off",
                "Stall sensitivity": _DEFAULT_STALL_SENSITIVITY,
            }
            fragment.firmware_modules.append(
                FirmwareModuleRequest(mcu_id=parsed.mcu_id, module=module)
            )
        return fragment


__all__ = ["RemoraDriverFirmwareMapper"]
