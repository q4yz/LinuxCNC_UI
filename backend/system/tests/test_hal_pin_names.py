"""Every pin / function the generated HAL names on a stock LinuxCNC
component must exist — caught here, not by LinuxCNC aborting on the
machine ("parameter or pin 'ztilt-ramp-0.min_' not found").

``COMPONENTS`` lists the pins (and parameters) and functions of the
stock components the generator loads, as LinuxCNC 2.9 names them
(``halcmd show pin`` / the components' man pages). Components of our
own (remora, PIDcontroller, compensation, webgui, ...) are not checked.
"""
from __future__ import annotations

import re

import pytest

from MachineConfigParser import MachineConfigParser
from services.halcompiler import compile_machine_hal, render_webgui_connections
from services.machineconfig.hardware_json_generator import build_hardware_json

#: component -> (pins and parameters, functions; "" = the instance itself)
COMPONENTS: dict[str, tuple[set[str], set[str]]] = {
    "and2": ({"in0", "in1", "out"}, {""}),
    "or2": ({"in0", "in1", "out"}, {""}),
    "not": ({"in", "out"}, {""}),
    "comp": ({"in0", "in1", "out", "equal", "hyst"}, {""}),
    "wcomp": ({"in", "min", "max", "out", "under", "over"}, {""}),
    "near": ({"in1", "in2", "out", "scale", "difference"}, {""}),
    "scale": ({"in", "gain", "offset", "out"}, {""}),
    "sum2": ({"in0", "in1", "gain0", "gain1", "offset", "out"}, {""}),
    "mux2": ({"sel", "in0", "in1", "out"}, {""}),
    "edge": ({"in", "out", "out-invert", "both", "in-edge", "out-width-ns", "time-left-ns"}, {""}),
    "limit2": ({"in", "out", "load", "min", "max", "maxv"}, {""}),
    "offset": ({"offset", "in", "out", "fb-in", "fb-out"}, {"update-output", "update-feedback"}),
    "conv_bit_float": ({"in", "out"}, {""}),
    "conv_bit_s32": ({"in", "out"}, {""}),
    "conv_s32_float": ({"in", "out"}, {""}),
    "conv_float_s32": ({"in", "out", "out-of-range", "clamp"}, {""}),
}

BASE = open("tests/fixtures/profiles/full_klipper.cfg").read()
Z1 = """
[stepper_z1]
step_pin: PD4
dir_pin: PD5
enable_pin: !PD6
microsteps: 16
rotation_distance: 8
endstop_pin: PD7
position_endstop: 0
position_max: 300
"""
Z_TILT = """
[probe]
pin: PB7

[z_tilt]
z_positions:
    -50, 100
    300, 100
points:
    20, 100
    230, 100
"""
IO = """
[output_pin light]
pin: PD8

[output_pin dimmer]
pin: PD9
pwm: True
scale: 100

[input_pin door]
pin: PD10
rising_halpin_set: light, 1
falling_halpin_set: light, 0
"""
MACHINES = {
    "printer": BASE,
    "z_tilt": BASE + Z1 + Z_TILT,
    "io": BASE + IO,
    "bed_mesh": BASE + "\n[bed_mesh]\nprobe_count: 3\n",
}

_LOADRT = re.compile(r"^loadrt\s+(\S+)(.*)$")
_TOKEN = re.compile(r"(?<![\w.-])([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)")


def _instances(hal: str) -> dict[str, str]:
    """``instance name -> component`` from the ``loadrt`` lines."""
    out: dict[str, str] = {}
    for line in hal.splitlines():
        m = _LOADRT.match(line.strip())
        if not m or m.group(1) not in COMPONENTS:
            continue
        names = re.search(r"names=(\S+)", m.group(2))
        for name in (names.group(1).split(",") if names else []):
            out[name] = m.group(1)
    return out


def _problems(hal: str, instances: dict[str, str]) -> list[str]:
    problems = []
    for number, line in enumerate(hal.splitlines(), start=1):
        code = line.split("#", 1)[0].strip()
        words = code.split()
        if not words or words[0] not in ("setp", "net", "addf"):
            continue
        tokens = words[1:2] if words[0] in ("setp", "addf") else words[2:]
        for token in tokens:
            if words[0] == "addf" and token in instances:
                if "" not in COMPONENTS[instances[token]][1]:
                    problems.append(f"{number}: addf {token}: {instances[token]} has no plain function")
                continue
            m = _TOKEN.fullmatch(token)
            if not m:
                continue
            instance, _, rest = token.partition(".")
            # Instance names may contain dots (none of ours do); match the longest known prefix.
            component = instances.get(instance)
            if component is None:
                continue
            pins, functions = COMPONENTS[component]
            known = functions if words[0] == "addf" else pins
            if rest not in known:
                problems.append(f"{number}: {code!r}: {component} has no {'function' if words[0] == 'addf' else 'pin'} {rest!r}")
    return problems


@pytest.mark.parametrize("name", sorted(MACHINES))
def test_generated_pins_exist(name):
    payload = build_hardware_json(MachineConfigParser().parse_string(MACHINES[name]), name)
    hal = compile_machine_hal(payload)
    instances = _instances(hal)
    assert instances, "no stock components loaded — the check would prove nothing"
    webgui = render_webgui_connections(payload)
    assert _problems(hal, instances) == []
    assert _problems(webgui, instances) == []


def test_the_check_catches_a_wrong_name():
    hal = "loadrt limit2 names=r\nsetp r.min_ -5\naddf r servo-thread\nloadrt offset names=o\naddf o servo-thread\n"
    problems = _problems(hal, _instances(hal))
    assert any("min_" in p for p in problems) and any("addf o" in p for p in problems)
