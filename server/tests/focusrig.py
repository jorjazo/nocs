"""A fake rig for focus tests: focusers with and without backlash, and a camera whose
stars follow a known V-curve at the focuser's optical position."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from nocs.devices import DeviceError, FrameType
from nocs.equipment import Role
from nocs.focus.curve import Hyperbola
from nocs.focus.focusers import FocuserCalibration, FocuserConfig
from nocs.imaging import Shot, StarMetrics
from nocs.jobs import JobContext, JobManager

CURVE = Hyperbola(a=2.0, b=300, c=10000)


class FakeFocuser:
    """Positions as reported; the optics lag ``backlash`` steps after a move inward."""

    def __init__(self, position: int, backlash: int = 0, maximum: int = 60000) -> None:
        self._position = position
        self.backlash = backlash
        self.lagging = False
        self.moves: list[int] = []
        self.maximum = maximum
        self.driver_backlash: int | None = None

    @property
    def position(self) -> int:
        return self._position

    @property
    def optical(self) -> int:
        return self._position + (self.backlash if self.lagging else 0)

    @property
    def max_position(self) -> int | None:
        return self.maximum

    @property
    def temperature(self) -> float | None:
        return 4.5

    @property
    def moving(self) -> bool:
        return False

    @property
    def can_abort(self) -> bool:
        return True

    async def move_to(self, position: int) -> None:
        await asyncio.sleep(0)
        if position != self._position:
            self.lagging = position < self._position
        self._position = position
        self.moves.append(position)

    async def disable_driver_backlash(self) -> None:
        self.driver_backlash = None

    async def abort(self) -> None:
        pass


class SlackFocuser(FakeFocuser):
    """A dead band: after the focuser reverses, its gears cross ``slack`` steps before
    the optics move. Pushing outward, the optics are at the position; pulling inward,
    ``slack`` steps outward of it."""

    def __init__(self, position: int, slack: int) -> None:
        super().__init__(position)
        self.slack = slack
        self.tube = position

    @property
    def optical(self) -> int:
        return self.tube

    async def move_to(self, position: int) -> None:
        await FakeFocuser.move_to(self, position)
        self.tube = min(max(self.tube, position), position + self.slack)


class EafLikeFocuser(FakeFocuser):
    """Like the ZWO EAF: a move goes on to its target when the command is cancelled,
    and a new move is refused until it gets there."""

    def __init__(self, position: int) -> None:
        super().__init__(position)
        self.travel: asyncio.Task[None] | None = None
        self.refused = 0
        self.underway = asyncio.Event()
        """Set when the fourth move starts: the sweep is under way."""

    @property
    def moving(self) -> bool:
        return self.travel is not None and not self.travel.done()

    async def move_to(self, position: int) -> None:
        if self.moving:
            self.refused += 1
            raise DeviceError("ZWO EAF.ABS_FOCUS_POSITION failed: Error: 5")

        async def go() -> None:
            await asyncio.sleep(0.05)
            await FakeFocuser.move_to(self, position)

        self.travel = asyncio.get_running_loop().create_task(go())
        if len(self.moves) >= 3:
            self.underway.set()
        await asyncio.shield(self.travel)


class FakeFocusers:
    def __init__(self, focuser: FakeFocuser) -> None:
        self.device = focuser
        self.config = FocuserConfig()

    def focuser(self) -> FakeFocuser:
        return self.device

    def backlash(self) -> FocuserConfig:
        return self.config

    def set_calibration(self, calibration: FocuserCalibration) -> None:
        self.config = self.config.model_copy(
            update={"calibration": calibration, "overshoot": calibration.overshoot}
        )


class FakeCamera:
    """Frames whose HFR is ``curve`` at the focuser's optical position."""

    def __init__(self, focuser: FakeFocuser, jobs: JobManager) -> None:
        self.focuser = focuser
        self.jobs = jobs
        self.curve: Callable[[int], float] = CURVE
        self.stars: Callable[[int], int] = lambda _: 40
        self.taken: list[int] = []
        self.gate: asyncio.Event | None = None

    def camera(self, role: Role) -> object:
        return object()

    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot:
        assert self.jobs.holder(role.value) == context.id
        assert frame_type is FrameType.LIGHT
        if self.gate is not None:
            await self.gate.wait()
        await asyncio.sleep(0)
        optical = self.focuser.optical
        self.taken.append(optical)
        return Shot(Path(str(optical)), 0, FrameType.LIGHT, datetime.now(UTC), seconds, None)

    async def measure(self, shot: Shot, *, discard: bool = True) -> StarMetrics:
        await asyncio.sleep(0)
        position = int(shot.path.name)
        stars = self.stars(position)
        return StarMetrics(stars, round(self.curve(position), 3) if stars else None, 0.0)
