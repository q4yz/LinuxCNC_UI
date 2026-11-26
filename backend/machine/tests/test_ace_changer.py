"""The ACE's half of a tool change (AceChanger) against the simulated ACE,
with simulated filament sensors on its filament path."""
from __future__ import annotations

import asyncio

import pytest
from core.ace_contract import NO_SLOT, UNKNOWN_SLOT
from models.machineconfig.HardwareJsonModels import Ace
from services.filament.ace import AceClient
from services.filament.ace.sim import SimulatedAce
from services.filament.AceChanger import AceChangeError, AceChanger

HUB_AT = 50.0


def config(**overrides) -> Ace:
    values = dict(
        serial="sim", toolhead_sensor="toolhead", hub_sensor="hub", bowden_length=900, feed_speed=25,
        retract_speed=25, approach_length=100, approach_speed=10, unload_length=950, timeout=180, park_x=0,
        park_y=0, z_lift=5, cutter=True, cutter_speed=50, cut_retract=30, sensor_to_nozzle=60, load_speed=5,
        purge_length=40, purge_speed=3,
    )
    values.update(overrides)
    return Ace(**values)


async def rig(cfg: Ace | None = None, sim: SimulatedAce | None = None):
    cfg = cfg or config()
    sim = sim or SimulatedAce(time_scale=0.002)
    client = AceClient(sim, request_timeout=0.5, keepalive_s=0.3, reconnect_s=0.05)
    client.start()
    assert await client.wait_connected(2)
    slots: list[int] = []

    def sensor(name: str) -> bool | None:
        return {"toolhead": sim.filament_at(cfg.bowden_length), "hub": sim.filament_at(HUB_AT)}.get(name)

    changer = AceChanger(client, cfg, sensor, poll_s=0.002, on_slot=slots.append)
    return sim, client, changer, slots


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


def test_load_feeds_to_the_toolhead_sensor_and_assists():
    async def go():
        sim, client, changer, slots = await rig()
        await changer.change(0)
        assert changer.current == 0 and slots[-1] == 0
        # stopped at the sensor (the simulator runs 500x real time: a 2 ms
        # poll overshoots ~10 mm here, ~0.2 mm at a real 10 mm/s)
        assert 900 <= sim.tip[0] < 950
        assert sim.feed_assist == {0}
        assert sim.log.methods.count("feed_filament") == 2  # fast, then the slow approach
        await client.stop()

    run(go())


def test_change_unwinds_the_old_slot_first():
    async def go():
        sim, client, changer, _ = await rig()
        await changer.change(0)
        await changer.change(1)
        assert changer.current == 1 and sim.tip[0] == 0.0 and sim.tip[1] >= 900
        assert sim.feed_assist == {1}
        calls = sim.log.methods
        assert calls.index("stop_feed_assist") < calls.index("unwind_filament") < len(calls) - 1
        # the same slot again: nothing to do
        before = len(sim.log.methods)
        await changer.change(1)
        assert len(sim.log.methods) == before
        # unload only
        await changer.change(NO_SLOT)
        assert changer.current == NO_SLOT and sim.tip[1] == 0.0
        await client.stop()

    run(go())


def test_an_empty_slot_is_refused_before_anything_moves():
    async def go():
        sim, client, changer, _ = await rig()
        with pytest.raises(AceChangeError, match="Slot 3 has no filament"):
            await changer.change(2)
        assert "feed_filament" not in sim.log.methods
        await client.stop()

    run(go())


@pytest.mark.parametrize("jam, message", [(20.0, "did not reach the hub sensor"),
                                          (600.0, "did not reach the toolhead sensor")])
def test_a_jam_fails_and_winds_the_filament_back(jam, message):
    async def go():
        sim = SimulatedAce(time_scale=0.002)
        sim.jam_after[3] = jam
        sim, client, changer, _ = await rig(sim=sim)
        with pytest.raises(AceChangeError, match=message):
            await changer.change(3)
        assert changer.current == NO_SLOT
        assert sim.tip[3] == 0.0  # pulled back: the retry starts clean
        await client.stop()

    run(go())


def test_unknown_filament_at_the_toolhead_is_not_guessed():
    async def go():
        sim, client, changer, _ = await rig()
        sim.tip[0] = 950.0  # loaded by hand, the changer does not know
        with pytest.raises(AceChangeError, match="not known from which slot"):
            await changer.change(1)
        assert "unwind_filament" not in sim.log.methods
        # the operator says which slot it is: the change works
        changer.set_current(0)
        await changer.change(1)
        assert changer.current == 1
        await client.stop()

    run(go())


def test_an_unload_that_leaves_filament_at_a_sensor_fails():
    async def go():
        _sim, client, changer, _ = await rig(cfg=config(unload_length=100))  # not far enough back
        await changer.change(0)
        with pytest.raises(AceChangeError, match="hub sensor still sees filament"):
            await changer.change(1)
        assert changer.current == 0  # still the loaded one
        await client.stop()

    run(go())


def test_ace_errors_become_change_errors_and_unreadable_sensors_too():
    async def go():
        sim, client, changer, _ = await rig()
        sim.error_methods["feed_filament"] = (9, "motor fault")
        with pytest.raises(AceChangeError, match="motor fault"):
            await changer.change(0)
        await client.stop()
        broken = AceChanger(client, config(), lambda name: None)
        with pytest.raises(AceChangeError, match="cannot be read"):
            broken.toolhead_loaded()

    run(go())


def test_reconcile_trusts_the_stored_slot_only_with_the_sensor():
    async def go():
        sim, client, changer, _ = await rig()
        changer.set_current(2)
        assert changer.reconcile() == NO_SLOT  # nothing at the toolhead: not loaded
        sim.tip[1] = 950.0
        assert changer.reconcile() == UNKNOWN_SLOT  # something is, from an unknown slot
        changer.set_current(1)
        assert changer.reconcile() == 1
        await client.stop()

    run(go())
