"""AceService: the HAL hand-over as ace_change.ngc drives it, the stored
slot, console commands and the REST routes — against the simulated ACE."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from core.ace_contract import NO_SLOT
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.filament.ace.sim import SimulatedAce
from services.filament.AceService import AcePins, AceService
from tests.test_ace_changer import HUB_AT, config


class FakePin:
    def __init__(self, value=None):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


def make_service(tmp_path, sim: SimulatedAce | None = None) -> tuple[AceService, SimulatedAce, AcePins]:
    cfg = config()
    sim = sim or SimulatedAce(time_scale=0.002)
    pins = AcePins(request=FakePin(False), slot=FakePin(0.0), done=FakePin(False), error=FakePin(False),
                   current=FakePin(-1.0))

    def sensor(name):
        return {"toolhead": sim.filament_at(cfg.bowden_length), "hub": sim.filament_at(HUB_AT)}.get(name)

    service = AceService(transport_factory=lambda _cfg: sim, sensor=sensor, pins=pins, config=cfg,
                         state_file=tmp_path / "ace_state.json", poll_s=0.005)
    service.changer_poll = 0.002
    return service, sim, pins


async def started(service: AceService) -> None:
    await service.start()
    assert service.changer is not None
    service.changer._poll_s = 0.002
    assert await service.client.wait_connected(2)


async def until(condition, timeout=20.0):
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


def test_the_ngc_hand_over(tmp_path):
    async def go():
        service, sim, pins = make_service(tmp_path)
        await started(service)
        # M68 E3 Q1 / M64 P3: load slot 1
        pins.slot.value, pins.request.value = 1.0, True
        await until(lambda: pins.done.value)
        assert pins.error.value is False and pins.current.value == 1.0
        assert sim.feed_assist == {1}
        assert json.loads((tmp_path / "ace_state.json").read_text())["current_slot"] == 1
        # M65 P3: done / error cleared
        pins.request.value = False
        await until(lambda: not pins.done.value)
        # a failing change: slot 2 is empty -> done with error, and a message
        pins.slot.value, pins.request.value = 2.0, True
        await until(lambda: pins.done.value)
        assert pins.error.value is True and "Slot 3 has no filament" in service.last_error
        assert service.state().last_error == service.last_error
        pins.request.value = False
        await until(lambda: not pins.error.value and not pins.done.value)
        # the operator fixes it (filament into slot 3), Resume asks again
        sim.slots[2].status = "ready"
        pins.request.value = True
        await until(lambda: pins.done.value)
        assert pins.error.value is False and pins.current.value == 2.0 and sim.tip[1] == 0.0
        pins.request.value = False
        await service.stop()

    run(go())


def test_the_loaded_slot_survives_a_restart(tmp_path):
    async def go():
        service, sim, pins = make_service(tmp_path)
        await started(service)
        pins.slot.value, pins.request.value = 0.0, True
        await until(lambda: pins.done.value)
        await service.stop()
        # same filament path, a new backend process
        again, _, pins2 = make_service(tmp_path, sim=sim)
        again.apply_initial()
        assert pins2.current.value == 0.0
        await started(again)
        await until(lambda: again.state().current_slot == 0)
        state = again.state()
        assert state.toolhead_sensor is True and state.slots[0].status == "ready" and state.connected
        await again.stop()

    run(go())


def test_mdi_and_console_commands(tmp_path):
    async def go():
        service, sim, _ = make_service(tmp_path)
        assert service.translate_mdi("T2") == "M640 P2"
        assert service.translate_mdi("ACE_CHANGE_TOOL TOOL=-1") == "M640 P-1"
        assert service.translate_mdi("G1 X1") == "G1 X1"
        await started(service)
        assert await asyncio.to_thread(service.run_command, "ACE_FEED INDEX=0 LENGTH=10 SPEED=20")
        feed = sim.log.methods.index("feed_filament")
        assert sim.log.params[feed] == {"index": 0, "length": 10.0, "speed": 20.0}
        await service.client.wait_ready(5, poll_s=0.01)
        assert await asyncio.to_thread(service.run_command, "ACE_START_DRYING TEMP=45 DURATION=60")
        assert service.client.status is not None
        assert (await service.client.get_status()).dryer.drying
        assert await asyncio.to_thread(service.run_command, "ACE_STOP_DRYING")
        assert not await asyncio.to_thread(service.run_command, "G1 X1")
        await service.stop()
        # without an [ace]: nothing is translated
        assert AceService(config=None).translate_mdi("T1") == "T1"

    run(go())


def test_rest_routes(tmp_path, monkeypatch):
    import routers.ace as ace_router

    service, _sim, pins = make_service(tmp_path)
    mdi: list[str] = []

    class FakeState:
        def run_mdi(self, command):
            mdi.append(command)

    import services.machine.StateService as state_module

    monkeypatch.setattr(ace_router, "get_ace_service", lambda: service)
    monkeypatch.setattr(state_module, "get_state_service", lambda: FakeState())

    @asynccontextmanager
    async def lifespan(_app):
        await started(service)
        yield
        await service.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(ace_router.router)
    with TestClient(app) as client:
        state = client.get("/api/v1/ace").json()
        assert state["configured"] and state["connected"] and len(state["slots"]) == 4
        assert state["current_slot"] == NO_SLOT and state["slots"][1]["color"] == [255, 0, 0]
        assert client.post("/api/v1/ace/change", json={"slot": 1}).status_code == 200
        assert mdi == ["M640 P1"]  # through MDI: the NGC's motion half runs too
        assert client.post("/api/v1/ace/change", json={"slot": 9}).status_code == 422
        assert client.post("/api/v1/ace/slots/0/feed", json={"length": 10, "speed": 20}).status_code == 200
        assert client.post("/api/v1/ace/slots/7/feed", json={"length": 10}).status_code == 422
        assert client.post("/api/v1/ace/dryer", json={"temp": 45, "minutes": 30}).json()["dryer"]["drying"]
        assert client.delete("/api/v1/ace/dryer").status_code == 200
        assert client.put("/api/v1/ace/current", json={"slot": 3}).json()["current_slot"] == 3
        assert pins.current.value == 3.0


def test_a_machine_without_an_ace(tmp_path):
    service = AceService(config=None, state_file=tmp_path / "s.json")
    assert service.state().configured is False
    run(service.start())  # nothing to start
    assert service.client is None
