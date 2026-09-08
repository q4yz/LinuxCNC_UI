"""Unit tests for the ``.hal`` signal-block parser/writer.

Pure text-processing tests — no filesystem, no FastAPI app. Endpoint
behavior (pin resolution against the live catalog, 404s, path safety)
lives in ``test_hal_file_signals.py``.
"""

from __future__ import annotations

from models.hal import HalFileSignalWrite
from services.hal_signal_file import (
    MARKER_BEGIN,
    MARKER_END,
    apply_signals,
    parse_net_lines,
    render_signals_block,
)


def test_parse_net_lines_extracts_name_and_pins():
    text = "net spindle-at-speed vfdmod.spindle.at-speed => spindle.0.at-speed webgui.spindle-at-speed\n"
    signals = parse_net_lines(text)
    assert len(signals) == 1
    assert signals[0].name == "spindle-at-speed"
    assert signals[0].pin_tokens == [
        "vfdmod.spindle.at-speed",
        "spindle.0.at-speed",
        "webgui.spindle-at-speed",
    ]


def test_parse_net_lines_ignores_non_net_directives():
    text = "\n".join(
        [
            "# a comment about the setup",
            "loadrt webgui",
            "addf webgui.update servo-thread",
            "setp webgui.some-pin 1.0",
            "net foo out.pin => in.pin",
            "source webgui_connections.hal",
        ]
    )
    signals = parse_net_lines(text)
    assert len(signals) == 1
    assert signals[0].name == "foo"


def test_parse_net_lines_strips_inline_comments():
    text = "net foo out.pin => in.pin  # wired for the X axis limit\n"
    signals = parse_net_lines(text)
    assert signals[0].pin_tokens == ["out.pin", "in.pin"]


def test_render_signals_block_contains_markers_and_warning():
    block = render_signals_block(
        [HalFileSignalWrite(name="foo", source="out.pin", targets=["in.pin"])]
    )
    assert MARKER_BEGIN in block
    assert MARKER_END in block
    assert "AUTO-GENERATED" in block
    assert "net foo out.pin => in.pin" in block


def test_render_signals_block_skips_unnamed_or_empty_signals():
    block = render_signals_block(
        [
            HalFileSignalWrite(name="", source="a", targets=["b"]),
            HalFileSignalWrite(name="empty", source=None, targets=[]),
            HalFileSignalWrite(name="real", source="a", targets=["b"]),
        ]
    )
    lines = [l for l in block.splitlines() if l.startswith("net ")]
    assert lines == ["net real a => b"]


def test_apply_signals_appends_block_when_no_markers_present():
    existing = "loadrt webgui\naddf webgui.update servo-thread\n"
    result = apply_signals(existing, [HalFileSignalWrite(name="foo", source="a", targets=["b"])])
    assert result.startswith(existing.rstrip("\n") + "\n")
    assert MARKER_BEGIN in result
    assert "net foo a => b" in result


def test_apply_signals_preserves_content_outside_markers():
    existing = "\n".join(
        [
            "loadrt webgui",
            "addf webgui.update servo-thread",
            "setp webgui.custom-pin 42",
        ]
    )
    result = apply_signals(existing, [HalFileSignalWrite(name="foo", source="a", targets=["b"])])
    for line in existing.splitlines():
        assert line in result


def test_apply_signals_replaces_existing_block_on_second_save():
    first = apply_signals(
        "loadrt webgui\n",
        [HalFileSignalWrite(name="old-signal", source="a", targets=["b"])],
    )
    second = apply_signals(
        first,
        [HalFileSignalWrite(name="new-signal", source="c", targets=["d"])],
    )
    assert "old-signal" not in second
    assert "new-signal" in second
    assert second.count(MARKER_BEGIN) == 1
    assert second.count(MARKER_END) == 1
    assert "loadrt webgui" in second


def test_apply_signals_round_trip_is_stable():
    signals = [HalFileSignalWrite(name="spindle-on", source="motion.spindle-on", targets=["vfd.spindle-on"])]
    once = apply_signals("loadrt webgui\n", signals)
    parsed = parse_net_lines(once)
    assert len(parsed) == 1
    assert parsed[0].name == "spindle-on"
    assert parsed[0].pin_tokens == ["motion.spindle-on", "vfd.spindle-on"]

    twice = apply_signals(once, signals)
    assert twice == once
