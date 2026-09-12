""":class:`HalFragment` -> the actual `machine.hal` text.

Pure formatting, nothing decided here. Section order is fixed
(loadrt, loadusr, addf, setp, net) per
`.agent/component/README.md` § 4; `addf` is further sorted by
`(thread, order)` since thread scheduling is a cross-component
invariant, not a per-fragment one — see `hal_fragment_models.Addf`.

`loadrt` lines that use `names=` are similarly merged per component,
one line per component rather than one per mapper. LinuxCNC's
realtime loader can only `loadrt` a given component module once per
session — a second `loadrt <comp>` for an already-loaded component
fails at boot ("<comp>: already exists", `insmod ... failed`), taking
the whole machine down with it. Two heaters both wanting
`PIDcontroller`, or a heater-gated fan and a watermark heater both
wanting `conv_bit_float`, is completely ordinary — the real reference
HAL (`machine_config/example/ender3/3Dprinter.hal`) loads its two
heaters' PID controllers as one `loadrt PIDcontroller
names=PID-bed,PID-ext0`, never two separate lines. No single mapper
can know about another mapper's use of the same component, so this
has to be a render-time, cross-fragment merge — the same reasoning
that puts the `addf` thread sort here instead of in a mapper.
"""

from __future__ import annotations

import re

from models.machineconfig.hal_fragment_models import BASE_THREAD, HalFragment, SERVO_THREAD

_THREAD_ORDER = {BASE_THREAD: 0, SERVO_THREAD: 1}

#: Matches ``loadrt <component> names=<name>`` — the only shape a
#: mapper uses for a component that might be instantiated more than
#: once across the machine (`scale`, `conv_bit_float`, `PIDcontroller`,
#: `wcomp`, `comp`, `near`, `not`, ...). A load with a different or no
#: parameter (a motion/MCU driver's own `cfg=`/`step_type=`/
#: `SPI_clk_div=`, or a bare singleton like `estop_latch`) is only
#: ever emitted once per machine today and is left exactly as its
#: mapper wrote it.
_LOADRT_NAMES_RE = re.compile(r"^loadrt (\S+) names=(.+)$")


def _merge_loadrt(lines: list[str]) -> list[str]:
    names_by_component: dict[str, list[str]] = {}
    for line in lines:
        match = _LOADRT_NAMES_RE.match(line)
        if match:
            names_by_component.setdefault(match.group(1), []).append(match.group(2))

    emitted: set[str] = set()
    merged: list[str] = []
    for line in lines:
        match = _LOADRT_NAMES_RE.match(line)
        if not match:
            merged.append(line)
            continue
        component = match.group(1)
        if component in emitted:
            continue
        emitted.add(component)
        merged.append(f"loadrt {component} names={','.join(names_by_component[component])}")
    return merged


def render_hal(fragment: HalFragment) -> str:
    sections: list[str] = []

    if fragment.loadrt:
        sections.append("\n".join(_merge_loadrt(fragment.loadrt)))
    if fragment.loadusr:
        sections.append("\n".join(fragment.loadusr))
    if fragment.addf:
        # A stable sort: entries tied on (thread, order) keep the
        # relative order their mapper emitted them in (e.g.
        # motion-command-handler before motion-controller).
        ordered = sorted(
            fragment.addf, key=lambda a: (_THREAD_ORDER.get(a.thread, 99), a.order)
        )
        sections.append("\n".join(f"addf {a.func} {a.thread}" for a in ordered))
    if fragment.setp:
        sections.append("\n".join(fragment.setp))
    if fragment.nets:
        sections.append("\n".join(fragment.nets))

    return "\n\n".join(sections) + "\n"


__all__ = ["render_hal"]
