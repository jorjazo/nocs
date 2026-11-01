"""Updates from apt, only when asked (ADR 0025), with fake apt, dpkg and systemd."""

from pathlib import Path

import anyio
import pytest
from test_timekeeping import Tools

from nocs.jobs import JobManager
from nocs.services.system import SystemBusyError, SystemService
from nocs.state import StateStore
from nocs.system.protocol import HelperError
from nocs.system.updates import UpdatePaths, Updates

UPGRADABLE = (
    "Listing...\n"
    "nocs/stable 0.1.1 arm64 [upgradable from: 0.1.0]\n"
    "indi-bin/noble 2.2.6+202611 arm64 [upgradable from: 2.2.5+202610]\n"
)


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tools:
    tools = Tools(tmp_path, monkeypatch)
    for tool in ("apt-get", "systemd-run", "dpkg"):
        tools.add(tool)
    tools.answer("apt", "list", UPGRADABLE)
    tools.answer("dpkg-query", "nocs", "0.1.0")
    tools.answer("systemctl", "show", "inactive\n")
    tools.answer(
        "journalctl",
        "nocs-update.service",
        "Unpacking nocs (0.1.1)...\nSetting up nocs (0.1.1)...\n",
    )
    return tools


@pytest.fixture
def paths(tmp_path: Path) -> UpdatePaths:
    (tmp_path / "archives").mkdir()
    return UpdatePaths(state=tmp_path / "state/updates.json", archives=tmp_path / "archives")


async def drive(updates: Updates) -> None:
    """Let the actor do what was asked."""
    async with anyio.create_task_group() as tg:
        tg.start_soon(updates.run)
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()


async def test_check_lists_what_would_be_upgraded(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    assert await updates.check({}) == {"accepted": True}
    assert (await updates.status({}))["state"] == "checking"
    await drive(updates)
    status = await updates.status({})
    assert status["state"] == "idle"
    assert status["upgradable"] == [
        {"name": "nocs", "to": "0.1.1", "from": "0.1.0"},
        {"name": "indi-bin", "to": "2.2.6+202611", "from": "2.2.5+202610"},
    ]
    assert status["installed"] == "0.1.0"
    assert "apt-get update" in tools.calls()


async def test_install_runs_apart_and_is_followed(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    await updates.install({})
    await drive(updates)
    run = next(call for call in tools.calls() if call.startswith("systemd-run"))
    assert "--unit=nocs-update" in run
    assert "--setenv=NEEDRESTART_MODE=l" in run
    assert run.endswith("apt-get -y -o Dpkg::Options::=--force-confold upgrade --with-new-pkgs")
    tools.answer("systemctl", "show", "active\n")
    assert (await updates.status({}))["state"] == "installing"
    tools.answer("systemctl", "show", "inactive\n")
    status = await updates.status({})
    assert (status["state"], status["previous"]) == ("succeeded", "0.1.0")
    assert status["log"] == ["Unpacking nocs (0.1.1)...", "Setting up nocs (0.1.1)..."]
    # A restarted nocs-system still knows what it was doing.
    assert (await Updates(paths).status({}))["state"] == "succeeded"
    tools.answer("systemctl", "show", "failed\n")
    assert (await updates.status({}))["state"] == "failed"


async def test_rollback_installs_the_cached_package(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    with pytest.raises(HelperError, match="no earlier version"):
        await updates.rollback({})
    await updates.install({})
    await drive(updates)
    (paths.archives / "nocs_0.1.0_arm64.deb").write_bytes(b"")
    await updates.rollback({})
    await drive(updates)
    assert tools.calls()[-1].endswith(f"dpkg -i {paths.archives / 'nocs_0.1.0_arm64.deb'}")


async def test_rollback_needs_the_package_in_the_cache(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    await updates.install({})
    await drive(updates)
    await updates.rollback({})
    await drive(updates)
    assert "no longer in apt's cache" in str((await updates.status({}))["error"])


async def test_one_thing_at_a_time(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    await updates.check({})
    with pytest.raises(HelperError, match="already"):
        await updates.install({})
    with pytest.raises(HelperError, match="unexpected arguments"):
        await Updates(paths).install({"packages": ["nocs"]})


async def test_nocsd_installs_only_between_jobs(tmp_path: Path) -> None:
    store = StateStore()
    jobs = JobManager(store)
    jobs.reserve("slew pad", ["mount"])
    service = SystemService(store, jobs, tmp_path / "missing.sock")
    with pytest.raises(SystemBusyError):
        await service.update("install")
    assert store.get(("updates",)) is None
