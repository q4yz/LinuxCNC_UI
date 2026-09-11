"""One heater/heated_bed/extruder tool's thermal half -> :class:`HalFragment`
(`.agent/component/heater.md` § 3, `exturder.md` § 3's "thermal half").

Covers both `[extruder]` and `[heater_bed]`-shaped tools identically —
`exturder.md` says as much ("the thermal half is heater.md verbatim
and is not repeated here"). The extruder's *motion* half (the joint
and its axis) is already handled by `StepperHalMapper`/
`RemoraStepperHalMapper`; this mapper only ever emits the PID/watermark
loop, the sensor reading, and (if the tool references one) a passthrough
export for its cooling fan — never step/dir/enable.

Grounded in `machine_config/example/ender3/3Dprinter.hal`'s real bed
and extruder-0 `PIDcontroller` sections, including the `.auto` wiring
off `remora-status` — the link-health watchdog that holds the loop in
manual until the board answers, so a dead MCU can't leave the heater
output latched. That signal only exists because `RemoraRouterMapper`
emits it unconditionally; heater support is Remora-only for now (the
same class-A gap `heater.md` § 4 already documents — no ADC on a bare
parallel port, `E_NO_ANALOG_INPUT`).
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper, heater_ini_section
from models.machineconfig.hal_fragment_models import (
    SERVO_THREAD,
    Addf,
    HalFragment,
    PinRequest,
    PinRole,
)

#: `comp` (watermark) hysteresis default — `heater.md` § 1's documented
#: default. Not yet a `Tool` field, so every watermark heater gets it
#: for now.
_DEFAULT_HYSTERESIS = 2.0
#: Duty-cycle ceiling the bit->float `scale` stage maps "on" to —
#: `heater.md` § 1's documented default, matching the PID branch's own
#: `CVmax` convention (0-100 %, not 0.0-1.0) so both control modes
#: feed `remora.SP.N` the same units.
_DEFAULT_MAX_POWER = 100.0


class HeaterHalMapper:
    """PID or watermark control loop, sensor reading, optional fan export."""

    @staticmethod
    def to_fragment(
        heater: dict[str, Any],
        sensor: dict[str, Any] | None,
        fan: dict[str, Any] | None,
    ) -> HalFragment:
        fragment = HalFragment()
        heater_id = str(heater["id"])
        sensor_id = str(sensor["id"]) if sensor else None

        control = (heater.get("control") or "pid").strip().lower()
        if control == "watermark":
            HeaterHalMapper._watermark_loop(fragment, heater, heater_id, sensor_id)
        else:
            HeaterHalMapper._pid_loop(fragment, heater_id, sensor_id)

        HeaterHalMapper._request(
            fragment, heater, "heater_pin", f"{heater_id}-heater-SP", PinRole.ANALOG_OUT, heater_id
        )
        if sensor is not None:
            HeaterHalMapper._request(
                fragment,
                sensor,
                "pin",
                f"{sensor_id}-PV",
                PinRole.ANALOG_IN,
                sensor_id,
                sensor_type=sensor.get("type"),
            )

        fan_ref = heater.get("fan")
        if fan_ref and fan is not None:
            # Passthrough only — matches the reference machine, which
            # wires a referenced fan as a plain SP channel with no
            # temperature gating (`ext0-cooling-SP => remora.SP.2`,
            # nothing more). `fan.md`'s richer `kind: heater` wcomp
            # gating needs schema fields `fans[]` doesn't carry yet
            # (that file's own § 2 admission) — future work, not a
            # regression from what ender3 actually does today.
            HeaterHalMapper._request(
                fragment, fan, "pin", f"{fan_ref}-SP", PinRole.ANALOG_OUT, heater_id
            )

        return fragment

    # -- control loops ----------------------------------------------------- #

    @staticmethod
    def _pid_loop(fragment: HalFragment, heater_id: str, sensor_id: str | None) -> None:
        section = heater_ini_section(heater_id)
        pid = f"PID-{heater_id}"

        fragment.loadrt.append(f"loadrt PIDcontroller names={pid}")
        fragment.addf.append(Addf(f"{pid}.compute", SERVO_THREAD, order=1))

        fragment.nets.append(f"net remora-status => {pid}.auto")
        fragment.nets.append(f"net {heater_id}-SP => {pid}.SP")
        if sensor_id is not None:
            fragment.nets.append(f"net {sensor_id}-PV => {pid}.PV")
        fragment.nets.append(f"net {heater_id}-heater-SP <= {pid}.CV")

        fragment.setp.extend(
            [
                f"setp {pid}.pOnM [{section}]PID_PONM",
                f"setp {pid}.direction [{section}]PID_DIR",
                f"setp {pid}.KP [{section}]PID_KP",
                f"setp {pid}.KI [{section}]PID_KI",
                f"setp {pid}.KD [{section}]PID_KD",
                f"setp {pid}.SPmin [{section}]PID_SPMIN",
                f"setp {pid}.SPmax [{section}]PID_SPMAX",
                f"setp {pid}.CVmin [{section}]PID_CVMIN",
                f"setp {pid}.CVmax [{section}]PID_CVMAX",
            ]
        )

    @staticmethod
    def _watermark_loop(
        fragment: HalFragment, heater: dict[str, Any], heater_id: str, sensor_id: str | None
    ) -> None:
        """`comp` alone is not enough here: its `.out` is a HAL **bit**
        (on/off), but `<id>-heater-SP` is routed straight into
        `remora.SP.N` — a **float** duty-cycle channel, the same one
        the PID loop's float `.CV` output feeds. Linking a bit pin to
        a float pin is a HAL type error at load, not a runtime one —
        caught before it ever reached real hardware, but a real bug in
        what was emitted. Fixed with `conv_bit_float` (the exact
        bit->float idiom `fan.md`'s own `kind: heater` gating already
        uses) then a `scale` stage so "on" reads as `max_power` percent
        rather than `1.0`, matching the PID branch's CVmax convention.
        """
        comp = f"comp-{heater_id}"
        conv = f"conv-{heater_id}"
        duty = f"duty-{heater_id}"
        hysteresis = heater.get("hysteresis", _DEFAULT_HYSTERESIS)
        max_power = heater.get("max_power", _DEFAULT_MAX_POWER)

        fragment.loadrt.extend([f"loadrt comp names={comp}", f"loadrt conv_bit_float names={conv}", f"loadrt scale names={duty}"])
        fragment.addf.extend(
            [
                Addf(comp, SERVO_THREAD, order=1),
                Addf(conv, SERVO_THREAD, order=1),
                Addf(duty, SERVO_THREAD, order=1),
            ]
        )
        fragment.setp.extend([f"setp {comp}.hyst {hysteresis}", f"setp {duty}.gain {max_power}"])

        if sensor_id is not None:
            fragment.nets.append(f"net {sensor_id}-PV => {comp}.in0")
        fragment.nets.append(f"net {heater_id}-SP => {comp}.in1")
        fragment.nets.append(f"net {heater_id}-heat-bit {comp}.out => {conv}.in")
        fragment.nets.append(f"net {heater_id}-heat-frac {conv}.out => {duty}.in")
        fragment.nets.append(f"net {heater_id}-heater-SP <= {duty}.out")

    # -- shared -------------------------------------------------------------- #

    @staticmethod
    def _request(
        fragment: HalFragment,
        record: dict[str, Any],
        field: str,
        signal: str,
        role: PinRole,
        owner: str,
        sensor_type: str | None = None,
    ) -> None:
        raw = record.get(field)
        if not raw:
            return
        fragment.requests.append(
            PinRequest(
                signal=signal,
                role=role,
                pin=PinStringMapper.from_string(raw),
                owner=owner,
                sensor_type=sensor_type,
            )
        )


__all__ = ["HeaterHalMapper"]
