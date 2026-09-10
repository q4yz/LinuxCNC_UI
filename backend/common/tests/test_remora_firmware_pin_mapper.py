"""RemoraFirmwarePinMapper — STM32 pin -> Remora `config.txt` spelling.

Every underscored example here is quoted verbatim from the real,
working `machine_config/example/ender3/config.txt`.
"""

from __future__ import annotations

from mappers.machineconfig import RemoraFirmwarePinMapper


def test_inserts_an_underscore_between_port_and_number():
    assert RemoraFirmwarePinMapper.to_firmware_pin("PF13") == "PF_13"
    assert RemoraFirmwarePinMapper.to_firmware_pin("PA0") == "PA_0"
    assert RemoraFirmwarePinMapper.to_firmware_pin("PG5") == "PG_5"
    assert RemoraFirmwarePinMapper.to_firmware_pin("PC15") == "PC_15"


def test_already_underscored_pins_pass_through_unchanged():
    assert RemoraFirmwarePinMapper.to_firmware_pin("PF_13") == "PF_13"


def test_non_stm32_shaped_pins_pass_through_unchanged():
    """A router that hands this something other than an STM32 port
    pin has bigger problems than formatting — never mangle it."""
    assert RemoraFirmwarePinMapper.to_firmware_pin("mcu:PF13") == "mcu:PF13"
    assert RemoraFirmwarePinMapper.to_firmware_pin("") == ""
    assert RemoraFirmwarePinMapper.to_firmware_pin("D2") == "D2"
