"""Record what real INDI drivers define, as raw protocol XML, for tests and facades.

Connects twice to indiserver: one connection only listens and saves every
message (no BLOBs), the other connects the chosen devices so their full
property set is defined, waits for it to settle, then disconnects the devices it
connected (leaving the hardware as it was found). The output can be replayed by
a fake indiserver in tests and read to write device facades.

Typical use in the lab, with the devices plugged in and their drivers running:

    uv run --project server python dev/tools/indi_record.py \\
        --connect "ZWO CCD ASI2600MC Pro" --connect "Pegasus PPBA" \\
        -o dev/recordings/zwo-ppba.xml

Without --connect it records what is defined without connecting anything; with
--all it connects every device on the server.

Usage: uv run --project server python dev/tools/indi_record.py [options] -o <file>
"""

import argparse
import asyncio
import contextlib
import sys
import time
from pathlib import Path

from nocs.devices import Device, DeviceError
from nocs.indi import IndiClient
from nocs.indi.protocol import encode_get_properties


async def listen(host: str, port: int, out: Path, stop: asyncio.Event) -> int:
    reader, writer = await asyncio.open_connection(host, port, limit=2**24)
    writer.write(encode_get_properties())
    await writer.drain()
    size = 0
    with out.open("wb") as f:
        try:
            while not stop.is_set():
                read = asyncio.ensure_future(reader.read(256 * 1024))
                stopped = asyncio.ensure_future(stop.wait())
                await asyncio.wait({read, stopped}, return_when=asyncio.FIRST_COMPLETED)
                stopped.cancel()
                if not read.done():
                    read.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await read
                    break
                if not (data := read.result()):
                    break
                f.write(data)
                size += len(data)
        finally:
            writer.close()
    return size


async def wait_quiet(client: IndiClient, quiet: float, limit: float) -> None:
    """Wait until no property has been defined for ``quiet`` seconds."""

    def count() -> int:
        return sum(len(p) for p in client.devices.values())

    deadline = time.monotonic() + limit
    last, since = count(), time.monotonic()
    while time.monotonic() < deadline and time.monotonic() - since < quiet:
        await asyncio.sleep(0.1)
        if (current := count()) != last:
            last, since = current, time.monotonic()


async def record(args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    listener = asyncio.create_task(listen(args.host, args.port, args.out, stop))
    connected: list[Device] = []
    async with IndiClient(args.host, args.port) as client:
        await wait_quiet(client, quiet=1.0, limit=10)
        names = sorted(client.devices) if args.all else args.connect
        for name in names:
            device = Device(client, name)
            if device.connected:
                print(f"{name}: already connected", file=sys.stderr)
                continue
            try:
                await device.connect(timeout=args.timeout)
            except DeviceError as e:
                print(f"{name}: {e}", file=sys.stderr)
                continue
            connected.append(device)
            print(f"{name}: connected", file=sys.stderr)
        # Drivers keep defining properties for a while after connecting.
        await wait_quiet(client, quiet=args.settle, limit=60)
        await asyncio.sleep(args.extra)
        stop.set()
        size = await listener
        for device in connected:
            if not args.keep_connected:
                with contextlib.suppress(DeviceError):
                    await device.disconnect(timeout=args.timeout)
        devices = ", ".join(sorted(client.devices)) or "none"
    print(f"wrote {size} bytes to {args.out} (devices: {devices})", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=7624)
    parser.add_argument("--connect", action="append", default=[], metavar="DEVICE")
    parser.add_argument("--all", action="store_true", help="connect every device")
    parser.add_argument("--keep-connected", action="store_true")
    parser.add_argument("--timeout", type=float, default=30, help="per-device connect timeout")
    parser.add_argument("--settle", type=float, default=3, help="quiet time after connecting")
    parser.add_argument("--extra", type=float, default=5, help="record this long afterwards")
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(record(args))


if __name__ == "__main__":
    main()
