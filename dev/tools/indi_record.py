"""Record what real INDI drivers define and answer, for tests and facades (ADR 0038).

A recorder (``nocs.indi.recording``) listens on a connection of its own (no BLOBs),
which indiserver also sends every client's commands, while this tool's client
connects the chosen devices so their full property set is defined. Once the
definitions settle it disconnects the devices it connected (leaving the hardware as
it was found) and writes a zip: the scrubbed session and a manifest. The output can be
replayed by a fake indiserver in tests and read to write device facades.

Typical use in the lab, with the devices plugged in and their drivers running:

    uv run --project server python dev/tools/indi_record.py \\
        --connect "ZWO CCD ASI2600MC Pro" --connect "Pegasus PPBA" \\
        -o dev/recordings/zwo-ppba.zip

Without --connect it records what is defined without connecting anything; with
--all it connects every device on the server. --device limits the recording to
some devices (every device by default).

Usage: uv run --project server python dev/tools/indi_record.py [options] -o <file>
"""

import argparse
import asyncio
import contextlib
import json
import sys
import time
from pathlib import Path

from nocs.devices import Device, DeviceError
from nocs.indi import IndiClient
from nocs.indi.recording import Recorder


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
    recorder = Recorder(args.host, args.port, args.out, devices=args.device or None, note=args.note)
    await recorder.start()
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
        for device in connected:
            if not args.keep_connected:
                with contextlib.suppress(DeviceError):
                    await device.disconnect(timeout=args.timeout)
    await recorder.stop()
    devices = ", ".join(recorder.recorded) or "none"
    scrubbed = json.dumps(dict(recorder.scrubber.counts))
    print(
        f"wrote {recorder.messages} messages to {args.out} (devices: {devices}; "
        f"scrubbed: {scrubbed}; ended: {recorder.reason})",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=7624)
    parser.add_argument("--connect", action="append", default=[], metavar="DEVICE")
    parser.add_argument("--all", action="store_true", help="connect every device")
    parser.add_argument(
        "--device", action="append", default=[], help="record only this device (repeatable)"
    )
    parser.add_argument("--note", default="", help="what was done during the recording")
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
