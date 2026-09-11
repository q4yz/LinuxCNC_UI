"""RemoraRouterMapper — `.agent/component/mcu_spi_remora.md` § 3-4."""

from __future__ import annotations

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import PinRequest, PinRole
from services.halcompiler.mcus.RemoraRouterMapper import RemoraRouterMapper


def _request(
    signal: str,
    role: PinRole,
    pin_string: str,
    owner: str = "endstop_x",
    sensor_type: str | None = None,
) -> PinRequest:
    return PinRequest(
        signal=signal,
        role=role,
        pin=PinStringMapper.from_string(pin_string),
        owner=owner,
        sensor_type=sensor_type,
    )


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


def test_base_fragment_with_no_reset_pin_emits_no_firmware_module():
    fragment = RemoraRouterMapper.base_fragment({"id": "mcu"})
    assert fragment.firmware_modules == []


def test_base_fragment_emits_the_reset_pin_module_when_declared():
    """Module shape verified against the real, working
    `machine_config/example/ender3/config.txt` — its very first
    module, before any joint or driver."""
    fragment = RemoraRouterMapper.base_fragment({"id": "mcu", "reset_pin": "PC15"})
    assert len(fragment.firmware_modules) == 1
    request = fragment.firmware_modules[0]
    assert request.mcu_id == "mcu"
    assert request.module == {
        "Name": "reset_pin",
        "Thread": "Servo",
        "Type": "Reset Pin",
        "Comment": "Reset pin",
        "Pin": "PC_15",
    }


def test_base_fragment_reset_pin_mcu_id_falls_back_to_the_mcu_record_id():
    fragment = RemoraRouterMapper.base_fragment({"id": "board_a", "reset_pin": "PC15"})
    assert fragment.firmware_modules[0].mcu_id == "board_a"


def test_endstop_requests_get_zero_padded_input_indices_in_order():
    requests = [
        _request("endstop_x-sw", PinRole.ENDSTOP, "PC0"),
        _request("endstop_y-sw", PinRole.ENDSTOP, "PC1", owner="endstop_y"),
    ]
    fragment = RemoraRouterMapper.route(requests)
    assert "net endstop_x-sw remora.input.00" in fragment.nets
    assert "net endstop_y-sw remora.input.01" in fragment.nets


def test_endstop_firmware_module_carries_pullup_and_invert_as_pin_flags():
    """Module shape verified against the real, working
    `machine_config/example/ender3/config.txt` — `"Type": "Digital
    Pin"` (with the space, not "DigitalPin"), a `"Name"` field, and
    the pin underscore-formatted."""
    fragment = RemoraRouterMapper.route([_request("endstop_x-sw", PinRole.ENDSTOP, "^!PC0")])
    module = fragment.firmware_modules[0].module
    assert module == {
        "Name": "endstop_endstop_x",
        "Thread": "Servo",
        "Type": "Digital Pin",
        "Comment": "endstop_x",
        "Pin": "!^PC_0",
        "Mode": "Input",
        "Data Bit": 0,
    }


def test_motion_roles_are_ignored():
    """STEP/DIR never reach a Remora router — class B has no HAL step/dir
    pin to route (the board owns the pulses)."""
    fragment = RemoraRouterMapper.route([_request("s-step", PinRole.STEP, "PF13")])
    assert fragment.nets == []
    assert fragment.firmware_modules == []


def test_analog_out_requests_get_sequential_sp_channels():
    requests = [
        _request("heater_bed-heater-SP", PinRole.ANALOG_OUT, "PB7", owner="heater_bed"),
        _request("heater_extruder-heater-SP", PinRole.ANALOG_OUT, "PE3", owner="heater_extruder"),
    ]
    fragment = RemoraRouterMapper.route(requests)
    assert "net heater_bed-heater-SP => remora.SP.0" in fragment.nets
    assert "net heater_extruder-heater-SP => remora.SP.1" in fragment.nets


def test_analog_out_requests_get_a_pwm_firmware_module():
    """Module shape verified against the real, working
    `machine_config/example/ender3/config.txt`'s `pwm_extruder` /
    `pwm_heater_bed` entries."""
    fragment = RemoraRouterMapper.route(
        [_request("heater_bed-heater-SP", PinRole.ANALOG_OUT, "PB7", owner="heater_bed")]
    )
    assert fragment.firmware_modules[0].module == {
        "Name": "pwm_heater_bed",
        "Thread": "Servo",
        "Type": "PWM",
        "Comment": "heater_bed",
        "SP[i]": 0,
        "PWM Pin": "PB_7",
    }


def test_analog_in_with_no_sensor_type_gets_no_firmware_module():
    """An honest gap, not "not yet implemented" — an unrecognised (or
    absent) `sensor_type` has no known thermistor curve, and
    fabricating one would silently misreport real temperatures."""
    fragment = RemoraRouterMapper.route(
        [_request("bed-PV", PinRole.ANALOG_IN, "PA0", owner="bed")]
    )
    assert fragment.firmware_modules == []


def test_analog_in_with_an_unrecognised_sensor_type_gets_no_firmware_module():
    fragment = RemoraRouterMapper.route(
        [_request("bed-PV", PinRole.ANALOG_IN, "PA0", owner="bed", sensor_type="EPCOS 100K")]
    )
    assert fragment.firmware_modules == []


def test_analog_in_with_a_known_sensor_type_gets_a_temperature_module():
    """Module shape (and the `beta`/`r0`/`t0` curve for "Generic 3950")
    verified against the real, working `machine_config/example/
    ender3/config.txt`'s `temp_extruder`/`temp_bed` modules."""
    fragment = RemoraRouterMapper.route(
        [_request("bed-PV", PinRole.ANALOG_IN, "PA0", owner="bed", sensor_type="Generic 3950")]
    )
    assert fragment.firmware_modules[0].module == {
        "Name": "temp_bed",
        "Thread": "Servo",
        "Type": "Temperature",
        "Comment": "bed",
        "PV[i]": 0,
        "Sensor": "Thermistor",
        "Thermistor": {
            "Pin": "PA_0",
            "beta": 3950,
            "r0": 100000,
            "t0": 25,
        },
    }


def test_analog_in_sensor_type_lookup_is_case_insensitive():
    fragment = RemoraRouterMapper.route(
        [_request("bed-PV", PinRole.ANALOG_IN, "PA0", owner="bed", sensor_type="GENERIC 3950")]
    )
    assert fragment.firmware_modules[0].module["Sensor"] == "Thermistor"


def test_analog_in_pv_index_still_advances_with_or_without_a_curve():
    requests = [
        _request("bed-PV", PinRole.ANALOG_IN, "PA0", owner="bed", sensor_type="Generic 3950"),
        _request("extruder-PV", PinRole.ANALOG_IN, "PA1", owner="extruder"),
    ]
    fragment = RemoraRouterMapper.route(requests)
    assert "net bed-PV <= remora.PV.0" in fragment.nets
    assert "net extruder-PV <= remora.PV.1" in fragment.nets
    assert fragment.firmware_modules[0].module["PV[i]"] == 0
    assert len(fragment.firmware_modules) == 1  # extruder has no known curve


def test_analog_in_requests_get_sequential_pv_channels():
    requests = [
        _request("bed-PV", PinRole.ANALOG_IN, "PA0", owner="bed"),
        _request("extruder-PV", PinRole.ANALOG_IN, "PA1", owner="extruder"),
    ]
    fragment = RemoraRouterMapper.route(requests)
    assert "net bed-PV <= remora.PV.0" in fragment.nets
    assert "net extruder-PV <= remora.PV.1" in fragment.nets


def test_digital_in_request_gets_a_digital_pin_module_named_distinctly_from_endstop():
    """Mechanically identical to ENDSTOP — same `remora.input.NN`,
    same "Digital Pin"/Input firmware shape — but the module's `Name`
    must not say "endstop_..." for something that isn't one (the
    E-stop's `fault_pin`, routed with `owner="estop"`)."""
    fragment = RemoraRouterMapper.route(
        [_request("estop-fault", PinRole.DIGITAL_IN, "PG6", owner="estop")]
    )
    assert "net estop-fault remora.input.00" in fragment.nets
    assert fragment.firmware_modules[0].module == {
        "Name": "digital_in_estop",
        "Thread": "Servo",
        "Type": "Digital Pin",
        "Comment": "estop",
        "Pin": "PG_6",
        "Mode": "Input",
        "Data Bit": 0,
    }


def test_endstop_and_digital_in_share_one_input_bit_space():
    """Both roles write into the same `remora.input.NN` array on the
    real board — they must not each start their own counter at 0 and
    collide on `Data Bit`."""
    requests = [
        _request("endstop_x-sw", PinRole.ENDSTOP, "PC0", owner="endstop_x"),
        _request("estop-fault", PinRole.DIGITAL_IN, "PG6", owner="estop"),
    ]
    fragment = RemoraRouterMapper.route(requests)
    assert "net endstop_x-sw remora.input.00" in fragment.nets
    assert "net estop-fault remora.input.01" in fragment.nets
    data_bits = {m.module["Data Bit"] for m in fragment.firmware_modules}
    assert data_bits == {0, 1}


def test_digital_out_request_is_an_honest_gap_not_a_crash():
    """No real reference `config.txt` shows a digital *output* module
    (every example is `Mode: Input`) — routing one through Remora
    produces no firmware module and no net, same "honest gap" class
    as ANALOG_IN's missing Temperature module, rather than a
    fabricated, unverified shape."""
    fragment = RemoraRouterMapper.route(
        [_request("estop-out", PinRole.DIGITAL_OUT, "PG7", owner="estop")]
    )
    assert fragment.nets == []
    assert fragment.firmware_modules == []


def test_endstop_and_analog_indices_do_not_collide():
    """Real ender3-shaped machine: endstops and heaters share one MCU.

    Each role must count its own index — an ANALOG_OUT request sitting
    between two ENDSTOP requests must not burn an endstop-input slot,
    and vice versa.
    """
    requests = [
        _request("endstop_x-sw", PinRole.ENDSTOP, "PC0", owner="endstop_x"),
        _request("heater_bed-heater-SP", PinRole.ANALOG_OUT, "PB7", owner="heater_bed"),
        _request("endstop_y-sw", PinRole.ENDSTOP, "PC1", owner="endstop_y"),
        _request("bed-PV", PinRole.ANALOG_IN, "PA0", owner="bed"),
    ]
    fragment = RemoraRouterMapper.route(requests)
    assert "net endstop_x-sw remora.input.00" in fragment.nets
    assert "net endstop_y-sw remora.input.01" in fragment.nets
    assert "net heater_bed-heater-SP => remora.SP.0" in fragment.nets
    assert "net bed-PV <= remora.PV.0" in fragment.nets
    # 2 endstops (Digital Pin) + 1 heater (PWM) — no module for the
    # ANALOG_IN request (no Temperature module yet, see above).
    digital_pins = [m for m in fragment.firmware_modules if m.module["Type"] == "Digital Pin"]
    assert {m.module["Data Bit"] for m in digital_pins} == {0, 1}
    assert len(fragment.firmware_modules) == 3
