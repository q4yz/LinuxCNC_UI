"""One digital spindle's status/control signals -> `webgui_connections.hal`.

Not `machine.hal` content — this is the UI-bindings pass
`DigitalSpindleHalMapper`'s own docstrings have deferred throughout
this compiler's build ("nothing in this component consumes
fault/is-connected/error-count yet"). It exists because the runtime
already expects these exact pin names: `common/mappers/tools/
SpindleDigitalMapper.py::from_dict_to_SpindleDigitalPins` builds the
webgui side of every one of them, suffixed by
`tool_id.replace("spindle_digital", "")` — a second spindle
(`spindle_digital_test`) gets `webgui.spindle-at-speed_test`, not a
bare `webgui.spindle-at-speed` colliding with the first. Get a name
wrong here and the net binds to a pin nothing reads.

Every signal name on the machine.hal side (`spindle-at-speed`,
`spindle-speed-cmd`, `<id>-target-rpm`, `<id>-web-target-rpm`,
`<id>-use-web-rpm`, ...) is exactly what `DigitalSpindleHalMapper`
already emits — this only adds one more reader/writer onto an
already-existing signal, in the separate file the operator hand-edits
(so it must never assume a signal exists that mapper didn't actually
create, hence the same presence checks on the raw spindle dict).

**Scope for this pass:** read-only status display (at-speed,
commanded/actual RPM, forward/reverse, health), the percentage RPM
override via halui, AND the absolute manual RPM override
(`webgui.absolute-master-override(-enable)`). The latter only ever
ADDS the two `webgui.*` pins onto the `mux2.in1`/`mux2.sel` signals
`DigitalSpindleHalMapper.build_speed_command` already declared — the
`mux2` selector itself lives in `machine.hal`, centralized, not here;
see `.agent/component/digital_spindle.md`.
"""

from __future__ import annotations

from typing import Any

#: (hardware.json field, machine.hal signal, webgui pin) — only
#: emitted when the machine.hal side actually created that signal
#: (mirrors `DigitalSpindleHalMapper`'s own presence checks).
_READOUTS: tuple[tuple[str, str, str], ...] = (
    ("run_pin", "spindle-forward", "spindle-forward"),
    ("reverse_pin", "spindle-reverse", "spindle-reverse"),
    ("is_connected_pin", "{id}-is-connected", "is-connected"),
    ("error_count_pin", "{id}-error-count", "error-count"),
    # The runtime's "last error" is this compiler's "fault" — same
    # health concept, different name on each side of the pin.
    ("fault_pin", "{id}-fault", "last-error"),
)


class SpindleWebguiMapper:
    """`net` lines binding one spindle's status onto its `webgui.*` pins."""

    @staticmethod
    def to_lines(spindle: dict[str, Any]) -> list[str]:
        spindle_id = str(spindle["id"])
        n = int(spindle.get("spindle_number") or 0)
        suffix = spindle_id.replace("spindle_digital", "", 1)

        lines = [
            f"# ----------------------------------------------------------",
            f"# Spindle: {spindle_id}",
            f"# ----------------------------------------------------------"
        ]

        # Commanded speed — the WINNING speed (mux2's output, always
        # emitted by DigitalSpindleHalMapper), not the raw G-code
        # signal: while the absolute override is active this is what
        # the drive is actually being asked for, and the display
        # should track that, not a value the drive is ignoring.
        lines.append(f"net {spindle_id}-target-rpm => webgui.TargetRpm{suffix}")

        if spindle.get("speed_fb_pin"):
            lines.append(f"net spindle-speed-fb => webgui.rpm-out{suffix}")

        if spindle.get("at_speed_pin") or spindle.get("speed_fb_pin"):
            # Either wired straight from the drive's own bit, or
            # derived by the `near` component — both name the signal
            # `spindle-at-speed` (see `DigitalSpindleHalMapper`).
            lines.append(f"net spindle-at-speed => webgui.spindle-at-speed{suffix}")

        for field, signal_template, pin in _READOUTS:
            if not spindle.get(field):
                continue
            signal = signal_template.format(id=spindle_id)
            lines.append(f"net {signal} => webgui.{pin}{suffix}")

        # --- Web GUI Override (Percentage) ---
        # Native LinuxCNC behaviour: `halui.spindle.N.override.*`
        # scales the G-code-commanded speed itself, so this already
        # reaches the drive through `spindle.N.speed-out` with no
        # mux2 involved — that selector only arbitrates the *absolute*
        # override below, which bypasses the G-code speed entirely.
        lines.extend([
            "",
            f"# --- Web GUI Override (Percentage) ---",
            f"# 1. Enable direct value mode",
            f"setp halui.spindle.{n}.override.direct-value true",
            f"# 2. Set the scale so each count equals 1% (0.01)",
            f"setp halui.spindle.{n}.override.scale 0.01",
            f"# 3. Connect the web signal to the counts pin",
            f"net spindle-override-{spindle_id} webgui.override{suffix} => halui.spindle.{n}.override.counts",
            ""
        ])

        # --- Web GUI Override (Absolute) ---
        # `<id>-web-target-rpm`/`<id>-use-web-rpm` are declared as
        # bare signals in machine.hal (mux2.in1/mux2.sel are already
        # readers) — these two lines are the only place their actual
        # writer pins get added, same "component declares, webgui
        # mapper connects the UI" split as every other signal here.
        lines.extend([
            f"# --- Web GUI Override (Absolute) ---",
            f"net {spindle_id}-web-target-rpm webgui.absolute-master-override{suffix} => mux2-{spindle_id}.in1",
            f"net {spindle_id}-use-web-rpm webgui.absolute-master-override-enable{suffix} => mux2-{spindle_id}.sel",
            ""
        ])

        return lines


__all__ = ["SpindleWebguiMapper"]
