"""Recording an INDI session, to replay a driver NOCS does not have in tests (ADR 0038).

A recording holds what indiserver sends about the chosen devices to a connection of
the recorder's own, which never enables BLOBs, each message with its time since the
start. That includes the commands: indiserver echoes every client's ``new*Vector`` to
the other clients interested in the device, so nocsd's, PHD2's and any other
client's commands come in the order indiserver passed them to the driver. The event
loop only queues bytes: a thread splits, scrubs and writes the session, and at the
end zips it with a manifest:

- ``manifest.json``: versions, drivers, the user's note, why it ended, what was
  scrubbed;
- ``session.jsonl``: one ``{"t": seconds, "xml": "<…/>"}`` per message.

What identifies the user (the site, serial numbers, addresses, home directories) is
replaced before anything is written.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import re
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from io import BufferedWriter
from pathlib import Path
from typing import cast

from nocs import __version__
from nocs.indi.protocol import ProtocolError, encode_get_properties, parse_number
from nocs.state import Json

FORMAT = 1
MAX_DURATION = 30 * 60.0
"""Seconds a recording lasts at most."""
MAX_BYTES = 20_000_000
"""Bytes of session a recording holds at most (the lab rig defines ~230 kB)."""
INDI_PACKAGES = ("indi-bin", "libindi1", "indi-3rdparty-drivers")
MANIFEST = "manifest.json"
SESSION = "session.jsonl"
_READ_SIZE = 256 * 1024


class EndReason(StrEnum):
    STOPPED = "stopped"
    DURATION = "time limit"
    SIZE = "size limit"
    DISCONNECTED = "indiserver closed the connection"
    INVALID = "invalid XML"


@dataclass(frozen=True, slots=True)
class Limits:
    duration: float = MAX_DURATION
    bytes: int = MAX_BYTES


DEFAULT_LIMITS = Limits()

# -- scrubbing ---------------------------------------------------------------

SERIAL_PROPERTIES = frozenset({"Serial Number", "SERIAL_NUMBER", "SN"})
"""Where drivers publish serial numbers (ZWO: ``Serial Number.SN``)."""
SERIAL_ELEMENTS = frozenset({"SN", "SERIAL", "SERIAL_NUMBER"})
SITE_ELEMENTS = frozenset({"LAT", "LONG", "ELEV"})
DOCUMENTATION_ADDRESS = "192.0.2.1"
"""An IPv4 address reserved for documentation (RFC 5737), for every address."""
_MIN_SERIAL = 6
"""Shorter serials are not looked for in other texts: they would match anything."""
_BY_ID = re.compile(r"(/dev/serial/by-id/usb-[^\s\"'<>]*_)([0-9A-Za-z]{4,})(-if\d+)")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOME = re.compile(r"/home/[^/\s\"'<>]+")


class Scrubber:
    """Replaces, in place, what identifies the user in protocol elements."""

    def __init__(self, hostname: str | None = None) -> None:
        self.counts: Counter[str] = Counter()
        """Values replaced, by kind: ``site``, ``serials``, ``hosts``, ``home``."""
        self._serials: dict[str, str] = {}
        self._hostname = (
            re.compile(rf"\b{re.escape(hostname)}\b")
            if hostname and hostname != "localhost"
            else None
        )

    def element(self, vector: ET.Element) -> None:
        if (message := vector.get("message")) is not None:
            vector.set("message", self.text(message))
        name = vector.get("name", "")
        number, text = vector.tag.endswith("NumberVector"), vector.tag.endswith("TextVector")
        for child in vector:
            if child.text is None:
                continue
            element = child.get("name", "")
            if number and name == "GEOGRAPHIC_COORD" and element in SITE_ELEMENTS:
                child.text = self._site(element, child.text)
            elif text and (name in SERIAL_PROPERTIES or element in SERIAL_ELEMENTS):
                child.text = self._serial(child.text)
            elif text and name == "DEVICE_ADDRESS" and element == "ADDRESS":
                child.text = self._address(child.text)
            elif text:
                child.text = self.text(child.text)

    def text(self, value: str) -> str:
        """Free text (a text element, a message) with what identifies the user replaced."""
        for serial, placeholder in self._serials.items():
            if len(serial) >= _MIN_SERIAL and serial in value:
                value = value.replace(serial, placeholder)
                self.counts["serials"] += 1
        value = _BY_ID.sub(self._by_id, value)
        value = self._sub(_IPV4, DOCUMENTATION_ADDRESS, value, "hosts")
        if self._hostname is not None:
            value = self._sub(self._hostname, "host", value, "hosts")
        return self._sub(_HOME, "/home/user", value, "home")

    def _sub(self, pattern: re.Pattern[str], replacement: str, value: str, kind: str) -> str:
        def replace(match: re.Match[str]) -> str:
            if match.group(0) != replacement:
                self.counts[kind] += 1
            return replacement

        return pattern.sub(replace, value)

    def _site(self, element: str, value: str) -> str:
        try:
            number = parse_number(value)
        except ProtocolError:
            number = 0.0
        # 1° (~100 km) keeps the hemisphere, which mounts' behaviour depends on.
        rounded = float(round(number, -2 if element == "ELEV" else 0))
        if rounded != number:
            self.counts["site"] += 1
        return repr(rounded)

    def _serial(self, value: str) -> str:
        serial = value.strip()
        if not serial:
            return value
        self.counts["serials"] += 1
        return self._serials.setdefault(serial, f"serial-{len(self._serials) + 1}")

    def _by_id(self, match: re.Match[str]) -> str:
        return match.group(1) + self._serial(match.group(2)) + match.group(3)

    def _address(self, value: str) -> str:
        if not value.strip() or _IPV4.fullmatch(value.strip()):
            return self.text(value)
        self.counts["hosts"] += 1
        return "host.invalid"


# -- the session, written by a thread ------------------------------------------


class _Splitter:
    """Splits a stream of top-level INDI elements into elements, as ``StreamParser`` does."""

    def __init__(self) -> None:
        self._parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("start", "end"))
        self._parser.feed(b"<indi>")
        self._root: ET.Element | None = None
        self._depth = 0

    def feed(self, data: bytes) -> list[ET.Element]:
        try:
            self._parser.feed(data)
            self._parser.flush()
            events = [cast(tuple[str, ET.Element], e) for e in self._parser.read_events()]
        except ET.ParseError as e:
            raise ProtocolError(f"invalid XML: {e}") from e
        elements: list[ET.Element] = []
        for event, elem in events:
            if event == "start":
                if self._root is None:
                    self._root = elem
                self._depth += 1
                continue
            self._depth -= 1
            if self._depth == 1 and self._root is not None:
                elements.append(elem)
                self._root.remove(elem)
        return elements


type _Item = tuple[float, bytes] | None


class _Writer(threading.Thread):
    def __init__(
        self,
        path: Path,
        devices: frozenset[str] | None,
        scrubber: Scrubber,
        max_bytes: int,
        on_end: Callable[[EndReason], None],
    ) -> None:
        super().__init__(name="indi-recording", daemon=True)
        self.items: queue.SimpleQueue[_Item] = queue.SimpleQueue()
        self.path = path
        self.devices = devices
        self.scrubber = scrubber
        self.max_bytes = max_bytes
        self.on_end = on_end
        self.bytes = 0
        self.messages = 0
        self.commands = 0
        self.blobs_dropped = 0
        self.recorded: set[str] = set()
        self.drivers: dict[str, dict[str, str]] = {}
        self._ended = False

    def run(self) -> None:
        splitter = _Splitter()
        with self.path.open("wb") as f:
            while (item := self.items.get()) is not None:
                if self._ended:
                    continue
                t, data = item
                try:
                    elements = splitter.feed(data)
                except ProtocolError:
                    self._end(EndReason.INVALID)
                    continue
                for elem in elements:
                    if self._wanted(elem) and not self._write(f, t, elem):
                        self._end(EndReason.SIZE)
                        break

    def _end(self, reason: EndReason) -> None:
        self._ended = True
        self.on_end(reason)

    def _wanted(self, elem: ET.Element) -> bool:
        if elem.tag in ("pingRequest", "pingReply"):
            return False
        device = elem.get("device")
        if device is None:
            return self.devices is None or elem.tag == "message"
        return self.devices is None or device in self.devices

    def _write(self, f: BufferedWriter, t: float, elem: ET.Element) -> bool:
        if elem.tag.endswith("BLOBVector") and not elem.tag.startswith("def"):
            for child in elem:
                if child.text and child.text.strip():
                    child.text = None
                    self.blobs_dropped += 1
        self.scrubber.element(elem)
        xml = ET.tostring(elem, encoding="unicode")
        line = (json.dumps({"t": round(t, 3), "xml": xml}) + "\n").encode()
        if self.bytes + len(line) > self.max_bytes:
            return False
        f.write(line)
        self.bytes += len(line)
        self.messages += 1
        self.commands += elem.tag.startswith("new")
        if (device := elem.get("device")) is not None:
            self.recorded.add(device)
            if elem.tag == "defTextVector" and elem.get("name") == "DRIVER_INFO":
                info = {child.get("name", ""): (child.text or "").strip() for child in elem}
                self.drivers[device] = {
                    "name": info.get("DRIVER_NAME", ""),
                    "exec": info.get("DRIVER_EXEC", ""),
                    "version": info.get("DRIVER_VERSION", ""),
                    "interface": info.get("DRIVER_INTERFACE", ""),
                }
        return True


# -- the recorder --------------------------------------------------------------


class Recorder:
    """One recording, from ``start`` to ``stop``; ``ended`` is set when it stops by
    itself (a limit, indiserver gone), and the owner then calls ``stop``."""

    def __init__(
        self,
        host: str,
        port: int,
        path: Path,
        *,
        devices: Collection[str] | None = None,
        note: str = "",
        limits: Limits = DEFAULT_LIMITS,
        hostname: str | None = None,
    ) -> None:
        self.host, self.port, self.path = host, port, path
        self.devices = frozenset(devices) if devices is not None else None
        self.note = note
        self.limits = limits
        self.scrubber = Scrubber(hostname if hostname is not None else socket.gethostname())
        self.ended = asyncio.Event()
        self.reason: EndReason | None = None
        self.started_at = datetime.now(UTC)
        self._start = time.monotonic()
        self._stopped_after: float | None = None
        self._session = path.with_suffix(".jsonl")
        self._thread = _Writer(
            self._session, self.devices, self.scrubber, limits.bytes, self._end_threadsafe
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._written = False

    @property
    def elapsed(self) -> float:
        if self._stopped_after is not None:
            return self._stopped_after
        return time.monotonic() - self._start

    @property
    def bytes(self) -> int:
        return self._thread.bytes

    @property
    def messages(self) -> int:
        return self._thread.messages

    @property
    def recorded(self) -> list[str]:
        """The devices the session holds messages of."""
        return sorted(self._thread.recorded)

    async def start(self, timeout: float = 5.0) -> None:
        self._loop = asyncio.get_running_loop()
        reader, self._stream = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout
        )
        self.started_at, self._start = datetime.now(UTC), time.monotonic()
        self._thread.start()
        # indiserver then sends this connection only these devices, every property
        # defined first; BLOBs stay off (enableBLOB defaults to Never).
        for device in sorted(self.devices) if self.devices is not None else [None]:
            self._stream.write(encode_get_properties(device))
        await self._stream.drain()
        self._task = asyncio.create_task(self._read(reader), name="indi-recording")

    async def stop(self) -> Path:
        """End the recording (if it has not ended by itself) and write the zip."""
        if self._written:
            return self.path
        self._end(EndReason.STOPPED)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._stream is not None:
            self._stream.close()
            with contextlib.suppress(ConnectionError, OSError):
                await self._stream.wait_closed()
        self._thread.items.put(None)
        if self._thread.is_alive():
            await asyncio.to_thread(self._thread.join)
        await asyncio.to_thread(self._bundle)
        self._written = True
        return self.path

    async def _read(self, reader: asyncio.StreamReader) -> None:
        reason = EndReason.DISCONNECTED
        try:
            async with asyncio.timeout(self.limits.duration):
                while data := await reader.read(_READ_SIZE):
                    self._thread.items.put((self.elapsed, data))
        except TimeoutError:
            reason = EndReason.DURATION
        except (ConnectionError, OSError):
            pass
        self._end(reason)

    def _end(self, reason: EndReason) -> None:
        if self.reason is None:
            self.reason = reason
            self._stopped_after = self.elapsed
            self.ended.set()

    def _end_threadsafe(self, reason: EndReason) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._end, reason)

    def manifest(self) -> dict[str, Json]:
        thread = self._thread
        devices: list[Json] | None = None
        if self.devices is not None:
            devices = [*sorted(self.devices)]
        recorded: list[Json] = [*self.recorded]
        return {
            "format": FORMAT,
            "nocs": __version__,
            "started": self.started_at.isoformat(timespec="seconds"),
            "duration": round(self.elapsed, 1),
            "end": self.reason.value if self.reason is not None else None,
            "note": self.note,
            "devices": devices,
            "recorded": recorded,
            "drivers": {device: dict(info) for device, info in sorted(thread.drivers.items())},
            "indi_packages": dict(indi_packages()),
            "messages": thread.messages,
            "commands": thread.commands,
            "bytes": thread.bytes,
            "blobs_dropped": thread.blobs_dropped,
            "scrubbed": dict(sorted(self.scrubber.counts.items())),
        }

    def _bundle(self) -> None:
        if not self._session.exists():
            self._session.touch()
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST, json.dumps(self.manifest(), indent=2) + "\n")
            archive.write(self._session, SESSION)
        self._session.unlink()


def indi_packages() -> dict[str, str]:
    """Installed INDI packages and their versions (none where dpkg is missing)."""
    try:
        out = subprocess.run(
            ["dpkg-query", "-W", "-f", "${Package}\\t${Version}\\n", *INDI_PACKAGES],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    packages: dict[str, str] = {}
    for line in out.splitlines():
        package, _, version = line.partition("\t")
        if version:
            packages[package] = version
    return packages


# -- reading -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordedMessage:
    t: float
    xml: str

    @property
    def command(self) -> bool:
        """A client's ``new*Vector``, echoed by indiserver."""
        return self.xml.startswith("<new")


@dataclass(frozen=True, slots=True)
class Recording:
    manifest: dict[str, Json]
    messages: list[RecordedMessage]

    def stream(self) -> bytes:
        """The session as indiserver sent it (``StreamParser`` reads it, commands aside)."""
        return b"".join(m.xml.encode() + b"\n" for m in self.messages)


def read(path: Path) -> Recording:
    with zipfile.ZipFile(path) as archive:
        manifest = cast(dict[str, Json], json.loads(archive.read(MANIFEST)))
        lines = archive.read(SESSION).decode().splitlines()
    messages: list[RecordedMessage] = []
    for line in lines:
        entry = cast(dict[str, Json], json.loads(line))
        t, xml = entry["t"], entry["xml"]
        assert isinstance(t, float | int)
        assert isinstance(xml, str)
        messages.append(RecordedMessage(float(t), xml))
    return Recording(manifest, messages)
