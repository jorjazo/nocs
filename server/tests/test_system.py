# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""nocs-system and nocsd's use of it (ADR 0027), with fake tools on the PATH."""

import os
import pwd
import subprocess
import sys
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import anyio
import pytest
from anyio.from_thread import start_blocking_portal
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import SystemState
from nocs.config import Settings
from nocs.jobs import JobManager
from nocs.services.system import OperationUnavailableError, SystemBusyError, SystemService
from nocs.state import StateStore
from nocs.system.client import HelperUnavailableError, call
from nocs.system.operations import Context, update_hosts
from nocs.system.protocol import HelperError
from nocs.system.server import Config, Helper, load_config

ALL = frozenset({"power", "hostname"})


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake systemctl and hostnamectl that log how they were called; returns the log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tools.log"
    for tool in ("systemctl", "hostnamectl"):
        script = bin_dir / tool
        script.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n')
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def config(tmp_path: Path, enabled: frozenset[str] = ALL, uid: int | None = None) -> Config:
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n127.0.1.1\tnocs\n")
    # Unix socket paths are short (108 bytes): pytest's directories can be longer.
    socket = Path(f"/tmp/nocs-system-test-{os.getpid()}-{id(tmp_path)}.sock")
    return Config(
        uid=os.getuid() if uid is None else uid,
        gid=os.getgid(),
        enabled=enabled,
        socket=socket,
        context=Context(hosts=hosts),
    )


@contextmanager
def serving(cfg: Config) -> Generator[Config]:
    """Run the helper on an event loop of its own, in a thread, like the real one."""
    with start_blocking_portal() as portal:
        future, _ = portal.start_task(Helper(cfg).serve)
        try:
            yield cfg
        finally:
            future.cancel()
    cfg.socket.unlink(missing_ok=True)


@pytest.fixture
def helper(tmp_path: Path, tools: Path) -> Iterator[Config]:
    with serving(config(tmp_path)) as cfg:
        yield cfg


async def test_hello_lists_the_enabled_operations(tmp_path: Path, tools: Path) -> None:
    with serving(config(tmp_path, enabled=frozenset({"hostname"}))) as cfg:
        hello = await call("hello", socket=cfg.socket)
    assert hello == {"version": 1, "operations": ["hostname.set"]}


async def test_reboot_and_power_off_run_systemctl(helper: Config, tools: Path) -> None:
    assert await call("power.reboot", socket=helper.socket) == {}
    assert await call("power.poweroff", socket=helper.socket) == {}
    assert calls(tools) == ["systemctl reboot", "systemctl poweroff"]


async def test_a_disabled_group_is_refused(tmp_path: Path, tools: Path) -> None:
    with (
        serving(config(tmp_path, enabled=frozenset({"hostname"}))) as cfg,
        pytest.raises(HelperError) as refused,
    ):
        await call("power.reboot", socket=cfg.socket)
    assert refused.value.code == "disabled"
    assert calls(tools) == []


async def test_unknown_operations_and_arguments_are_refused(helper: Config, tools: Path) -> None:
    with pytest.raises(HelperError) as unknown:
        await call("shell.run", {"command": "id"}, socket=helper.socket)
    assert unknown.value.code == "unknown"
    with pytest.raises(HelperError) as extra:
        await call("power.reboot", {"when": "now"}, socket=helper.socket)
    assert extra.value.code == "invalid"
    assert calls(tools) == []


async def test_set_hostname(helper: Config, tools: Path) -> None:
    assert await call("hostname.set", {"name": " Nocs-West "}, socket=helper.socket) == {
        "name": "nocs-west"
    }
    assert calls(tools) == ["hostnamectl set-hostname nocs-west"]
    assert helper.context.hosts.read_text() == "127.0.0.1\tlocalhost\n127.0.1.1\tnocs-west\n"


@pytest.mark.parametrize("name", ["", "-nocs", "nocs-", "no cs", "nocs.local", "a" * 64, "ñocs"])
async def test_invalid_hostnames_run_nothing(helper: Config, tools: Path, name: str) -> None:
    with pytest.raises(HelperError) as refused:
        await call("hostname.set", {"name": name}, socket=helper.socket)
    assert refused.value.code == "invalid"
    assert calls(tools) == []


async def test_a_failing_tool_reports_its_message(helper: Config, tools: Path) -> None:
    systemctl = tools.parent / "bin" / "systemctl"
    systemctl.write_text("#!/bin/sh\necho 'Access denied' >&2\nexit 1\n")
    with pytest.raises(HelperError) as failed:
        await call("power.reboot", socket=helper.socket)
    assert failed.value.code == "failed"
    assert str(failed.value) == "systemctl: Access denied"


@pytest.mark.skipif(os.getuid() == 0, reason="root is always served")
async def test_other_users_get_no_answer(tmp_path: Path, tools: Path) -> None:
    with (
        serving(config(tmp_path, uid=os.getuid() + 1)) as cfg,
        pytest.raises(HelperUnavailableError, match="closed the connection"),
    ):
        await call("power.reboot", socket=cfg.socket)
    assert calls(tools) == []


async def test_bad_messages_get_an_error_and_the_connection_goes_on(helper: Config) -> None:
    async with await anyio.connect_unix(helper.socket) as stream:
        await stream.send(b"not json\n[1]\n" + b'{"id": 7, "op": "hello"}\n')
        replies = b""
        while replies.count(b"\n") < 3:
            replies += await stream.receive()
    first, second, third = replies.splitlines()
    assert b'"code":"invalid"' in first
    assert b'"code":"invalid"' in second
    assert third.startswith(b'{"id":7,"result":')


async def test_a_message_too_long_closes_the_connection(helper: Config) -> None:
    async with await anyio.connect_unix(helper.socket) as stream:
        await stream.send(b"x" * 70000)
        reply = await stream.receive()
    assert b"at most 65536 bytes" in reply


async def test_without_helper_calls_say_it_is_not_running(tmp_path: Path) -> None:
    with pytest.raises(HelperUnavailableError, match="not running"):
        await call("hello", socket=tmp_path / "missing.sock")


def test_load_config(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    user = pwd.getpwuid(os.getuid())
    path = tmp_path / "system.conf"
    path.write_text(
        f"[helper]\nuser = {user.pw_name}\n[operations]\nenabled = power, magic  # comment\n"
    )
    loaded = load_config(path)
    assert (loaded.uid, loaded.gid, loaded.enabled) == (user.pw_uid, user.pw_gid, {"power"})
    assert "unknown group of operations 'magic'" in caplog.text


def test_update_hosts_adds_the_entry_after_localhost(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n::1 ip6-localhost\n")
    update_hosts(hosts, "nocs")
    assert hosts.read_text() == "127.0.0.1 localhost\n127.0.1.1\tnocs\n::1 ip6-localhost\n"


def test_the_helper_imports_nothing_else_from_nocs() -> None:
    """It runs as root: the network stack and the scientific libraries stay out (ADR 0027)."""
    probe = (
        "import sys, nocs.system.server\n"
        "print(' '.join(m for m in sys.modules if m.split('.')[0] in"
        " {'numpy', 'cv2', 'astropy', 'fastapi', 'starlette', 'pydantic', 'uvicorn'}"
        " or (m.startswith('nocs.') and not m.startswith('nocs.system'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


# -- nocsd's side ---------------------------------------------------------------


async def test_service_publishes_what_the_helper_offers(helper: Config) -> None:
    store = StateStore()
    service = SystemService(store, JobManager(store), helper.socket)
    await service.refresh()
    state = SystemState.model_validate(store.get(("system",)))
    assert state.helper is True
    assert state.operations == ["power.reboot", "power.poweroff", "hostname.set"]
    assert state.error is None


async def test_reboot_waits_for_running_work_unless_forced(helper: Config, tools: Path) -> None:
    store = StateStore()
    jobs = JobManager(store)
    service = SystemService(store, jobs, helper.socket)
    await service.refresh()
    jobs.reserve("slew pad", ["mount"])
    with pytest.raises(SystemBusyError, match="slew pad running"):
        await service.reboot()
    assert calls(tools) == []
    await service.reboot(force=True)
    assert calls(tools) == ["systemctl reboot"]


async def test_service_without_helper(tmp_path: Path) -> None:
    store = StateStore()
    service = SystemService(store, JobManager(store), tmp_path / "missing.sock")
    await service.refresh()
    state = SystemState.model_validate(store.get(("system",)))
    assert (state.helper, state.operations) == (False, [])
    assert "not running" in str(state.error)
    with pytest.raises(OperationUnavailableError, match=r"cannot do power\.poweroff"):
        await service.power_off()
    with pytest.raises(ValueError, match="hyphens"):
        await service.set_hostname("no cs")


@pytest.fixture
def api(tmp_path: Path, tools: Path) -> Iterator[TestClient]:
    with serving(config(tmp_path)) as cfg:
        settings = Settings(
            indi_host="127.0.0.1",
            indi_port=9,
            config_dir=tmp_path / "config",
            data_dir=tmp_path / "data",
            system_socket=cfg.socket,
        )
        with TestClient(create_app(settings)) as client:
            pair_owner(client)
            yield client


def test_api_reboot_and_rename(api: TestClient, tools: Path) -> None:
    client = api
    assert client.post("/api/system/reboot").status_code == 204
    assert client.post("/api/system/poweroff", json={"force": False}).status_code == 204
    assert client.put("/api/system/hostname", json={"name": "rig-2"}).status_code == 204
    assert calls(tools) == [
        "systemctl reboot",
        "systemctl poweroff",
        "hostnamectl set-hostname rig-2",
    ]
    response = client.put("/api/system/hostname", json={"name": "rig 2"})
    assert response.status_code == 422
    assert "hyphens" in response.json()["detail"]
    assert client.get("/api/state").json()["state"]["system"]["helper"] is True


def test_api_without_helper_is_503(tmp_path: Path) -> None:
    settings = Settings(
        indi_host="127.0.0.1",
        indi_port=9,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        system_socket=tmp_path / "missing.sock",
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        response = client.post("/api/system/reboot")
    assert response.status_code == 503
    assert "not running" in response.json()["detail"]
