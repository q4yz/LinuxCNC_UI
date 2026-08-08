"""Pure-Python parser for ``.macro`` text payloads (issue #95).

Splits a raw ``.macro`` text payload into an **ordered list of
alternating static and Python blocks**. ``static`` blocks contain
the G-code (or anything else) that lives outside ``{ ... }``;
``python`` blocks contain the source inside the braces.

This module is intentionally **library-only**:

* No HTTP endpoint. The router is unchanged — see
  :mod:`backend.modules.macros.router`.
* No execution. The parser never calls :func:`eval`,
  :func:`exec`, :func:`compile`, or any function from the
  standard-library :mod:`ast` module on the python block content.
  The future Interpreter module (a separate ticket) consumes the
  structured output and decides what to do with it.

Algorithm
~~~~~~~~~~

A single-pass character scanner with a small state machine:

* When ``in_python`` is ``False`` and we see ``{``, we emit the
  accumulated static buffer (if non-empty) as a ``static`` block,
  switch into python mode, and reset the buffer for the python
  block.
* When ``in_python`` is ``True`` and we see ``}`` while
  ``string_quote`` is ``None``, we emit the accumulated python
  buffer as a ``python`` block, switch back to static mode, and
  reset the buffer for the static block.
* Inside a Python string literal (``string_quote`` is ``"`` or
  ``'``), every character — including ``{`` and ``}`` — is
  recorded as literal content; it never toggles the state. So
  ``{s = "}"}`` is a single, valid python block.
* ``\\`` inside python mode sets ``escape_next = True``: the next
  character is consumed as literal content regardless of what it
  is. So ``\\"`` does not close a double-quoted string.
* At end of input we emit whatever is in the buffer as the final
  block. If ``in_python`` is still ``True`` at EOF we raise
  :class:`MacroParseError` with the character offset where the
  unclosed opening brace was seen.

Whitespace semantics
~~~~~~~~~~~~~~~~~~~~

Before a block is emitted the accumulated buffer is run through
:meth:`str.strip`. The newlines adjacent to the ``{`` / ``}``
delimiters are removed; the Interpreter module sees the interior
content only. The exact whitespace inside each block is the
``strip`` output, not the literal characters between delimiters.

Scope notes
~~~~~~~~~~~

Triple-quoted strings (``\"\"\"...\"\"\"`` / ``'''...'''``) are
**not** in scope for this ticket. If operators hit them a
follow-up can extend the string-state machine. Bracket / bracket /
paren nesting inside Python is also not modeled: the parser does
not understand Python at all, it only tracks string state.
"""

from __future__ import annotations

from typing import List, Literal, TypedDict


# ---------------------------------------------------------------------- #
# Public types                                                            #
# ---------------------------------------------------------------------- #


class MacroParseError(ValueError):
    """Raised when a ``.macro`` source cannot be parsed.

    The most common cause is an unclosed ``{`` at end of input.
    The exception message reports the character offset of the
    opening brace that was never closed; the future Interpreter
    module can catch this uniformly alongside other value errors.

    Subclassing :class:`ValueError` (rather than introducing a
    new hierarchy) keeps callers that already handle
    ``ValueError`` working without a code change.
    """


class Block(TypedDict):
    """Structured representation of a single parsed block.

    Attributes:
        type: Either ``"static"`` (raw text outside ``{...}``) or
            ``"python"`` (the interior Python source inside the
            braces). The :data:`Literal` keeps the type-checker
            honest; at runtime this is a plain dict.
        content: The block's text content with leading and
            trailing whitespace stripped.
    """

    type: Literal["static", "python"]
    content: str


# ---------------------------------------------------------------------- #
# Parser                                                                  #
# ---------------------------------------------------------------------- #


def parse_macro(source: str) -> List[Block]:
    """Parse a ``.macro`` text payload into an ordered list of blocks.

    The block sequence is stable and matches the source order.
    The Interpreter module (separate ticket) iterates over the
    returned blocks and dispatches static blocks as G-code and
    python blocks through the Python runtime.

    Args:
        source: Raw ``.macro`` text content as returned by
            :meth:`MacroStorage.read`.

    Returns:
        An ordered list of :class:`Block` typed dicts. Empty
        input returns ``[]``. A source with no ``{`` returns a
        single-element list of one ``static`` block. A source
        that is just ``{}`` returns ``[{"type": "python",
        "content": ""}]`` (no leading static block is emitted
        because the static buffer was empty when ``{`` arrived).

    Raises:
        MacroParseError: If the source ends inside an unclosed
            python block. The exception message reports the
            character offset of the opening brace that was never
            closed.

    Example:
        >>> src = 'G28 ; Home all axes\\n{print("hi")}\\nG1 X10 Y10 F3000 ; Move'
        >>> result = parse_macro(src)
        >>> [b["type"] for b in result]
        ['static', 'python', 'static']
        >>> result[0]["content"]
        'G28 ; Home all axes'
        >>> result[1]["content"]
        'print("hi")'
        >>> result[2]["content"]
        'G1 X10 Y10 F3000 ; Move'
    """
    blocks: List[Block] = []

    # State machine ----------------------------------------------------
    in_python = False
    string_quote: Literal[None, '"', "'"] = None
    escape_next = False
    # When ``in_python`` flips to ``True`` we record the offset of
    # the opening brace so a future EOF-time :class:`MacroParseError`
    # can report it.
    open_brace_offset: int | None = None

    # We accumulate into a single buffer and decide what kind of
    # block it becomes at the moment a state transition fires.
    buffer: List[str] = []

    for offset, ch in enumerate(source):
        if not in_python:
            # Static mode — only ``{`` matters; everything else
            # (including literal ``}``) is verbatim content.
            if ch == "{":
                static_content = "".join(buffer).strip()
                if static_content:
                    blocks.append(
                        {"type": "static", "content": static_content}
                    )
                buffer = []
                in_python = True
                string_quote = None
                escape_next = False
                open_brace_offset = offset
                continue
            buffer.append(ch)
            continue

        # Python mode --------------------------------------------------
        if escape_next:
            # Previous ``\\`` already consumed — this character is
            # literal regardless of what it is (``\\"``, ``\\'``,
            # ``\\{``, ``\\}``, ``\\\\`` all land here).
            buffer.append(ch)
            escape_next = False
            continue

        if ch == "\\":
            buffer.append(ch)
            escape_next = True
            continue

        if string_quote is not None:
            # Inside a Python string literal. Only the matching
            # quote ends the literal; every other character
            # (including stray ``{`` / ``}``) is content.
            if ch == string_quote:
                string_quote = None
            buffer.append(ch)
            continue

        if ch in ('"', "'"):
            string_quote = ch  # type: ignore[assignment]
            buffer.append(ch)
            continue

        if ch == "}":
            python_content = "".join(buffer).strip()
            blocks.append(
                {"type": "python", "content": python_content}
            )
            buffer = []
            in_python = False
            string_quote = None
            escape_next = False
            open_brace_offset = None
            continue

        buffer.append(ch)

    # End-of-input cleanup --------------------------------------------
    if in_python:
        # ``open_brace_offset`` is always set when ``in_python`` is
        # ``True`` because the only state transition into python
        # mode is the ``{`` branch above. The assertion documents
        # the invariant for static analyzers.
        assert open_brace_offset is not None
        raise MacroParseError(
            "unclosed '{' in macro source at offset "
            f"{open_brace_offset}"
        )

    trailing = "".join(buffer).strip()
    if trailing:
        blocks.append({"type": "static", "content": trailing})

    return blocks


__all__ = ["Block", "MacroParseError", "parse_macro"]
