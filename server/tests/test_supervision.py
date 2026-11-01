"""Noticing a hung indiserver, restarting services and feeding systemd's watchdog
(ADR 0030), with a fake indiserver that can stop answering."""

import asyncio
import os
import socket
from collections.abc import AsyncIterator, Generator
from pathlib import Path

import anyio
import pytest

from nocs.indi import IndiClient
from nocs.indi.protocol import PingReply, StreamParser
from nocs.jobs import JobManager
from nocs.services import indi_bridge, watchdog
from nocs.services.indi_bridge import IndiBridge
from nocs.services.system import SystemBusyError, SystemService
from nocs.state import StateStore
from nocs.system.operations import Context, restart_service
from nocs.system.protocol import HelperError


class FakeIndiserver:
    """Answers pings while ``answering``; every connection counts."""

    def __init__(self) -> None:
        self.answering = True
        self.connections = 0
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while data := await reader.read(65536):
                for chunk in data.split(b"/>"):
                    if b"<pingRequest" in chunk and self.answering:
                        uid = chunk.split(b'uid="', 1)[1].split(b'"', 1)[0]
                        writer.write(b'<pingReply uid="' + uid + b'"/>\n')
                        await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()


@pytest.fixture
async def indiserver() -> AsyncIterator[FakeIndiserver]:
    server = FakeIndiserver()
    await server.start()
    yield server
    await server.stop()


def test_ping_replies_are_parsed() -> None:
    assert StreamParser().feed(b'<pingReply uid="nocs-1"/>') == [PingReply("nocs-1")]


async def test_ping(indiserver: FakeIndiserver) -> None:
    client = IndiClient("127.0.0.1", indiserver.port)
    await client.connect()
    assert await client.ping(1.0) < 1.0
    indiserver.answering = False
    with pytest.raises(TimeoutError):
        await client.ping(0.2)
    await client.close()


async def test_a_hung_indiserver_is_restarted_and_reconnected(
    indiserver: FakeIndiserver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(indi_bridge, "PING_EVERY", 0.05)
    monkeypatch.setattr(indi_bridge, "PING_TIMEOUT", 0.1)
    monkeypatch.setattr(indi_bridge, "MISSES", 2)
    store = StateStore()
    restarts: list[float] = []

    async def restart() -> None:
        restarts.append(anyio.current_time())
        indiserver.answering = True  # as a fresh indiserver would

    bridge = IndiBridge(store, "127.0.0.1", indiserver.port, on_hung=restart)
    task = asyncio.create_task(bridge.run())
    with anyio.fail_after(5):
        while indiserver.connections < 1 or bridge.client is None:  # noqa: ASYNC110
            await anyio.sleep(0.01)
        indiserver.answering = False
        while store.get(("indi", "server", "responsive")) is not False:  # noqa: ASYNC110
            await anyio.sleep(0.01)
        assert store.get(("indi", "server", "connected")) is True
        while indiserver.connections < 2:  # noqa: ASYNC110
            await anyio.sleep(0.01)
    assert len(restarts) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_services_restart_runs_systemctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "calls.log"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f'#!/bin/sh\necho "systemctl $*" >> "{log}"\n')
    systemctl.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    assert await restart_service(Context(), {"service": "indiserver"}) == {}
    assert log.read_text() == "systemctl restart nocs-indiserver.service\n"
    bad: list[dict[str, object]] = [
        {"service": "nocsd"},
        {"service": "ssh"},
        {},
        {"service": "phd2", "x": 1},
    ]
    for args in bad:
        with pytest.raises(HelperError, match="the arguments are"):
            await restart_service(Context(), args)
    assert log.read_text().count("\n") == 1


async def test_restarting_indiserver_waits_for_jobs_unless_forced(tmp_path: Path) -> None:
    store = StateStore()
    jobs = JobManager(store)
    jobs.reserve("slew pad", ["mount"])
    service = SystemService(store, jobs, tmp_path / "missing.sock")
    with pytest.raises(SystemBusyError):
        await service.restart_service("indiserver")


@pytest.fixture
def notify_socket() -> Generator[tuple[socket.socket, str]]:
    # Unix socket paths are short: pytest's directories can be too long for one.
    path = f"/tmp/nocs-notify-{os.getpid()}.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(path)
    sock.settimeout(1)
    yield sock, path
    sock.close()
    os.unlink(path)


def test_notify_outside_systemd_does_nothing() -> None:
    assert watchdog.notify("READY=1", {}) is False
    assert watchdog.interval({}) is None


def test_the_watchdog_is_fed_three_times_a_period() -> None:
    environ = {"WATCHDOG_USEC": "30000000", "WATCHDOG_PID": str(os.getpid())}
    assert watchdog.interval(environ) == 10.0
    assert watchdog.interval(environ | {"WATCHDOG_PID": "1"}) is None  # meant for another


async def test_ready_then_watchdog(notify_socket: tuple[socket.socket, str]) -> None:
    sock, path = notify_socket
    environ = {"NOTIFY_SOCKET": path, "WATCHDOG_USEC": "300000"}
    with anyio.move_on_after(0.25):
        await watchdog.run(environ)
    messages: list[bytes] = []
    sock.settimeout(0.1)
    try:
        while True:
            messages.append(sock.recv(64))
    except TimeoutError:
        pass
    assert messages[0] == b"READY=1"
    assert messages[1:3] == [b"WATCHDOG=1", b"WATCHDOG=1"]
