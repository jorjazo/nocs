# ruff: noqa: E501, RUF001, ASYNC240
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""A long simulated night against nocsd, recording how the computer holds up.

``run`` drives a night through nocsd's API and records, every ``--every`` seconds:

- per process (nocsd, its imaging worker and other children, and every process of
  the INDI and PHD2 containers): resident memory, open file descriptors, CPU;
- the computer: CPU temperature, throttling and under-voltage (``nocs.services.health``,
  and ``vcgencmd get_throttled`` where it answers), load, available memory, free space
  and the write rate of the drive frames go to, nocsd's own bytes written;
- nocsd's responsiveness: ``GET /api/health`` once a second (its latency is the event
  loop's), and how late WebSocket patches reach a phone-like client;
- that client: it keeps a WebSocket open, applies snapshots and patches, checks their
  versions follow on, sleeps and reconnects every few minutes (resuming, or now and
  then from scratch), posts its clock like the app, downloads every preview and every
  ``--fits-every``-th frame;
- warnings, errors and tracebacks in nocsd's log.

The night: cool, unpark, centre on a southern field half an hour east of the meridian,
guide, autofocus, then three filters in batches of five until ``--hours`` are up, with
autofocus on a temperature change (the focuser simulator's temperature drops
``--cooling`` °C per hour, like a night) and every hour, a dither every 3 frames, a
pointing check every 10 and a meridian flip 5 minutes past the meridian (ADR 0033);
then stop guiding, park and warm. Frames are 26 MP (the reference rig's sensor).
To keep a drive from filling up, files of frames beyond ``--keep-frames`` are deleted,
oldest first (the catalog keeps them; bytes written are still counted).

``summarize`` turns a results directory into ``summary.md``.

Usually started by ``run.sh`` (which brings up its own simulators and nocsd).
By hand, with a nocsd already running:

    uv run --project server python dev/tools/soak/soak.py run --url http://127.0.0.1:28000 \\
        --nocsd-pid <pid> --containers nocs-soak-indi-1,nocs-soak-phd2-1 --out <dir> --hours 1
    uv run --project server python dev/tools/soak/soak.py summarize <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gzip
import json
import math
import os
import queue
import random
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from nocs.api.auth import COOKIE
from nocs.mount.coords import j2000_to_jnow, sidereal_time
from nocs.services.health import HealthPaths, read_health

PASSPHRASE = "soak soak soak soak"
SENSOR = {"SIM_XRES": 6248, "SIM_YRES": 4176, "SIM_XSIZE": 3.76, "SIM_YSIZE": 3.76}
TARGET_RA, TARGET_DEC = 3.0, -65.0
TARGET = {"name": "Soak field", "ra": TARGET_RA, "dec": TARGET_DEC}
"""J2000: circumpolar at the site's −30°; above 15° for ten hours past the meridian."""
LATITUDE = -30.03
HOUR_ANGLE = -0.5
"""Hours west of the meridian when the night starts: it flips half an hour in."""
FOCUSER = "Focuser Simulator"
CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(when: datetime) -> str:
    return when.isoformat(timespec="milliseconds")


# -- processes ------------------------------------------------------------------------


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def children_of() -> dict[int, list[int]]:
    tree: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        stat = _read(f"/proc/{entry}/stat")
        if stat is None:
            continue
        # comm may hold spaces and parentheses: the fields follow the last ')'.
        rest = stat[stat.rfind(")") + 2 :].split()
        tree.setdefault(int(rest[1]), []).append(int(entry))
    return tree


def descendants(root: int, tree: dict[int, list[int]]) -> list[int]:
    found, todo = [], list(tree.get(root, []))
    while todo:
        pid = todo.pop()
        found.append(pid)
        todo.extend(tree.get(pid, []))
    return found


def process_name(pid: int) -> str:
    comm = (_read(f"/proc/{pid}/comm") or "?").strip()
    cmdline = (_read(f"/proc/{pid}/cmdline") or "").replace("\0", " ")
    if "multiprocessing.resource_tracker" in cmdline:
        return "resource_tracker"
    if "multiprocessing.spawn" in cmdline or "spawn_main" in cmdline:
        return "worker"
    if len(comm) == 15 and cmdline:  # the kernel cuts comm to 15 characters
        return os.path.basename(cmdline.split(" ", 1)[0])
    return comm


@dataclass
class ProcessReading:
    rss: int = 0
    """Bytes."""
    fds: int | None = 0
    threads: int = 0
    ticks: int = 0
    count: int = 0


def read_process(pid: int) -> tuple[int, int | None, int, int] | None:
    """Resident bytes, open descriptors (None when not ours to see), threads, CPU ticks."""
    stat = _read(f"/proc/{pid}/stat")
    statm = _read(f"/proc/{pid}/statm")
    if stat is None or statm is None:
        return None
    rest = stat[stat.rfind(")") + 2 :].split()
    ticks = int(rest[11]) + int(rest[12])
    threads = int(rest[17])
    rss = int(statm.split()[1]) * PAGE
    try:
        fds: int | None = len(os.listdir(f"/proc/{pid}/fd"))
    except OSError:
        fds = None
    return rss, fds, threads, ticks


def container_pid(name: str) -> int | None:
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Pid}}", name],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    return int(out) if out.isdigit() and out != "0" else None


class Processes:
    """Groups of processes, read as one reading per name in each group."""

    def __init__(self, nocsd: int, containers: list[str]) -> None:
        self.nocsd = nocsd
        self.containers = containers
        self._ticks: dict[int, int] = {}
        self._last = time.monotonic()

    def sample(self) -> dict[str, dict[str, Any]]:
        tree = children_of()
        groups: dict[str, list[int]] = {"nocsd": [self.nocsd, *descendants(self.nocsd, tree)]}
        for container in self.containers:
            pid = container_pid(container)
            if pid is not None:
                short = container.removeprefix("nocs-soak-").removesuffix("-1")
                groups[short] = [pid, *descendants(pid, tree)]
        moment = time.monotonic()
        elapsed, self._last = moment - self._last, moment
        ticks: dict[int, int] = {}
        readings: dict[str, ProcessReading] = {}
        cpu: dict[str, float] = {}
        for group, pids in groups.items():
            for pid in pids:
                found = read_process(pid)
                if found is None:
                    continue
                rss, fds, threads, used = found
                name = "nocsd" if pid == self.nocsd else process_name(pid)
                if name in ("docker-init", "tini"):
                    continue
                key = f"{group}/{name}" if group != "nocsd" or name != "nocsd" else "nocsd"
                reading = readings.setdefault(key, ProcessReading())
                reading.rss += rss
                reading.fds = None if fds is None or reading.fds is None else reading.fds + fds
                reading.threads += threads
                reading.ticks += used
                reading.count += 1
                ticks[pid] = used
                cpu[key] = cpu.get(key, 0.0) + (used - self._ticks.get(pid, 0))
        # A process seen for the first time counts its whole life, once: fine for the
        # short ones (ASTAP), and the first sample of the long ones is skipped below.
        first = not self._ticks
        self._ticks = ticks
        out: dict[str, dict[str, Any]] = {}
        for key, reading in readings.items():
            out[key] = {
                "rss": reading.rss,
                "fds": reading.fds,
                "threads": reading.threads,
                "count": reading.count,
                "cpu": None if first else round(100 * cpu[key] / CLK_TCK / elapsed, 1),
            }
        return out


def io_written(pid: int) -> int | None:
    text = _read(f"/proc/{pid}/io")
    if text is None:
        return None
    for line in text.splitlines():
        if line.startswith("write_bytes:"):
            return int(line.split()[1])
    return None


# -- the computer ---------------------------------------------------------------------


def disk_sectors_written(path: Path) -> int | None:
    """Sectors written to the block device that holds ``path`` (512 bytes each)."""
    st = os.stat(path)
    major, minor = os.major(st.st_dev), os.minor(st.st_dev)
    for line in (_read("/proc/diskstats") or "").splitlines():
        fields = line.split()
        if int(fields[0]) == major and int(fields[1]) == minor:
            return int(fields[9])
    return None


def vcgencmd_throttled() -> int | None:
    for command in (["vcgencmd", "get_throttled"], ["sudo", "-n", "vcgencmd", "get_throttled"]):
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=5).stdout
        except (subprocess.SubprocessError, OSError):
            continue
        if match := re.search(r"throttled=(0x[0-9a-fA-F]+)", out):
            return int(match.group(1), 16)
    return None


def system_sample(storage: Path) -> dict[str, Any]:
    health = read_health(HealthPaths())
    meminfo = {
        line.split(":")[0]: int(line.split()[1])
        for line in (_read("/proc/meminfo") or "").splitlines()
        if line.split()[1:2] and line.split()[1].isdigit()
    }
    vfs = os.statvfs(storage)
    return {
        "temperature": health.cpu_temperature,
        "throttled": health.throttled,
        "under_voltage": health.under_voltage,
        "vc_throttled": vcgencmd_throttled(),
        "load": os.getloadavg()[0],
        "mem_available": meminfo.get("MemAvailable", 0) * 1024,
        "storage_free": vfs.f_bavail * vfs.f_frsize,
        "sectors_written": disk_sectors_written(storage),
        # multiprocessing's named semaphores (all users' here): a leak shows as growth.
        "semaphores": sum(1 for n in os.listdir("/dev/shm") if n.startswith("sem."))
        if os.path.isdir("/dev/shm")
        else None,
    }


# -- nocsd's API ----------------------------------------------------------------------


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


@dataclass
class Window:
    """What happened between two samples."""

    health: list[float] = field(default_factory=list[float])
    health_failures: int = 0
    patch_lag: list[float] = field(default_factory=list[float])
    lag_missed: int = 0
    connects: list[float] = field(default_factory=list[float])
    connect_failures: int = 0
    snapshots: int = 0
    snapshot_bytes: int = 0
    patches: int = 0
    patch_bytes: int = 0
    gaps: int = 0
    previews: list[float] = field(default_factory=list[float])
    fits: list[tuple[float, int]] = field(default_factory=list[tuple[float, int]])
    download_failures: int = 0
    frames: int = 0
    frame_bytes: int = 0
    log: Counter[str] = field(default_factory=Counter[str])

    def summary(self) -> dict[str, Any]:
        def ms(values: list[float], fraction: float) -> float | None:
            found = percentile(values, fraction)
            return None if found is None else round(found * 1000, 1)

        return {
            "health_n": len(self.health),
            "health_p50": ms(self.health, 0.5),
            "health_p99": ms(self.health, 0.99),
            "health_max": ms(self.health, 1.0),
            "health_failures": self.health_failures,
            "patch_lag_n": len(self.patch_lag),
            "patch_lag_p50": ms(self.patch_lag, 0.5),
            "patch_lag_max": ms(self.patch_lag, 1.0),
            "lag_missed": self.lag_missed,
            "connects": len(self.connects),
            "connect_max": ms(self.connects, 1.0),
            "connect_failures": self.connect_failures,
            "snapshots": self.snapshots,
            "snapshot_bytes": self.snapshot_bytes,
            "patches": self.patches,
            "patch_bytes": self.patch_bytes,
            "gaps": self.gaps,
            "previews": len(self.previews),
            "preview_max": ms(self.previews, 1.0),
            "fits": len(self.fits),
            "fits_mbps": (
                round(sum(b for _, b in self.fits) / sum(t for t, _ in self.fits) / 1e6, 1)
                if self.fits
                else None
            ),
            "download_failures": self.download_failures,
            "frames": self.frames,
            "frame_bytes": self.frame_bytes,
            "log": dict(self.log),
        }


def apply(state: dict[str, Any], ops: list[dict[str, Any]]) -> None:
    for op in ops:
        *parents, last = op["path"]
        node = state
        for key in parents:
            node = node.setdefault(key, {})
        if op["op"] == "set":
            node[last] = op.get("value")
        else:
            node.pop(last, None)


def dig(state: dict[str, Any], *path: str) -> Any:
    node: Any = state
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)  # pyright: ignore[reportUnknownMemberType]
    return node


class Night:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out: Path = args.out
        self.url: str = args.url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.url, timeout=60)
        self.window = Window()
        self.rng = random.Random(args.seed)
        self.processes = Processes(args.nocsd_pid, args.containers)
        self.storage: Path = args.storage
        self.state: dict[str, Any] = {}
        self.clock_sent: float | None = None
        self.downloads: asyncio.Queue[tuple[str, str]] = asyncio.Queue(100)
        self.started = time.monotonic()
        self.ends = now_utc() + timedelta(hours=args.hours)
        self.done = asyncio.Event()
        self.interrupted = asyncio.Event()
        self.events_seen: set[tuple[str, str, str]] = set()
        self.frames_seen: set[int] = set()
        self.pruned = 0
        self.log_offset = 0
        self.writes: queue.Queue[tuple[Path, str] | None] = queue.Queue()
        self.writing = threading.Thread(target=self.writer, daemon=True)
        self.writing.start()

    # setup

    async def call(self, method: str, path: str, ok: tuple[int, ...] = (200,), **kw: Any) -> Any:
        response = await self.http.request(method, path, **kw)
        if response.status_code not in ok:
            raise RuntimeError(f"{method} {path}: {response.status_code} {response.text}")
        return response.json() if response.content else None

    async def get_state(self) -> dict[str, Any]:
        return (await self.call("GET", "/api/state"))["state"]

    async def wait_for(self, what: str, check: Any, timeout: float = 120) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            current = await self.get_state()
            if check(current):
                return current
            if time.monotonic() > deadline:
                raise RuntimeError(f"timed out waiting for {what}")
            await asyncio.sleep(1)

    async def pair(self) -> None:
        auth = await self.call("GET", "/api/auth")
        body = {"passphrase": PASSPHRASE, "name": "soak"}
        path = "/api/auth/setup" if auth["setup_required"] else "/api/auth/pair"
        await self.call("POST", path, ok=(201,), json=body)

    async def post_clock(self) -> None:
        self.clock_sent = time.monotonic()
        await self.call("POST", "/api/clock", json={"utc": iso(now_utc()), "utc_offset": -3})

    async def set_property(self, device: str, name: str, values: dict[str, Any]) -> None:
        path = f"/api/indi/devices/{device}/properties/{name}"
        await self.call("POST", path, ok=(202,), json={"values": values})

    async def set_up(self) -> str:
        await self.pair()
        sims = json.loads(Path(self.args.profile).read_text())
        now = now_utc()
        target = j2000_to_jnow(TARGET_RA, TARGET_DEC, now)
        longitude = ((target.ra + HOUR_ANGLE - sidereal_time(0, now)) * 15 + 180) % 360 - 180
        profile = {
            **sims,
            "name": "Soak",
            "devices": {k: v for k, v in sims["devices"].items() if k != "weather"},
            "imaging": {
                "focal_length": 1000,
                "aperture": 150,
                "autofocus": {"step": 4000, "exposure": 2},
            },
            "site": {
                "name": "Soak",
                "latitude": LATITUDE,
                "longitude": longitude,
                "elevation": 700,
            },
        }
        await self.call("PUT", "/api/profiles/soak", ok=(204,), json=profile)
        await self.call("POST", "/api/equipment/connect", ok=(202,), json={"profile": "soak"})
        current = await self.wait_for(
            "the rig",
            lambda s: (
                s.get("focuser") is not None
                and s.get("filter_wheel") is not None
                and s.get("mount") is not None
                and {"main_camera", "guide_camera"} <= set(s.get("cameras") or {})
            ),
        )
        await self.set_property("CCD Simulator", "SIMULATOR_SETTINGS", SENSOR)
        # At the guide scope's 4"/px the simulator's 3.5" stars are under a pixel, and
        # PHD2 keeps losing them ("low HFD"): a guide scope's stars span a few pixels.
        await self.set_property("Guide Simulator", "SIMULATOR_SETTINGS", {"SIM_SEEING": 14})
        await self.call(
            "POST",
            "/api/cameras/main_camera/settings",
            ok=(204,),
            json={"binning": 1, "region": "full"},
        )
        await self.post_clock()
        await self.wait_for(
            "site and time", lambda s: s["mount"]["site_sent"] and s["mount"]["time_sent"]
        )
        names = [n for n in current["filter_wheel"]["names"] if n][:3]
        exposure = self.args.exposure
        sequence = {
            "name": "Soak",
            "start": {
                "children": [
                    {"kind": "cool", "temperature": -10, "ramp": 0},
                    {"kind": "unpark"},
                ]
            },
            "targets": {
                "children": [
                    {
                        "kind": "container",
                        "target": TARGET,
                        "conditions": [{"kind": "until_time", "time": iso(self.ends)}],
                        "triggers": [
                            {"kind": "autofocus", "temperature_change": 1.0, "minutes": 60},
                            {"kind": "dither", "every": 3, "dither": {"pixels": 5}},
                            {"kind": "recenter", "every": 10, "recenter": {"drift": 2}},
                            {"kind": "flip", "after": 5, "flip": {"center": {}}},
                        ],
                        "children": [
                            {"kind": "center"},
                            {"kind": "guide", "on": True},
                            {"kind": "autofocus"},
                            {
                                "kind": "expose",
                                "batch": 5,
                                "rows": [
                                    {"filter": n, "exposure": exposure, "count": 10000}
                                    for n in names
                                ],
                            },
                        ],
                    }
                ]
            },
            "end": {
                "children": [
                    {"kind": "guide", "on": False},
                    {"kind": "park"},
                    {"kind": "warm", "ramp": 0},
                ]
            },
        }
        (self.out / "sequence.json").write_text(json.dumps(sequence, indent=2))
        await self.call("PUT", "/api/sequences/soak", ok=(204,), json=sequence)
        started = await self.call("POST", "/api/sequences/soak/start", ok=(202,))
        return started["job"]

    # the night

    async def run(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        for number in (signal.SIGINT, signal.SIGTERM):
            # Stop the night as a user would (park, warm), then write what was found.
            loop.add_signal_handler(number, self.interrupted.set)
        tasks: list[asyncio.Task[None]] = [asyncio.create_task(self.sampler())]
        try:
            job = await self.set_up()
            print(f"sequence started (job {job}); ends {iso(self.ends)}", flush=True)
            tasks += [
                asyncio.create_task(self.prober()),
                asyncio.create_task(self.phone()),
                asyncio.create_task(self.downloader()),
                asyncio.create_task(self.night_cools()),
            ]
            outcome = await self.watch(job)
        finally:
            self.done.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.flush_sample()
            with contextlib.suppress(Exception):
                await self.save_report()
            await self.http.aclose()
            self.writes.put(None)
            await asyncio.to_thread(self.writing.join)
        print(f"night over: {outcome}", flush=True)
        return 0 if outcome == "completed" else 1

    async def watch(self, job: str) -> str:
        grace = timedelta(minutes=20)
        stopping = False
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.interrupted.wait(), 5)
            if self.interrupted.is_set() and not stopping:
                stopping = True
                self.note("interrupted: stopping the run, with its end")
                with contextlib.suppress(httpx.HTTPError, RuntimeError):
                    await self.call("POST", "/api/sequence/stop", ok=(204,), json={"run_end": True})
            try:
                current = await self.get_state()
            except (httpx.HTTPError, RuntimeError) as e:
                self.note(f"state: {e!r}")
                continue
            self.record_events(current)
            run = dig(current, "sequence", "run") or {}
            if (
                dig(current, "jobs", job, "state") not in (None, "running")
                or run.get("state") == "finished"
            ):
                return str(run.get("outcome"))
            if now_utc() > self.ends + grace:
                self.note("the run did not end on time: stopping it")
                await self.call("POST", "/api/sequence/stop", ok=(204,), json={"run_end": True})
                grace += timedelta(minutes=20)

    def record_events(self, current: dict[str, Any]) -> None:
        lines = []
        for event in dig(current, "sequence", "events") or []:
            key = (event["time"], event["kind"], event["message"])
            if key not in self.events_seen:
                self.events_seen.add(key)
                lines.append(json.dumps(event) + "\n")
        self.append("events.jsonl", "".join(lines))

    async def save_report(self) -> None:
        sessions = await self.call("GET", "/api/sessions")
        if sessions:
            latest = sessions[0]["id"]
            report = await self.call("GET", f"/api/sessions/{latest}/report")
            (self.out / "report.json").write_text(json.dumps(report, indent=2))

    async def night_cools(self) -> None:
        """The focuser's temperature drops through the night, in steps of 0.25 °C."""
        found = dig(await self.get_state(), "focuser", "temperature")
        temperature = 15.0 if found is None else float(found)
        step = 0.25
        while self.args.cooling > 0:
            await asyncio.sleep(3600 * step / self.args.cooling)
            temperature -= step
            with contextlib.suppress(httpx.HTTPError, RuntimeError):
                await self.set_property(FOCUSER, "FOCUS_TEMPERATURE", {"TEMPERATURE": temperature})

    # nocsd's responsiveness

    async def prober(self) -> None:
        async with httpx.AsyncClient(base_url=self.url, timeout=10) as client:
            while True:
                begin = time.monotonic()
                try:
                    response = await client.get("/api/health")
                    response.raise_for_status()
                    self.window.health.append(time.monotonic() - begin)
                except httpx.HTTPError:
                    self.window.health_failures += 1
                await asyncio.sleep(max(0.0, 1 - (time.monotonic() - begin)))

    # the phone

    async def phone(self) -> None:
        epoch: str | None = None
        version: int | None = None
        sessions = 0
        cookie = self.http.cookies.get(COOKIE)
        uri = self.url.replace("http", "ws", 1) + "/api/ws"
        while True:
            fresh = sessions % 4 == 3  # the app opened again, not woken up
            hello = (
                {"type": "hello"}
                if fresh or epoch is None
                else {"type": "hello", "epoch": epoch, "since": version}
            )
            stay = self.rng.uniform(*self.args.ws_stay)
            begin = time.monotonic()
            try:
                async with connect(
                    uri, additional_headers={"Cookie": f"{COOKIE}={cookie}"}, max_size=None
                ) as ws:
                    await ws.send(json.dumps(hello))
                    first = True
                    clock = asyncio.create_task(self.clock_probes())
                    try:
                        async with asyncio.timeout(stay):
                            async for raw in ws:
                                text = raw if isinstance(raw, str) else raw.decode()
                                message = json.loads(text)
                                if first:
                                    self.window.connects.append(time.monotonic() - begin)
                                    first = False
                                epoch, version = self.receive(message, text, version, epoch)
                    except TimeoutError:
                        pass
                    finally:
                        clock.cancel()
            except (OSError, ConnectionClosed, TimeoutError) as e:
                self.window.connect_failures += 1
                self.note(f"websocket: {e!r}")
            sessions += 1
            await asyncio.sleep(self.rng.uniform(*self.args.ws_sleep))

    def receive(
        self, message: dict[str, Any], text: str, version: int | None, epoch: str | None
    ) -> tuple[str | None, int | None]:
        if message.get("type") == "snapshot":
            self.window.snapshots += 1
            self.window.snapshot_bytes += len(text)
            self.state = message["state"]
            self.watch_frames()
            return message["epoch"], message["version"]
        if message.get("type") != "patch":
            return epoch, version
        self.window.patches += 1
        self.window.patch_bytes += len(text)
        if version is not None and message["version"] != version + 1:
            self.window.gaps += 1
            self.note(f"patch {message['version']} after {version}")
        apply(self.state, message["ops"])
        if self.clock_sent is not None and any(
            op["path"][:1] == ["clock"] for op in message["ops"]
        ):
            self.window.patch_lag.append(time.monotonic() - self.clock_sent)
            self.clock_sent = None
        self.watch_frames()
        return epoch, message["version"]

    async def clock_probes(self) -> None:
        """Post the clock like the app when it connects, then every 30 s; a patch follows."""
        while True:
            if self.clock_sent is not None:
                self.window.lag_missed += 1
            with contextlib.suppress(httpx.HTTPError, RuntimeError):
                await self.post_clock()
            await asyncio.sleep(30)

    def watch_frames(self) -> None:
        preview = dig(self.state, "cameras", "main_camera", "preview", "url")
        if preview and preview != getattr(self, "_preview", None):
            self._preview = preview
            with contextlib.suppress(asyncio.QueueFull):
                self.downloads.put_nowait(("preview", preview))
        frame = dig(self.state, "cameras", "main_camera", "last_frame") or {}
        frame_id = frame.get("id")
        if frame_id is not None and frame_id not in self.frames_seen:
            self.frames_seen.add(frame_id)
            self.window.frames += 1
            self.window.frame_bytes += frame.get("size") or 0
            if len(self.frames_seen) % self.args.fits_every == 0:
                with contextlib.suppress(asyncio.QueueFull):
                    self.downloads.put_nowait(("fits", f"/api/frames/{frame_id}/file"))

    async def downloader(self) -> None:
        while True:
            kind, path = await self.downloads.get()
            begin = time.monotonic()
            size = 0
            try:
                async with self.http.stream("GET", path) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(1 << 20):
                        size += len(chunk)
            except httpx.HTTPError as e:
                self.window.download_failures += 1
                self.note(f"download {path}: {e!r}")
                continue
            took = time.monotonic() - begin
            if kind == "preview":
                self.window.previews.append(took)
            else:
                self.window.fits.append((took, size))

    # recording

    def note(self, text: str) -> None:
        self.append("soak.log", f"{iso(now_utc())} {text}\n")

    def append(self, name: str, text: str) -> None:
        """Append in the writer thread: on a microSD busy with a frame, an append can wait
        seconds, and this loop's waits would read as nocsd's latency."""
        if text:
            self.writes.put((self.out / name, text))

    def writer(self) -> None:
        while (item := self.writes.get()) is not None:
            path, text = item
            with path.open("a") as f:
                f.write(text)

    def scan_log(self) -> None:
        path: Path = self.args.log
        if not path.exists():
            return
        with path.open("rb") as f:
            f.seek(self.log_offset)
            chunk = f.read()
        complete = chunk.rfind(b"\n") + 1
        self.log_offset += complete
        with (self.out / "errors.log").open("a") as errors:
            for line in chunk[:complete].decode(errors="replace").splitlines():
                level = next(
                    (w for w in ("CRITICAL", "ERROR", "WARNING", "Traceback") if w in line), None
                )
                if level is not None:
                    self.window.log[level] += 1
                    errors.write(line + "\n")

    def prune(self) -> None:
        # Saved frames only: incoming/ holds guide frames for a second (ADR 0023).
        found: list[tuple[float, Path]] = []
        for path in (self.storage / "NOCS").rglob("*"):
            if path.suffix.lower() in (".fits", ".fit", ".xisf"):
                with contextlib.suppress(OSError):  # moved or deleted meanwhile
                    found.append((path.stat().st_mtime, path))
        frames = [path for _, path in sorted(found)]
        for path in frames[: max(0, len(frames) - self.args.keep_frames)]:
            with contextlib.suppress(OSError):
                path.unlink()
                self.pruned += 1

    async def sampler(self) -> None:
        while True:
            await asyncio.sleep(self.args.every)
            try:
                await self.flush_sample()
            except Exception as e:  # one bad sample must not end the recording (or pruning)
                self.note(f"sample: {e!r}")

    async def flush_sample(self) -> None:
        window, self.window = self.window, Window()
        processes = await asyncio.to_thread(self.processes.sample)
        system = await asyncio.to_thread(system_sample, self.storage)
        await asyncio.to_thread(self.scan_log)
        await asyncio.to_thread(self.prune)
        sample = {
            "time": iso(now_utc()),
            "elapsed": round(time.monotonic() - self.started, 1),
            "processes": processes,
            "system": system,
            "nocsd_written": io_written(self.args.nocsd_pid),
            "pruned": self.pruned,
            **window.summary(),
        }
        self.append("samples.jsonl", json.dumps(sample) + "\n")


# -- summary --------------------------------------------------------------------------


def slope(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope, per unit of the first coordinate."""
    if len(points) < 3:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else sum((x - mx) * (y - my) for x, y in points) / den


def fmt(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def summarize(out: Path, warmup: float) -> str:
    path = out / "samples.jsonl"
    text = (
        path.read_text()
        if path.exists()
        else gzip.decompress(path.with_suffix(".jsonl.gz").read_bytes()).decode()
    )
    samples = [json.loads(line) for line in text.splitlines()]
    if not samples:
        return "no samples\n"
    hours = samples[-1]["elapsed"] / 3600
    steady = [s for s in samples if s["elapsed"] >= warmup] or samples
    lines = [
        f"# Soak: {out.name}",
        "",
        f"{samples[0]['time']} → {samples[-1]['time']} ({hours:.2f} h, {len(samples)} samples);"
        f" slopes after the first {warmup / 60:.0f} min.",
        "",
        "## Processes",
        "",
        "| process | n | RSS start → end (MB) | max | slope MB/h | fds start → end | max | CPU % mean / p95 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    keys = sorted({k for s in samples for k in s["processes"]})
    for key in keys:
        seen = [s for s in steady if key in s["processes"]]
        if not seen:
            continue
        rows = [s["processes"][key] for s in seen]
        rss = [r["rss"] / 1e6 for r in rows]
        fds = [r["fds"] for r in rows if r["fds"] is not None]
        cpu = [r["cpu"] for r in rows if r["cpu"] is not None]
        per_hour = slope([(s["elapsed"] / 3600, s["processes"][key]["rss"] / 1e6) for s in seen])
        lines.append(
            f"| {key} | {max(r['count'] for r in rows)} | {rss[0]:.0f} → {rss[-1]:.0f} | {max(rss):.0f}"
            f" | {fmt(per_hour)} | {fds[0] if fds else '—'} → {fds[-1] if fds else '—'}"
            f" | {max(fds) if fds else '—'} | {fmt(statistics.fmean(cpu) if cpu else None)}"
            f" / {fmt(percentile(cpu, 0.95))} |"
        )
    system = [s["system"] for s in samples]
    temps = [x["temperature"] for x in system if x["temperature"] is not None]
    written = [s["nocsd_written"] for s in samples if s["nocsd_written"] is not None]
    sectors = [x["sectors_written"] for x in system if x["sectors_written"] is not None]
    vc = [x["vc_throttled"] for x in system if x["vc_throttled"] is not None]
    lines += [
        "",
        "## The computer",
        "",
        f"- CPU temperature: {fmt(min(temps) if temps else None)} – {fmt(max(temps) if temps else None)} °C,"
        f" mean {fmt(statistics.fmean(temps) if temps else None)}",
        f"- throttled (cpufreq): {any(x['throttled'] for x in system)};"
        f" under-voltage: {any(x['under_voltage'] for x in system)};"
        f" vcgencmd get_throttled: {', '.join(sorted({hex(v) for v in vc})) or 'not available'}",
        f"- load average (1 min): mean {statistics.fmean(x['load'] for x in system):.2f},"
        f" max {max(x['load'] for x in system):.2f}",
        f"- available memory: {min(x['mem_available'] for x in system) / 1e9:.2f} GB at least",
        f"- POSIX semaphores in /dev/shm: {system[0].get('semaphores')} → {system[-1].get('semaphores')}"
        f" (max {max((x.get('semaphores') or 0) for x in system)}); nocsd's children:"
        f" {max(sum(v['count'] for k, v in s['processes'].items() if k.startswith('nocsd/')) for s in samples)} at most",
        f"- storage free: {system[0]['storage_free'] / 1e9:.1f} → {system[-1]['storage_free'] / 1e9:.1f} GB"
        f" (frames pruned meanwhile: {samples[-1]['pruned']})",
    ]
    if len(written) > 1:
        lines.append(
            f"- nocsd wrote {(written[-1] - written[0]) / 1e9:.1f} GB"
            f" ({(written[-1] - written[0]) / 1e6 / (hours * 3600):.2f} MB/s)"
        )
    if len(sectors) > 1:
        total = (sectors[-1] - sectors[0]) * 512
        lines.append(
            f"- the frames' drive took {total / 1e9:.1f} GB of writes ({total / 1e6 / (hours * 3600):.2f} MB/s)"
        )
    frames = sum(s["frames"] for s in samples)
    frame_bytes = sum(s["frame_bytes"] for s in samples)
    health = [s for s in samples if s["health_n"]]
    lags = [s for s in samples if s["patch_lag_n"]]
    lines += [
        "",
        "## nocsd and the phone",
        "",
        f"- frames: {frames} ({frames / hours:.0f}/h), {frame_bytes / 1e9:.1f} GB,"
        f" {frame_bytes / max(frames, 1) / 1e6:.1f} MB each",
        f"- `/api/health` latency (≈ event loop): p50 of windows {fmt(statistics.median(s['health_p50'] for s in health))} ms,"
        f" worst p99 {fmt(max(s['health_p99'] for s in health))} ms, max {fmt(max(s['health_max'] for s in health))} ms;"
        f" failures {sum(s['health_failures'] for s in samples)}"
        if health
        else "- no health probes",
        f"- patch lag (clock posted → patch on the WebSocket): median {fmt(statistics.median(s['patch_lag_p50'] for s in lags))} ms,"
        f" max {fmt(max(s['patch_lag_max'] for s in lags))} ms; probes without a patch {sum(s['lag_missed'] for s in samples)}"
        if lags
        else "- no patch lag probes",
        f"- WebSocket: {sum(s['connects'] for s in samples)} connections"
        f" ({sum(s['snapshots'] for s in samples)} snapshots),"
        f" {sum(s['connect_failures'] for s in samples)} failures, {sum(s['gaps'] for s in samples)} version gaps,"
        f" {sum(s['patches'] for s in samples)} patches ({sum(s['patch_bytes'] for s in samples) / 1e6 / (hours * 3600) * 1000:.1f} kB/s);"
        f" slowest connection {fmt(max((s['connect_max'] or 0) for s in samples))} ms",
        f"- downloads: {sum(s['previews'] for s in samples)} previews (slowest {fmt(max((s['preview_max'] or 0) for s in samples))} ms),"
        f" {sum(s['fits'] for s in samples)} FITS; {sum(s['download_failures'] for s in samples)} failures",
    ]
    log: Counter[str] = Counter()
    for s in samples:
        log.update(s["log"])
    lines += ["", "## Log", "", f"- {dict(log) or 'nothing at WARNING or above'}"]
    errors = out / "errors.log"
    if errors.exists():
        # The message without its time stamp and numbers, most frequent first.
        kinds = Counter(
            re.sub(r"\d+(\.\d+)?", "N", line.split(" ", 2)[-1])[:140]
            for line in errors.read_text().splitlines()
        )
        lines += [f"- {n}× `{text}`" for text, n in kinds.most_common(12)]
    report = out / "report.json"
    if report.exists():
        data = json.loads(report.read_text())
        lines += ["", "## The session report", "", "```", json.dumps(_brief(data), indent=1), "```"]
    return "\n".join(lines) + "\n"


def _brief(report: dict[str, Any]) -> dict[str, Any]:
    keep = ("outcome", "started", "ended", "filters", "autofocus", "failures")
    brief = {k: report[k] for k in keep if k in report}
    if isinstance(brief.get("autofocus"), list):
        brief["autofocus"] = len(brief["autofocus"])  # pyright: ignore[reportArgumentType]
    events = report.get("events") or []
    brief["events"] = dict(Counter(e.get("kind") for e in events))
    return brief


# -- command line ---------------------------------------------------------------------


def pair_of_floats(text: str) -> tuple[float, float]:
    low, _, high = text.partition(",")
    return float(low), float(high or low)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--url", default="http://127.0.0.1:28000")
    run.add_argument("--nocsd-pid", type=int, required=True)
    run.add_argument("--containers", type=lambda s: [c for c in s.split(",") if c], default=[])
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--log", type=Path, help="nocsd's log (default: <out>/nocsd.log)")
    run.add_argument("--storage", type=Path, required=True, help="where nocsd saves frames")
    run.add_argument(
        "--profile",
        type=Path,
        default=Path(__file__).parents[2] / "profiles" / "simulators.json",
    )
    run.add_argument("--hours", type=float, default=1.0)
    run.add_argument("--exposure", type=float, default=5.0, help="light frames, seconds")
    run.add_argument("--cooling", type=float, default=1.0, help="°C per hour at the focuser")
    run.add_argument("--every", type=float, default=30.0, help="seconds between samples")
    run.add_argument("--keep-frames", type=int, default=60)
    run.add_argument("--fits-every", type=int, default=10)
    run.add_argument("--ws-stay", type=pair_of_floats, default=(120.0, 900.0), help="min,max s")
    run.add_argument("--ws-sleep", type=pair_of_floats, default=(1.0, 60.0), help="min,max s")
    run.add_argument("--seed", type=int, default=1)
    summary = sub.add_parser("summarize")
    summary.add_argument("out", type=Path)
    summary.add_argument("--warmup", type=float, default=600, help="seconds left out of slopes")
    args = parser.parse_args()
    if args.command == "summarize":
        text = summarize(args.out, args.warmup)
        (args.out / "summary.md").write_text(text)
        print(text)
        return 0
    args.log = args.log or args.out / "nocsd.log"
    return asyncio.run(Night(args).run())


if __name__ == "__main__":
    sys.exit(main())
