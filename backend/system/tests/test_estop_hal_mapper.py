"""EstopHalMapper — `.agent/component/estop.md` § 3.

The UI pulse chain half is grounded in the runtime's own contract:
`StateService.activate_estop()` (`machine/services/StateService.py`)
just asserts `webgui.estop` `True` and leaves it there — a continuous
level — and its own docstring says the HAL layer is responsible for
"generating the required rising edge (pulse)". The physical chain half
is grounded in the real reference machine,
`machine_config/example/PrintNC-WEBGUI/Machine.hal` (lines 41-57).
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import PinRole
from services.halcompiler.components.EstopHalMapper import EstopHalMapper

_PARPORT_MCU = {"mcu": {"id": "mcu", "connection": "parallelport"}}
_REMORA_MCU = {"mcu": {"id": "mcu", "connection": "remora-spi"}}


def test_the_ui_pulse_chain_is_always_present():
    """No hardware at all — the empty-[estop] / UI-only case."""
    fragment = EstopHalMapper.to_fragment({}, {})

    assert "loadrt oneshot names=estop-pulse-generator" in fragment.loadrt
    assert "setp estop-pulse-generator.width 0.1" in fragment.setp
    assert "net continuous-estop-in webgui.estop => estop-pulse-generator.in" in fragment.nets
    assert "net pulsed-estop-out estop-pulse-generator.out => halui.estop.activate" in fragment.nets
    assert not fragment.requests


def test_the_oneshot_runs_in_the_servo_thread():
    fragment = EstopHalMapper.to_fragment({}, {})
    assert len(fragment.addf) == 1
    assert fragment.addf[0].func == "estop-pulse-generator"
    assert fragment.addf[0].thread == "servo-thread"


def test_no_physical_pins_means_no_requests_and_no_latch():
    fragment = EstopHalMapper.to_fragment({"fault_pin": None, "out_pin": None}, _PARPORT_MCU)
    assert fragment.requests == []
    assert not any("estop_latch" in line for line in fragment.loadrt)


def test_fault_pin_on_a_class_a_mcu_gets_the_full_latch_chain():
    """Matches the real reference machine's wiring exactly."""
    fragment = EstopHalMapper.to_fragment({"fault_pin": "10"}, _PARPORT_MCU)

    assert "loadrt estop_latch" in fragment.loadrt
    assert fragment.addf[-1].func == "estop-latch.0"
    assert fragment.addf[-1].thread == "servo-thread"
    assert "net estop-fault => estop-latch.0.fault-in" in fragment.nets
    assert "net estop-reset <= iocontrol.0.user-request-enable" in fragment.nets
    assert "net estop-reset => estop-latch.0.reset" in fragment.nets
    assert "net estop-ext <= estop-latch.0.ok-out" in fragment.nets
    assert "net estop-ext => iocontrol.0.emc-enable-in" in fragment.nets

    [request] = fragment.requests
    assert request.signal == "estop-fault"
    assert request.role is PinRole.DIGITAL_IN
    assert request.pin.pin_id == "10"
    assert request.owner == "estop"


def test_out_pin_on_a_class_a_mcu_mirrors_the_enable_state():
    fragment = EstopHalMapper.to_fragment({"out_pin": "14"}, _PARPORT_MCU)

    assert "net estop-out <= iocontrol.0.user-enable-out" in fragment.nets
    [request] = fragment.requests
    assert request.signal == "estop-out"
    assert request.role is PinRole.DIGITAL_OUT
    assert request.pin.pin_id == "14"


def test_fault_pin_and_out_pin_are_independent():
    """Declaring one does not require or imply the other."""
    fault_only = EstopHalMapper.to_fragment({"fault_pin": "10"}, _PARPORT_MCU)
    assert not any("user-enable-out" in n for n in fault_only.nets)

    out_only = EstopHalMapper.to_fragment({"out_pin": "14"}, _PARPORT_MCU)
    assert not any("estop_latch" in line for line in out_only.loadrt)
    assert not any("fault-in" in n for n in out_only.nets)


def test_class_b_mcu_gets_the_physical_pin_routed_but_not_the_iocontrol_chain():
    """RemoraRouterMapper's own `base_fragment()` already nets
    `iocontrol.0.user-enable-out`/`user-request-enable`/
    `emc-enable-in` for its SPI link-health chain — wiring
    `estop_latch` on top of the same pins would double-drive them.
    The physical pin still routes (a real `config.txt` module), only
    the core iocontrol linkage is skipped."""
    fragment = EstopHalMapper.to_fragment(
        {"fault_pin": "PG6", "out_pin": "PG7"}, _REMORA_MCU
    )

    assert not any("estop_latch" in line for line in fragment.loadrt)
    assert not any("iocontrol" in n for n in fragment.nets)
    assert not any("estop-latch" in n for n in fragment.nets)

    signals = {r.signal: r for r in fragment.requests}
    assert signals["estop-fault"].role is PinRole.DIGITAL_IN
    assert signals["estop-out"].role is PinRole.DIGITAL_OUT


def test_gating_is_per_pin_not_per_machine():
    """A machine could (unusually) route fault_pin through a
    class-B MCU while out_pin sits on a class-A one — each pin's own
    target MCU decides, not some machine-wide default."""
    mcus = {
        "remora": {"id": "remora", "connection": "remora-spi"},
        "par0": {"id": "par0", "connection": "parallelport"},
    }
    fragment = EstopHalMapper.to_fragment(
        {"fault_pin": "remora:PG6", "out_pin": "par0:14"}, mcus
    )
    assert not any("emc-enable-in" in n for n in fragment.nets)
    assert "net estop-out <= iocontrol.0.user-enable-out" in fragment.nets


def test_unknown_mcu_id_is_treated_as_not_owning_iocontrol():
    """A pin naming an undeclared MCU is a validator concern
    (E_UNKNOWN_MCU) — this mapper trusts a validated payload and
    simply doesn't find a POSITION-class match, so it wires the
    iocontrol chain (the class-A-shaped default) rather than raising."""
    fragment = EstopHalMapper.to_fragment({"out_pin": "ghost:14"}, {})
    assert "net estop-out <= iocontrol.0.user-enable-out" in fragment.nets
