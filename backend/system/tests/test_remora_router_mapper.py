"""RemoraRouterMapper — `.agent/component/mcu_spi_remora.md` § 3-4."""

from __future__ import annotations

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import PinRequest, PinRole
from services.halcompiler.mcus.RemoraRouterMapper import RemoraRouterMapper


def _request(signal: str, role: PinRole, pin_string: str, owner: str = "endstop_x") -> PinRequest:
    return PinRequest(signal=signal, role=role, pin=PinStringMapper.from_string(pin_string), owner=owner)


def test_base_fragment_loads_the_spi_component_with_the_configured_divider():
    fragment = RemoraRouterMapper.base_fragment({"id": "mcu", "parameters": {"spi_clk_div": 32}})
    assert "loadrt remora-spi SPI_clk_div=32" in fragment.loadrt


def test_base_fragment_falls_back_to_the_documented_default_divider():
    fragment = RemoraRouterMapper.base_fragment({"id": "mcu"})
    assert "loadrt remora-spi SPI_clk_div=64" in fragment.loadrt


def test_lpc_chip_loads_the_lpc_component_with_no_arguments():
    fragment = RemoraRouterMapper.base_fragment({"id": "mcu", "parameters": {"chip": "lpc17xx"}})
    assert fragment.loadrt == ["loadrt remora_lpc"]


def test_base_fragment_wires_the_spi_estop_watchdog_chain():
    fragment = RemoraRouterMapper.base_fragment({"id": "mcu"})
    assert "net user-enable-out <= iocontrol.0.user-enable-out => remora.SPI-enable" in fragment.nets
    assert "net user-request-enable <= iocontrol.0.user-request-enable => remora.SPI-reset" in fragment.nets
    assert "net remora-status <= remora.SPI-status => iocontrol.0.emc-enable-in" in fragment.nets


def test_base_fragment_addf_order_sandwiches_motion_at_order_one():
    """`remora.read`(0) -> motion(1, from MotionSystemHalMapper) ->
    `remora.update-freq`/`remora.write`(2) — matches the real
    `ender3.hal` thread-attachment block exactly."""
    fragment = RemoraRouterMapper.base_fragment({"id": "mcu"})
    by_func = {a.func: a.order for a in fragment.addf}
    assert by_func["remora.read"] == 0
    assert by_func["remora.update-freq"] == 2
    assert by_func["remora.write"] == 2
    assert all(a.thread == "servo-thread" for a in fragment.addf)


def test_endstop_requests_get_zero_padded_input_indices_in_order():
    requests = [
        _request("endstop_x-sw", PinRole.ENDSTOP, "PC0"),
        _request("endstop_y-sw", PinRole.ENDSTOP, "PC1", owner="endstop_y"),
    ]
    fragment = RemoraRouterMapper.route(requests)
    assert "net endstop_x-sw remora.input.00" in fragment.nets
    assert "net endstop_y-sw remora.input.01" in fragment.nets


def test_endstop_firmware_module_carries_pullup_and_invert_as_pin_flags():
    fragment = RemoraRouterMapper.route([_request("endstop_x-sw", PinRole.ENDSTOP, "^!PC0")])
    module = fragment.firmware_modules[0].module
    assert module == {
        "Thread": "Servo",
        "Type": "DigitalPin",
        "Comment": "endstop_x",
        "Pin": "!^PC0",
        "Mode": "Input",
        "Data Bit": 0,
    }


def test_non_endstop_roles_are_ignored():
    """Phase 2 is motion-only — no heater/spindle SP/PV routing yet."""
    fragment = RemoraRouterMapper.route([_request("s-step", PinRole.STEP, "PF13")])
    assert fragment.nets == []
    assert fragment.firmware_modules == []
