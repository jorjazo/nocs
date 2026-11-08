"""The live stack service: which frames go to which stack, calibration, the state."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from test_calibration_library import row

from nocs.api.schemas import StackState
from nocs.stacking.frames import Offered
from nocs.stacking.masters import Calibration, Kind, Master
from nocs.stacking.service import MISSES, LiveStackService
from nocs.stacking.settings import StackLook
from nocs.stacking.stack import Added, Cause, Look, Rendered, StackLostError
from nocs.state import StateStore
from nocs.storage import FrameRow, FrameUnavailableError

_fits: Any = fits

# The frames are headers alone (write): astropy warns that their data is missing.
pytestmark = pytest.mark.filterwarnings("ignore:File may have been truncated")


@dataclass
class Call:
    stack_id: str
    path: str
    new: bool
    calibration: Calibration | None


@dataclass
class FakeWorker:
    previews_dir: Path
    calls: list[Call] = field(default_factory=list[Call])
    frames: dict[str, int] = field(default_factory=dict[str, int])
    refuse: list[Cause | None] = field(default_factory=list[Cause | None])
    """Outcomes to give next (None: accept)."""
    masters: list[tuple[str, Kind, list[str], str | None]] = field(
        default_factory=list[tuple[str, Kind, list[str], str | None]]
    )
    dropped: list[str] = field(default_factory=list[str])
    lose: bool = False
    seen: list[bool] = field(default_factory=list[bool])
    """For each call, whether the file was there when the worker read it."""
    gate: asyncio.Event | None = None

    async def stack_add(
        self,
        stack_id: str,
        fits_path: str,
        bayer: str | None,
        *,
        new: bool,
        stars: int | None,
        hfr: float | None,
        look: Look,
        calibration: Calibration | None = None,
    ) -> Added:
        if self.gate is not None:
            await self.gate.wait()
        self.seen.append(os.path.isfile(fits_path))  # noqa: ASYNC240 (a test double)
        self.calls.append(Call(stack_id, fits_path, new, calibration))
        if self.lose:
            self.lose = False
            self.frames.clear()
            raise StackLostError("restarted")
        if new:
            self.frames[stack_id] = 0
        elif stack_id not in self.frames:
            raise StackLostError("unknown")
        cause = self.refuse.pop(0) if self.refuse else None
        if cause is not None:
            return Added(False, f"no ({cause})", self.frames[stack_id], 1, cause=cause)
        self.frames[stack_id] += 1
        preview = self.previews_dir / f"{len(self.calls):032x}.jpg"
        return Added(
            True,
            None,
            self.frames[stack_id],
            0,
            shift=(1.0, 2.0),
            rotation=0.1,
            stars=40,
            rms=0.1,
            clipped=0.0,
            preview=Rendered(str(preview), 1920, 1280),
            seconds=1.0,
        )

    async def stack_render(self, stack_id: str, look: Look) -> Rendered:
        if stack_id not in self.frames:
            raise StackLostError("unknown")
        return Rendered(str(self.previews_dir / f"{'f' * 32}.jpg"), 1920, 1280)

    async def stack_drop(self, stack_id: str) -> None:
        self.dropped.append(stack_id)
        self.frames.pop(stack_id, None)

    async def build_master(
        self,
        path: str,
        kind: Kind,
        frames: list[str],
        bayer: str | None,
        subtract: str | None = None,
    ) -> Master:
        self.masters.append((path, kind, frames, subtract))
        return Master(path, kind, len(frames))


@dataclass
class FakeLibrary:
    rows: list[FrameRow]
    missing: set[int] = field(default_factory=set[int])

    def calibration_frames(self, cameras: list[str]) -> list[FrameRow]:
        return self.rows

    def frame_file(self, frame_id: int) -> tuple[FrameRow, Path]:
        if frame_id in self.missing:
            raise FrameUnavailableError("unplugged")
        found = next(r for r in self.rows if r.id == frame_id)
        return found, Path(f"/frames/{frame_id}.fits")


def write(path: Path, width: int = 6248, height: int = 4176) -> Path:
    """A FITS header for a frame of that size, without its data: only the header is read."""
    header = _fits.Header()
    header["SIMPLE"] = True
    header["BITPIX"] = 16
    header["NAXIS"] = 2
    header["NAXIS1"] = width
    header["NAXIS2"] = height
    path.write_bytes(header.tostring().encode())
    return path


class Rig:
    def __init__(self, tmp_path: Path, rows: list[FrameRow] | None = None) -> None:
        self.tmp = tmp_path
        self.store = StateStore()
        self.worker = FakeWorker(tmp_path / "previews")
        self.library = FakeLibrary(rows or [])
        self.service = LiveStackService(
            self.store, self.worker, lambda: self.library, tmp_path / "config", tmp_path / "data"
        )
        (tmp_path / "config").mkdir()
        self.count = 0

    def frame(self, **changes: Any) -> Offered:
        self.count += 1
        path = write(self.tmp / f"frame{self.count}.fits")
        offered = Offered(
            path=path,
            owned=False,
            bayer="RGGB",
            taken=datetime(2026, 10, 31, 23, self.count % 60, tzinfo=UTC),
            night=date(2026, 10, 31),
            exposure=300.0,
            camera="ZWO CCD ASI2600MC Duo",
            gain=100.0,
            offset=50.0,
            binning=1,
            temperature=-10.0,
            filter="L",
            target="NGC 253",
            frame_id=self.count,
        )
        return replace(offered, **changes)

    def state(self) -> StackState:
        return StackState.model_validate(self.store.get(("stack",)))


@pytest.fixture
async def rig(tmp_path: Path):
    rig = Rig(tmp_path)
    await rig.service.start()
    await rig.service.set_on(True)
    task = asyncio.create_task(rig.service.run())
    yield rig
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def offer(rig: Rig, frame: Offered) -> None:
    await rig.service.offer(frame)
    await rig.service.idle()


async def test_off_by_default_and_offers_are_ignored(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert rig.state().on is False
    assert rig.state().status == "off"
    await rig.service.offer(rig.frame())
    assert rig.worker.calls == []


async def test_the_switch_persists(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.service.set_on(True)
    await rig.service.set_look(StackLook(background=0.3))
    service = LiveStackService(
        StateStore(), rig.worker, lambda: rig.library, tmp_path / "config", tmp_path / "data"
    )
    assert not service.on  # until started: the settings are read off the event loop
    await service.start()
    assert service.on
    assert service.settings.look.background == 0.3


async def test_frames_of_one_setup_go_to_one_stack(rig: Rig) -> None:
    for _ in range(3):
        await offer(rig, rig.frame())
    ids = {c.stack_id for c in rig.worker.calls}
    assert len(ids) == 1
    assert [c.new for c in rig.worker.calls] == [True, False, False]
    state = rig.state()
    assert state.status == "stacking"
    assert state.current is not None
    assert state.current.frames == 3
    assert state.current.exposure == 900.0
    assert state.current.target == "NGC 253"
    assert state.current.setup.width == 6248
    assert state.current.preview is not None
    assert state.current.preview.url.startswith("/api/previews/")
    assert state.current.last is not None
    assert state.current.last.accepted


@pytest.mark.parametrize(
    "change",
    [{"exposure": 120.0}, {"gain": 200.0}, {"binning": 2}, {"filter": "R"}, {"target": "M 83"}],
)
async def test_another_setup_starts_a_new_stack(rig: Rig, change: dict[str, Any]) -> None:
    await offer(rig, rig.frame())
    await offer(rig, rig.frame(**change))
    first, second = rig.worker.calls
    assert first.stack_id != second.stack_id
    assert second.new
    # A colour camera keeps only the current stack.
    assert rig.worker.dropped == [first.stack_id]


async def test_a_mono_camera_keeps_a_stack_per_filter(rig: Rig) -> None:
    await offer(rig, rig.frame(bayer=None, filter="R"))
    await offer(rig, rig.frame(bayer=None, filter="G"))
    await offer(rig, rig.frame(bayer=None, filter="R"))
    r1, g, r2 = rig.worker.calls
    assert r2.stack_id == r1.stack_id
    assert not r2.new
    assert g.stack_id != r1.stack_id
    assert rig.state().stacks == 2


async def test_a_new_stack_by_hand(rig: Rig) -> None:
    await offer(rig, rig.frame())
    await rig.service.reset()
    await offer(rig, rig.frame())
    first, second = rig.worker.calls
    assert second.new
    assert first.stack_id != second.stack_id


async def test_frames_that_do_not_register_start_a_new_stack(rig: Rig) -> None:
    await offer(rig, rig.frame())
    rig.worker.refuse = ["registration"] * MISSES
    for _ in range(MISSES):
        await offer(rig, rig.frame())
    calls = rig.worker.calls
    # The third miss starts a new stack with that same frame.
    assert calls[-1].new
    assert calls[-1].path == calls[-2].path
    assert calls[-1].stack_id != calls[0].stack_id
    state = rig.state()
    assert state.current is not None
    assert state.current.frames == 1
    assert any("did not register" in n for n in state.current.calibration.notes)


async def test_the_gate_does_not_count_as_a_miss(rig: Rig) -> None:
    await offer(rig, rig.frame())
    rig.worker.refuse = ["gate"] * (MISSES + 1)
    for _ in range(MISSES + 1):
        await offer(rig, rig.frame())
    assert not any(c.new for c in rig.worker.calls[1:])
    state = rig.state()
    assert state.current is not None
    assert state.current.last is not None
    assert state.current.last.cause == "gate"


async def test_a_lost_stack_starts_again(rig: Rig) -> None:
    await offer(rig, rig.frame())
    rig.worker.lose = True
    await offer(rig, rig.frame())
    calls = rig.worker.calls
    assert calls[-1].new
    assert calls[-1].stack_id != calls[0].stack_id
    assert rig.state().current is not None


async def test_newest_frame_wins_while_busy(rig: Rig, tmp_path: Path) -> None:
    rig.worker.gate = asyncio.Event()
    await rig.service.offer(rig.frame())
    await asyncio.sleep(0)  # the first is in the worker
    loop_frames = [rig.frame(owned=True) for _ in range(3)]
    for f in loop_frames:
        await rig.service.offer(f)
    rig.worker.gate.set()
    await rig.service.idle()
    assert len(rig.worker.calls) == 2  # the first, and the newest of the three
    state = rig.state()
    assert state.current is not None
    assert state.current.skipped == 2
    # Unsaved frames were stacked from a link of their own, deleted afterwards.
    assert rig.worker.seen == [True, True]
    assert Path(rig.worker.calls[1].path).parent == tmp_path / "data" / "stacking"
    assert not any((tmp_path / "data" / "stacking").iterdir())
    assert all(f.path.exists() for f in loop_frames)  # the capture's own files stay


async def test_switching_off_ends_the_stacks(rig: Rig) -> None:
    await offer(rig, rig.frame())
    first = rig.worker.calls[0].stack_id
    await rig.service.set_on(False)
    assert rig.worker.dropped == [first]
    assert rig.state().status == "off"
    assert rig.state().current is None


async def test_a_new_look_renders_the_stack_again(rig: Rig) -> None:
    await offer(rig, rig.frame())
    await rig.service.set_look(StackLook(saturation=1.5))
    state = rig.state()
    assert state.look.saturation == 1.5
    assert state.current is not None
    assert state.current.preview is not None
    assert state.current.preview.url == f"/api/previews/{'f' * 32}.jpg"


async def test_calibration_masters_from_the_library(tmp_path: Path) -> None:
    darks = [row("dark") for _ in range(3)]
    flats = [row("flat", filter="L", exposure=2.0) for _ in range(2)]
    bias = [row("bias", exposure=0.001) for _ in range(2)]
    rig = Rig(tmp_path, darks + flats + bias)
    rig.library.missing = {darks[0].id}
    await rig.service.set_on(True)
    task = asyncio.create_task(rig.service.run())
    try:
        await offer(rig, rig.frame())
    finally:
        task.cancel()
    kinds = [(kind, len(files)) for _, kind, files, _ in rig.worker.masters]
    assert kinds == [("dark", 2), ("bias", 2), ("flat", 2)]  # one dark is unplugged
    dark_path, _, _, _ = rig.worker.masters[0]
    bias_path, _, _, _ = rig.worker.masters[1]
    assert rig.worker.masters[2][3] == bias_path  # the flats lose their bias
    assert Path(dark_path).parent == tmp_path / "data" / "masters"
    calibration = rig.worker.calls[0].calibration
    assert calibration is not None
    assert calibration.dark == dark_path
    assert calibration.flat == rig.worker.masters[2][0]
    state = rig.state()
    assert state.current is not None
    assert state.current.calibration.dark
    assert state.current.calibration.flat
    assert state.current.calibration.notes == ["darks: 3", "flats: 2"]
    assert state.current.calibration.dark_kind == "dark"
    assert state.current.calibration.dark_frames == 2  # one is on an unplugged drive
    assert state.current.calibration.flat_frames == 2
    assert not state.current.calibration.flats_unused


async def test_without_calibration_frames_the_stack_is_cosmetic(rig: Rig) -> None:
    await offer(rig, rig.frame())
    calibration = rig.worker.calls[0].calibration
    assert calibration == Calibration(cosmetic=True)
    state = rig.state()
    assert state.current is not None
    assert state.current.calibration.cosmetic
    assert state.current.calibration.notes == ["no darks or bias", "no flats"]
    assert state.current.calibration.dark_kind is None
    assert state.current.calibration.dark_frames == 0


async def test_new_stack_while_its_masters_are_built(tmp_path: Path) -> None:
    darks = [row("dark") for _ in range(2)]
    rig = Rig(tmp_path, darks)
    await rig.service.set_on(True)
    building = asyncio.Event()
    release = asyncio.Event()
    build = rig.worker.build_master

    async def slow(*args: Any, **kwargs: Any) -> Master:
        building.set()
        await release.wait()
        return await build(*args, **kwargs)

    rig.worker.build_master = slow  # type: ignore[method-assign]
    task = asyncio.create_task(rig.service.run())
    try:
        await rig.service.offer(rig.frame())
        await building.wait()
        await rig.service.reset()  # while the dark master is built
        release.set()
        await rig.service.idle()
        state = rig.state()
        # The frame went with its stack, quietly: no failure, nothing in the worker.
        assert state.status != "failed"
        assert state.error is None
        assert rig.worker.calls == []
        await offer(rig, rig.frame())
        assert rig.worker.calls[-1].new
    finally:
        task.cancel()


async def test_a_stack_ended_while_its_first_frame_is_added_is_dropped(rig: Rig) -> None:
    rig.worker.gate = asyncio.Event()
    await rig.service.offer(rig.frame())
    await asyncio.sleep(0.01)  # the frame is in the worker
    await rig.service.reset()
    rig.worker.gate.set()
    await rig.service.idle()
    # The worker would otherwise hold a stack nobody knows of (~200 MB at 26 MP).
    assert rig.worker.frames == {}
    assert rig.worker.dropped == [rig.worker.calls[0].stack_id]


async def test_a_frame_that_cannot_be_deleted_does_not_stop_stacking(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "unlink", refuse)
    await offer(rig, rig.frame(owned=True))
    monkeypatch.undo()
    await offer(rig, rig.frame(owned=True))
    assert len(rig.worker.calls) == 2


async def test_links_left_behind_are_deleted_at_start(tmp_path: Path) -> None:
    links = tmp_path / "data" / "stacking"
    links.mkdir(parents=True)
    (links / "old.fits").write_bytes(b"x")
    rig = Rig(tmp_path)
    await rig.service.start()
    assert list(links.iterdir()) == []


async def test_switching_on_again_clears_a_failure(rig: Rig) -> None:
    rig.worker.lose = True
    rig.worker.refuse = []

    async def broken(*args: Any, **kwargs: Any) -> Added:
        raise RuntimeError("the worker broke")

    rig.worker.stack_add = broken  # type: ignore[method-assign]
    await offer(rig, rig.frame())
    assert rig.state().status == "failed"
    await rig.service.set_on(False)
    await rig.service.set_on(True)
    state = rig.state()
    assert (state.status, state.error) == ("idle", None)


async def test_bias_only_calibration_says_so(tmp_path: Path) -> None:
    bias = [row("bias", exposure=0.001) for _ in range(2)]
    rig = Rig(tmp_path, bias)
    await rig.service.set_on(True)
    task = asyncio.create_task(rig.service.run())
    try:
        await offer(rig, rig.frame())
    finally:
        task.cancel()
    calibration = rig.worker.calls[0].calibration
    assert calibration is not None
    assert calibration.bias
    assert calibration.cosmetic


async def test_a_master_that_fails_is_reported_as_such(tmp_path: Path) -> None:
    darks = [row("dark") for _ in range(2)]
    flats = [row("flat", filter="L", exposure=2.0) for _ in range(2)]
    bias = [row("bias", exposure=0.001) for _ in range(2)]
    rig = Rig(tmp_path, darks + flats + bias)
    await rig.service.set_on(True)
    build = rig.worker.build_master
    seen: list[Any] = []

    async def failing(path: str, kind: Kind, *args: Any, **kwargs: Any) -> Master:
        seen.append(rig.state().building)
        if kind in ("dark", "flat"):
            raise OSError("a broken file")
        return await build(path, kind, *args, **kwargs)

    rig.worker.build_master = failing  # type: ignore[method-assign]
    task = asyncio.create_task(rig.service.run())
    try:
        await offer(rig, rig.frame())
    finally:
        task.cancel()
    state = rig.state()
    assert state.current is not None
    calibration = state.current.calibration
    assert (calibration.dark_failed, calibration.flat_failed) == (True, True)
    assert (calibration.dark_frames, calibration.flat_frames) == (0, 0)
    assert state.building is None  # done
    # While each was built, the state said which.
    assert [(b.kind, b.frames) for b in seen] == [("dark", 2), ("bias", 2), ("flat", 2)]
