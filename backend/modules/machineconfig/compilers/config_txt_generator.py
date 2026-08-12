"""Generate ``config.txt`` — the Remora board JSON payload.

``config.txt`` is the file that gets flashed to the Remora board.
It contains a ``Modules`` array with different module types:

* ``Reset Pin`` — board reset pin (static)
* ``Stepgen`` — step generator with joint number, step/dir/enable pins
* ``TMC2209`` — TMC driver with RX pin, RSense, current, microsteps
* ``Digital Pin`` — digital input/output with pin, mode, data bit
* ``Temperature`` — temperature sensor with PV index, thermistor params
* ``PWM`` — PWM output with SP index, PWM pin, optional PWM max
* ``RCServo`` — RC servo with SP index, servo pin

The generator walks the parsed Klipper graph and emits modules
dynamically based on what's configured. Missing sections (e.g. no
extruder, no fans) simply result in fewer modules.

Multi-MCU note
--------------
The Klipper profile may declare any number of ``[mcu]`` /
``[mcu NAME]`` sections. The Remora board payload only models a
single flashed firmware image, so the generator resolves one MCU
to drive the file:

* exactly one MCU with ``connection`` in
  ``{"remora-spi", "remora-eth"}`` — that MCU owns the payload.
* zero or multiple remora MCUs — ``config.txt`` is not generated
  (the operator is expected to hand-edit or pick one to flash).
* pins belonging to other MCUs (rs485 / parallelport / dummy) are
  silently skipped; the Remora firmware has no way to address
  them, and downstream LinuxCNC transports handle their wiring.
* bare pins (no ``mcu:`` qualifier) are routed to the remora MCU
  when it is the only MCU declared; otherwise they are skipped
  too.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..models import Extruder, MachineConfigGraph, MCU
from ..parser import derive_fan_name, split_pin
from .axis_builder import AxisBuilder

#: Connection types that map onto a single flashed Remora board.
REMORA_CONNECTION_TYPES: frozenset[str] = frozenset(
    {"remora-spi", "remora-eth"}
)

#: Fallback board label when no ``[mcu board]`` is provided.
DEFAULT_BOARD = "BIGTREETECH OCTOPUS"

logger = logging.getLogger("backend.modules.machineconfig.compilers.config_txt_generator")


# --------------------------------------------------------------------- #
# Pin conversion                                                         #
# --------------------------------------------------------------------- #


def klipper_to_remora_pin(pin: str | None) -> str | None:
    """Convert Klipper pin format (PF13, !PF13, or ^PF13) to Remora format (PF_13).

    The Remora JSON uses underscores between port and pin number.
    Active-low markers (``!``) and pull-up markers (``^``) are
    stripped — the Remora firmware handles polarity and pull-ups
    internally.
    """
    if not pin:
        return None
    # Strip active-low and pull-up markers
    if pin.startswith("!") or pin.startswith("^"):
        pin = pin[1:]
    # Add underscore between port and pin number
    match = re.match(r"^([A-Z]+)(\d+)$", pin)
    if match:
        port, num = match.groups()
        return f"{port}_{num}"
    return pin


def remora_to_klipper_pin(pin: str | None) -> str | None:
    """Convert Remora pin format (PF_13) to Klipper format (PF13)."""
    if not pin:
        return None
    return pin.replace("_", "")


def resolve_remora_mcu(graph: MachineConfigGraph) -> tuple[MCU | None, str]:
    """Pick the single remora MCU that owns this config.txt payload.

    Returns a tuple ``(mcu_or_none, mode)`` where ``mode`` is one of:

    * ``"single"`` — exactly one MCU declared a remora connection;
      the caller may emit ``config.txt`` against that MCU.
    * ``"none"`` — no remora MCU declared; the caller should skip
      generation entirely.
    * ``"ambiguous"`` — more than one remora MCU declared; the
      caller should skip generation entirely (the brief assumes
      only one remora device and warns the operator by absence).

    Bare-pinned steppers / heaters (no ``mcu:`` qualifier) only
    implicitly belong to the remora MCU when it is the **only**
    MCU declared. This avoids silently routing pins onto a board
    the operator wasn't expecting.
    """
    remora_mcus: list[MCU] = [
        mcu
        for mcu in graph.mcus.values()
        if mcu.connection in REMORA_CONNECTION_TYPES
    ]
    if len(remora_mcus) == 0:
        return (None, "none")
    if len(remora_mcus) > 1:
        return (None, "ambiguous")
    return (remora_mcus[0], "single")


def _pin_owned_by(
    pin: str | None,
    mcu: MCU | None,
    mcu_name: str,
    graph: MachineConfigGraph,
) -> str | None:
    """Decide whether ``pin`` belongs to the remora MCU and strip the qualifier.

    Returns the bare pin (without the ``mcu:`` prefix) when the pin
    belongs to the remora MCU, ``None`` when it belongs to a
    different MCU (so the caller can skip the module), or the pin
    verbatim when it carries no qualifier and the remora MCU is the
    only declared MCU.

    The function never raises: an orphan qualifier was rejected at
    parse time; by the time the generator runs, every qualified pin
    is either matched or routes to a known non-remora MCU.
    """
    raw_mcu, raw_pin = split_pin(pin)
    if raw_pin is None:
        return None
    if raw_mcu is None:
        # No qualifier — only emit when the remora MCU is the sole
        # declared MCU; if multiple MCUs coexist we can't tell which
        # bare pin belongs where, so we skip rather than guess.
        if len(graph.mcus) <= 1:
            return raw_pin
        return None
    if raw_mcu == mcu_name:
        return raw_pin
    return None


# --------------------------------------------------------------------- #
# Module builders                                                        #
# --------------------------------------------------------------------- #


def _reset_pin_module() -> dict[str, Any]:
    """Static reset pin module."""
    return {
        "Name": "reset_pin",
        "Thread": "Servo",
        "Type": "Reset Pin",
        "Comment": "Reset pin",
        "Pin": "PC_15",
    }


def _stepgen_module(
    name: str,
    joint_number: int,
    axis_letter: str,
    step_pin: str | None,
    dir_pin: str | None,
    enable_pin: str | None,
    comment_override: str | None = None,
) -> dict[str, Any]:
    """Build a Stepgen module for one joint.

    ``name`` is the unique symbolic handle (e.g. ``stepgen_x``)
    derived from the hardware.json id; downstream HAL/Python
    controllers address the module by this name.
    ``comment_override`` lets the caller pass a pre-formatted comment
    (e.g. ``"Extruder - Joint 3 step generator"``) instead of the
    default ``<AXIS> DRIVER<n> - Joint <n> step generator``.
    """
    if comment_override is None:
        comment_override = (
            f"{axis_letter.upper()} DRIVER{joint_number} - "
            f"Joint {joint_number} step generator"
        )
    return {
        "Name": name,
        "Thread": "Base",
        "Type": "Stepgen",
        "Comment": comment_override,
        "Joint Number": joint_number,
        "Step Pin": klipper_to_remora_pin(step_pin),
        "Direction Pin": klipper_to_remora_pin(dir_pin),
        "Enable Pin": klipper_to_remora_pin(enable_pin),
    }


def _tmc2209_module(
    name: str,
    joint_number: int,
    axis_letter: str,
    uart_pin: str | None,
    run_current: float | None,
    microsteps: int | None,
    stealthchop_threshold: int | None,
) -> dict[str, Any] | None:
    """Build a TMC2209 module for one joint.

    Returns None if the TMC2209 section is not configured for this
    stepper.
    """
    if uart_pin is None:
        return None
    return {
        "Name": name,
        "Thread": "On load",
        "Type": "TMC2209",
        "Comment": f"{axis_letter.upper()} - Joint {joint_number} TMC driver",
        "RX pin": klipper_to_remora_pin(uart_pin),
        "RSense": 0.11,
        "Current": int((run_current or 0.8) * 1000),  # A → mA
        "Microsteps": microsteps or 16,
        "Stealth chop": "on" if (stealthchop_threshold or 999999) > 0 else "off",
        "Stall sensitivity": 0,
    }


def _digital_pin_module(
    name: str,
    comment: str,
    pin: str | None,
    data_bit: int,
) -> dict[str, Any] | None:
    """Build a Digital Pin module for an endstop."""
    if pin is None:
        return None
    return {
        "Name": name,
        "Thread": "Servo",
        "Type": "Digital Pin",
        "Comment": comment,
        "Pin": klipper_to_remora_pin(pin),
        "Mode": "Input",
        "Data Bit": data_bit,
    }


def _temperature_module(
    name: str,
    comment: str,
    pv_index: int,
    sensor_pin: str | None,
    sensor_type: str | None,
) -> dict[str, Any] | None:
    """Build a Temperature module for a heater."""
    if sensor_pin is None:
        return None
    # Try to derive the beta coefficient from the sensor_type string
    # (the goal uses 3950 for ``Generic 3950``; default to 3990 for
    # unknown types so the firmware still calibrates reasonably).
    beta = 3990
    if sensor_type:
        for token in sensor_type.split():
            if token.isdigit() and len(token) == 4 and token.startswith("3"):
                beta = int(token)
                break
    return {
        "Name": name,
        "Thread": "Servo",
        "Type": "Temperature",
        "Comment": comment,
        "PV[i]": pv_index,
        "Sensor": sensor_type or "Thermistor",
        "Thermistor": {
            "Pin": klipper_to_remora_pin(sensor_pin),
            "beta": beta,
            "r0": 100000,
            "t0": 25,
        },
    }


def _pwm_module(
    name: str,
    comment: str,
    sp_index: int,
    pwm_pin: str | None,
    pwm_max: int | None = None,
) -> dict[str, Any] | None:
    """Build a PWM module for a heater or fan.

    ``name`` is the symbolic handle (e.g. ``pwm_heater_bed`` or
    ``pwm_fan_part_cooling``) the HAL uses to wire the SP[i] index
    to a named signal.
    """
    if pwm_pin is None:
        return None
    module = {
        "Name": name,
        "Thread": "Servo",
        "Type": "PWM",
        "Comment": comment,
        "SP[i]": sp_index,
        "PWM Pin": klipper_to_remora_pin(pwm_pin),
    }
    if pwm_max is not None:
        module["PWM Max"] = pwm_max
    return module


def _rcservo_module(
    name: str,
    comment: str,
    sp_index: int,
    servo_pin: str | None,
) -> dict[str, Any] | None:
    """Build an RCServo module for a probe."""
    if servo_pin is None:
        return None
    return {
        "Name": name,
        "Thread": "Base",
        "Type": "RCServo",
        "Comment": comment,
        "SP[i]": sp_index,
        "Servo Pin": klipper_to_remora_pin(servo_pin),
    }


# --------------------------------------------------------------------- #
# Main generator                                                         #
# --------------------------------------------------------------------- #


def build_config_txt(graph: MachineConfigGraph, machine_name: str) -> dict[str, Any]:
    """Build the config.txt payload from a parsed Klipper graph.

    Every module carries a ``Name`` field derived from the
    :mod:`backend.modules.machineconfig.models.hardware_json_models`
    record id. The HAL/Python layer addresses modules by these
    names; the positional ``SP[i]`` / ``PV[i]`` indices stay because
    Remora firmware requires them.

    Multi-MCU handling
    ------------------
    The function resolves a single remora MCU via
    :func:`resolve_remora_mcu`. When zero or more than one remora
    MCU is declared the function returns an empty payload
    (``{"Board": "", "Modules": []}``) so the caller can skip
    writing ``config.txt``. The :func:`write_config_txt` wrapper
    deletes the file in that case so a stale board payload never
    reaches the deploy step.

    Parameters
    ----------
    graph:
        Parsed Klipper profile.
    machine_name:
        The machine name (from the source file stem).

    Returns
    -------
    dict
        The config.txt payload, ready to be serialized.
    """
    remora_mcu, remora_mode = resolve_remora_mcu(graph)
    if remora_mode != "single" or remora_mcu is None:
        logger.info(
            "config.txt: skipped (remora_mode=%s, declared=%d mcus)",
            remora_mode,
            len(graph.mcus),
        )
        return {"Board": "", "Modules": []}
    remora_name = _mcu_display_name(graph, remora_mcu)
    board = remora_mcu.board or DEFAULT_BOARD

    axes = AxisBuilder(graph).build()

    modules: list[dict[str, Any]] = []

    # 1. Reset pin (static)
    modules.append(_reset_pin_module())

    # 2. Stepgen + TMC2209 modules (per joint)
    joint_number = 0
    data_bit = 0
    pv_index = 0
    sp_index = 0

    for axis in axes:
        for joint in axis.joints:
            # Find the original stepper for this joint. Cartesian
            # joints look up by axis letter; the extruder (axis
            # letter ``A``) is the unique ``Extruder`` record on the
            # heaters dict and carries its own stepper fields.
            stepper = graph.steppers.get(axis.letter.lower())
            extruder_record = None
            if stepper is None:
                for name, s in graph.steppers.items():
                    if s.axis.upper() == axis.letter:
                        stepper = s
                        break
            if stepper is None and axis.letter.upper() == "A":
                # The extruder lives under heaters — pull the first
                # ``Extruder`` instance as the canonical stepper source.
                for h in graph.heaters.values():
                    if isinstance(h, Extruder):
                        extruder_record = h
                        break

            # Joint 0..N-1 share the canonical Klipper stepper; the
            # extruder (Joint N) gets its own stepgen module from the
            # extruder record.
            raw_step_pin = stepper.step_pin if stepper else None
            raw_dir_pin = stepper.dir_pin if stepper else None
            raw_enable_pin = stepper.enable_pin if stepper else None
            if extruder_record is not None:
                raw_step_pin = extruder_record.step_pin
                raw_dir_pin = extruder_record.dir_pin
                raw_enable_pin = extruder_record.enable_pin

            # Route every pin through the multi-MCU selector before
            # any module is constructed. A pin routed to a different
            # MCU becomes ``None`` here and the corresponding modules
            # are silently dropped for that joint.
            step_pin = _pin_owned_by(raw_step_pin, remora_mcu, remora_name, graph) if raw_step_pin else None
            dir_pin = _pin_owned_by(raw_dir_pin, remora_mcu, remora_name, graph) if raw_dir_pin else None
            enable_pin = _pin_owned_by(raw_enable_pin, remora_mcu, remora_name, graph) if raw_enable_pin else None

            # Decide whether the joint actually belongs to the remora
            # board. A joint is emitted when:
            #
            # * at least one of its explicit pins routes to the remora
            #   MCU, OR
            # * the stepper had no explicit pins at all (legacy behaviour:
            #   render positional defaults and let downstream the operator
            #   hand-edit).
            #
            # A joint whose ALL explicit pins route to a non-remora
            # MCU is silently dropped — the right move when the profile
            # declares e.g. ``step_pin: rs485_com:PA1`` for a stepper
            # that has no remora-side pins to back it up.
            remora_pin_count = sum(
                1 for p in (step_pin, dir_pin, enable_pin) if p is not None
            )
            had_explicit_pins = any(
                p is not None
                for p in (raw_step_pin, raw_dir_pin, raw_enable_pin)
            )
            if had_explicit_pins and remora_pin_count == 0:
                joint_number += 1
                continue
            has_record = stepper is not None or extruder_record is not None
            if not has_record:
                joint_number += 1
                continue

            # The stepgen ``Name`` matches the hardware.json stepper id
            # (``stepper_x`` for Cartesian joints, ``extruder`` for
            # the extruder joint).
            if extruder_record is not None:
                stepgen_name = "extruder"
                axis_label = "Extruder"
            else:
                stepgen_name = stepper.section_name
                axis_label = axis.letter.upper()
            # Stepgen comment: ``<axis> - Joint <n> step generator``
            # (the goal uses this shorter form; the DRIVER<n> prefix
            # was historical Klipper output).
            stepgen_comment = (
                f"{axis_label} - Joint {joint_number} step generator"
            )
            modules.append(
                _stepgen_module(
                    stepgen_name,
                    joint_number,
                    axis.letter,
                    step_pin,
                    dir_pin,
                    enable_pin,
                    comment_override=stepgen_comment,
                )
            )

            # TMC2209 module (if configured). ``Name`` follows the
            # ``driver_<stepper_id>`` convention used by
            # ``hardware.json`` so HAL can wire Remora signals by
            # the same handle. The TMC2209 -> stepper link is
            # keyed by the Klipper ``[tmc2209 stepper_X]`` section
            # header, which matches the stepper ``section_name``.
            tmc_section = stepper.section_name if stepper else None
            tmc_record = (
                graph.tmc2209s.get(tmc_section) if tmc_section else None
            )
            tmc_uart_raw = getattr(tmc_record, "uart_pin", None) if tmc_record else None
            tmc_uart = (
                _pin_owned_by(tmc_uart_raw, remora_mcu, remora_name, graph)
                if tmc_uart_raw
                else None
            )
            if tmc_record and tmc_uart is not None:
                modules.append(
                    _tmc2209_module(
                        f"driver_{tmc_section}",
                        joint_number,
                        axis.letter,
                        tmc_uart,
                        getattr(tmc_record, "run_current", None),
                        getattr(stepper, "microsteps", None) if stepper else None,
                        getattr(tmc_record, "stealthchop_threshold", None),
                    )
                )

            # Digital Pin module for endstop — ``Name`` matches
            # the hardware.json endstop record id (``endstop_X_MIN``
            # / ``homing_X_MIN`` etc.) so the HAL can reference the
            # exact switch by handle. The endstop switch name
            # (e.g. ``X_MIN``) is derived from the Klipper
            # ``endstop_switch`` section; we fall back to
            # ``<AXIS>_MIN`` when no explicit section is declared.
            raw_endstop_pin = stepper.endstop_pin if stepper else None
            endstop_pin = (
                _pin_owned_by(raw_endstop_pin, remora_mcu, remora_name, graph)
                if raw_endstop_pin
                else None
            )
            if endstop_pin is not None:
                endstop_switch_name = (
                    next(iter(graph.endstop_switches.keys()), None)
                    if graph.endstop_switches
                    else None
                )
                switch_suffix = (
                    endstop_switch_name
                    if endstop_switch_name
                    else f"{axis.letter.upper()}_MIN"
                )
                endstop_comment = (
                    f"{axis.letter.upper()} endstop ({raw_endstop_pin})"
                )
                dp_name = f"endstop_{switch_suffix}"
                dp = _digital_pin_module(
                    dp_name,
                    endstop_comment,
                    endstop_pin,
                    data_bit,
                )
                if dp:
                    modules.append(dp)
                    data_bit += 1

            joint_number += 1

    # 3. Temperature + PWM modules for heaters
    # Walk the graph's heaters dict in canonical name order. Extruders
    # are indexed as "Ext 0", "Ext 1", ... in the order they appear
    # in the source file (so the first extruder is always Ext 0).
    # Non-extruder heaters keep their canonical name as the Remora
    # module comment.
    sorted_heaters = sorted(graph.heaters.values(), key=lambda h: h.name)

    extruder_index = 0
    for heater in sorted_heaters:
        if isinstance(heater, Extruder):
            label = "Extruder"
            comment = f"{label} temperature sensor"
            pwm_comment = f"{label} heater PWM"
            extruder_index += 1
        else:
            # ``[heater_bed]`` -> ``Heated Bed`` for the sensor
            # comment; the PWM comment uses ``Bed`` (matches the
            # goal's hand-written convention where ``Bed heater PWM``
            # is shorter than ``Heated Bed heater PWM``).
            label = heater.name
            if label.startswith("heater_"):
                rest = label[len("heater_"):]
                if rest == "bed":
                    sensor_label = "Heated Bed"
                    pwm_label = "Bed"
                else:
                    sensor_label = rest.replace("_", " ").title()
                    pwm_label = sensor_label
            else:
                sensor_label = label.replace("_", " ").title()
                pwm_label = sensor_label
            comment = f"{sensor_label} temperature sensor"
            pwm_comment = f"{pwm_label} heater PWM"

        # ``Name`` derives from the canonical hardware.json id
        # (``heater_bed`` -> ``temp_bed`` + ``pwm_heater_bed``).
        temp_name = (
            f"temp_{heater.name.removeprefix('heater_')}"
            if heater.name.startswith("heater_")
            else f"temp_{heater.name}"
        )
        pwm_name = f"pwm_{heater.name}"

        sensor_pin = (
            _pin_owned_by(heater.sensor_pin, remora_mcu, remora_name, graph)
            if heater.sensor_pin
            else None
        )
        heater_pin = (
            _pin_owned_by(heater.heater_pin, remora_mcu, remora_name, graph)
            if heater.heater_pin
            else None
        )

        temp = _temperature_module(
            temp_name,
            comment,
            pv_index,
            sensor_pin,
            heater.sensor_type,
        )
        if temp:
            modules.append(temp)
            pv_index += 1

        pwm = _pwm_module(
            pwm_name,
            pwm_comment,
            sp_index,
            heater_pin,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    # 4. Standalone ``[fan]`` / ``[fan_generic]`` sections. These
    # follow the heater PWMs and reuse the same SP[i] counter so the
    # indexing stays contiguous. ``Name`` is the canonical fan id
    # (``fan_part_cooling``) — the HAL binds the matching symbolic
    # signal to the same SP[i] index.
    sorted_fans = sorted(graph.fans.values(), key=lambda f: f.name)
    for fan in sorted_fans:
        fan_pin = (
            _pin_owned_by(fan.pin, remora_mcu, remora_name, graph)
            if fan.pin
            else None
        )
        if fan_pin is None:
            continue
        if fan.max_power is not None:
            # 0.0–1.0 → 0–255. Round so the integer is stable across
            # float formatting.
            pwm_max = max(0, min(255, round(fan.max_power * 255)))
        else:
            # Default 50% duty-cycle cap when the user didn't pin
            # ``max_power`` on the Klipper side. The goal uses 128
            # for the part-cooling fan.
            pwm_max = 128
        pwm = _pwm_module(
            f"pwm_{fan.name}",
            f"{fan.name.replace('_', ' ')} PWM",
            sp_index,
            fan_pin,
            pwm_max=pwm_max,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    # 5. Spindle PWM (if configured)
    if graph.spindle_analog and graph.spindle_analog.pwm_pin:
        spindle_pwm_pin = _pin_owned_by(
            graph.spindle_analog.pwm_pin,
            remora_mcu,
            remora_name,
            graph,
        )
        if spindle_pwm_pin is not None:
            pwm = _pwm_module(
                "spindle_pwm",
                "Spindle PWM",
                sp_index,
                spindle_pwm_pin,
            )
            if pwm:
                modules.append(pwm)
                sp_index += 1

    # 6. RCServo for probe (if configured)
    # TODO: add probe support to parser when needed

    payload = {
        "Board": board,
        "Modules": modules,
    }

    logger.info(
        "config.txt: %d modules (%d stepgen, %d tmc2209, %d digital pin, %d temperature, %d pwm) for board=%s",
        len(modules),
        sum(1 for m in modules if m["Type"] == "Stepgen"),
        sum(1 for m in modules if m["Type"] == "TMC2209"),
        sum(1 for m in modules if m["Type"] == "Digital Pin"),
        sum(1 for m in modules if m["Type"] == "Temperature"),
        sum(1 for m in modules if m["Type"] == "PWM"),
        board,
    )
    return payload


def _mcu_display_name(graph: MachineConfigGraph, mcu: MCU) -> str:
    """Return the section header key for ``mcu`` inside ``graph.mcus``.

    Two MCUs can hold equal dataclasses; the canonical lookup
    matches by ``id`` to avoid picking the wrong name when two
    transports share the same field values. Falls back to an empty
    string when no entry matches (shouldn't happen in practice —
    the caller is the one that just resolved the MCU).
    """
    for name, stored in graph.mcus.items():
        if stored is mcu:
            return name
    return ""


def write_config_txt(
    path: Path,
    graph: MachineConfigGraph,
    machine_name: str,
) -> None:
    """Write config.txt to disk.

    When the resolved graph has zero or multiple remora MCUs the
    payload is empty (``:data:`REMORA_CONNECTION_TYPES` yields no
    unique owner); the function deletes any existing ``config.txt``
    at ``path`` so a stale Remora payload never reaches the deploy
    step. Without the cleanup a previous compile run would silently
    ship a board file that belongs to a machine the operator no
    longer runs.
    """
    payload = build_config_txt(graph, machine_name)
    if not payload.get("Modules"):
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "DEFAULT_BOARD",
    "REMORA_CONNECTION_TYPES",
    "build_config_txt",
    "klipper_to_remora_pin",
    "remora_to_klipper_pin",
    "resolve_remora_mcu",
    "write_config_txt",
]