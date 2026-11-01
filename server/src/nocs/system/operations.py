"""The operations nocs-system performs (ADR 0027).

Each one validates its arguments, then runs the OS's own command-line tool with an
argument list, never through a shell, so no value can become a command.
"""

from __future__ import annotations

import json
import logging
import os
import pwd
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import anyio
import anyio.to_thread

from nocs.system.network import Network
from nocs.system.protocol import HelperError, Message, validate_hostname
from nocs.system.share import Share
from nocs.system.updates import Updates

log = logging.getLogger("nocs.system")


@dataclass(frozen=True, slots=True)
class Context:
    """Files operations change, and the user they act for; replaced in tests."""

    hosts: Path = Path("/etc/hosts")
    media: Path = Path("/media/nocs")
    """Where drives are mounted, one directory per filesystem UUID."""
    sys_class_block: Path = Path("/sys/class/block")
    owner: str = "nocs"
    """The user served, who must be able to write to the drives mounted for it."""
    network: Network | None = None
    """The Wi-Fi's actor, where the network group is on (ADR 0028)."""
    updates: Updates | None = None
    """The updates' actor, where the update group is on (ADR 0025)."""
    share: Share | None = None
    """The SMB share, where the share group is on (ADR 0037)."""


type Operation = Callable[[Context, Message], Awaitable[Message]]


async def run(*argv: str) -> str:
    """Run a tool; its standard output, or ``HelperError("failed")`` with its message."""
    try:
        result = await anyio.run_process(list(argv), check=False)
    except FileNotFoundError as e:
        raise HelperError("failed", f"{argv[0]} is not installed") from e
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise HelperError("failed", f"{argv[0]}: {detail or f'exit status {result.returncode}'}")
    return result.stdout.decode(errors="replace")


def _no_args(args: Message) -> None:
    if args:
        raise HelperError("invalid", f"unexpected arguments: {', '.join(sorted(args))}")


async def reboot(_: Context, args: Message) -> Message:
    _no_args(args)
    await run("systemctl", "reboot")
    return {}


async def power_off(_: Context, args: Message) -> Message:
    _no_args(args)
    await run("systemctl", "poweroff")
    return {}


async def set_hostname(context: Context, args: Message) -> Message:
    name = args.get("name")
    if not isinstance(name, str) or set(args) != {"name"}:
        raise HelperError("invalid", "the arguments are {name: <host name>}")
    name = validate_hostname(name)
    await run("hostnamectl", "set-hostname", name)
    await anyio.to_thread.run_sync(update_hosts, context.hosts, name)
    return {"name": name}


def update_hosts(path: Path, name: str) -> None:
    """Point ``127.0.1.1`` at the new name, as Ubuntu sets it up, so that sudo and
    other tools that look up their own host name keep finding it."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    entry = f"127.0.1.1\t{name}"
    updated = [entry if line.split()[:1] == ["127.0.1.1"] else line for line in lines]
    if entry not in updated:
        loopback = next((i for i, line in enumerate(updated) if line.startswith("127.0.0.1")), -1)
        updated.insert(loopback + 1, entry)
    new = path.with_name(f".{path.name}.nocs-system")
    new.write_text("\n".join(updated) + "\n")
    os.chmod(new, 0o644)
    new.replace(path)


# -- storage --------------------------------------------------------------------

OWNED = frozenset({"vfat", "exfat", "ntfs", "ntfs3"})
"""Filesystems without owners: the mount gives every file to the user served."""
SUPPORTED = OWNED | {"ext4", "ext3", "ext2", "btrfs", "xfs"}
_DEVICE = re.compile(r"/dev/(sd[a-z]+[0-9]*)")
_UUID = re.compile(r"[A-Za-z0-9-]{1,64}")


async def mount(context: Context, args: Message) -> Message:
    """Mount a USB drive's filesystem at ``<media>/<UUID>`` for the user served.

    systemd mounts it (``systemd-mount``), in its own namespace rather than this
    sandboxed service's, after a file system check.
    """
    device = args.get("device")
    if not isinstance(device, str) or set(args) != {"device"} or not _DEVICE.fullmatch(device):
        raise HelperError("invalid", "the arguments are {device: /dev/sd…}")
    name = device.removeprefix("/dev/")
    if not await anyio.to_thread.run_sync(_is_usb, context.sys_class_block / name):
        raise HelperError("invalid", f"{device} is not a USB drive")
    info = await _lsblk(device, "PATH", "FSTYPE", "UUID", "MOUNTPOINTS")
    fs = info.get("fstype")
    uuid = info.get("uuid")
    mounted = [m for m in cast(list[object], info.get("mountpoints") or []) if m]
    if mounted:
        raise HelperError("invalid", f"{device} is already mounted at {mounted[0]}")
    if not isinstance(fs, str) or fs not in SUPPORTED:
        raise HelperError("invalid", f"NOCS cannot use a {fs or 'blank'} drive")
    if not isinstance(uuid, str) or not _UUID.fullmatch(uuid):
        raise HelperError("invalid", f"{device} has no filesystem UUID")
    where = context.media / uuid
    argv = ["systemd-mount", "--collect", "--options=noatime"]
    if fs in OWNED:
        argv.append(f"--owner={context.owner}")
    await run(*argv, device, str(where))
    if fs not in OWNED:
        await anyio.to_thread.run_sync(_own_frames_folder, where, context.owner)
    if context.share is not None:
        await _refresh_share(context.share)
    return {"mount_point": str(where)}


async def eject(context: Context, args: Message) -> Message:
    """Unmount a drive mounted by ``mount`` (which writes everything out), then
    power it off if nothing else on it is mounted."""
    mount_point = args.get("mount_point")
    if not isinstance(mount_point, str) or set(args) != {"mount_point"}:
        raise HelperError("invalid", "the arguments are {mount_point: <path>}")
    where = Path(mount_point)
    if ".." in where.parts or where.parent != context.media or not _UUID.fullmatch(where.name):
        raise HelperError("invalid", f"NOCS did not mount {mount_point}")
    source = (await run("findmnt", "--noheadings", "--output", "SOURCE", str(where))).strip()
    if not source:
        raise HelperError("invalid", f"nothing is mounted at {mount_point}")
    if context.share is not None:  # smbd would keep the drive busy
        await _refresh_share(context.share, without=where)
    await run("systemd-umount", str(where))
    powered_off = False
    disk = (await run("lsblk", "--noheadings", "--nodeps", "--output", "PKNAME", source)).strip()
    if disk:
        others = await _lsblk(f"/dev/{disk}", "MOUNTPOINTS")
        if not any(m for m in cast(list[object], others.get("mountpoints") or [])):
            try:
                await run("udisksctl", "power-off", "--no-user-interaction", "-b", f"/dev/{disk}")
                powered_off = True
            except HelperError as e:
                log.info("cannot power off /dev/%s: %s", disk, e)
    return {"powered_off": powered_off}


async def _refresh_share(share: Share, *, without: Path | None = None) -> None:
    """A drive mounted or about to be ejected changes what is shared; a failure there
    must not fail the mount or the eject."""
    try:
        await share.refresh({}, without=without)
    except HelperError as e:
        log.warning("share: %s", e)


async def _lsblk(device: str, *columns: str) -> dict[str, object]:
    """lsblk's columns for one device, as JSON (lowercase keys)."""
    output = await run("lsblk", "--json", "--nodeps", "--output", ",".join(columns), device)
    try:
        devices = json.loads(output)["blockdevices"]
        return cast(dict[str, object], devices[0])
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        raise HelperError("failed", f"lsblk said something NOCS cannot read: {e}") from e


def _is_usb(node: Path) -> bool:
    """``/sys/class/block/sda1`` links into the USB device that holds it."""
    return "/usb" in str(node.resolve())


def _own_frames_folder(where: Path, owner: str) -> None:
    """Filesystems with owners (ext4…) keep theirs; NOCS gets its own folder on them."""
    folder = where / "NOCS"
    user = pwd.getpwnam(owner)
    if not folder.exists():
        folder.mkdir()
        os.chown(folder, user.pw_uid, user.pw_gid)


# -- time ---------------------------------------------------------------------

EARLIEST = 1767225600.0
"""2026-01-01 UTC: no client clock earlier than this is believed."""
LATEST = 4102444800.0
"""2100-01-01 UTC."""


async def set_time(_: Context, args: Message) -> Message:
    """Step the system clock to a client's time, unless something keeps it already
    (ADR 0029): chrony with a source (GPS, NTP), or systemd-timesyncd."""
    utc = args.get("utc")
    if isinstance(utc, bool) or not isinstance(utc, int | float) or set(args) != {"utc"}:
        raise HelperError("invalid", "the arguments are {utc: <seconds since 1970>}")
    if not EARLIEST <= utc <= LATEST:
        raise HelperError("invalid", f"{utc} is not a believable time")
    if keeper := await synchronised():
        raise HelperError("invalid", f"the clock is kept by {keeper}: NOCS leaves it alone")
    await run("date", "--utc", f"--set=@{utc:.3f}")
    try:  # so that a Pi with a battery on its RTC boots with the right time
        await run("hwclock", "--systohc", "--utc")
    except HelperError as e:
        log.info("cannot set the RTC: %s", e)
    return {}


async def synchronised() -> str | None:
    """What keeps the system clock right now, if anything."""
    try:
        tracking = await run("chronyc", "-c", "tracking")
    except HelperError:
        try:
            synced = await run("timedatectl", "show", "--property=NTPSynchronized", "--value")
        except HelperError:
            return None
        return "systemd-timesyncd" if synced.strip() == "yes" else None
    fields = tracking.strip().split(",")
    return "chrony" if len(fields) >= 14 and fields[13] != "Not synchronised" else None


# -- services -----------------------------------------------------------------

SERVICES = {"indiserver": "nocs-indiserver.service", "phd2": "nocs-phd2.service"}
"""The services nocsd may restart: the engines it depends on, never itself."""


async def restart_service(_: Context, args: Message) -> Message:
    """Restart indiserver (all drivers start again) or PHD2, e.g. when hung (ADR 0030)."""
    service = args.get("service")
    if not isinstance(service, str) or set(args) != {"service"} or service not in SERVICES:
        raise HelperError("invalid", f"the arguments are {{service: {' or '.join(SERVICES)}}}")
    await run("systemctl", "restart", SERVICES[service])
    return {}


# -- network (ADR 0028) --------------------------------------------------------


def _network(context: Context) -> Network:
    if context.network is None:
        raise HelperError("disabled", "the network is not NOCS's to manage here")
    return context.network


async def network_status(context: Context, args: Message) -> Message:
    return await _network(context).status(args)


async def network_join(context: Context, args: Message) -> Message:
    return await _network(context).join(args)


async def network_forget(context: Context, args: Message) -> Message:
    return await _network(context).forget(args)


async def network_access_point(context: Context, args: Message) -> Message:
    return await _network(context).access_point(args)


async def network_mode(context: Context, args: Message) -> Message:
    return await _network(context).set_mode(args)


# -- updates (ADR 0025) --------------------------------------------------------


def _updates(context: Context) -> Updates:
    if context.updates is None:
        raise HelperError("disabled", "updates are not NOCS's to install here")
    return context.updates


async def update_status(context: Context, args: Message) -> Message:
    return await _updates(context).status(args)


async def update_check(context: Context, args: Message) -> Message:
    return await _updates(context).check(args)


async def update_install(context: Context, args: Message) -> Message:
    return await _updates(context).install(args)


async def update_rollback(context: Context, args: Message) -> Message:
    return await _updates(context).rollback(args)


# -- share (ADR 0037) ----------------------------------------------------------


def _share(context: Context) -> Share:
    if context.share is None:
        raise HelperError("disabled", "the SMB share is not NOCS's to run here")
    return context.share


async def share_status(context: Context, args: Message) -> Message:
    return await _share(context).status(args)


async def share_enable(context: Context, args: Message) -> Message:
    return await _share(context).enable(args)


async def share_refresh(context: Context, args: Message) -> Message:
    return await _share(context).refresh(args)


OPERATIONS: dict[str, Operation] = {
    "power.reboot": reboot,
    "power.poweroff": power_off,
    "hostname.set": set_hostname,
    "storage.mount": mount,
    "storage.eject": eject,
    "time.set": set_time,
    "services.restart": restart_service,
    "network.status": network_status,
    "network.join": network_join,
    "network.forget": network_forget,
    "network.access_point": network_access_point,
    "network.mode": network_mode,
    "update.status": update_status,
    "update.check": update_check,
    "update.install": update_install,
    "update.rollback": update_rollback,
    "share.status": share_status,
    "share.enable": share_enable,
    "share.refresh": share_refresh,
}
