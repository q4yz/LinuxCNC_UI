"""LED colours and Klipper's SET_LED (`core.led_color`), and their upload
conversion to ``M183`` (`core.gcode_converter`)."""
from __future__ import annotations

import pytest

from core.gcode_converter import convert
from core.led_color import SetLed, decode, encode, parse_set_led


def test_encode_decode():
    assert encode(1, 0.5, 0) == 0xFF8000
    assert encode(0, 0, 0, white=1) == 0xFFFFFF  # white onto R, G, B
    assert decode(0xFF8000) == (1.0, 128 / 255, 0.0)


def test_parse_set_led():
    assert parse_set_led("SET_LED LED=SB RED=1 GREEN=0.5 INDEX=2 TRANSMIT=1") == SetLed(
        led="sb", red=1.0, green=0.5, index=2)
    assert parse_set_led("G1 X1") is None and parse_set_led("SET_LEDX LED=a") is None
    for bad in ("SET_LED RED=1", "SET_LED LED=a RED=2", "SET_LED LED=a INDEX=0", "SET_LED LED=a RED=x"):
        with pytest.raises(ValueError):
            parse_set_led(bad)


def test_upload_conversion():
    out = convert("SET_LED LED=sb RED=1 INDEX=2\nM150 R255 U0 B0\nM150 R255 U255 B255 P128 I1 S1\n",
                  led_names=["case", "sb"]).text.splitlines()
    assert out[:3] == ["M183 P16711680 Q102", "M183 P16711680 Q0", "M183 P8421504 Q102"]


def test_upload_conversion_without_leds():
    out = convert("SET_LED LED=sb RED=1\nM150 R255\n").text.splitlines()
    assert out[0].startswith("; SET_LED") and out[1] == "M150 R255"  # a user M150 stays
