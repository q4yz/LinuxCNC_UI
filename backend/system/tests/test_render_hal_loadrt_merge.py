"""render_hal — merges `loadrt <comp> names=...` lines per component.

Real bug, not a hypothetical: a heater-gated fan (`FanHalMapper`) and a
watermark heater (`HeaterHalMapper`) each independently emit their own
`loadrt conv_bit_float names=...` line. Before this fix, ``render_hal``
joined every mapper's ``loadrt`` lines verbatim, so the assembled
``machine.hal`` carried two separate `loadrt conv_bit_float` calls.
LinuxCNC's realtime loader can only load a given component module once
per session — the second call fails at boot with
"conv_bit_float: already exists" / "insmod ... failed", and
`emcStatusBuffer` is never created because LinuxCNC never finished
booting, which is what actually surfaced this (the backend's telemetry
loop then spins forever logging "emcStatusBuffer invalid err=5").

The real reference HAL (`machine_config/example/ender3/3Dprinter.hal`)
confirms the correct shape: two heaters' PID controllers load as one
``loadrt PIDcontroller names=PID-bed,PID-ext0``, never two lines.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import HalFragment
from services.halcompiler import render_hal


def test_two_components_sharing_the_same_loadrt_target_are_merged_into_one_line():
    fragment = HalFragment(
        loadrt=[
            "loadrt conv_bit_float names=conv-heater_bed",
            "loadrt conv_bit_float names=conv-fan1",
        ]
    )
    text = render_hal(fragment)
    assert "loadrt conv_bit_float names=conv-heater_bed,conv-fan1" in text
    # Only one loadrt line for this component — a second one is
    # exactly the boot-crashing bug this test guards against.
    assert text.count("loadrt conv_bit_float") == 1


def test_matches_the_real_reference_hal_shape_for_two_pid_heaters():
    fragment = HalFragment(
        loadrt=[
            "loadrt PIDcontroller names=PID-bed",
            "loadrt PIDcontroller names=PID-ext0",
        ]
    )
    text = render_hal(fragment)
    assert "loadrt PIDcontroller names=PID-bed,PID-ext0" in text
    assert text.count("loadrt PIDcontroller") == 1


def test_three_or_more_instances_of_one_component_all_merge_together():
    fragment = HalFragment(
        loadrt=[
            "loadrt scale names=scale-a",
            "loadrt scale names=scale-b",
            "loadrt scale names=scale-c",
        ]
    )
    text = render_hal(fragment)
    assert "loadrt scale names=scale-a,scale-b,scale-c" in text
    assert text.count("loadrt scale") == 1


def test_different_components_are_not_merged_with_each_other():
    fragment = HalFragment(
        loadrt=[
            "loadrt wcomp names=wcomp-fan1",
            "loadrt conv_bit_float names=conv-fan1",
            "loadrt scale names=scale-fan1",
        ]
    )
    text = render_hal(fragment)
    assert "loadrt wcomp names=wcomp-fan1" in text
    assert "loadrt conv_bit_float names=conv-fan1" in text
    assert "loadrt scale names=scale-fan1" in text


def test_merged_line_lands_at_the_first_occurrences_position():
    # Position matters: `.agent/component/README.md` § 4 orders
    # loadrt before addf/setp/net, but doesn't otherwise mandate an
    # order between components — the merge just must not reorder
    # unrelated loadrt lines around the merged one.
    fragment = HalFragment(
        loadrt=[
            "loadrt wcomp names=wcomp-fan1",
            "loadrt conv_bit_float names=conv-fan1",
            "loadrt PIDcontroller names=PID-bed",
            "loadrt conv_bit_float names=conv-heater_bed",
        ]
    )
    lines = render_hal(fragment).strip().splitlines()
    assert lines == [
        "loadrt wcomp names=wcomp-fan1",
        "loadrt conv_bit_float names=conv-fan1,conv-heater_bed",
        "loadrt PIDcontroller names=PID-bed",
    ]


def test_loadrt_lines_without_names_are_left_untouched_and_unmerged():
    # Motion/MCU driver loads use their own single-use parameters
    # (or none at all) and are only ever emitted once per machine —
    # merging would be meaningless and could corrupt the line.
    fragment = HalFragment(
        loadrt=[
            "loadrt remora-spi SPI_clk_div=8",
            'loadrt hal_parport cfg="0x378 out"',
            "loadrt estop_latch",
            "loadrt stepgen step_type=0,0,0",
        ]
    )
    text = render_hal(fragment)
    for line in fragment.loadrt:
        assert line in text
    assert text.count("\n\n") == 0  # still one contiguous loadrt block


def test_a_single_unshared_component_is_unaffected():
    fragment = HalFragment(loadrt=["loadrt conv_bit_float names=conv-fan1"])
    text = render_hal(fragment)
    assert "loadrt conv_bit_float names=conv-fan1" in text
    assert text.count("loadrt conv_bit_float") == 1
