"""Updates from apt, only when asked (ADR 0025), with fake apt, dpkg and systemd."""

from pathlib import Path
from typing import cast

import anyio
import pytest
from test_timekeeping import Tools

from nocs.api.schemas import UpdatesState
from nocs.jobs import JobManager
from nocs.services.system import SystemBusyError, SystemService, package_kind
from nocs.state import StateStore
from nocs.system.protocol import HelperError
from nocs.system.updates import UpdatePaths, Updates

UPGRADABLE = (
    "Listing...\n"
    "nocs/stable 0.1.1 arm64 [upgradable from: 0.1.0]\n"
    "indi-bin/noble 2.2.6+202611 arm64 [upgradable from: 2.2.5+202610]\n"
    "libc6/resolute-updates,resolute-security 2.43-2ubuntu2.4 arm64 "
    "[upgradable from: 2.43-2ubuntu2.3]\n"
)


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tools:
    tools = Tools(tmp_path, monkeypatch)
    for tool in ("apt-get", "systemd-run", "dpkg", "systemctl"):
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
    return UpdatePaths(
        state=tmp_path / "state/updates.json",
        archives=tmp_path / "archives",
        reboot_required=tmp_path / "reboot-required",
    )


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
        {"name": "nocs", "to": "0.1.1", "from": "0.1.0", "security": False},
        {"name": "indi-bin", "to": "2.2.6+202611", "from": "2.2.5+202610", "security": False},
        {
            "name": "libc6",
            "to": "2.43-2ubuntu2.4",
            "from": "2.43-2ubuntu2.3",
            "security": True,
        },
    ]
    assert status["installed"] == "0.1.0"
    assert (status["upgraded"], status["reboot_required"]) == ([], False)
    assert "apt-get update" in tools.calls()


async def test_install_runs_apart_and_is_followed(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    await updates.check({})
    await drive(updates)
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
    assert [p["name"] for p in cast(list[dict[str, str]], status["upgraded"])] == [
        "nocs",
        "indi-bin",
        "libc6",
    ]
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
    # The appliance's settings go back with it.
    (paths.archives / "nocs-appliance_0.1.0_all.deb").write_bytes(b"")
    await updates.rollback({})
    await drive(updates)
    assert tools.calls()[-1].endswith(
        f"dpkg -i {paths.archives / 'nocs_0.1.0_arm64.deb'} "
        f"{paths.archives / 'nocs-appliance_0.1.0_all.deb'}"
    )


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


async def test_after_installing_apt_says_what_is_left(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    await updates.check({})
    await drive(updates)
    await updates.install({})
    await drive(updates)
    tools.answer("systemctl", "show", "active\n")
    tools.answer("apt", "list", "Listing...\n")
    assert len(cast(list[object], (await updates.status({}))["upgradable"])) == 3
    tools.answer("systemctl", "show", "inactive\n")
    (paths.reboot_required).write_text("*** System restart required ***\n")
    status = await updates.status({})
    assert (status["upgradable"], status["reboot_required"]) == ([], True)
    assert len(cast(list[object], status["upgraded"])) == 3
    listed = sum(call.startswith("apt list") for call in tools.calls())
    await updates.status({})
    assert sum(call.startswith("apt list") for call in tools.calls()) == listed  # once


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("nocs", "nocs"),
        ("nocs-appliance", "nocs"),
        ("indi-bin", "indi"),
        ("libindi1", "indi"),
        ("libindi-data", "indi"),
        ("indi-3rdparty-drivers", "indi"),
        ("phd2", "phd2"),
        ("libindicator3-7", "system"),
        ("libc6", "system"),
        ("linux-image-raspi", "system"),
    ],
)
def test_packages_are_what_they_are_to_the_rig(name: str, kind: str) -> None:
    assert package_kind(name) == kind


async def test_nocsd_classifies_the_packages(
    tools: Tools, paths: UpdatePaths, tmp_path: Path
) -> None:
    from nocs.services.system import _updates_state  # pyright: ignore[reportPrivateUsage]

    tools.answer(
        "apt",
        "list",
        UPGRADABLE + "linux-image-raspi/resolute-updates,resolute-security 7.0.0-1023.23 arm64 "
        "[upgradable from: 7.0.0-1017.17]\n",
    )
    updates = Updates(paths)
    await updates.check({})
    await drive(updates)
    state = _updates_state(await updates.status({}))
    assert isinstance(state, dict)
    assert state["packages"] == [
        {
            "name": "nocs",
            "from": "0.1.0",
            "to": "0.1.1",
            "kind": "nocs",
            "security": False,
            "reboot": False,
        },
        {
            "name": "indi-bin",
            "from": "2.2.5+202610",
            "to": "2.2.6+202611",
            "kind": "indi",
            "security": False,
            "reboot": False,
        },
        {
            "name": "libc6",
            "from": "2.43-2ubuntu2.3",
            "to": "2.43-2ubuntu2.4",
            "kind": "system",
            "security": True,
            "reboot": False,
        },
        {
            "name": "linux-image-raspi",
            "from": "7.0.0-1017.17",
            "to": "7.0.0-1023.23",
            "kind": "system",
            "security": True,
            "reboot": True,
        },
    ]
    assert (state["upgraded"], state["reboot_required"]) == ([], False)
    UpdatesState.model_validate(state)  # as the state documents it


async def test_apt_is_read_without_its_translations(tools: Tools, paths: UpdatePaths) -> None:
    apt = tools.dir / "apt"
    apt.write_text(
        '#!/bin/sh\n[ "$LC_ALL" = C ] && exec /bin/cat "$0-list.out"\n'
        'echo "nocs/stable 0.1.1 arm64 [actualizable desde: 0.1.0]"\n'
    )
    updates = Updates(paths)
    await updates.check({})
    await drive(updates)
    assert len(cast(list[object], (await updates.status({}))["upgradable"])) == 3


async def test_no_check_while_installing(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    await updates.check({})
    await drive(updates)
    await updates.install({})
    await drive(updates)
    tools.answer("systemctl", "show", "active\n")
    tools.answer("apt", "list", "Listing...\n")
    with pytest.raises(HelperError, match="an update is being installed"):
        await updates.check({})
    await drive(updates)
    status = await updates.status({})
    assert (status["state"], status["task"], status["error"]) == ("installing", "install", None)
    assert len(cast(list[object], status["upgraded"])) == 3
    assert sum(call == "apt-get update" for call in tools.calls()) == 1
    # The install ends well: nothing of the refused check is left in its result.
    tools.answer("systemctl", "show", "inactive\n")
    status = await updates.status({})
    assert (status["state"], status["error"], status["upgradable"]) == ("succeeded", None, [])


async def test_an_install_that_never_started_is_no_success(
    tools: Tools, paths: UpdatePaths
) -> None:
    (tools.dir / "systemd-run").write_text("#!/bin/sh\necho 'Failed to start' >&2\nexit 1\n")
    updates = Updates(paths)
    await updates.check({})
    await drive(updates)
    await updates.install({})
    await drive(updates)
    status = await updates.status({})
    assert (status["state"], status["task"], status["upgraded"]) == ("idle", None, [])
    assert status["error"] == "systemd-run: Failed to start"


async def test_no_second_install_while_installing(tools: Tools, paths: UpdatePaths) -> None:
    updates = Updates(paths)
    await updates.check({})
    await drive(updates)
    await updates.install({})
    await drive(updates)
    tools.answer("systemctl", "show", "active\n")
    tools.answer("apt", "list", "Listing...\n")
    (paths.archives / "nocs_0.1.0_arm64.deb").write_bytes(b"")
    for again in (updates.install, updates.rollback):
        with pytest.raises(HelperError, match="an update is being installed"):
            await again({})
        await drive(updates)
    assert sum(call.startswith("systemd-run") for call in tools.calls()) == 1
    # The install ends well: nothing of the refusals is left in its result.
    tools.answer("systemctl", "show", "inactive\n")
    status = await updates.status({})
    assert (status["state"], status["task"], status["error"]) == ("succeeded", "install", None)
    assert len(cast(list[object], status["upgraded"])) == 3
