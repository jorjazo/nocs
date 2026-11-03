"""Recording an INDI session (ADR 0038) against a fake indiserver."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nocs.indi.protocol import DefineProperty, StreamParser
from nocs.indi.recording import (
    DEFAULT_LIMITS,
    EndReason,
    Limits,
    Recorder,
    Scrubber,
    read,
)

SERIAL = "2e2bcd002b020900"

SESSION = f"""
<defTextVector device="Camera" name="DRIVER_INFO" state="Idle" perm="ro">
    <defText name="DRIVER_NAME">ZWO CCD</defText>
    <defText name="DRIVER_EXEC">indi_asi_ccd</defText>
    <defText name="DRIVER_VERSION">2.6</defText>
    <defText name="DRIVER_INTERFACE">6</defText>
</defTextVector>
<defTextVector device="Camera" name="Serial Number" state="Idle" perm="ro">
    <defText name="SN">
{SERIAL}
    </defText>
</defTextVector>
<defNumberVector device="Mount" name="GEOGRAPHIC_COORD" state="Idle" perm="rw">
    <defNumber name="LAT" format="%012.8m" min="-90" max="90" step="0">-30.027777</defNumber>
    <defNumber name="LONG" format="%012.8m" min="0" max="360" step="0">289.2667</defNumber>
    <defNumber name="ELEV" format="%g" min="-200" max="10000" step="0">2371</defNumber>
</defNumberVector>
<defTextVector device="Mount" name="DEVICE_PORT" state="Ok" perm="rw">
    <defText name="PORT">/dev/serial/by-id/usb-ZWO_Systems_ZWO_Device_123456-if00</defText>
</defTextVector>
<defTextVector device="Mount" name="DEVICE_ADDRESS" state="Idle" perm="rw">
    <defText name="ADDRESS">mount.lan</defText>
    <defText name="PORT">9999</defText>
</defTextVector>
<defTextVector device="Other" name="DRIVER_INFO" state="Idle" perm="ro">
    <defText name="DRIVER_EXEC">indi_other</defText>
</defTextVector>
<message device="Camera" timestamp="2026-11-03T20:00:00"
    message="{SERIAL} at 10.0.0.5 saves to /home/jorjazo/frames on nocs-lab"/>
<setBLOBVector device="Camera" name="CCD1" state="Ok">
    <oneBLOB name="CCD1" size="3" format=".fits">QUJD</oneBLOB>
</setBLOBVector>
<newNumberVector device="Mount" name="GEOGRAPHIC_COORD">
    <oneNumber name="LAT">-30.027777</oneNumber>
    <oneNumber name="LONG">289.2667</oneNumber>
    <oneNumber name="ELEV">2371</oneNumber>
</newNumberVector>
<newSwitchVector device="Other" name="CONNECTION">
    <oneSwitch name="CONNECT">On</oneSwitch>
</newSwitchVector>
""".encode()
"""What a fake indiserver sends: definitions, a message, a BLOB and two clients'
commands (indiserver echoes them to every other client)."""
ALL = 10
CHOSEN = 8
"""Messages about Camera and Mount."""


class FakeServer:
    """Sends ``SESSION`` to whoever connects and keeps what they send."""

    def __init__(self) -> None:
        self.received = bytearray()
        self.clients: list[asyncio.StreamWriter] = []
        self.port = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.append(writer)
        writer.write(SESSION)
        await writer.drain()
        while data := await reader.read(4096):
            self.received += data

    def close_clients(self) -> None:
        for writer in self.clients:
            writer.close()


@pytest.fixture
async def server() -> AsyncIterator[FakeServer]:
    fake = FakeServer()
    tcp = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    fake.port = tcp.sockets[0].getsockname()[1]
    async with tcp:
        yield fake
        fake.close_clients()


async def wait_messages(recorder: Recorder, count: int) -> None:
    async with asyncio.timeout(5):
        while recorder.messages < count:  # noqa: ASYNC110 (counted by the writer thread)
            await asyncio.sleep(0.01)


def recorder(
    server: FakeServer,
    tmp_path: Path,
    *,
    devices: list[str] | None = None,
    note: str = "",
    limits: Limits = DEFAULT_LIMITS,
) -> Recorder:
    path = tmp_path / "session.zip"
    return Recorder(
        "127.0.0.1",
        server.port,
        path,
        devices=devices,
        note=note,
        limits=limits,
        hostname="nocs-lab",
    )


async def test_records_the_chosen_devices_scrubbed(server: FakeServer, tmp_path: Path) -> None:
    rec = recorder(server, tmp_path, devices=["Camera", "Mount"], note="slewed, parked")
    await rec.start()
    await wait_messages(rec, CHOSEN)
    path = await rec.stop()

    assert b'<getProperties version="1.7" device="Camera" />' in server.received
    assert b'<getProperties version="1.7" device="Mount" />' in server.received
    recording = read(path)
    xml = "".join(m.xml for m in recording.messages)
    assert [m.command for m in recording.messages].count(True) == 1
    assert "Other" not in xml
    # The site rounded to 1° (elevation to 100 m), in definitions and commands alike.
    assert xml.count(">-30.0<") == 2
    assert xml.count(">289.0<") == 2
    assert xml.count(">2400.0<") == 2
    # Serial numbers, addresses, the host name and home directories replaced.
    assert SERIAL not in xml
    assert "123456" not in xml
    assert "usb-ZWO_Systems_ZWO_Device_serial-2-if00" in xml
    assert "serial-1 at 192.0.2.1 saves to /home/user/frames on host" in xml
    assert ">host.invalid<" in xml
    assert "QUJD" not in xml

    manifest = recording.manifest
    assert manifest["format"] == 1
    assert manifest["note"] == "slewed, parked"
    assert manifest["end"] == "stopped"
    assert manifest["devices"] == ["Camera", "Mount"]
    assert manifest["recorded"] == ["Camera", "Mount"]
    assert manifest["drivers"] == {
        "Camera": {"name": "ZWO CCD", "exec": "indi_asi_ccd", "version": "2.6", "interface": "6"}
    }
    assert manifest["blobs_dropped"] == 1
    assert manifest["messages"] == len(recording.messages) == CHOSEN
    assert manifest["commands"] == 1
    assert manifest["scrubbed"] == {"home": 1, "hosts": 3, "serials": 3, "site": 6}
    assert not (tmp_path / "session.jsonl").exists()

    parsed = StreamParser().feed(recording.stream())
    assert len([m for m in parsed if isinstance(m, DefineProperty)]) == 5


async def test_records_every_device_by_default(server: FakeServer, tmp_path: Path) -> None:
    rec = recorder(server, tmp_path)
    await rec.start()
    await wait_messages(rec, ALL)
    await rec.stop()

    assert b'<getProperties version="1.7" />' in server.received
    assert rec.recorded == ["Camera", "Mount", "Other"]


async def test_stops_at_its_size_limit(server: FakeServer, tmp_path: Path) -> None:
    rec = recorder(server, tmp_path, limits=Limits(bytes=1500))
    await rec.start()
    async with asyncio.timeout(5):
        await rec.ended.wait()
    await rec.stop()

    assert rec.reason is EndReason.SIZE
    manifest = read(rec.path).manifest
    assert manifest["end"] == "size limit"
    assert isinstance(size := manifest["bytes"], int)
    assert 0 < size <= 1500


async def test_stops_at_its_time_limit(server: FakeServer, tmp_path: Path) -> None:
    rec = recorder(server, tmp_path, limits=Limits(duration=0.3))
    await rec.start()
    async with asyncio.timeout(5):
        await rec.ended.wait()
    await rec.stop()

    assert rec.reason is EndReason.DURATION
    assert read(rec.path).manifest["end"] == "time limit"


async def test_stops_when_indiserver_closes(server: FakeServer, tmp_path: Path) -> None:
    rec = recorder(server, tmp_path)
    await rec.start()
    await wait_messages(rec, ALL)
    server.close_clients()
    async with asyncio.timeout(5):
        await rec.ended.wait()
    await rec.stop()

    assert rec.reason is EndReason.DISCONNECTED
    assert len(read(rec.path).messages) == ALL


async def test_stopping_twice_keeps_the_recording(server: FakeServer, tmp_path: Path) -> None:
    rec = recorder(server, tmp_path)
    await rec.start()
    await wait_messages(rec, ALL)
    await rec.stop()
    await rec.stop()

    assert len(read(rec.path).messages) == ALL


def test_scrubber_leaves_what_does_not_identify() -> None:
    scrubber = Scrubber(hostname="localhost")

    assert scrubber.text("connected to localhost, driver 2.2.5") == (
        "connected to localhost, driver 2.2.5"
    )
    assert scrubber.text("/home/user/x and 192.0.2.1") == "/home/user/x and 192.0.2.1"
    assert not scrubber.counts
