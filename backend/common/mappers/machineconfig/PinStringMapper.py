"""Klipper pin string -> :class:`ParsedPin`.

Pure translation, no I/O — the mapper layer's contract
(``.agent/context/BACKEND_LAYERS.md`` § 1.4).
"""

from __future__ import annotations

from models.machineconfig.pin_models import DEFAULT_MCU_ID, ParsedPin

#: Modifier characters and the ``ParsedPin`` flag each one sets.
_MODIFIERS = {"!": "invert", "^": "pullup", "~": "pulldown"}


class PinStringMapper:
    """Splits ``[modifiers][<mcu_id>:]<pin_id>`` into its parts."""

    @classmethod
    def from_string(cls, raw: str) -> ParsedPin:
        """Parse ``raw``.

        Modifiers may combine (``^!PC0``) and may sit either before the
        whole string or directly after the ``<mcu>:`` prefix
        (``par0:!02``) — hand-written configs use both, and accepting
        one spelling but not the other would reject valid machines.

        Raises :class:`ValueError` when the string is empty or has no
        pin left after the prefix; the caller turns that into a
        diagnostic rather than letting it escape.
        """
        if raw is None or not str(raw).strip():
            raise ValueError("pin string is empty")

        text = str(raw).strip()
        flags = {name: False for name in _MODIFIERS.values()}

        text = cls._take_modifiers(text, flags)

        mcu_id = DEFAULT_MCU_ID
        if ":" in text:
            prefix, _, remainder = text.partition(":")
            prefix = prefix.strip()
            if not prefix:
                raise ValueError(f"pin string {raw!r} has an empty MCU prefix")
            mcu_id = prefix
            # A second modifier run may follow the colon.
            text = cls._take_modifiers(remainder.strip(), flags)

        pin_id = text.strip()
        if not pin_id:
            raise ValueError(f"pin string {raw!r} has no pin after the MCU prefix")

        return ParsedPin(raw=str(raw), mcu_id=mcu_id, pin_id=pin_id, **flags)

    @staticmethod
    def _take_modifiers(text: str, flags: dict[str, bool]) -> str:
        """Strip leading modifier characters, recording each in ``flags``."""
        index = 0
        while index < len(text) and text[index] in _MODIFIERS:
            flags[_MODIFIERS[text[index]]] = True
            index += 1
        return text[index:]
