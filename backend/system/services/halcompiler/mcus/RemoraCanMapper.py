"""Remora CAN expansion: nodes behind a ``remora-spi`` hub.

Remora-m8p ``CAN_PROTOCOL.md``: LinuxCNC only sees the hub. A node's
modules live in the hub's ``config.txt`` (``"CAN" -> "Nodes"``), their
``Joint Number``\\ s are the hub's ``remora.joint.N``, and their
``Data Bit``\\ s are the hub's LinuxCNC bits (``remora.input.NN``
/ ``remora.output.NN``) — so a node's pin requests are routed through
the hub's :class:`RemoraRouterMapper` (one shared bit-space) and only
the finished modules move into the node's entry here.

``"Status Bit"`` is a LinuxCNC input that is 1 only while every
mandatory node runs; the hub's base fragment puts its inverse into the
E-stop latch. It defaults to bit 15 once the hub has a mandatory node.
"""

from __future__ import annotations

from typing import Mapping

from models.machineconfig.HardwareJsonModels import Fan, McuInfo, Tool

DEFAULT_BITRATE = 1_000_000
#: Node PWM periods (the node makes the PWM itself, 0 ... 100 % from
#: ``remora.SP.N``): a slow one for a heater's thermal mass, 100 Hz
#: (0.25 % steps, the firmware default) for a fan.
HEATER_PERIOD_US = 100_000
FAN_PERIOD_US = 10_000
#: Every pin's fallback while LinuxCNC / the node is gone — never configurable.
SAFE_LEVEL = "Low"
DEFAULT_STATUS_BIT = 15
MAX_NODE = 15


class RemoraCanMapper:
    @staticmethod
    # Topology on plain values: MachineValidator calls these with the raw
    # payload's dicts, the compiler with typed McuInfo records.

    @staticmethod
    def is_node(connection: str | None) -> bool:
        return connection == "remora-can"

    @staticmethod
    def hub_id(can_hub: str | None, connections: Mapping[str, str | None]) -> str | None:
        """A node's hub: ``can_hub``, or the machine's only ``remora-spi``
        MCU; ``None`` if neither resolves. ``connections``: MCU id ->
        ``connection``."""
        if can_hub:
            return can_hub if connections.get(can_hub) == "remora-spi" else None
        hubs = [mcu_id for mcu_id, connection in connections.items() if connection == "remora-spi"]
        return hubs[0] if len(hubs) == 1 else None

    @staticmethod
    def connections(mcus_by_id: Mapping[str, McuInfo]) -> dict[str, str | None]:
        return {mcu_id: mcu.connection for mcu_id, mcu in mcus_by_id.items()}

    @staticmethod
    def hub_of(node: McuInfo, mcus_by_id: Mapping[str, McuInfo]) -> str | None:
        return RemoraCanMapper.hub_id(node.can_hub, RemoraCanMapper.connections(mcus_by_id))

    @staticmethod
    def nodes_of(hub_id: str, mcus_by_id: Mapping[str, McuInfo]) -> list[McuInfo]:
        """The hub's nodes, in declaration order."""
        return [
            mcu for mcu in mcus_by_id.values()
            if RemoraCanMapper.is_node(mcu.connection) and RemoraCanMapper.hub_of(mcu, mcus_by_id) == hub_id
        ]

    @staticmethod
    def node_numbers(nodes: list[McuInfo]) -> dict[str, int]:
        """Declared ``can_node`` numbers, the rest next free 1 ... 15 in order."""
        taken = {n.can_node for n in nodes if n.can_node}
        numbers: dict[str, int] = {}
        free = (n for n in range(1, MAX_NODE + 1) if n not in taken)
        for node in nodes:
            numbers[node.id] = node.can_node if node.can_node else next(free, 0)
        return numbers

    @staticmethod
    def status_bit(hub: McuInfo, nodes: list[McuInfo]) -> int | None:
        """Declared ``can_status_bit``, else 15 once a node is mandatory (the default)."""
        if hub.can_status_bit is not None:
            return hub.can_status_bit
        if any(node.mandatory is not False for node in nodes):
            return DEFAULT_STATUS_BIT
        return None

    @staticmethod
    def node_module(module: dict[str, object]) -> dict[str, object]:
        """A module the hub router built, in the node's dialect.

        Pin and ``"Modifier"`` pass through as the hub router wrote them
        (no ``^`` prefix on either side), and an input gets ``"Lost State":
        "Low"``, what LinuxCNC reads while the node is lost: always Low,
        like every output's Safe State (the machine must be safe at Low).
        Every module keeps its hub numbers (``Joint Number``, ``PV[i]``,
        ``Data Bit``) and its keys, but none has a ``"Name"`` /
        ``"Thread"``: the node schedules them itself. A Stepgen's name
        becomes its comment.
        """
        out = dict(module)
        name = out.pop("Name", None)
        out.pop("Thread", None)
        if out.get("Type") == "Stepgen" and name:
            out["Comment"] = str(name)
        if out.get("Mode") == "Input":
            out["Lost State"] = SAFE_LEVEL
        return out

    @staticmethod
    def pwm_settings(
        module: dict[str, object],
        tools_by_id: Mapping[str, Tool],
        fans_by_id: Mapping[str, Fan],
    ) -> dict[str, object]:
        """A node ``"PWM"`` module with its ``"Period us"`` and its
        ``"Safe Duty"`` — the duty after boot, while LinuxCNC is gone and
        when the node loses the hub: 0 for a heater and a part fan, 100
        for a hotend fan (``kind: heater``), which must keep cooling.
        Any other module passes through unchanged.
        """
        if module.get("Type") != "PWM":
            return module
        owner = str(module.get("Comment", ""))
        if owner in tools_by_id:
            period, safe_duty = HEATER_PERIOD_US, 0
        else:
            fan = fans_by_id.get(owner)
            hotend_fan = fan is not None and fan.kind == "heater"
            period, safe_duty = FAN_PERIOD_US, 100 if hotend_fan else 0
        # an [output_pin]'s own cycle_time is already on the module
        return {**module, "Period us": module.get("Period us", period), "Safe Duty": safe_duty}

    @staticmethod
    def can_block(
        hub: McuInfo,
        nodes: list[McuInfo],
        modules_by_node: dict[str, list[dict[str, object]]],
    ) -> dict[str, object]:
        """The hub ``config.txt``'s top-level ``"CAN"`` object."""
        numbers = RemoraCanMapper.node_numbers(nodes)
        block: dict[str, object] = {"Bitrate": hub.can_bitrate or DEFAULT_BITRATE}
        status_bit = RemoraCanMapper.status_bit(hub, nodes)
        if status_bit is not None:
            block["Status Bit"] = status_bit
        block["Nodes"] = [
            {
                "UUID": node.canbus_uuid,
                "Node": numbers[node.id],
                "Comment": node.id,
                "Mandatory": "False" if node.mandatory is False else "True",
                "Modules": [RemoraCanMapper.node_module(module) for module in modules_by_node.get(node.id, [])],
            }
            for node in nodes
        ]
        return block


__all__ = ["DEFAULT_BITRATE", "DEFAULT_STATUS_BIT", "RemoraCanMapper"]
