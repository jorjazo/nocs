"""Finding mounted volumes and telling drives apart, from a fake /proc, /dev and /sys."""

import os
from pathlib import Path, PurePosixPath

import pytest

from nocs.storage.volumes import INTERNAL, Attached, SystemPaths, Volumes, unmounted_usb


class FakeSystem:
    """Mounts, block devices and disks as the kernel and udev publish them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths = SystemPaths(
            mountinfo=root / "proc/self/mountinfo",
            by_uuid=root / "dev/disk/by-uuid",
            by_label=root / "dev/disk/by-label",
            sys_block=root / "sys/dev/block",
            sys_class_block=root / "sys/class/block",
            udev_data=root / "run/udev/data",
        )
        for directory in (
            self.paths.by_uuid,
            self.paths.by_label,
            self.paths.sys_block,
            self.paths.udev_data,
        ):
            directory.mkdir(parents=True)
        self.paths.mountinfo.parent.mkdir(parents=True)
        self._lines: list[str] = []
        self.write()

    def block(
        self,
        name: str,
        device: tuple[int, int],
        disk: str,
        *,
        bus: str = "usb1/1-1/1-1:1.0/host0/target0:0:0/0:0:0:0",
        uuid: str | None = None,
        label: str | None = None,
    ) -> None:
        """A partition ``name`` of ``disk`` on ``bus``, holding a filesystem."""
        node = self.root / "sys/devices/platform" / bus / "block" / disk / name
        node.mkdir(parents=True)
        (node / "partition").write_text("1\n")
        number = f"{device[0]}:{device[1]}"
        (self.paths.sys_block / number).symlink_to(node)
        (self.paths.sys_class_block / name).mkdir(parents=True)
        (self.paths.sys_class_block / name / "dev").write_text(number + "\n")
        if uuid is not None:
            (self.paths.by_uuid / uuid).symlink_to(f"../../{name}")
        if label is not None:
            (self.paths.by_label / label.replace(" ", "\\x20")).symlink_to(f"../../{name}")

    def plug(
        self,
        name: str,
        device: tuple[int, int],
        disk: str,
        *,
        fs: str = "exfat",
        uuid: str | None = None,
        label: str | None = None,
        usage: str = "filesystem",
        bus: str = "usb1/1-1/1-1:1.0/host0/target0:0:0/0:0:0:0",
    ) -> None:
        """A partition ``name`` of ``disk`` plugged in, as the kernel links it and udev
        identifies it; the disk carries an old filesystem signature of its own."""
        disk_node = self.root / "sys/devices/platform" / bus / "block" / disk
        node = disk_node / name
        node.mkdir(parents=True)
        (node / "partition").write_text("1\n")
        number = f"{device[0]}:{device[1]}"
        (node / "dev").write_text(number + "\n")
        (disk_node / "dev").write_text(f"{device[0]}:{device[1] - 1}\n")
        self.paths.sys_class_block.mkdir(parents=True, exist_ok=True)
        (self.paths.sys_block / number).symlink_to(node)
        (self.paths.sys_class_block / name).symlink_to(node)
        if not (self.paths.sys_class_block / disk).exists():
            (self.paths.sys_class_block / disk).symlink_to(disk_node)
        udev = [f"E:ID_FS_USAGE={usage}", f"E:ID_FS_TYPE={fs}"]
        if uuid is not None:
            udev.append(f"E:ID_FS_UUID={uuid}")
            (self.paths.by_uuid / uuid).symlink_to(f"../../{name}")
        if label is not None:
            udev.append(f"E:ID_FS_LABEL={label}")
        (self.paths.udev_data / f"b{number}").write_text("\n".join(udev) + "\n")
        disk_udev = self.paths.udev_data / f"b{device[0]}:{device[1] - 1}"
        disk_udev.write_text("E:ID_FS_USAGE=filesystem\nE:ID_FS_TYPE=vfat\n")

    def mount(
        self,
        device: tuple[int, int],
        mount_point: Path | str,
        fs: str = "ext4",
        *,
        root: str = "/",
        options: str = "rw,relatime",
    ) -> None:
        point = str(mount_point).replace(" ", "\\040")
        number = len(self._lines) + 20
        self._lines.append(
            f"{number} 1 {device[0]}:{device[1]} {root} {point} {options} shared:1 - {fs} src rw"
        )
        self.write()

    def unmount(self, mount_point: Path | str) -> None:
        point = str(mount_point).replace(" ", "\\040")
        self._lines = [line for line in self._lines if line.split()[4] != point]
        self.write()

    def write(self) -> None:
        self.paths.mountinfo.write_text("".join(f"{line}\n" for line in self._lines))


def device_of(path: Path) -> tuple[int, int]:
    dev = os.stat(path).st_dev
    return os.major(dev), os.minor(dev)


SD = "mmc_host/mmc0/mmc0:aaaa"


@pytest.fixture
def system(tmp_path: Path) -> FakeSystem:
    return FakeSystem(tmp_path / "fake")


def test_mounts_identities_and_disks(system: FakeSystem, tmp_path: Path) -> None:
    system.block("mmcblk0p2", (179, 2), "mmcblk0", bus=SD, uuid="ROOT-UUID", label="writable")
    system.block("mmcblk0p3", (179, 3), "mmcblk0", bus=SD, uuid="DATA-UUID")
    system.block("sda1", (8, 1), "sda", uuid="1234-ABCD", label="My SSD")
    system.mount((179, 2), "/")
    system.mount((0, 25), "/run", "tmpfs")
    system.mount((179, 3), "/mnt/data")
    system.mount((8, 1), "/media/nocs/My SSD", "exfat", options="ro,relatime")
    system.mount((0, 30), "/mnt/ram", "tmpfs")
    system.mount((8, 1), "/mnt/a/b/too-deep")
    volumes = Volumes(system.paths)

    root = volumes.mount_of(Path("/home/nocs"))
    assert root is not None
    root_volume = volumes.volume(root)
    assert (root_volume.id, root_volume.label, root_volume.system, root_volume.sd) == (
        "ROOT-UUID",
        "writable",
        True,
        True,
    )
    ssd = volumes.mount_of(Path("/media/nocs/My SSD/NOCS"))
    assert ssd is not None
    assert (ssd.mount_point, ssd.fs_type, ssd.read_only) == (
        Path("/media/nocs/My SSD"),
        "exfat",
        True,
    )
    ssd_volume = volumes.volume(ssd)
    assert (ssd_volume.id, ssd_volume.label, ssd_volume.system, ssd_volume.sd) == (
        "1234-ABCD",
        "My SSD",
        False,
        False,
    )
    run = volumes.mount_of(Path("/run/indi"))
    assert run is not None
    assert volumes.volume(run).id == "mount:/run"

    # Another partition of the system's SD card: SD and on the system disk.
    external = {d.volume.mount.mount_point: d for d in volumes.external()}
    assert set(external) == {Path("/mnt/data"), Path("/media/nocs/My SSD")}
    data = external[Path("/mnt/data")]
    assert (data.id, data.volume.system, data.volume.sd) == ("DATA-UUID", True, True)
    assert external[Path("/media/nocs/My SSD")].writable is False  # read-only mount


def test_internal_destination_is_relative_to_its_filesystem(
    system: FakeSystem, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    system.block("nvme0n1p2", device_of(data), "nvme0n1", bus="pci0/nvme/nvme0", uuid="NVME")
    system.mount(device_of(data), "/")
    destination = Volumes(system.paths).destination(data, internal=True)
    assert destination is not None
    assert (destination.id, destination.label, destination.internal) == (
        INTERNAL,
        "Internal",
        True,
    )
    assert destination.volume.id == "NVME"
    assert destination.relative == PurePosixPath(str(data.resolve()).lstrip("/"))
    assert destination.writable
    assert destination.free > 0
    assert (destination.volume.system, destination.volume.sd) == (True, False)


def test_locate_follows_a_volume_to_its_current_mount_point(system: FakeSystem) -> None:
    system.block("sda1", (8, 1), "sda", uuid="1234-ABCD")
    system.mount((8, 1), "/media/nocs/SSD")
    relative = PurePosixPath("NOCS/2026-10-30/Light/M31/a.fits")
    assert Volumes(system.paths).locate("1234-ABCD", relative) == Path(
        "/media/nocs/SSD/NOCS/2026-10-30/Light/M31/a.fits"
    )
    system.unmount("/media/nocs/SSD")
    assert Volumes(system.paths).locate("1234-ABCD", relative) is None
    system.mount((8, 1), "/mnt/usb")
    assert Volumes(system.paths).locate("1234-ABCD", relative) == Path(
        "/mnt/usb/NOCS/2026-10-30/Light/M31/a.fits"
    )
    # A bind mount of a subdirectory reaches only what is inside it.
    system.unmount("/mnt/usb")
    system.mount((8, 1), "/srv/astro", root="/NOCS")
    assert Volumes(system.paths).locate("1234-ABCD", relative) == Path(
        "/srv/astro/2026-10-30/Light/M31/a.fits"
    )
    assert Volumes(system.paths).locate("1234-ABCD", PurePosixPath("other/x")) is None


def test_usb_drives_plugged_in_but_not_mounted(system: FakeSystem) -> None:
    system.plug("sdb1", (8, 17), "sdb", fs="exfat", uuid="AB12-CD34", label="NIGHTS")
    system.plug("sdc1", (8, 33), "sdc", fs="swap", usage="other")
    system.plug("sdd1", (8, 49), "sdd", fs="ext4", uuid="in-use")
    system.mount((8, 49), "/media/nocs/in-use")
    system.plug("nvme0n1p1", (259, 1), "nvme0n1", fs="ext4", uuid="inside", bus="pcie0/nvme0")
    found = unmounted_usb(system.paths, Volumes(system.paths).mounts)
    assert found == [Attached("/dev/sdb1", (8, 17), "NIGHTS", "exfat", "AB12-CD34")]


def test_mounted_usb_drives_are_removable(system: FakeSystem) -> None:
    system.block("sda1", (8, 1), "sda", uuid="USB")
    system.mount((8, 1), "/media/nocs/USB")
    usb = Volumes(system.paths).volume(Volumes(system.paths).mounts[0])
    assert usb.usb is True
