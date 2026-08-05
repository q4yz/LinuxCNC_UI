"""Parser for hybrid G-code and brace-delimited Python macros."""
from __future__ import annotations

import ast
from dataclasses import dataclass


class MacroParseError(ValueError):
    """Raised when a macro contains an unmatched or invalid Python block."""


@dataclass(frozen=True)
class GCODEText:
    text: str


@dataclass(frozen=True)
class PythonBlock:
    code: str
    line: int


Segment = GCODEText | PythonBlock


def parse(body: str) -> list[Segment]:
    segments: list[Segment] = []
    start = 0
    index = 0
    while index < len(body):
        if body[index] != "{":
            index += 1
            continue
        if index > start:
            segments.append(GCODEText(body[start:index]))
        block_start = index
        depth = 1
        index += 1
        while index < len(body) and depth:
            if body[index] == "{":
                depth += 1
            elif body[index] == "}":
                depth -= 1
            index += 1
        if depth:
            line = body.count("\n", 0, block_start) + 1
            raise MacroParseError(f"Unmatched '{{' on line {line}")
        code = body[block_start + 1:index - 1]
        line = body.count("\n", 0, block_start) + 1
        try:
            ast.parse(code, filename="<macro>", mode="exec")
        except SyntaxError as exc:
            raise MacroParseError(f"Python syntax error on line {line + (exc.lineno or 1) - 1}: {exc.msg}") from exc
        segments.append(PythonBlock(code, line))
        start = index
    if start < len(body):
        segments.append(GCODEText(body[start:]))
    return segments
