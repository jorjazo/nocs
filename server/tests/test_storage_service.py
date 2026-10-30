"""Choosing destinations, saving frames into place and downloading them (ADR 0013).

The "external drive" is a directory on /dev/shm, a filesystem of its own, so the
check that a destination really is on its drive runs against real devices.
"""

import io
import os
import shutil
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from test_storage_layout import write_fits
from test_volumes import SD, FakeSystem, device_of

from nocs.equipment import Optics, Site
from nocs.state import StateStore
from nocs.storage import FrameFacts, FrameFilter, FrameUnavailableError, StorageError
from nocs.storage import service as storage_service
from nocs.storage.service import StorageService

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline

SITE = Site(name="Lab", latitude=-30.2, longitude=-70.7, elevation=2400)
OPTICS = Optics(focal_length=400, aperture=80, reducer=0.8)


@pytest.fixture
def shm() -> Iterator[Path]:
    base = Path("/dev/shm")
    if not base.is_dir() or not os.access(base, os.W_OK):
        pytest.skip("needs a writable /dev/shm")
    path = base / f"nocs-test-{uuid.uuid4().hex}"
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)


class Rig:
    def __init__(self, tmp_path: Path, shm: Path) -> None:
        self.tmp = tmp_path
        self.data = tmp_path / "data"
        self.config = tmp_path / "config"
        self.data.mkdir()
        if device_of(shm) == device_of(self.data):
            pytest.skip("/dev/shm is on the same filesystem as the test directory")
        self.search = shm
        self.usb = shm / "usb"
        self.usb.mkdir()
        self.system = FakeSystem(tmp_path / "fake")
        self.system.block("mmcblk0p2", device_of(self.data), "mmcblk0", bus=SD, uuid="ROOT")
        self.system.block("sda1", device_of(shm), "sda", uuid="USB-UUID", label="USB")
        self.system.mount(device_of(self.data), "/")
        self.system.mount(device_of(shm), self.usb, "exfat")
        self.store = StateStore()
        self.count = 0

    def service(self) -> StorageService:
        return StorageService(
            self.store,
            self.config,
            self.data,
            self.data,
            lambda: SITE.longitude,
            paths=self.system.paths,
            search=(self.search,),
        )

    def frame(self, frame_type: str = "light", start: str = "2026-10-31T01:00:00") -> FrameFacts:
        """A frame as the capture service hands it over, in its incoming directory."""
        self.count += 1
        incoming = self.data / "incoming"
        incoming.mkdir(exist_ok=True)
        source = incoming / f"main_camera_{self.count}.fits"
        write_fits(source, DATE_OBS=start, FILTER="Ha", CCD_TEMP=-9.6, FOCALLEN=320.0)
        return FrameFacts(
            source=source,
            frame_type=frame_type,
            exposure=300,
            arrived=datetime(2026, 10, 31, 1, 5, tzinfo=UTC),
            camera="CCD Simulator",
            gain=100,
            offset=10,
            binning=1,
            temperature=-9.6,
            cooler_target=-10,
            filter="Red",
            profile="sim",
            site=SITE,
            optics=OPTICS,
        )

    @property
    def state(self) -> Any:
        return self.store.get(("storage",))


@pytest.fixture
def rig(tmp_path: Path, shm: Path) -> Rig:
    return Rig(tmp_path, shm)


@pytest.fixture
async def service(rig: Rig) -> AsyncIterator[StorageService]:
    service = rig.service()
    await service.refresh()
    yield service
    await service.close()


async def test_state_lists_destinations(rig: Rig, service: StorageService) -> None:
    state = rig.state
    assert [d["id"] for d in state["destinations"]] == ["internal", "USB-UUID"]
    internal, usb = state["destinations"]
    assert (internal["system"], internal["sd"], internal["internal"]) == (True, True, True)
    assert (usb["label"], usb["fs"], usb["system"], usb["path"]) == (
        "USB",
        "exfat",
        False,
        str(rig.usb),
    )
    assert (state["choice"], state["destination"], state["error"]) == ("auto", "USB-UUID", None)


async def test_automatic_saves_to_the_external_drive(rig: Rig, service: StorageService) -> None:
    await service.set_target("M 31")
    facts = rig.frame()
    saved = service.save(facts)
    assert saved.destination == "USB-UUID"
    assert (
        str(saved.relative)
        == "2026-10-30/Light/M_31/Ha/20261031-010000_Light_Ha_300s_-10C_0001.fits"
    )
    assert saved.path == rig.usb / "NOCS" / saved.relative
    assert not facts.source.exists()
    with _fits.open(saved.path) as hdus:
        header = hdus[0].header
        assert header["OBJECT"] == "M 31"
        assert header["SWCREATE"].startswith("NOCS ")
        assert (header["SITENAME"], header["SITEELEV"]) == ("Lab", 2400)
        assert header["FOCALLEN"] == 320.0  # the driver's value stays
        assert (header["APTDIA"], header["FOCRATIO"], header["SET-TEMP"]) == (80, 4.0, -10)
        assert header["FILTER"] == "Ha"

    [located] = service.frames(FrameFilter())
    row = located.row
    assert (row.id, row.target, row.filter, row.volume, row.volume_label) == (
        saved.id,
        "M 31",
        "Ha",
        "USB-UUID",
        "USB",
    )
    assert (row.width, row.height, row.temperature) == (64, 48, -9.6)
    assert located.path == saved.path
    service.set_metrics(saved.id, 120, 1.8)
    again = service.frame(saved.id)
    assert again is not None
    assert (again.row.stars, again.row.hfr) == (120, 1.8)

    # Calibration frames ignore the target; the sequence restarts per folder.
    flat = service.save(rig.frame("flat"))
    assert str(flat.relative).startswith("2026-10-30/Flat/Ha/")
    second = service.save(rig.frame())
    assert second.relative.name.endswith("_0002.fits")


async def test_names_are_never_reused(rig: Rig, service: StorageService) -> None:
    await service.set_template("{type}_{exposure}s")
    first = service.save(rig.frame())
    assert first.path.name == "Light_300s.fits"
    assert service.save(rig.frame()).path.name == "Light_300s_2.fits"
    assert first.path.is_file()


async def test_a_night_that_started_on_a_drive_never_falls_back(
    rig: Rig, service: StorageService
) -> None:
    service.save(rig.frame())
    rig.system.unmount(rig.usb)
    await service.refresh()
    assert "USB" in rig.state["error"]
    facts = rig.frame()
    with pytest.raises(StorageError, match="USB"):
        service.save(facts)
    assert facts.source.exists()
    kept = service.keep_unsaved(facts.source)
    assert kept is not None
    assert kept.parent == rig.data / "unsaved"
    assert not facts.source.exists()

    # The next night starts afresh: no drive, so internal.
    saved = service.save(rig.frame(start="2026-10-31T23:00:00"))
    assert saved.destination == "internal"
    assert saved.path.is_relative_to(rig.data / "NOCS" / "2026-10-31")


async def test_explicit_choices(rig: Rig, service: StorageService) -> None:
    await service.choose("internal")
    assert (rig.state["choice"], rig.state["destination"]) == ("internal", "internal")
    assert service.save(rig.frame()).destination == "internal"
    with pytest.raises(StorageError):
        await service.choose("NOT-MOUNTED")

    await service.choose("USB-UUID")
    rig.system.unmount(rig.usb)
    with pytest.raises(StorageError, match="USB is not mounted"):
        service.save(rig.frame())
    rig.system.mount(device_of(rig.usb), rig.usb, "exfat")
    assert service.save(rig.frame()).destination == "USB-UUID"

    # Kept across restarts, with the target and template.
    await service.set_target("NGC 7000")
    await service.set_template("{target}_{seq}")
    restarted = rig.service()
    await restarted.refresh()
    assert (rig.state["choice"], rig.state["target"], rig.state["template"]) == (
        "USB-UUID",
        "NGC 7000",
        "{target}_{seq}",
    )
    assert restarted.save(rig.frame()).path.name == "NGC_7000_0001.fits"
    await restarted.close()


async def test_empty_mount_point_is_refused(rig: Rig, service: StorageService) -> None:
    # The mount table says a drive is at the mount point, but the directory is on
    # another filesystem: never write to whatever is underneath.
    rig.system.block("sdb1", (8, 17), "sdb", uuid="GHOST")
    ghost = rig.search / "ghost"
    ghost.mkdir()
    rig.system.mount((8, 17), ghost)
    await service.choose("GHOST")
    with pytest.raises(StorageError, match="no longer mounted"):
        service.save(rig.frame())


async def test_free_space_reserve(
    rig: Rig, service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage_service, "RESERVE", 1 << 60)
    with pytest.raises(StorageError, match="full"):
        service.save(rig.frame())
    await service.refresh()
    assert "full" in rig.state["error"]


async def test_bad_commands(service: StorageService) -> None:
    with pytest.raises(ValueError, match="unknown field"):
        await service.set_template("{nope}")
    with pytest.raises(ValueError, match="letters"):
        await service.set_target("///")
    await service.set_target("")
    assert service.target is None


async def test_zip_of_a_night(rig: Rig, service: StorageService) -> None:
    await service.set_target("M31")
    saved = [service.save(rig.frame()), service.save(rig.frame("dark"))]
    frames = service.frames(FrameFilter())
    size, chunks = service.zip(frames)
    data = b"".join(chunks)
    assert len(data) == size
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == sorted(str(s.relative) for s in saved)
        assert archive.read(str(saved[0].relative)) == saved[0].path.read_bytes()

    saved[1].path.unlink()
    size, chunks = service.zip(service.frames(FrameFilter()))
    data = b"".join(chunks)
    assert len(data) == size
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert str(saved[1].relative) in archive.read("MISSING.txt").decode()

    # The same name on two drives (a night split between them) is kept twice.
    await service.set_template("{type}_{seq}")
    on_usb = service.save(rig.frame("bias"))
    await service.choose("internal")
    on_internal = service.save(rig.frame("bias"))
    assert on_usb.relative == on_internal.relative
    found = service.frames(FrameFilter(frame_type="bias"))
    size, chunks = service.zip(found)
    with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert sorted(archive.namelist()) == [
            "2026-10-30/Bias/Bias_0001.fits",
            "2026-10-30/Bias/Bias_0001_2.fits",
        ]

    rig.system.unmount(rig.usb)
    with pytest.raises(FrameUnavailableError, match="USB"):
        service.zip(service.frames(FrameFilter()))
    with pytest.raises(FrameUnavailableError):
        service.frame_file(saved[0].id)
    with pytest.raises(KeyError):
        service.frame_file(9999)


async def test_unusable_catalog_refuses_to_save(rig: Rig) -> None:
    import sqlite3

    rig.data.mkdir(exist_ok=True)
    with sqlite3.connect(rig.data / "catalog.sqlite") as raw:
        raw.execute("PRAGMA user_version = 999")
    service = rig.service()
    await service.refresh()
    assert "catalog" in rig.state["error"]
    with pytest.raises(StorageError, match="newer"):
        service.save(rig.frame())
    await service.close()
