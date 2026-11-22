"""Python port of ``frontend/src/modules/macros/parser.ts``.

Splits a raw ``.macro`` text payload into an ordered list of
alternating ``static`` (G-code) and ``python`` blocks delimited by
``{ ... }``.

The state machine is intentionally identical to the frontend
parser so the two implementations cannot drift: same
``in_python`` / ``string_quote`` / ``escape_next`` flags, same
whitelisted characters, same error message for an unclosed
``{``.

Why port rather than call the backend from the frontend? The
macros store used to round-trip the parse through the frontend
parser and fire each non-blank static line as one MDI call. The
new design makes ``POST /api/v1/modules/macros/{name}/start?kind=macro``
the single dispatch entry point so the parse lives next to the
hardware layer. A future frontend consumer (the universal
editor's preview, a "next-block" navigator) keeps the JS parser
around — the JS parser and this Python parser must stay
byte-identical on the same input.

Whitespace semantics: leading / trailing whitespace on each block
is stripped via the same rule the JS parser uses so the operator
does not see the newline adjacent to a ``{`` / ``}`` delimiter
in the block they actually receive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


class MacroParseError(Exception):
    """Raised when the macro source ends inside an unclosed ``{``.

    The message reports the character offset of the opening brace
    that was never closed.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.name = "MacroParseError"


@dataclass
class MacroBlock:
    """One parsed block inside a ``.macro`` file.

    Attributes:
        type: ``"static"`` for G-code, ``"python"`` for a
            ``{ ... }`` block whose interpreter is not implemented.
        content: The block payload with surrounding whitespace
            stripped (``str.strip``).
    """

    type: str
    content: str


def parse_macro(source: str) -> List[MacroBlock]:
    """Parse a ``.macro`` text payload into an ordered list of blocks.

    Args:
        source: Raw ``.macro`` content as returned by the macros
            module's ``GET /api/v1/modules/macros/{name}``.

    Returns:
        A list of :class:`MacroBlock` ordered as they appear in the
        source. Empty input returns ``[]``. A source with no ``{``
        returns a single-element list of one ``static`` block. A
        source that is just ``{}`` returns one ``python`` block with
        an empty content string.

    Raises:
        MacroParseError: If the source ends inside an unclosed
            ``{`` python block. The message reports the character
            offset of the opening brace that was never closed.
    """
    if not isinstance(source, str):
        raise MacroParseError(
            f"macro source must be a string, got {type(source).__name__}"
        )

    blocks: List[MacroBlock] = []
    in_python = False
    string_quote: str | None = None
    escape_next = False
    open_brace_offset: int | None = None
    buffer: List[str] = []

    for offset, ch in enumerate(source):
        if not in_python:
            if ch == "{":
                static_content = "".join(buffer).strip()
                if static_content:
                    blocks.append(MacroBlock(type="static", content=static_content))
                buffer = []
                in_python = True
                string_quote = None
                escape_next = False
                open_brace_offset = offset
                continue
            buffer.append(ch)
            continue

        # Python mode -------------------------------------------------
        if escape_next:
            buffer.append(ch)
            escape_next = False
            continue

        if ch == "\\":
            buffer.append(ch)
            escape_next = True
            continue

        if string_quote is not None:
            if ch == string_quote:
                string_quote = None
            buffer.append(ch)
            continue

        if ch == '"' or ch == "'":
            string_quote = ch
            buffer.append(ch)
            continue

        if ch == "}":
            python_content = "".join(buffer).strip()
            blocks.append(MacroBlock(type="python", content=python_content))
            buffer = []
            in_python = False
            string_quote = None
            escape_next = False
            open_brace_offset = None
            continue

        buffer.append(ch)

    if in_python:
        raise MacroParseError(
            f"unclosed '{{' in macro source at offset {open_brace_offset}"
        )

    trailing = "".join(buffer).strip()
    if trailing:
        blocks.append(MacroBlock(type="static", content=trailing))

    return blocks


def split_static_block(content: str) -> List[str]:
    """Split one ``static`` block into per-line MDI commands.

    The result is one trimmed, non-empty line per command. Blank
    lines and pure-whitespace lines are dropped so the dispatch
    loop never fires an empty MDI at the controller.
    """
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip()
    ]


__all__ = ["MacroBlock", "MacroParseError", "parse_macro", "split_static_block"]