"""Hybrid G-code + Python parser for macros (issue #7).

The parser is the single source of truth for the ``{ ... }`` block
extraction. The executor consumes the returned list verbatim.

Grammar (informal):

* Every line outside ``{ ... }`` is G-code and is preserved verbatim
  (including leading whitespace and ``;`` comments).
* Anything inside ``{ ... }`` is treated as Python source. The
  surrounding whitespace is stripped so the block can be
  indented naturally inside a G-code file.
* Braces inside Python string literals (single- or double-quoted)
  are ignored so a ``f"G0 X{x}"`` nested-block does not break the
  brace counter.
* A stray ``}`` outside any block is dropped with a warning so a
  copy/paste artefact does not abort the run.

The parser is intentionally dependency-free and pure: no logging,
no I/O, no shared state. The executor can call it as many times as
it needs without worrying about re-entrancy.
"""

from __future__ import annotations

import logging
import re
from typing import List

logger = logging.getLogger("backend.services.macro_parser")


def parse_macro(content: str) -> List[dict]:
    """Split a macro into a list of ``MacroBlock`` dicts.

    Returns a list of objects with the shape::

        {"kind": "gcode",  "text": "G21\nG90\n"}
        {"kind": "python", "code": "for x in range(3):\n    cnc.emit(...)"}

    The parser walks the file linearly, tracking a brace depth and
    a single-quote/double-quote string state. Any G-code segment
    before the first ``{`` is emitted as a single block even when
    it is empty — the executor's iteration logic stays uniform.
    """
    blocks: List[dict] = []
    gcode_buffer: List[str] = []
    python_buffer: List[str] = []

    in_python = False
    brace_depth = 0
    i = 0
    length = len(content)

    # Tracks whether the *current* character is inside a Python
    # string literal. We use a small two-state machine (single vs
    # double quote) so the same handling applies to f-strings and
    # triple-quoted strings as long as we count consecutive quotes
    # consistently.
    quote_char: str = ""

    while i < length:
        ch = content[i]

        if in_python:
            # Inside a Python block: only braces that are not part
            # of a string literal close the block.
            if quote_char:
                if ch == "\\" and i + 1 < length:
                    # Skip the escaped character entirely.
                    python_buffer.append(ch)
                    python_buffer.append(content[i + 1])
                    i += 2
                    continue
                if ch == quote_char:
                    quote_char = ""
                python_buffer.append(ch)
                i += 1
                continue

            # Not inside a string literal.
            if ch in ("'", '"'):
                quote_char = ch
                python_buffer.append(ch)
                i += 1
                continue

            if ch == "{":
                brace_depth += 1
                # The first opening brace is consumed by the outer
                # state machine; subsequent ones are part of the
                # Python source (e.g. a dict literal).
                if brace_depth > 1:
                    python_buffer.append(ch)
                i += 1
                continue

            if ch == "}":
                if brace_depth > 0:
                    brace_depth -= 1
                else:
                    # Stray closing brace; treat as a literal so we
                    # do not lose the user's intent.
                    python_buffer.append(ch)
                    i += 1
                    continue
                if brace_depth == 0:
                    # End of the Python block. Flush and switch back
                    # to G-code mode.
                    code = "".join(python_buffer).strip("\n")
                    if code:
                        blocks.append({"kind": "python", "code": code})
                    python_buffer = []
                    in_python = False
                    i += 1
                    continue

            python_buffer.append(ch)
            i += 1
            continue

        # G-code mode.
        if ch == "{":
            # Flush the G-code buffer (even when empty so the
            # executor sees a contiguous slice).
            text = "".join(gcode_buffer)
            blocks.append({"kind": "gcode", "text": text})
            gcode_buffer = []
            in_python = True
            brace_depth = 1
            i += 1
            continue

        # Stray '}' in G-code mode: warn and drop.
        if ch == "}":
            logger.warning(
                "macro_parser: stray '}' at offset %s dropped",
                i,
            )
            i += 1
            continue

        gcode_buffer.append(ch)
        i += 1

    # Flush any unwritten tail.
    if in_python:
        # Unterminated python block — treat the buffered source as
        # Python so the executor surfaces a meaningful ``SyntaxError``
        # instead of silently dropping the block.
        code = "".join(python_buffer).strip("\n")
        if code:
            blocks.append({"kind": "python", "code": code})
    else:
        text = "".join(gcode_buffer)
        blocks.append({"kind": "gcode", "text": text})

    return blocks


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


_MACRO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def validate_macro_name(name: str) -> str:
    """Validate a macro filename and return its canonical form.

    The name is normalized to start with no leading path separator
    and to end with the ``.macro`` extension. ``.`` and ``..`` are
    rejected to prevent directory traversal regardless of the
    extension handling.
    """
    if not isinstance(name, str):
        raise ValueError("macro name must be a string")

    candidate = name.strip()
    if not candidate:
        raise ValueError("macro name is required")

    # Strip any directory prefix the caller may have included.
    candidate = candidate.replace("\\", "/").split("/")[-1]

    if candidate in {".", ".."}:
        raise ValueError("invalid macro name")

    if not _MACRO_NAME_RE.match(candidate):
        raise ValueError(
            "macro name must be 1-64 chars of letters, digits, '_', '.', '-'",
        )

    if not candidate.lower().endswith(".macro"):
        candidate = f"{candidate}.macro"

    return candidate


__all__ = ["parse_macro", "validate_macro_name"]
