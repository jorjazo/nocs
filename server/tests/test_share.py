# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""nocs-system's SMB share (ADR 0037), with fake tools on the PATH."""

import json
import os
import pwd
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner
from test_system import config, serving

from nocs.api import create_app
from nocs.api.schemas import AppState, ShareState
from nocs.config import Settings
from nocs.jobs import JobManager
from nocs.services.system import SystemService
from nocs.state import StateStore
from nocs.system.operations import Context, eject, set_hostname
from nocs.system.protocol import HelperError
from nocs.system.server import Config, load_config
from nocs.system.share import Folder, Share, SharePaths, folders, share_name, smb_conf

OWNER = pwd.getpwuid(os.getuid()).pw_name


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake systemctl (keeping whether the units are enabled in a file), findmnt,
    lsblk, smbpasswd, smbcontrol, smbstatus and systemd-umount; their answers are
    files in the returned directory, and ``calls.log`` says how they were called."""
    answers = tmp_path / "answers"
    answers.mkdir()
    (answers / "findmnt.json").write_text(json.dumps({"filesystems": []}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = answers / "calls.log"
    scripts = {
        "systemctl": f"""case "$1" in
  is-enabled) cat "{answers}/enabled" 2>/dev/null || echo disabled ;;
  is-active) cat "{answers}/active" 2>/dev/null || echo inactive ;;
  enable) echo enabled > "{answers}/enabled"; echo active > "{answers}/active" ;;
  disable) echo disabled > "{answers}/enabled"; echo inactive > "{answers}/active" ;;
esac""",
        "findmnt": f"""case "$*" in
  *--json*) cat "{answers}/findmnt.json" ;;
  *) echo /dev/sda1 ;;
esac""",
        "lsblk": "",
        "smbpasswd": f'cat > "{answers}/smbpasswd.stdin"',
        "smbcontrol": "",
        "smbstatus": f'cat "{answers}/smbstatus.json" 2>/dev/null',
        "systemd-umount": "",
    }
    for tool, body in scripts.items():
        script = bin_dir / tool
        script.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n{body}\n')
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return answers


def paths(tmp_path: Path) -> SharePaths:
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "media").mkdir(exist_ok=True)
    return SharePaths(
        config=tmp_path / "etc/share/smb.conf",
        private=tmp_path / "private",
        runtime=tmp_path / "run",
        internal=tmp_path / "data",
        media=tmp_path / "media",
    )


def mounted(tmp_path: Path, tools: Path, *drives: tuple[str, str | None]) -> None:
    """Drives mounted under media (with their NOCS folders), as findmnt lists them."""
    entries: list[dict[str, object]] = [{"target": "/", "uuid": "root-uuid", "label": "writable"}]
    for uuid, label in drives:
        (tmp_path / "media" / uuid / "NOCS").mkdir(parents=True, exist_ok=True)
        entries.append({"target": str(tmp_path / "media" / uuid), "uuid": uuid, "label": label})
    (tools / "findmnt.json").write_text(json.dumps({"filesystems": entries}))


def calls(tools: Path, *names: str) -> list[str]:
    log = tools / "calls.log"
    lines = log.read_text().splitlines() if log.exists() else []
    queries = ("systemctl is-enabled", "systemctl is-active")
    return [line for line in lines if line.split()[0] in names and not line.startswith(queries)]


def shares_in(config: Path) -> list[str]:
    return [line[1:-1] for line in config.read_text().splitlines() if line.startswith("[")]


@pytest.mark.parametrize(
    ("label", "uuid", "name"),
    [
        ("ASI-SSD", "AB12-CD34", "ASI-SSD"),
        (None, "ab12-cd34", "USB-AB12"),
        ("", "0f3c-77", "USB-0F3C"),
        ("Fotos [2026]; rm -rf", "x", "Fotos _2026_ rm -rf"),
        ("...", "be-ef", "USB-BEEF"),
        ("internal", "x", "internal-2"),
        ("A" * 40, "x", "A" * 32),
        ("Señal ✨", "x", "Se_al"),
    ],
)
def test_share_names(label: str | None, uuid: str, name: str) -> None:
    assert share_name(label, uuid, {"internal"}) == name


def test_share_names_are_unique_without_regard_to_case() -> None:
    taken = {"internal"}
    names = [share_name(label, "x", taken) for label in ("SSD", "ssd", "SSD", "B" * 32)]
    assert names == ["SSD", "ssd-2", "SSD-3", "B" * 32]
    assert share_name("B" * 32, "x", taken) == "B" * 30 + "-2"


def test_the_configuration_shares_only_frames_read_only(tmp_path: Path) -> None:
    shared = folders(Path("/var/lib/nocs"), [("AB12-CD34", "SSD")], Path("/media/nocs"))
    assert shared == [
        Folder("Internal", Path("/var/lib/nocs/NOCS"), "internal"),
        Folder("SSD", Path("/media/nocs/AB12-CD34/NOCS"), "AB12-CD34", "SSD"),
    ]
    text = smb_conf(shared, SharePaths(), "nocs")
    assert shares_in_text(text) == ["global", "Internal", "SSD"]
    for setting in (
        "disable netbios = yes",
        "server min protocol = SMB2_10",
        "map to guest = Bad User",
        "guest account = nocs",
        "passdb backend = tdbsam:/var/lib/nocs-share/passdb.tdb",
        "lock directory = /run/nocs-share/lock",
        "logging = systemd",
        "load printers = no",
        "follow symlinks = no",
        "path = /var/lib/nocs/NOCS",
        "path = /media/nocs/AB12-CD34/NOCS",
        "comment = NOCS frames on SSD",
    ):
        assert setting in text.splitlines()
    assert text.count("read only = yes") == text.count("guest ok = yes") == 2
    assert "writ" not in text.replace("Written", "")  # nothing writable


def shares_in_text(text: str) -> list[str]:
    return [line[1:-1] for line in text.splitlines() if line.startswith("[")]


async def test_switching_on(tmp_path: Path, tools: Path) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "ASI SSD"), ("0f3c-77", None))
    share = Share(paths(tmp_path), owner=OWNER)
    status = await share.enable({"on": True})
    config = tmp_path / "etc/share/smb.conf"
    assert shares_in(config) == ["global", "Internal", "USB-0F3C", "ASI SSD"]
    assert (tmp_path / "data/NOCS").is_dir()  # made for the user served
    assert (tmp_path / "private").stat().st_mode & 0o777 == 0o700
    assert calls(tools, "smbpasswd", "systemctl")[-2:] == [
        f"smbpasswd -c {config} -s -a {OWNER}",
        "systemctl enable --now nocs-share.service nocs-wsdd.service",
    ]
    assert (tools / "smbpasswd.stdin").read_text() == "nocs\nnocs\n"
    assert status == {
        "on": True,
        "running": True,
        "shares": [
            {"name": "Internal", "volume": "internal", "label": None},
            {"name": "USB-0F3C", "volume": "0f3c-77", "label": None},
            {"name": "ASI SSD", "volume": "AB12-CD34", "label": "ASI SSD"},
        ],
        "clients": 0,
    }


async def test_only_drives_mounted_by_nocs_with_their_folder_are_shared(
    tmp_path: Path, tools: Path
) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "SSD"))
    entries = json.loads((tools / "findmnt.json").read_text())["filesystems"]
    entries += [
        {"target": "/mnt/other", "uuid": "1111-2222", "label": "Other"},
        {"target": str(tmp_path / "media/AB12-CD34/inner"), "uuid": "3333", "label": "Inner"},
        {"target": str(tmp_path / "media/gone"), "uuid": "4444", "label": "Gone"},  # no folder
    ]
    (tools / "findmnt.json").write_text(json.dumps({"filesystems": entries}))
    await Share(paths(tmp_path), owner=OWNER).enable({"on": True})
    assert shares_in(tmp_path / "etc/share/smb.conf") == ["global", "Internal", "SSD"]


async def test_switching_off(tmp_path: Path, tools: Path) -> None:
    share = Share(paths(tmp_path), owner=OWNER)
    await share.enable({"on": True})
    status = await share.enable({"on": False})
    assert calls(tools, "systemctl")[-1] == (
        "systemctl disable --now nocs-wsdd.service nocs-share.service"
    )
    assert status == {"on": False, "running": False, "shares": [], "clients": 0}


@pytest.mark.parametrize("args", [{}, {"on": "yes"}, {"on": True, "path": "/"}])
async def test_enable_refuses_other_arguments(
    tmp_path: Path, tools: Path, args: dict[str, object]
) -> None:
    with pytest.raises(HelperError, match="the arguments are") as refused:
        await Share(paths(tmp_path), owner=OWNER).enable(args)
    assert refused.value.code == "invalid"
    assert calls(tools, "systemctl", "smbpasswd") == []


async def test_refresh_does_nothing_while_off(tmp_path: Path, tools: Path) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "SSD"))
    assert await Share(paths(tmp_path), owner=OWNER).refresh({}) == {"changed": False}
    assert not (tmp_path / "etc/share/smb.conf").exists()


async def test_refresh_follows_the_drives(tmp_path: Path, tools: Path) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "SSD"))
    share = Share(paths(tmp_path), owner=OWNER)
    await share.enable({"on": True})
    assert await share.refresh({}) == {"changed": False}
    assert calls(tools, "smbcontrol") == []
    mounted(tmp_path, tools)  # the drive was pulled out
    assert await share.refresh({}) == {"changed": True}
    config = tmp_path / "etc/share/smb.conf"
    assert shares_in(config) == ["global", "Internal"]
    assert calls(tools, "smbcontrol") == [
        f"smbcontrol --configfile={config} smbd reload-config",
        f"smbcontrol --configfile={config} smbd close-share SSD",
    ]


async def test_status_counts_the_computers_connected(tmp_path: Path, tools: Path) -> None:
    share = Share(paths(tmp_path), owner=OWNER)
    await share.enable({"on": True})
    sessions = {
        "1": {"remote_machine": "192.168.1.20"},
        "2": {"remote_machine": "192.168.1.20"},
        "3": {"remote_machine": "fe80::1"},
    }
    (tools / "smbstatus.json").write_text(json.dumps({"sessions": sessions}))
    status = await share.status({})
    assert status["clients"] == 2
    (tools / "smbstatus.json").write_text("not json")
    assert (await share.status({}))["clients"] == 0


async def test_a_new_helper_reports_the_shares_of_a_share_left_on(
    tmp_path: Path, tools: Path
) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "SSD"))
    await Share(paths(tmp_path), owner=OWNER).enable({"on": True})
    restarted = Share(paths(tmp_path), owner=OWNER)
    assert (await restarted.status({}))["shares"] == [
        {"name": "Internal", "volume": "internal", "label": None},
        {"name": "SSD", "volume": "AB12-CD34", "label": "SSD"},
    ]
    mounted(tmp_path, tools)
    await restarted.run()  # at start: the drive went while the helper was down
    assert shares_in(tmp_path / "etc/share/smb.conf") == ["global", "Internal"]


async def test_eject_takes_the_drive_out_of_the_share_first(tmp_path: Path, tools: Path) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "SSD"))
    share = Share(paths(tmp_path), owner=OWNER)
    await share.enable({"on": True})
    context = Context(media=tmp_path / "media", owner=OWNER, share=share)
    await eject(context, {"mount_point": str(tmp_path / "media/AB12-CD34")})
    config = tmp_path / "etc/share/smb.conf"
    assert shares_in(config) == ["global", "Internal"]
    assert calls(tools, "smbcontrol", "systemd-umount") == [
        f"smbcontrol --configfile={config} smbd reload-config",
        f"smbcontrol --configfile={config} smbd close-share SSD",
        f"systemd-umount {tmp_path / 'media/AB12-CD34'}",
    ]


def test_load_config_runs_the_share_where_its_group_is_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "system.conf"
    path.write_text(f"[helper]\nuser = {OWNER}\n[operations]\nenabled = power\n")
    assert load_config(path).context.share is None
    path.write_text(
        f"[helper]\nuser = {OWNER}\n[operations]\nenabled = share\n[share]\ninternal = /srv/x\n"
    )
    assert load_config(path).context.share is not None
    path.write_text(
        f"[helper]\nuser = {OWNER}\n[operations]\nenabled = share\n[share]\ninternal = x]\n"
    )
    assert load_config(path).context.share is not None
    assert "must be an absolute path" in caplog.text


async def test_a_new_host_name_restarts_the_share(tmp_path: Path, tools: Path) -> None:
    (tmp_path / "hosts").write_text("127.0.0.1\tlocalhost\n")
    (tools.parent / "bin/hostnamectl").write_text("#!/bin/sh\n")
    (tools.parent / "bin/hostnamectl").chmod(0o755)
    share = Share(paths(tmp_path), owner=OWNER)
    await set_hostname(Context(hosts=tmp_path / "hosts", share=share), {"name": "rig2"})
    assert calls(tools, "systemctl") == [
        "systemctl try-restart nocs-share.service nocs-wsdd.service"
    ]


def test_the_api_switches_the_share_and_publishes_it(tmp_path: Path, tools: Path) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "SSD"))
    base = config(tmp_path, enabled=frozenset({"share"}))
    cfg = Config(
        uid=base.uid,
        gid=base.gid,
        enabled=base.enabled,
        socket=base.socket,
        context=Context(share=Share(paths(tmp_path), owner=OWNER)),
    )
    with serving(cfg):
        settings = Settings(
            indi_host="127.0.0.1",
            indi_port=9,
            gpsd_port=9,
            config_dir=tmp_path / "config",
            data_dir=tmp_path / "nocsd",
            system_socket=cfg.socket,
        )
        with TestClient(create_app(settings)) as client:
            assert client.put("/api/system/share", json={"on": True}).status_code == 401
            pair_owner(client)
            assert client.put("/api/system/share", json={"on": "x"}).status_code == 422
            response = client.put("/api/system/share", json={"on": True})
            assert response.status_code == 204, response.text
            state = client.get("/api/state").json()["state"]
            AppState.model_validate(state)
            assert state["share"] == {
                "on": True,
                "running": True,
                "shares": [
                    {"name": "Internal", "volume": "internal", "label": None},
                    {"name": "SSD", "volume": "AB12-CD34", "label": "SSD"},
                ],
                "clients": 0,
            }
            assert client.put("/api/system/share", json={"on": False}).status_code == 204
            assert client.get("/api/state").json()["state"]["share"]["on"] is False


async def test_nocsd_refreshes_a_share_left_on(tmp_path: Path, tools: Path) -> None:
    mounted(tmp_path, tools, ("AB12-CD34", "SSD"))
    base = config(tmp_path, enabled=frozenset({"share"}))
    share = Share(paths(tmp_path), owner=OWNER)
    cfg = Config(base.uid, base.gid, base.enabled, base.socket, Context(share=share))
    with serving(cfg):
        store = StateStore()
        service = SystemService(store, JobManager(store), cfg.socket)
        await service.refresh()
        await service.read_share()
        assert ShareState.model_validate(store.get(("share",))).on is False
        await service.share(True)
        assert len(ShareState.model_validate(store.get(("share",))).shares) == 2
        mounted(tmp_path, tools)  # pulled out without ejecting
        await service.read_share()
        state = ShareState.model_validate(store.get(("share",)))
        assert [share.name for share in state.shares] == ["Internal"]
