"""Joint + axis -> :class:`HalFragment`, class B (`.agent/component/mcu_spi_remora.md`).

Remora owns the motion: the board runs its own position loop off
`remora.joint.N.pos-cmd`, so there is no `stepgen` to size and no
`steplen`/`stepspace`/`dirhold`/`dirsetup` timing to set — that is the
entire reason this is a separate mapper from :class:`StepperHalMapper`
rather than a branch inside it (README § 2, "a joint's step_pin/dir_pin
mean structurally different things depending on class").

**Joint pins never become HAL nets.** `step_pin`/`dir_pin`/`enable_pin`
are firmware values — they go into the board's `config.txt` sidecar as
one `Stepgen` module per joint (`mcu_spi_remora.md` § 4), never a
`net`. This mapper reports them as :class:`FirmwareModuleRequest`
entries; the assembler aggregates them per MCU into the actual file.
Module shape verified against the real, working
`machine_config/example/ender3/config.txt` — `"Type": "Stepgen"`, a
`"Name"` field, and pins spelled with Remora's underscore convention
(`"PF_11"`, not Klipper's `"PF11"`) all come from that file, not from
generic Remora documentation.

The `remora.joint.N.enable` net, unlike class A's optional enable pin,
is unconditional — every joint in the reference config
(`machine_config/example/ender3/ender3.hal`) wires it, because the
board always owns an enable line for the module it just loaded.

Endstop wiring mirrors :class:`StepperHalMapper`'s axis-scoped,
endstop-id-named signal (so two axes sharing one switch collapse onto
one writer) but additionally targets `neg-lim-sw-in` — confirmed
against `3Dprinter.hal`'s `net X-stop remora.input.00 => joint.0.home
-sw-in joint.0.neg-lim-sw-in`, genuinely different wiring from the
parport reference machine, which wires `home-sw-in` alone.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper, RemoraFirmwarePinMapper
from models.machineconfig.hal_fragment_models import (
    FirmwareModuleRequest,
    HalFragment,
    PinRequest,
    PinRole,
)


class RemoraStepperHalMapper:
    """Per-axis HAL: position loop, home switch. No stepgen, no step/dir nets."""

    @staticmethod
    def to_fragment(
        axis: dict[str, Any],
        joints: list[dict[str, Any]],
        endstop: dict[str, Any] | None,
    ) -> HalFragment:
        fragment = HalFragment()
        endstop_signal = f"{endstop['id']}-sw" if endstop else None

        for joint in joints:
            RemoraStepperHalMapper._joint(fragment, joint)
            if endstop_signal is not None:
                n = joint["joint_number"]
                fragment.nets.append(
                    f"net {endstop_signal} => joint.{n}.home-sw-in joint.{n}.neg-lim-sw-in"
                )

        if endstop is not None:
            fragment.requests.append(
                PinRequest(
                    signal=endstop_signal,
                    role=PinRole.ENDSTOP,
                    pin=PinStringMapper.from_string(endstop["pin"]),
                    owner=str(endstop["id"]),
                )
            )

        return fragment

    @staticmethod
    def _joint(fragment: HalFragment, joint: dict[str, Any]) -> None:
        n = joint["joint_number"]

        fragment.setp.extend(
            [
                f"setp remora.joint.{n}.scale [JOINT_{n}]SCALE",
                f"setp remora.joint.{n}.maxaccel [JOINT_{n}]STEPGEN_MAXACCEL",
            ]
        )
        # Optional position-loop tuning — real, working values from
        # the reference config, not invented
        # (ender3.hal: `deadband` on joint 2, `pgain` on joint 3).
        # `deadband` there is a literal; `pgain` is an ini-var
        # reference, matching every gain elsewhere in this compiler
        # (heater PID) being re-tunable without regenerating the HAL.
        if joint.get("deadband") is not None:
            fragment.setp.append(f"setp remora.joint.{n}.deadband {joint['deadband']}")
        if joint.get("pgain") is not None:
            fragment.setp.append(f"setp remora.joint.{n}.pgain [JOINT_{n}]PGAIN")
        fragment.nets.extend(
            [
                f"net j{n}pos-cmd joint.{n}.motor-pos-cmd => remora.joint.{n}.pos-cmd",
                f"net j{n}pos-fb remora.joint.{n}.pos-fb => joint.{n}.motor-pos-fb",
                f"net j{n}enable joint.{n}.amp-enable-out => remora.joint.{n}.enable",
            ]
        )

        step_pin = joint.get("step_pin")
        if not step_pin:
            return
        joint_id = str(joint["id"])
        parsed = PinStringMapper.from_string(step_pin)
        module: dict[str, Any] = {
            "Name": joint_id,
            "Thread": "Base",
            # "Stepgen", not "Stepper" — the real reference config
            # (machine_config/example/ender3/config.txt) is the ground
            # truth for every key/value in this module, verified
            # against actual working firmware, not generic examples.
            "Type": "Stepgen",
            "Comment": f"{joint_id} step generator",
            "Joint Number": n,
            "Step Pin": RemoraFirmwarePinMapper.to_firmware_pin(parsed.pin_id),
        }
        for field, key in (("dir_pin", "Direction Pin"), ("enable_pin", "Enable Pin")):
            raw = joint.get(field)
            if not raw:
                continue
            pin = PinStringMapper.from_string(raw)
            firmware_pin = RemoraFirmwarePinMapper.to_firmware_pin(pin.pin_id)
            module[key] = f"{'!' if pin.invert else ''}{firmware_pin}"
        fragment.firmware_modules.append(FirmwareModuleRequest(mcu_id=parsed.mcu_id, module=module))


__all__ = ["RemoraStepperHalMapper"]
