"""Tests for the macros parser (issue #95).

Covers the pure-Python ``parse_macro`` function in
:mod:`backend.modules.macros.parser` and its re-export from
:mod:`backend.modules.macros`.

The parser is library-only: no HTTP endpoint, no execution. These
tests are pure-Python unit tests against the function — there is
no FastAPI / TestClient surface to drive.

Coverage:

* The ticket's example input → exactly three blocks in order.
* Edge cases from the acceptance criteria: empty input, no
  braces, just ``{}``.
* String-boundary cases: ``}`` inside ``"..."`` or ``'...'``
  does not close the python block; ``{`` inside a string is
  literal; escape sequences ``\\"`` / ``\\'`` / ``\\\\`` do not
  toggle the string state.
* Malformed input: an unclosed ``{`` at EOF raises
  :class:`MacroParseError` with the character offset of the
  opening brace.
* Strip semantics: the newlines adjacent to ``{`` / ``}`` are
  removed from each block.
* Structural: ``Block`` is a TypedDict; ``parse_macro`` is
  exported from the package; the parser never imports ``exec`` /
  ``eval`` / ``compile`` / ``ast.parse`` and never references
  those names in its own source.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


# ---------------------------------------------------------------------- #
# Ticket example                                                          #
# ---------------------------------------------------------------------- #


class TestTicketExample:
    """The documented ticket example produces three blocks."""

    SOURCE = (
        "G28 ; Home all axes\n"
        '{print("hi")}\n'
        "G1 X10 Y10 F3000 ; Move to start position"
    )

    def test_returns_three_blocks_in_order(self):
        from modules.macros.parser import parse_macro

        result = parse_macro(self.SOURCE)
        assert [b["type"] for b in result] == [
            "static",
            "python",
            "static",
        ]

    def test_static_blocks_match_documented_strings(self):
        from modules.macros.parser import parse_macro

        result = parse_macro(self.SOURCE)
        assert result[0]["content"] == "G28 ; Home all axes"
        assert result[2]["content"] == (
            "G1 X10 Y10 F3000 ; Move to start position"
        )

    def test_python_block_preserves_print_quoting(self):
        from modules.macros.parser import parse_macro

        result = parse_macro(self.SOURCE)
        assert result[1]["content"] == 'print("hi")'


# ---------------------------------------------------------------------- #
# Empty / no-brace / just-braces edge cases                                #
# ---------------------------------------------------------------------- #


class TestEdgeCases:
    """Edge cases from the acceptance criteria."""

    def test_empty_input_returns_empty_list(self):
        from modules.macros.parser import parse_macro

        assert parse_macro("") == []

    def test_no_braces_returns_single_static_block(self):
        from modules.macros.parser import parse_macro

        result = parse_macro("hello world\nG1 X0 Y0")
        assert result == [
            {"type": "static", "content": "hello world\nG1 X0 Y0"}
        ]

    def test_no_braces_strips_leading_and_trailing_whitespace(self):
        from modules.macros.parser import parse_macro

        result = parse_macro("   \n  G1 X0 Y0  \n   ")
        assert result == [{"type": "static", "content": "G1 X0 Y0"}]

    def test_just_open_close_returns_empty_python_block(self):
        from modules.macros.parser import parse_macro

        # The static buffer is empty when ``{`` arrives, so no
        # leading static block is emitted. The python buffer is
        # empty when ``}`` arrives, but we still emit it.
        assert parse_macro("{}") == [
            {"type": "python", "content": ""}
        ]

    def test_text_around_braces_yields_three_blocks(self):
        from modules.macros.parser import parse_macro

        result = parse_macro("pre{body}post")
        assert result == [
            {"type": "static", "content": "pre"},
            {"type": "python", "content": "body"},
            {"type": "static", "content": "post"},
        ]


# ---------------------------------------------------------------------- #
# String-boundary cases                                                    #
# ---------------------------------------------------------------------- #


class TestStringBoundaries:
    """``{`` / ``}`` inside Python string literals are literal content."""

    def test_close_brace_inside_double_quoted_string_does_not_close(self):
        from modules.macros.parser import parse_macro

        # The ``}`` inside the double-quoted string is content;
        # the *real* close brace ends the block.
        result = parse_macro('{s = "}"; print(s)}')
        assert result == [{"type": "python", "content": 's = "}"; print(s)'}]

    def test_close_brace_inside_single_quoted_string_does_not_close(self):
        from modules.macros.parser import parse_macro

        result = parse_macro("{s = '}'; print(s)}")
        assert result == [{"type": "python", "content": "s = '}'; print(s)"}]

    def test_open_brace_inside_string_is_literal(self):
        from modules.macros.parser import parse_macro

        # The ``{`` inside the string must not open a new python
        # block — the parser does not recurse.
        result = parse_macro('{s = "{"; print(s)}')
        assert result == [{"type": "python", "content": 's = "{"; print(s)'}]

    def test_both_brace_types_inside_same_string(self):
        from modules.macros.parser import parse_macro

        result = parse_macro('{s = "}{"; print(s)}')
        assert result == [{"type": "python", "content": 's = "}{"; print(s)'}]


# ---------------------------------------------------------------------- #
# Escape-sequence cases                                                    #
# ---------------------------------------------------------------------- #


class TestEscapeSequences:
    """Escape sequences inside Python do not toggle the string state."""

    def test_escaped_double_quote_inside_double_quoted_string(self):
        from modules.macros.parser import parse_macro

        # The string is still open after the escaped quote; the
        # matching unescaped ``"`` ends the literal.
        result = parse_macro('{s = "a\\"b"; print(s)}')
        assert result == [{"type": "python", "content": 's = "a\\"b"; print(s)'}]

    def test_escaped_single_quote_inside_single_quoted_string(self):
        from modules.macros.parser import parse_macro

        result = parse_macro("{s = 'a\\'b'; print(s)}")
        assert result == [{"type": "python", "content": "s = 'a\\'b'; print(s)"}]

    def test_escaped_backslash_consumed_literally(self):
        from modules.macros.parser import parse_macro

        # ``\\\\`` → first ``\\`` sets escape_next; the second ``\\``
        # is consumed as literal content; the next ``n`` is also
        # literal (because escape_next was reset by the second
        # ``\\``). Net result: the ``n`` lands in the buffer.
        result = parse_macro("{s = 'a\\\\n'; print(s)}")
        assert result == [{"type": "python", "content": "s = 'a\\\\n'; print(s)"}]

    def test_escape_then_open_brace_is_literal_inside_string(self):
        from modules.macros.parser import parse_macro

        # After ``\\`` the following ``{`` is literal content,
        # not a state transition (we are inside a python block
        # already, so this just verifies escape_next is honoured
        # even for non-quote characters).
        result = parse_macro('{s = "\\{"; print(s)}')
        assert result == [{"type": "python", "content": 's = "\\{"; print(s)'}]


# ---------------------------------------------------------------------- #
# Malformed input                                                          #
# ---------------------------------------------------------------------- #


class TestMalformedInput:
    """Malformed inputs raise :class:`MacroParseError` with the right offset."""

    def test_unclosed_open_brace_raises(self):
        from modules.macros.parser import MacroParseError, parse_macro

        with pytest.raises(MacroParseError):
            parse_macro("G28\n{print('hi')\nG1 X10")

    def test_unclosed_open_brace_reports_offset(self):
        from modules.macros.parser import MacroParseError, parse_macro

        # ``{`` is at index 4. The error message must mention
        # that offset so the future Interpreter module can point
        # at the offending brace.
        source = "G28\n{print('hi')"
        with pytest.raises(MacroParseError) as excinfo:
            parse_macro(source)
        assert "offset 4" in str(excinfo.value)

    def test_lone_open_brace_raises(self):
        from modules.macros.parser import MacroParseError, parse_macro

        with pytest.raises(MacroParseError) as excinfo:
            parse_macro("{")
        assert "offset 0" in str(excinfo.value)

    def test_unclosed_open_brace_offset_is_first_not_last(self):
        """If the source has multiple ``{`` and only one is
        unclosed, the reported offset must be the first unclosed
        opening brace (the one that opened the still-active
        python block).
        """
        from modules.macros.parser import MacroParseError, parse_macro

        # Index map of ``"{abc }{def"``:
        #   0: ``{``   1: a    2: b    3: c    4: (space)
        #   5: ``}``   6: ``{``   7: d   8: e   9: f
        # The first ``{`` (offset 0) opens block A; ``}`` at
        # offset 5 closes it; the second ``{`` (offset 6) opens
        # block B; block B is still open at EOF.
        source = "{abc }{def"
        with pytest.raises(MacroParseError) as excinfo:
            parse_macro(source)
        assert "offset 6" in str(excinfo.value)

    def test_orphan_close_brace_is_literal_content(self):
        """An unmatched ``}`` outside a python block is literal
        static content — it never closes a block that was never
        opened.
        """
        from modules.macros.parser import parse_macro

        result = parse_macro("G90\n}\nG91")
        assert result == [{"type": "static", "content": "G90\n}\nG91"}]


# ---------------------------------------------------------------------- #
# Strip semantics                                                          #
# ---------------------------------------------------------------------- #


class TestStripSemantics:
    """Adjacent newlines are stripped from each block."""

    def test_static_block_strips_newlines_around_open_brace(self):
        from modules.macros.parser import parse_macro

        result = parse_macro("G28\n{x = 1}\nG90")
        assert result[0]["content"] == "G28"
        assert result[1]["content"] == "x = 1"
        assert result[2]["content"] == "G90"

    def test_python_block_strips_leading_and_trailing_whitespace(self):
        from modules.macros.parser import parse_macro

        # Whitespace between ``{`` and the first statement, and
        # between the last statement and ``}``, is removed.
        result = parse_macro("{\n    x = 1\n    y = 2\n}")
        assert result == [
            {"type": "python", "content": "x = 1\n    y = 2"}
        ]

    def test_multiline_python_block(self):
        from modules.macros.parser import parse_macro

        result = parse_macro("{\nx = 1\ny = 2\nz = 3\n}")
        assert result == [{"type": "python", "content": "x = 1\ny = 2\nz = 3"}]

    def test_multiple_python_blocks(self):
        from modules.macros.parser import parse_macro

        # Leading ``{`` arrives on an empty static buffer so the
        # first emitted block is the python block, not a static
        # block. The trailing ``G1 X10`` is emitted as the final
        # static block at EOF.
        result = parse_macro("{a = 1}\nG1 X0\n{b = 2}\nG1 X10")
        assert [b["type"] for b in result] == [
            "python",
            "static",
            "python",
            "static",
        ]
        assert result[0]["content"] == "a = 1"
        assert result[1]["content"] == "G1 X0"
        assert result[2]["content"] == "b = 2"
        assert result[3]["content"] == "G1 X10"


# ---------------------------------------------------------------------- #
# Structural / export tests                                                #
# ---------------------------------------------------------------------- #


class TestStructural:
    """The parser is library-only and exported from the package."""

    def test_parse_macro_exported_from_package(self):
        # ``backend.modules.macros`` re-exports ``parse_macro`` so
        # the future Interpreter module can import it via the
        # short path.
        from modules.macros import parse_macro

        assert callable(parse_macro)

    def test_block_is_typed_dict(self):
        from modules.macros.parser import Block

        # ``Block`` is a TypedDict — at runtime a TypedDict is a
        # plain ``dict`` subclass, so ``isinstance`` passes and
        # ``__total__`` / ``__required_keys__`` / ``__optional_keys__``
        # are defined.
        assert isinstance(Block(), dict)
        assert hasattr(Block, "__required_keys__")
        required = Block.__required_keys__
        assert "type" in required
        assert "content" in required

    def test_macro_parse_error_is_value_error(self):
        from modules.macros.parser import MacroParseError

        assert issubclass(MacroParseError, ValueError)

    def test_parser_source_contains_no_execution_calls(self):
        """The parser must never call ``eval``, ``exec``,
        ``compile``, or ``ast.parse``. We assert this structurally
        by scanning the module source for those tokens outside of
        this test file.
        """
        from modules.macros import parser as parser_module

        source = Path(parser_module.__file__).read_text(encoding="utf-8")
        forbidden = ("eval(", "exec(", "compile(", "ast.parse")
        for token in forbidden:
            assert token not in source, (
                f"parser.py must not contain {token!r} — "
                "the parser is library-only and must never execute code"
            )

    def test_parser_module_has_no_third_party_imports(self):
        """The parser is pure stdlib. Anything else would be a
        regression worth flagging.
        """
        from modules.macros import parser as parser_module

        source = Path(parser_module.__file__).read_text(encoding="utf-8")
        # The only ``import`` lines should be ``from __future__``
        # and ``from typing import ...``.
        allowed_substrings = ("from __future__", "from typing import")
        for line in source.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            assert any(allowed in stripped for allowed in allowed_substrings), (
                f"Unexpected import in parser.py: {stripped!r}"
            )

    def test_parser_function_signature(self):
        from modules.macros.parser import parse_macro

        sig = inspect.signature(parse_macro)
        params = list(sig.parameters.values())
        assert len(params) == 1
        assert params[0].name == "source"
        # ``source`` has no default — the parser is a one-shot
        # pure function over the supplied text.
        assert params[0].default is inspect.Parameter.empty


# ---------------------------------------------------------------------- #
# Doctest smoke test                                                       #
# ---------------------------------------------------------------------- #


def test_docstring_doctest_example_runs_cleanly():
    """The example in the parser docstring should run cleanly under
    :mod:`doctest` — we import ``doctest`` and run it once here so
    any drift between the docstring and the implementation is
    caught by CI.
    """
    import doctest

    from modules.macros import parser as parser_module

    results = doctest.testmod(
        parser_module,
        verbose=False,
        name="parser_doctest",
    )
    # ``testmod`` returns ``(failed, attempted)``. We want zero
    # failures; ``attempted`` may legitimately be ``0`` if the
    # docstring has no ``>>>`` markers, but our docstring does.
    assert results.failed == 0
    assert results.attempted > 0
