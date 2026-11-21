"""Full-size pictures of what the viewer shows, for visitors: rendered once, kept."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nocs.devices import FrameType
from nocs.equipment import Role
from nocs.imaging.capture import KeptFrame, Shot
from nocs.imaging.pictures import NothingToShowError, Pictures

TAKEN = datetime(2026, 11, 21, 3, 4, 5, tzinfo=UTC)


@dataclass
class Worker:
    renders: list[tuple[str, str | None]] = field(default_factory=list[tuple[str, str | None]])

    async def picture(self, fits_path: str, jpeg_path: str, bayer: str | None) -> tuple[int, int]:
        self.renders.append((Path(fits_path).read_text(), bayer))  # noqa: ASYNC240 (a test double)
        Path(jpeg_path).write_bytes(b"jpeg")  # noqa: ASYNC240 (a test double)
        return 10, 10


@dataclass
class Stacker:
    key: str | None = None
    name: str | None = "M 42"
    renders: int = 0

    def picture_key(self) -> str | None:
        return self.key

    def picture_name(self) -> str | None:
        return self.name

    async def picture(self, path: Path) -> None:
        self.renders += 1
        path.write_bytes(b"stack")  # noqa: ASYNC240 (a test double)


def kept(path: Path, taken: datetime = TAKEN) -> KeptFrame:
    shot = Shot(path, 4, FrameType.LIGHT, taken, 10.0, "RGGB")
    return KeptFrame(shot=shot, owned=True, pointing=None, stars=0, hfr=None)


async def test_a_frame_is_rendered_once_and_kept_until_the_next(tmp_path: Path) -> None:
    frame = tmp_path / "frame.fits"
    frame.write_text("first")
    shown: dict[Role, KeptFrame | None] = {Role.MAIN_CAMERA: None}
    worker = Worker()
    pictures = Pictures(tmp_path / "pictures", worker, shown.get, lambda: None)
    with pytest.raises(NothingToShowError):
        await pictures.frame()

    shown[Role.MAIN_CAMERA] = kept(frame)
    first = await pictures.frame()
    assert first.name == "NOCS_frame_20261121_030405.jpg"
    assert await pictures.frame() == first
    assert worker.renders == [("first", "RGGB")]  # one render for two downloads
    assert [p.suffix for p in (tmp_path / "pictures").iterdir()] == [".jpg"]  # no link left

    second = tmp_path / "second.fits"
    second.write_text("second")
    shown[Role.MAIN_CAMERA] = kept(second, TAKEN.replace(second=6))
    newer = await pictures.frame()
    assert newer.path != first.path
    assert not first.path.exists()  # only the latest is kept
    assert worker.renders[-1] == ("second", "RGGB")

    second.unlink()  # replaced by a newer frame while asked for
    shown[Role.MAIN_CAMERA] = kept(second, TAKEN.replace(second=7))
    with pytest.raises(NothingToShowError):
        await pictures.frame()


async def test_the_stack_is_rendered_again_when_it_changes(tmp_path: Path) -> None:
    stacker = Stacker()
    pictures = Pictures(
        tmp_path / "pictures", Worker(), lambda _: None, lambda: stacker, now=lambda: TAKEN
    )
    with pytest.raises(NothingToShowError):
        await pictures.stack()
    stacker.key = "a-3"
    first = await pictures.stack()
    assert first.name == "NOCS_M_42_20261121_030405.jpg"
    assert first.path.read_bytes() == b"stack"
    await pictures.stack()
    assert stacker.renders == 1
    stacker.key = "a-4"  # a frame more, or another look
    await pictures.stack()
    assert stacker.renders == 2
    pictures.clear()
    assert not any((tmp_path / "pictures").iterdir())
