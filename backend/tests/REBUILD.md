# Test Rebuild Backlog

Contracts that lost or never had coverage in the backend OOP
refactor. Pick one per iteration; prefer focused unit tests over
`TestClient` boilerplate unless the contract is HTTP-shaped.

## P1 — small, high value

- [x] ~~`exceptions/http.py` — `NotFoundError` / `BadRequestError` /
      `ConflictError` raise correct status codes and preserve
      `__cause__` chaining.~~ *(Done: migrated `modules/machineconfig/router.py`
      and `modules/macros/router.py` to the typed class hierarchy; the
      `services/http_errors.py` shim has been removed. Still no
      dedicated unit test — see the deleted `test_http_errors.py`.)*
- [ ] `exceptions/http.py` — add a focused unit test asserting the
      three error classes raise the right status code, populate the
      `detail` field, and preserve `__cause__` chaining. (The deleted
      `test_http_errors.py` covered this contract for the old
      `raise_*` helpers; port the assertions to the class-based API.)
- [ ] `modules/tools/dtos/*` — frozen-dataclass immutability:
      `frozen=True` is enforced; mutating raises
      `FrozenInstanceError`.
- [ ] `modules/tools/mapper/*` — round-trip
      `from_dict_to_*Pins` → `to_state_dto` for each tool type
      (digital spindle, analog spindle, heater, extruder).

## P2 — service state machines

- [ ] `SpindleDigitalService.set_spindle` rejects mid-spin
      direction reversal with 409 (the contract that the previous
      `clean_env` fixture was silently papering over).
- [ ] `HeaterService.set_heater` rejects when target exceeds
      `max_temp` from the pins DTO.
- [ ] `ExtruderService` G91 / G90 wrapping: assert the MDI
      dispatch order (`G91` → `G1 E{dist} F{speed}` → `G90`).

## P3 — registry / integration

- [ ] `ModuleRegistry` rejects a candidate missing `manifest`,
      `get_router`, or `on_load` (raises `ContractViolation`).
- [ ] `ModuleRegistry._build_default_settings_router` mounts the
      canonical four settings endpoints **before** the module
      router (so `…/{name}/settings` cannot be shadowed by a
      module-owned route).
- [ ] `EventBus` deduplicates rapid `state.*` publishes within
      the same tick.

## P4 — HAL pin subscription

- [ ] `tools/module.py::_subscribe_spindle_pins` is idempotent
      under repeated `on_load` (subsequent calls don't
      double-subscribe).
- [ ] `apply_spindle_pin` re-export from `hardware.connection` —
      guard against accidental removal by asserting
      `from hardware.connection import apply_spindle_pin` resolves.