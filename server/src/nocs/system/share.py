"""The SMB share of the frames for desktop computers (ADR 0037).

Samba's ``smbd`` runs as ``nocs-share.service`` on a configuration this module
writes, and ``wsdd`` as ``nocs-wsdd.service`` so that Windows finds the box; both
only while the owner has the share on, which the OS keeps as those units being
enabled. Read-only, for guests and for the published login ``nocs`` / ``nocs``, as
the user served (``nocs``).

Only the folders where frames are saved are shared, one share per volume: its
``NOCS`` folder. ``Internal`` is the internal destination's; each drive mounted at
``<media>/<UUID>`` gets one named by its label. The list comes from what is mounted
there, never from nocsd.
"""

from __future__ import annotations

import json
import logging
import os
import pwd
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import anyio
import anyio.to_thread

from nocs.system.protocol import HelperError, Message

log = logging.getLogger("nocs.system")

UNITS = ("nocs-share.service", "nocs-wsdd.service")
"""smbd first: wsdd only announces it."""
SMBD = UNITS[0]
INTERNAL = "Internal"
FRAMES = "NOCS"
"""The folder below each destination that holds the frames (ADR 0013)."""
LOGIN = "nocs"
"""The published login, user and password alike: it protects nothing, and is there
for Windows 11, which refuses guests (ADR 0037)."""
MAX_NAME = 32
_UUID = re.compile(r"[A-Za-z0-9-]{1,64}")
_UNSAFE = re.compile(r"[^A-Za-z0-9 _.-]+")


@dataclass(frozen=True, slots=True)
class SharePaths:
    config: Path = Path("/etc/nocs/share/smb.conf")
    private: Path = Path("/var/lib/nocs-share")
    """Samba's passdb, root's only."""
    runtime: Path = Path("/run/nocs-share")
    """Samba's locking, state and cache databases: kept off the microSD."""
    internal: Path = Path("/var/lib/nocs")
    """The internal storage destination (nocsd's data directory on the appliance)."""
    media: Path = Path("/media/nocs")
    """Where nocs-system mounts drives, one directory per filesystem UUID."""


@dataclass(frozen=True, slots=True)
class Folder:
    name: str
    """The share's name, as a desktop shows it."""
    path: Path
    volume: str
    """``internal`` or the drive's filesystem UUID."""
    label: str | None = None

    def info(self) -> Message:
        return {"name": self.name, "volume": self.volume, "label": self.label}


def share_name(label: str | None, uuid: str, taken: set[str]) -> str:
    """A drive's share name: its label made safe for smb.conf and desktops, or
    ``USB-<first 4 of the UUID>``; unique without regard to case, as SMB compares."""
    name = _UNSAFE.sub("_", label or "").strip(" ._")[:MAX_NAME].rstrip(" ._")
    if not name:
        name = f"USB-{uuid.replace('-', '')[:4].upper()}"
    unique, n = name, 2
    while unique.lower() in taken:
        suffix = f"-{n}"
        unique, n = f"{name[: MAX_NAME - len(suffix)]}{suffix}", n + 1
    taken.add(unique.lower())
    return unique


def folders(internal: Path, drives: list[tuple[str, str | None]], media: Path) -> list[Folder]:
    """The shares: the internal destination's frames, then each drive's (UUID, label)
    in the order given."""
    shared = [Folder(INTERNAL, internal / FRAMES, "internal")]
    taken = {INTERNAL.lower()}
    for uuid, label in drives:
        name = share_name(label, uuid, taken)
        shared.append(Folder(name, media / uuid / FRAMES, uuid, label))
    return shared


def smb_conf(shared: list[Folder], paths: SharePaths, owner: str) -> str:
    """smbd's whole configuration: standalone, SMB 2.1 and newer, no NetBIOS, no
    printers, logs to the journal, every share read-only for guests and ``nocs``."""
    run = paths.runtime
    lines = [
        "# Written by nocs-system (ADR 0037) whenever the share or the drives change:",
        "# changes made here are lost.",
        "[global]",
        "server role = standalone server",
        "server string = NOCS",
        "workgroup = WORKGROUP",
        "disable netbios = yes",
        "smb ports = 445",
        "server min protocol = SMB2_10",
        "ntlm auth = ntlmv2-only",
        "map to guest = Bad User",
        f"guest account = {owner}",
        f"passdb backend = tdbsam:{paths.private / 'passdb.tdb'}",
        f"private dir = {paths.private}",
        f"lock directory = {run / 'lock'}",
        f"state directory = {run / 'state'}",
        f"cache directory = {run / 'cache'}",
        f"pid directory = {run}",
        f"ncalrpc dir = {run / 'ncalrpc'}",
        "logging = systemd",
        "log level = 1",
        "load printers = no",
        "printing = bsd",
        "printcap name = /dev/null",
        "disable spoolss = yes",
        "usershare max shares = 0",
        "multicast dns register = yes",
        "follow symlinks = no",
        "wide links = no",
    ]
    for folder in shared:
        lines += [
            "",
            f"[{folder.name}]",
            f"path = {folder.path}",
            "comment = NOCS frames" + (f" on {folder.label}" if folder.label else ""),
            "read only = yes",
            "guest ok = yes",
            f"force user = {owner}",
        ]
    return "\n".join(lines) + "\n"


class Share:
    def __init__(self, paths: SharePaths | None = None, owner: str = "nocs") -> None:
        self._paths = paths or SharePaths()
        self._owner = owner
        self._shared: list[Folder] = []
        self._lock = anyio.Lock()

    async def run(self) -> None:
        """At start, bring the configuration up to date with the drives mounted now."""
        try:
            if await self._enabled():
                await self.refresh({})
        except HelperError as e:
            log.warning("share: %s", e)

    # -- operations --------------------------------------------------------------

    async def status(self, args: Message) -> Message:
        _no_args(args)
        on, running = await self._enabled(), await self._running()
        if on and not self._shared:
            found = await self._folders()
            self._shared = [f for f in found if await anyio.to_thread.run_sync(f.path.is_dir)]
        return {
            "on": on,
            "running": running,
            "shares": [folder.info() for folder in self._shared] if on else [],
            "clients": await self._clients() if running else 0,
        }

    async def enable(self, args: Message) -> Message:
        on = args.get("on")
        if not isinstance(on, bool) or set(args) != {"on"}:
            raise HelperError("invalid", "the arguments are {on: true or false}")
        async with self._lock:
            if on:
                await self._write()
                await self._login()
                await _run("systemctl", "enable", "--now", *UNITS)
            else:
                await _run("systemctl", "disable", "--now", *reversed(UNITS))
        log.info("share %s", "on" if on else "off")
        return await self.status({})

    async def refresh(self, args: Message, *, without: Path | None = None) -> Message:
        """Share what is mounted now (less ``without``, a drive about to be ejected),
        and tell smbd if the shares changed."""
        _no_args(args)
        async with self._lock:
            if not await self._enabled():
                return {"changed": False}
            before = [(f.name, f.path) for f in self._shared]
            changed = await self._write(without)
            if changed and await self._running():
                await self._smbcontrol("reload-config")
                for name, path in before:
                    if not any(f.path == path for f in self._shared):
                        await self._smbcontrol("close-share", name)
            return {"changed": changed}

    # -- inside ------------------------------------------------------------------

    async def _write(self, without: Path | None = None) -> bool:
        """Write smb.conf for the folders there are now; whether it changed."""
        found = [f for f in await self._folders() if f.path.parent != without]
        return await anyio.to_thread.run_sync(self._replace, found)

    def _replace(self, found: list[Folder]) -> bool:
        for folder in found:
            _frames_folder(folder.path, self._owner)
        self._shared = [folder for folder in found if folder.path.is_dir()]
        text = smb_conf(self._shared, self._paths, self._owner)
        self._paths.private.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._paths.runtime.mkdir(mode=0o755, parents=True, exist_ok=True)
        config = self._paths.config
        try:
            if config.read_text() == text:
                return False
        except FileNotFoundError:
            config.parent.mkdir(parents=True, exist_ok=True)
        new = config.with_name(f".{config.name}.nocs-system")
        new.write_text(text)
        os.chmod(new, 0o644)
        new.replace(config)
        return True

    async def _folders(self) -> list[Folder]:
        """The internal destination's frames, and each drive mounted under ``media``."""
        output = await _run(
            "findmnt", "--json", "--list", "--output", "TARGET,UUID,LABEL", check=False
        )
        drives: list[tuple[str, str | None]] = []
        try:
            entries = cast(list[dict[str, object]], json.loads(output)["filesystems"])
        except (json.JSONDecodeError, KeyError, TypeError):
            entries = []
        for entry in entries:
            target = Path(str(entry.get("target")))
            if target.parent != self._paths.media or not _UUID.fullmatch(target.name):
                continue
            label = entry.get("label")
            drives.append((target.name, label if isinstance(label, str) and label else None))
        drives.sort()
        return folders(self._paths.internal, drives, self._paths.media)

    async def _smbcontrol(self, *message: str) -> None:
        """Tell the running smbd something; it acts on it in its own time."""
        config = f"--configfile={self._paths.config}"
        await _run("smbcontrol", config, "smbd", *message, check=message[0] != "close-share")

    async def _login(self) -> None:
        """Put the published login in Samba's passdb, on smbpasswd's standard input."""
        await _run(
            "smbpasswd", "-c", str(self._paths.config), "-s", "-a", self._owner,
            stdin=f"{LOGIN}\n{LOGIN}\n".encode(),
        )  # fmt: skip

    async def _enabled(self) -> bool:
        output = await _run("systemctl", "is-enabled", SMBD, check=False)
        return output.strip() == "enabled"

    async def _running(self) -> bool:
        output = await _run("systemctl", "is-active", SMBD, check=False)
        return output.strip() == "active"

    async def _clients(self) -> int:
        """The computers with a session open, by address."""
        output = await _run(
            "smbstatus", f"--configfile={self._paths.config}", "--json", check=False
        )
        try:
            sessions = cast(dict[str, dict[str, object]], json.loads(output)["sessions"])
            return len({str(s.get("remote_machine")) for s in sessions.values()})
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return 0


def _frames_folder(folder: Path, owner: str) -> None:
    """A volume's ``NOCS`` folder, made for the user served if it is not there yet
    (smbd refuses a share whose path is missing)."""
    if folder.exists() or not folder.parent.is_dir():
        return
    folder.mkdir()
    if os.geteuid() == 0:
        user = pwd.getpwnam(owner)
        os.chown(folder, user.pw_uid, user.pw_gid)


def _no_args(args: Message) -> None:
    if args:
        raise HelperError("invalid", f"unexpected arguments: {', '.join(sorted(args))}")


async def _run(*argv: str, check: bool = True, stdin: bytes | None = None) -> str:
    try:
        result = await anyio.run_process(list(argv), input=stdin, check=False)
    except FileNotFoundError as e:
        if check:
            raise HelperError("failed", f"{argv[0]} is not installed") from e
        return ""
    if check and result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise HelperError("failed", f"{argv[0]}: {detail or f'exit status {result.returncode}'}")
    return result.stdout.decode(errors="replace")
