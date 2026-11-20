"""Startup: pins are created, the HAL component locked, then the start
values written — a write before ``initialize_component`` is lost."""
from __future__ import annotations

import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main.py"


def _setup() -> ast.FunctionDef:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "setup_hal_pins")


def test_both_start_paths_use_the_shared_setup():
    source = MAIN.read_text(encoding="utf-8")
    # the definition + lifespan (mock) + __main__ (real HAL)
    assert source.count("setup_hal_pins()") == 3
    assert source.count(".preload_hal_pins()") == 1  # only inside setup_hal_pins


def test_start_values_are_written_after_the_component_is_ready():
    calls = [
        (n.func.attr, n.lineno)
        for n in ast.walk(_setup())
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    ]
    ready = next(line for name, line in calls if name == "initialize_component")
    assert all(line < ready for name, line in calls if name == "preload_hal_pins")
    assert all(line > ready for name, line in calls if name in ("apply_initial", "apply_start_values"))


def test_preloading_writes_nothing(monkeypatch):
    """The four services that wrote in preload now only create pins."""
    from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
    from services.PidCalibrateService import get_pid_calibrate_service
    from services.PrintTuningService import get_print_tuning_service
    from services.ResonanceService import get_resonance_service
    from services.ShaperService import get_shaper_service

    writes: list[str] = []
    monkeypatch.setattr(ReadWriteDynamicHalPin, "set_value", lambda self, value: writes.append(self.pin))
    for service in (get_print_tuning_service(), get_shaper_service(), get_pid_calibrate_service(), get_resonance_service()):
        service.preload_hal_pins()
    assert writes == []
    get_print_tuning_service().apply_initial()
    assert {"flow", "z-offset", "pressure-advance"} <= set(writes)
