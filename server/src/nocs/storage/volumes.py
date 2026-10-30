"""Mounted filesystems where frames can be saved (ADR 0013).

Everything is read from files any user can read: ``/proc/self/mountinfo`` for the
mounts, ``/dev/disk/by-uuid`` and ``by-label`` for filesystem identities (with
``/sys/class/block/<name>/dev`` for the device each link names), and
``/sys/dev/block`` for the disk behind each one. nocsd mounts nothing.

All functions here block (file system access): call them from a thread.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from nocs.state import Json

INTERNAL = "internal"
"""Id of the configured internal destination."""

SEARCH = (Path("/media"), Path("/mnt"))
"""Mount points under these (up to two levels deep) are candidate destinations."""

VIRTUAL = frozenset(
    {
        "autofs",
        "binfmt_misc",
        "bpf",
        "cgroup",
        "cgroup2",
        "configfs",
        "debugfs",
        "devpts",
        "devtmpfs",
        "efivarfs",
        "fusectl",
        "hugetlbfs",
        "mqueue",
        "overlay",
        "proc",
        "pstore",
        "ramfs",
        "securityfs",
        "squashfs",
        "sysfs",
        "tmpfs",
        "tracefs",
    }
)
"""Filesystem types that hold no user data on a drive (or lose it at reboot)."""


@dataclass(frozen=True, slots=True)
class SystemPaths:
    """Where the kernel publishes mounts and block devices (replaced in tests)."""

    mountinfo: Path = Path("/proc/self/mountinfo")
    by_uuid: Path = Path("/dev/disk/by-uuid")
    by_label: Path = Path("/dev/disk/by-label")
    sys_block: Path = Path("/sys/dev/block")
    sys_class_block: Path = Path("/sys/class/block")


@dataclass(frozen=True, slots=True)
class Mount:
    device: tuple[int, int]
    """Major and minor number of the filesystem (``st_dev``)."""
    root: PurePosixPath
    """Directory of the filesystem mounted here (not ``/`` for bind mounts)."""
    mount_point: Path
    fs_type: str
    read_only: bool


@dataclass(frozen=True, slots=True)
class Volume:
    """A mounted filesystem, identified so it can be found again under another mount point."""

    id: str
    """Filesystem UUID, or ``mount:<mount point>`` when it has none."""
    mount: Mount
    label: str
    system: bool
    """On the same disk as ``/``."""
    sd: bool
    """That disk is an SD/MMC card."""


@dataclass(frozen=True, slots=True)
class Destination:
    """A directory frames can be saved below, as ``<directory>/NOCS/…``."""

    id: str
    """``internal`` or the volume id."""
    label: str
    volume: Volume
    directory: Path
    """Absolute path of the destination directory."""
    relative: PurePosixPath
    """The same directory, relative to the root of its filesystem."""
    total: int
    free: int
    writable: bool
    internal: bool = field(default=False)

    def info(self) -> dict[str, Json]:
        return {
            "id": self.id,
            "label": self.label,
            "path": str(self.directory),
            "fs": self.volume.mount.fs_type,
            "total": self.total,
            "free": self.free,
            "writable": self.writable,
            "system": self.volume.system,
            "sd": self.volume.sd,
            "internal": self.internal,
        }


def _unescape(value: str) -> str:
    """Undo the octal escapes of mountinfo (``\\040`` is a space)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def read_mounts(paths: SystemPaths) -> list[Mount]:
    mounts: list[Mount] = []
    for line in paths.mountinfo.read_text().splitlines():
        # id parent major:minor root mount-point options [optional…] - fstype source super-options
        left, _, right = line.partition(" - ")
        fields = left.split()
        after = right.split()
        if len(fields) < 6 or not after:
            continue
        major, _, minor = fields[2].partition(":")
        mounts.append(
            Mount(
                device=(int(major), int(minor)),
                root=PurePosixPath(_unescape(fields[3])),
                mount_point=Path(_unescape(fields[4])),
                fs_type=after[0],
                read_only="ro" in fields[5].split(","),
            )
        )
    return mounts


def _links(directory: Path, sys_class_block: Path) -> dict[tuple[int, int], str]:
    """Block device → link name, for the ``/dev/disk/by-*`` directories."""
    found: dict[tuple[int, int], str] = {}
    try:
        entries = list(directory.iterdir())
    except OSError:
        return found
    for link in entries:
        try:
            # by-uuid/<uuid> -> ../../sda1, and /sys/class/block/sda1/dev holds "8:1".
            node = os.path.basename(os.readlink(link))
            major, _, minor = (sys_class_block / node / "dev").read_text().strip().partition(":")
            device = (int(major), int(minor))
        except (OSError, ValueError):
            continue
        # udev escapes characters such as spaces as \x20.
        name = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), link.name)
        found[device] = name
    return found


def _disk(device: tuple[int, int], paths: SystemPaths) -> tuple[str, bool] | None:
    """The disk holding a block device (itself, or the parent of a partition), and if it is SD."""
    try:
        node = (paths.sys_block / f"{device[0]}:{device[1]}").resolve(strict=True)
    except OSError:
        return None
    if (node / "partition").exists():
        node = node.parent
    sd = node.name.startswith("mmcblk") or "/mmc_host/" in str(node)
    return str(node), sd


def _contains(mount: Mount, path: Path) -> bool:
    return path == mount.mount_point or path.is_relative_to(mount.mount_point)


class Volumes:
    """A snapshot of the mounted filesystems."""

    def __init__(self, paths: SystemPaths | None = None) -> None:
        self._paths = paths or SystemPaths()
        self.mounts = read_mounts(self._paths)
        self._uuids = _links(self._paths.by_uuid, self._paths.sys_class_block)
        self._labels = _links(self._paths.by_label, self._paths.sys_class_block)
        root = self.mount_of(Path("/"))
        self._system_disk = _disk(root.device, self._paths) if root is not None else None

    def mount_of(self, path: Path) -> Mount | None:
        """The mount a path lives on: the last mounted one containing it."""
        found: Mount | None = None
        for mount in self.mounts:
            if _contains(mount, path) and (
                found is None or len(mount.mount_point.parts) >= len(found.mount_point.parts)
            ):
                found = mount
        return found

    def volume(self, mount: Mount) -> Volume:
        uuid = self._uuids.get(mount.device)
        disk = _disk(mount.device, self._paths)
        return Volume(
            id=uuid if uuid is not None else f"mount:{mount.mount_point}",
            mount=mount,
            label=self._labels.get(mount.device) or mount.mount_point.name or "/",
            system=disk is not None
            and self._system_disk is not None
            and disk[0] == self._system_disk[0],
            sd=disk is not None and disk[1],
        )

    def destination(self, directory: Path, *, internal: bool = False) -> Destination | None:
        """Describe a directory as a destination; ``None`` if it is on no known mount."""
        directory = Path(os.path.realpath(directory))
        mount = self.mount_of(directory)
        if mount is None:
            return None
        volume = self.volume(mount)
        relative = mount.root / directory.relative_to(mount.mount_point)
        total, free, writable = _space(directory, mount)
        return Destination(
            id=INTERNAL if internal else volume.id,
            label="Internal" if internal else volume.label,
            volume=volume,
            directory=directory,
            relative=PurePosixPath(relative.as_posix().lstrip("/")),
            total=total,
            free=free,
            writable=writable,
            internal=internal,
        )

    def external(self, search: tuple[Path, ...] = SEARCH) -> list[Destination]:
        """Filesystems that can hold data, mounted under the search directories."""
        found: list[Destination] = []
        for mount in self.mounts:
            if mount.fs_type in VIRTUAL:
                continue
            if not any(
                mount.mount_point.is_relative_to(base)
                and 1 <= len(mount.mount_point.relative_to(base).parts) <= 2
                for base in search
            ):
                continue
            destination = self.destination(mount.mount_point)
            if destination is not None and destination.volume.mount == mount:
                found.append(destination)
        return found

    def locate(self, volume_id: str, relative: PurePosixPath) -> Path | None:
        """Where a path relative to a filesystem's root is now, if that filesystem is mounted."""
        for mount in reversed(self.mounts):
            if self.volume(mount).id != volume_id:
                continue
            within = PurePosixPath("/") / relative
            if within == mount.root or within.is_relative_to(mount.root):
                return mount.mount_point / within.relative_to(mount.root)
        return None


def _space(directory: Path, mount: Mount) -> tuple[int, int, bool]:
    """Total and free bytes for nocsd, and whether it can write there."""
    probe = directory
    while not probe.exists() and probe != mount.mount_point and probe.parent != probe:
        probe = probe.parent  # the destination directory is created at the first save
    try:
        stats = os.statvfs(probe)
    except OSError:
        return 0, 0, False
    read_only = mount.read_only or bool(stats.f_flag & os.ST_RDONLY)
    writable = not read_only and os.access(probe, os.W_OK | os.X_OK)
    return stats.f_blocks * stats.f_frsize, stats.f_bavail * stats.f_frsize, writable
