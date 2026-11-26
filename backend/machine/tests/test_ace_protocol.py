"""ACE Pro protocol layer: frames, the client, against a simulated ACE."""
from __future__ import annotations

import asyncio
import json

import pytest
from services.filament.ace import (
    AceClient,
    AceError,
    AceStatus,
    AceTimeout,
    AceUnavailable,
    FrameDecoder,
    FrameError,
    crc16_mcrf4xx,
    encode_frame,
)
from services.filament.ace.frame import HEADER, MAX_PAYLOAD, _frame
from services.filament.ace.sim import SimulatedAce

# -- frames -------------------------------------------------------------------- #


def test_crc_is_crc16_mcrf4xx():
    assert crc16_mcrf4xx(b"123456789") == 0x6F91  # the catalogue's check value


def test_frame_layout():
    frame = encode_frame({"id": 1, "method": "get_status"})
    payload = b'{"id":1,"method":"get_status"}'
    assert frame[:2] == HEADER
    assert int.from_bytes(frame[2:4], "little") == len(payload)
    assert frame[4:-3] == payload
    assert int.from_bytes(frame[-3:-1], "little") == crc16_mcrf4xx(payload)
    assert frame[-1] == 0xFE


def test_frames_the_ace_would_freeze_on_are_refused():
    with pytest.raises(FrameError):
        encode_frame({"id": 1, "method": "x", "params": {"pad": "a" * MAX_PAYLOAD}})
    with pytest.raises(FrameError):
        encode_frame({"id": 1, "x": object()})


def test_a_crc_that_reads_like_a_header_is_avoided():
    # find a message whose CRC would be FF AA, then check it is re-padded
    for i in range(200_000):
        message = {"id": i, "method": "get_status"}
        payload = json.dumps(message, separators=(",", ":")).encode()
        if crc16_mcrf4xx(payload).to_bytes(2, "little") == HEADER:
            break
    else:
        pytest.skip("no colliding id in range")
    frame = encode_frame(message)
    assert frame[-3:-1] != HEADER
    assert FrameDecoder().feed(frame)[0]["id"] == i


def test_decoder_handles_split_frames_garbage_and_bad_crc():
    decoder = FrameDecoder()
    good = encode_frame({"id": 7, "result": {"a": 1}})
    corrupt = bytearray(encode_frame({"id": 8}))
    corrupt[6] ^= 0x01  # break the payload: CRC fails
    stream = b"\x00\x13garbage" + bytes(corrupt) + good[:5]
    assert decoder.feed(stream) == []
    assert decoder.feed(good[5:]) == [{"id": 7, "result": {"a": 1}}]
    assert decoder.dropped == 1
    # a header with an absurd length does not swallow the stream
    huge = HEADER + (5000).to_bytes(2, "little") + b"xx"
    assert decoder.feed(huge + good) == [{"id": 7, "result": {"a": 1}}]
    # a lone FF at the end may start the next frame
    assert decoder.feed(good + b"\xff") == [{"id": 7, "result": {"a": 1}}]
    assert decoder.feed(good[1:]) == [{"id": 7, "result": {"a": 1}}]


def test_non_object_json_is_dropped():
    decoder = FrameDecoder()
    assert decoder.feed(_frame(b"[1,2]")) == []
    assert decoder.dropped == 1


# -- the client against the simulator ----------------------------------------- #


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


async def connected(sim: SimulatedAce, **kwargs) -> AceClient:
    client = AceClient(sim, request_timeout=0.3, keepalive_s=0.2, reconnect_s=0.05, **kwargs)
    client.start()
    assert await client.wait_connected(2)
    for _ in range(100):  # get_info is the first request after connecting
        if client.info is not None:
            break
        await asyncio.sleep(0.01)
    return client


def test_connect_reads_info_and_status():
    async def go():
        sim = SimulatedAce()
        client = await connected(sim)
        assert client.info.model == "Anycubic Color Engine Pro" and client.info.slots == 4
        status = await client.get_status()
        assert isinstance(status, AceStatus) and status.ready
        assert [s.has_filament for s in status.slots] == [True, True, False, True]
        assert status.slots[1].color == (255, 0, 0) and status.slots[3].type == "PETG"
        info = await client.get_filament_info(3)
        assert info.extruder_temp == (190.0, 230.0) and info.diameter == 1.75
        await client.stop()

    run(go())


def test_feed_is_busy_until_done_and_validated():
    async def go():
        sim = SimulatedAce(time_scale=0.01)  # 100 mm @ 50 mm/s -> 20 ms
        client = await connected(sim)
        await client.feed(1, 100, 50)
        assert sim.log.params[-1] == {"index": 1, "length": 100, "speed": 50}
        status = await client.wait_ready(2, poll_s=0.01)
        assert status.ready
        # a busy ACE refuses a second move with an error code
        await client.feed(0, 1000, 10)
        with pytest.raises(AceError) as busy:
            await client.feed(1, 10, 10)
        assert busy.value.code == 1
        await client.stop_feed(0)
        # nothing invalid reaches the ACE
        sent = len(sim.log.methods)
        for bad in (lambda: client.feed(4, 10, 10), lambda: client.feed(0, 0, 10), lambda: client.feed(0, 10, 500),
                    lambda: client.unwind(0, 10, 10, mode=7), lambda: client.start_drying(80, 60),
                    lambda: client.start_drying(45, 0)):
            with pytest.raises(ValueError):
                await bad()
        assert len(sim.log.methods) == sent
        await client.stop()

    run(go())


def test_empty_slot_feed_feed_assist_and_dryer():
    async def go():
        sim = SimulatedAce(time_scale=0.001)
        client = await connected(sim)
        with pytest.raises(AceError, match="slot empty"):
            await client.feed(2, 10, 10)
        await client.start_feed_assist(3)
        assert sim.feed_assist == {3}
        await client.stop_feed_assist(3)  # answers with msg "" — still a success
        assert sim.feed_assist == set()
        await client.start_drying(50, 120)
        status = await client.get_status()
        assert status.dryer.drying and status.dryer.target_temp == 50
        await client.stop_drying()
        assert not (await client.get_status()).dryer.drying
        await client.stop()

    run(go())


def test_keepalive_keeps_the_link_and_the_status_fresh():
    async def go():
        statuses: list[AceStatus] = []
        sim = SimulatedAce(silence_disconnect_s=0.6)
        client = await connected(sim, on_status=statuses.append)
        await asyncio.sleep(1.5)  # longer than the ACE tolerates silence
        assert client.connected and sim.opens == 1
        assert len(statuses) >= 3 and client.status is not None
        await client.stop()

    run(go())


def test_a_silent_host_loses_the_link_and_reconnects():
    async def go():
        sim = SimulatedAce(silence_disconnect_s=0.6)
        client = AceClient(sim, request_timeout=0.3, keepalive_s=5.0, reconnect_s=0.05)  # keep-alive too slow
        client.start()
        assert await client.wait_connected(2)
        await asyncio.sleep(1.0)
        # the simulated ACE reset its link; the client reopened it
        assert sim.opens >= 2
        assert await client.wait_connected(2)
        await client.stop()

    run(go())


def test_unplugged_requests_fail_fast_and_reconnect_later():
    async def go():
        events: list[bool] = []
        sim = SimulatedAce()
        client = await connected(sim, on_connection=events.append)
        sim.unplugged = True
        for _ in range(100):
            if not client.connected:
                break
            await asyncio.sleep(0.01)
        with pytest.raises(AceUnavailable):
            await client.get_status()
        sim.unplugged = False
        assert await client.wait_connected(2)
        assert (await client.get_status()).ready
        assert events[:3] == [True, False, True]
        await client.stop()

    run(go())


def test_lost_answers_time_out_and_garbage_is_skipped():
    async def go():
        sim = SimulatedAce()
        client = await connected(sim)
        sim.drop_next = 1
        with pytest.raises(AceTimeout):
            await client.get_status()
        sim.garbage_before_next = b"\xff\xaa\x09\x00junk\x00\xfe\x01\x02"
        assert (await client.get_status()).ready  # the next answer still arrives
        sim.error_methods["drying_stop"] = (5, "dryer fault")
        with pytest.raises(AceError) as err:
            await client.stop_drying()
        assert (err.value.code, err.value.msg) == (5, "dryer fault")
        await client.stop()

    run(go())


def test_requests_are_serialised_one_in_flight():
    async def go():
        sim = SimulatedAce()
        client = await connected(sim)
        results = await asyncio.gather(*(client.get_status() for _ in range(10)))
        assert all(r.ready for r in results)
        await client.stop()

    run(go())


def test_lenient_parsing_of_unexpected_answers():
    status = AceStatus.parse({"status": "busy", "action": None, "slots": [{"status": "ready", "color": [300, -1]},
                                                                           "junk"], "dryer_status": "?"})
    assert status.action == "" and not status.ready and not status.dryer.drying
    assert len(status.slots) == 1 and status.slots[0].color is None


def test_the_protocol_package_stands_alone():
    """No LinuxCNC, HAL or backend imports: it can be lifted out as a package."""
    import pathlib
    import re

    package = pathlib.Path(__file__).resolve().parents[1] / "services" / "filament" / "ace"
    allowed = {"argparse", "asyncio", "collections", "contextlib", "dataclasses", "itertools", "json", "logging", "sys", "time",
               "typing", "__future__", "serial"}
    for path in package.glob("*.py"):
        for name in re.findall(r"^\s*(?:from|import)\s+([\w.]+)", path.read_text(encoding="utf-8"), re.MULTILINE):
            if name.startswith("."):
                continue
            assert name.split(".")[0] in allowed, f"{path.name} imports {name}"
