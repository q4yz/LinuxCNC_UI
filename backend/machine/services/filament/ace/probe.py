"""Bring-up check for a real ACE Pro: connect, print info and status.

    cd backend/machine
    PYTHONPATH=../common python -m services.filament.ace.probe /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00
    ... --feed 1 --length 20 --speed 10     # push 20 mm of slot 1 (then --unwind to pull it back)

Read-only unless --feed / --unwind / --dry is given. Run it with the
backends stopped (one program per serial port).
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .client import AceClient
from .transport import SerialTransport


async def _main(args: argparse.Namespace) -> int:
    client = AceClient(SerialTransport(args.port))
    client.start()
    try:
        if not await client.wait_connected(5):
            print(f"no connection: {client.last_error or 'timeout'}", file=sys.stderr)
            return 1
        info = await client.get_info()
        print(f"model {info.model!r}, firmware {info.firmware}, boot {info.boot_firmware}, {info.slots} slots")
        status = await client.get_status()
        print(f"status {status.status} {status.action}, dryer {status.dryer.status}, temp {status.temp}")
        for slot in status.slots:
            print(f"  slot {slot.index}: {slot.status:6} {slot.type:5} {slot.brand} color={slot.color} rfid={slot.rfid}")
        if args.feed is not None:
            await client.feed(args.feed, args.length, args.speed)
            print(f"feeding slot {args.feed}: {args.length} mm at {args.speed} mm/s")
            await client.wait_ready(args.length / args.speed + 10)
        if args.unwind is not None:
            await client.unwind(args.unwind, args.length, args.speed)
            print(f"unwinding slot {args.unwind}: {args.length} mm at {args.speed} mm/s")
            await client.wait_ready(args.length / args.speed + 10)
        if args.dry is not None:
            await client.start_drying(args.dry, args.minutes)
            print(f"drying at {args.dry} °C for {args.minutes} min (stop with --stop-dry)")
        if args.stop_dry:
            await client.stop_drying()
        print(f"raw status: {status.raw}")
        return 0
    finally:
        await client.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--feed", type=int, metavar="SLOT")
    parser.add_argument("--unwind", type=int, metavar="SLOT")
    parser.add_argument("--length", type=float, default=20.0, help="mm (default 20)")
    parser.add_argument("--speed", type=float, default=10.0, help="mm/s (default 10)")
    parser.add_argument("--dry", type=float, metavar="TEMP_C")
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--stop-dry", action="store_true")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
