"""ParportRouterMapper — `.agent/component/mcu_parallelport.md` § 3-4."""

from __future__ import annotations

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import PinRequest, PinRole
from services.halcompiler.mcus.ParportRouterMapper import ParportRouterMapper


def _request(signal: str, role: PinRole, pin_string: str, owner: str = "x") -> PinRequest:
    return PinRequest(signal=signal, role=role, pin=PinStringMapper.from_string(pin_string), owner=owner)


def test_base_fragment_uses_declared_parameters():
    mcu = {"id": "mcu", "parameters": {"address": "0", "direction": "out", "reset_time": 3000}}
    fragment = ParportRouterMapper.base_fragment(mcu)

    assert 'loadrt hal_parport cfg="0 out"' in fragment.loadrt
    assert "setp parport.0.reset-time 3000" in fragment.setp


def test_base_fragment_falls_back_to_documented_defaults():
    fragment = ParportRouterMapper.base_fragment({"id": "mcu"})
    assert 'loadrt hal_parport cfg="0 out"' in fragment.loadrt
    assert "setp parport.0.reset-time 2500" in fragment.setp


def test_base_fragment_addf_order_is_read_write_reset():
    fragment = ParportRouterMapper.base_fragment({"id": "mcu"})
    order = [a.func for a in sorted(fragment.addf, key=lambda a: a.order)]
    assert order == ["parport.0.read", "parport.0.write", "parport.0.reset"]


def test_step_gets_reset_flag_dir_and_enable_do_not():
    requests = [
        _request("s-step", PinRole.STEP, "02"),
        _request("s-dir", PinRole.DIR, "03"),
        _request("s-enable", PinRole.ENABLE, "14"),
    ]
    fragment = ParportRouterMapper.route(requests)

    assert "setp parport.0.pin-02-out-reset 1" in fragment.setp
    assert not any("pin-03-out-reset" in s for s in fragment.setp)
    assert not any("pin-14-out-reset" in s for s in fragment.setp)


def test_invert_flag_is_carried_through_to_out_invert():
    requests = [_request("s-dir", PinRole.DIR, "!03")]
    fragment = ParportRouterMapper.route(requests)
    assert "setp parport.0.pin-03-out-invert 1" in fragment.setp

    requests = [_request("s-dir", PinRole.DIR, "07")]
    fragment = ParportRouterMapper.route(requests)
    assert "setp parport.0.pin-07-out-invert 0" in fragment.setp


def test_output_roles_get_a_consumer_net():
    fragment = ParportRouterMapper.route([_request("s-step", PinRole.STEP, "08")])
    assert "net s-step => parport.0.pin-08-out" in fragment.nets


def test_endstop_picks_in_or_in_not_by_invert_never_a_setp():
    plain = ParportRouterMapper.route([_request("home", PinRole.ENDSTOP, "12")])
    assert "net home <= parport.0.pin-12-in" in plain.nets
    assert not plain.setp

    inverted = ParportRouterMapper.route([_request("home", PinRole.ENDSTOP, "!13")])
    assert "net home <= parport.0.pin-13-in-not" in inverted.nets
    assert not inverted.setp


def test_pin_ids_are_zero_padded_to_two_digits():
    fragment = ParportRouterMapper.route([_request("s-step", PinRole.STEP, "2")])
    assert "net s-step => parport.0.pin-02-out" in fragment.nets


def test_non_numeric_pin_ids_pass_through_unpadded():
    """A parport router should never see one, but must not corrupt it either."""
    fragment = ParportRouterMapper.route([_request("s-step", PinRole.STEP, "PF13")])
    assert "net s-step => parport.0.pin-PF13-out" in fragment.nets
