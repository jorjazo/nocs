"""Spike: drive a headless PHD2 through its JSON-RPC event server.

Usage (with `docker compose -f dev/compose.yaml up -d`):

    uv run --project server python dev/spikes/phd2_probe.py info
    uv run --project server python dev/spikes/phd2_probe.py guide

``info`` prints PHD2's state and profile; ``guide`` points the simulated mount
at a star field, then connects, calibrates, guides and dithers through PHD2.
Findings are in docs/spikes/phd2-headless.md.
"""

import asyncio
import json
import sys
import time
from typing import Any

from nocs.devices import Camera, Mount
from nocs.indi import IndiClient

PHD2 = ("127.0.0.1", 4400)
INDI = ("127.0.0.1", 7624)
SETTLE = {"pixels": 1.5, "time": 8, "timeout": 90}
QUIET_EVENTS = {"LoopingExposures", "GuideStep", "Calibrating", "Settling"}


class Phd2:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader, self.writer = reader, writer
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.waiters: list[tuple[set[str], asyncio.Future[dict[str, Any]]]] = []
        self.counts: dict[str, int] = {}
        self.last: dict[str, dict[str, Any]] = {}
        self.task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        while line := await self.reader.readline():
            msg = json.loads(line)
            if "jsonrpc" in msg and msg.get("id") in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
                continue
            name = msg.get("Event", "?")
            self.counts[name] = self.counts.get(name, 0) + 1
            self.last[name] = msg
            if name not in QUIET_EVENTS:
                print(f"  [{time.strftime('%X')}] event {name}: {json.dumps(msg)[:220]}")
            for names, future in list(self.waiters):
                if name in names and not future.done():
                    future.set_result(msg)

    async def call(self, method: str, params: Any = None, timeout: float = 15) -> Any:
        rid = self.next_id
        self.next_id += 1
        request: dict[str, Any] = {"method": method, "id": rid}
        if params is not None:
            request["params"] = params
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        self.writer.write((json.dumps(request) + "\r\n").encode())
        await self.writer.drain()
        response = await asyncio.wait_for(future, timeout)
        shown = response.get("result", response.get("error"))
        args = json.dumps(params) if params is not None else ""
        print(f"{method}({args}) -> {json.dumps(shown)[:300]}")
        return response

    async def wait_event(self, *names: str, timeout: float) -> dict[str, Any]:
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        entry = (set(names), future)
        self.waiters.append(entry)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.waiters.remove(entry)


async def connect_phd2() -> Phd2:
    reader, writer = await asyncio.open_connection(*PHD2)
    phd2 = Phd2(reader, writer)
    await asyncio.sleep(0.5)
    return phd2


async def info() -> None:
    phd2 = await connect_phd2()
    for method in (
        "get_app_state",
        "get_profiles",
        "get_profile",
        "get_connected",
        "get_current_equipment",
        "get_exposure",
        "get_pixel_scale",
    ):
        await phd2.call(method)


async def point_mount() -> None:
    """Unpark and track a rich star field; give the guide camera optics."""
    async with IndiClient(*INDI) as client:
        mount = Mount(client, "Telescope Simulator")
        await mount.connect()
        await mount.unpark()
        await mount.goto(5.6, -5.4)  # Orion's sword: plenty of guide stars
        guide = Camera(client, "Guide Simulator")
        await guide.connect()
        await client.send(guide.name, "SCOPE_INFO", {"FOCAL_LENGTH": 400, "APERTURE": 80})
        print(f"mount at RA {mount.coordinates.ra:.3f} h, Dec {mount.coordinates.dec:.2f}°")


async def guide() -> None:
    await point_mount()
    phd2 = await connect_phd2()
    started = time.monotonic()
    await phd2.call("set_connected", [True], timeout=60)
    await phd2.call("get_current_equipment")
    await phd2.call("set_exposure", [2000])
    await phd2.call("clear_calibration", ["both"])
    await phd2.call("loop")
    await asyncio.sleep(5)
    await phd2.call("find_star", timeout=30)
    await phd2.call("guide", {"settle": SETTLE, "recalibrate": True})
    done = await phd2.wait_event("SettleDone", timeout=600)
    print(f"guiding settled after {time.monotonic() - started:.0f} s: {done}")
    await asyncio.sleep(20)
    stats = phd2.last.get("GuideStep", {})
    print(f"last guide step: RA {stats.get('RADistanceRaw')} Dec {stats.get('DECDistanceRaw')} px")
    await phd2.call("get_calibration_data", ["Mount"])
    await phd2.call("dither", {"amount": 3, "raOnly": False, "settle": SETTLE})
    done = await phd2.wait_event("SettleDone", timeout=180)
    print(f"dither settled: {done}")
    await phd2.call("stop_capture")
    print("event counts:", json.dumps(phd2.counts))


asyncio.run({"info": info, "guide": guide}[sys.argv[1] if len(sys.argv) > 1 else "info"]())
