"""Masters of a sequence's groups of darks, bias and flats."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from test_calibration_library import row

from nocs.calibration import master
from nocs.calibration.groups import GroupMasterService
from nocs.calibration.master import GroupMaster, GroupMasterError, MasterKind
from nocs.imaging.pipeline import FrameAnalysis, Histogram
from nocs.state import StateStore
from nocs.storage import FrameFacts, FrameRow, SavedFrame
from nocs.storage.layout import NameFields, file_stem, folder

_fits: Any = fits


def frame(path: Path, value: int, *, height: int = 130, width: int = 40) -> Path:
    data = np.full((height, width), value, dtype=np.uint16)
    data[0, 0] = 60000 if value == 300 else value  # a hot pixel in one frame only
    header = _fits.Header()
    header["IMAGETYP"] = "Dark Frame"
    header["BAYERPAT"] = "RGGB"
    header["EXPTIME"] = 120.0
    _fits.PrimaryHDU(data=data, header=header).writeto(path)
    return path


def test_a_master_is_the_median_in_the_sensor_s_pixels(tmp_path: Path) -> None:
    frames = [str(frame(tmp_path / f"{i}.fits", v)) for i, v in enumerate((100, 300, 200))]
    built = master.build(str(tmp_path / "master.fits"), "dark", frames)
    assert built == GroupMaster(str(tmp_path / "master.fits"), "dark", 3, 40, 130)
    with _fits.open(built.path) as hdul:
        data = np.asarray(hdul[0].data)
        header = hdul[0].header
    assert data.dtype == np.uint16
    assert data.shape == (130, 40)  # strips of 64 rows, the last one short
    assert int(data[0, 0]) == 200  # the hot pixel of one frame is gone
    assert int(data[129, 39]) == 200
    assert header["IMAGETYP"] == "Master Dark"
    assert header["NCOMBINE"] == 3
    assert header["BAYERPAT"] == "RGGB"  # still a mosaic
    with pytest.raises(GroupMasterError, match="is not 40x130"):
        master.build(
            str(tmp_path / "other.fits"),
            "dark",
            [*frames, str(frame(tmp_path / "x.fits", 1, width=8))],
        )
    with pytest.raises(GroupMasterError, match="no frames"):
        master.build(str(tmp_path / "none.fits"), "bias", [])


def test_masters_have_a_folder_and_a_name_of_their_own() -> None:
    night = date(2026, 11, 17)
    assert folder("master_dark", night, "M 42", "L") == PurePosixPath("2026-11-17/Master")
    assert folder("master_flat", night, None, "Ha") == PurePosixPath("2026-11-17/Master/Ha")
    fields = NameFields(
        target=None,
        night=night,
        frame_type="master_bias",
        filter=None,
        exposure=0.001,
        gain=100,
        offset=None,
        temperature=-10,
        binning=1,
        camera="ZWO",
        start=datetime(2026, 11, 18, 3, tzinfo=UTC),
        seq=1,
    )
    assert file_stem("{type}_{temperature}C_{seq}", fields) == "MasterBias_-10C_0001"


@dataclass
class Library:
    root: Path
    rows: dict[int, FrameRow]
    saved: list[FrameFacts] = field(default_factory=list[FrameFacts])

    def frame_file(self, frame_id: int) -> tuple[FrameRow, Path]:
        found = self.rows[frame_id]
        return found, self.root / found.path

    def save(self, facts: FrameFacts) -> SavedFrame:
        self.saved.append(facts)
        assert facts.source.is_file()
        relative = PurePosixPath("2026-11-17/Master/x.fits")
        return SavedFrame(77, self.root / "x.fits", relative, "drive", 1, datetime.now(UTC))


class Worker:
    async def group_master(
        self, path: str, kind: MasterKind, frames: list[str]
    ) -> tuple[GroupMaster, FrameAnalysis]:
        built = master.build(path, kind, frames)
        preview = FrameAnalysis(
            "/previews/abc.jpg", 40, 30, True, 0, None, Histogram([], 0, 1, 0, 0), 0.1
        )
        return built, preview


async def test_a_group_s_master_is_saved_and_shown(tmp_path: Path) -> None:
    rows: dict[int, FrameRow] = {}
    for i, value in enumerate((100, 200, 300), start=1):
        frame(tmp_path / f"{i}.fits", value)
        rows[i] = replace(row("dark"), id=i, path=PurePosixPath(f"{i}.fits"))
    library = Library(tmp_path, rows)
    store = StateStore()
    service = GroupMasterService(store, Worker(), lambda: library, tmp_path / "data")
    service.forget()
    kept = await service.keep("dark", [1, 2, 3, 99])
    assert kept == {"master": "dark", "frames": 3, "path": "2026-11-17/Master/x.fits"}
    [facts] = library.saved
    assert facts.frame_type == "master_dark"
    assert (facts.exposure, facts.camera) == (rows[1].exposure, rows[1].camera)
    state = store.get(("sequence", "master"))
    assert isinstance(state, dict)
    assert state["kind"] == "dark"
    assert state["preview"] == {"url": "/api/previews/abc.jpg", "width": 40, "height": 30}
    assert not list((tmp_path / "data" / "masters-new").iterdir())  # moved by storage
    assert await service.keep("bias", [99]) is None
