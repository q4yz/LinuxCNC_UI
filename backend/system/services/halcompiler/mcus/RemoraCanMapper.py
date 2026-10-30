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

from typing import Any

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
    def is_node(mcu: dict[str, Any] | None) -> bool:
        return mcu is not None and mcu.get("connection") == "remora-can"

    @staticmethod
    def hub_id(node: dict[str, Any], mcus_by_id: dict[str, dict[str, Any]]) -> str | None:
        """``can_hub``, or the machine's only ``remora-spi`` MCU; ``None`` if neither resolves."""
        declared = node.get("can_hub")
        if declared:
            hub = mcus_by_id.get(str(declared))
            return str(declared) if hub and hub.get("connection") == "remora-spi" else None
        hubs = [mcu_id for mcu_id, mcu in mcus_by_id.items() if mcu.get("connection") == "remora-spi"]
        return hubs[0] if len(hubs) == 1 else None

    @staticmethod
    def nodes_of(hub_id: str, mcus_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """The hub's nodes, in declaration order."""
        return [
            mcu for mcu in mcus_by_id.values()
            if RemoraCanMapper.is_node(mcu) and RemoraCanMapper.hub_id(mcu, mcus_by_id) == hub_id
        ]

    @staticmethod
    def node_numbers(nodes: list[dict[str, Any]]) -> dict[str, int]:
        """Declared ``can_node`` numbers, the rest next free 1 ... 15 in order."""
        taken = {int(n["can_node"]) for n in nodes if n.get("can_node")}
        numbers: dict[str, int] = {}
        free = (n for n in range(1, MAX_NODE + 1) if n not in taken)
        for node in nodes:
            numbers[str(node["id"])] = int(node["can_node"]) if node.get("can_node") else next(free, 0)
        return numbers

    @staticmethod
    def status_bit(hub: dict[str, Any], nodes: list[dict[str, Any]]) -> int | None:
        """Declared ``can_status_bit``, else 15 once a node is mandatory (the default)."""
        if hub.get("can_status_bit") is not None:
            return int(hub["can_status_bit"])
        if any(node.get("mandatory") is not False for node in nodes):
            return DEFAULT_STATUS_BIT
        return None

    @staticmethod
    def node_module(module: dict[str, object], node: dict[str, Any]) -> dict[str, object]:
        """A module the hub router built, in the node's dialect.

        A node's pin string has no ``^`` modifier prefix — pull-ups are
        the ``"Modifier"`` key there — and an input gets ``"Lost State":
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
        pin = str(out.get("Pin", ""))
        if pin.startswith("^"):
            out["Pin"] = pin[1:]
            out["Modifier"] = "Pull Up"
        if out.get("Mode") == "Input":
            out["Lost State"] = SAFE_LEVEL
        return out

    @staticmethod
    def pwm_settings(
        module: dict[str, object],
        tools_by_id: dict[str, dict[str, Any]],
        fans_by_id: dict[str, dict[str, Any]],
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
            hotend_fan = (fans_by_id.get(owner) or {}).get("kind") == "heater"
            period, safe_duty = FAN_PERIOD_US, 100 if hotend_fan else 0
        return {**module, "Period us": period, "Safe Duty": safe_duty}

    @staticmethod
    def can_block(
        hub: dict[str, Any],
        nodes: list[dict[str, Any]],
        modules_by_node: dict[str, list[dict[str, object]]],
    ) -> dict[str, object]:
        """The hub ``config.txt``'s top-level ``"CAN"`` object."""
        numbers = RemoraCanMapper.node_numbers(nodes)
        block: dict[str, object] = {"Bitrate": int(hub.get("can_bitrate") or DEFAULT_BITRATE)}
        status_bit = RemoraCanMapper.status_bit(hub, nodes)
        if status_bit is not None:
            block["Status Bit"] = status_bit
        block["Nodes"] = [
            {
                "UUID": node["canbus_uuid"],
                "Node": numbers[str(node["id"])],
                "Comment": str(node["id"]),
                "Mandatory": "False" if node.get("mandatory") is False else "True",
                "Modules": [
                    RemoraCanMapper.node_module(module, node)
                    for module in modules_by_node.get(str(node["id"]), [])
                ],
            }
            for node in nodes
        ]
        return block


__all__ = ["DEFAULT_BITRATE", "DEFAULT_STATUS_BIT", "RemoraCanMapper"]
