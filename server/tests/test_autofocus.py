"""Autofocus runs against a fake rig: a focuser with backlash and a camera whose stars
follow a known V-curve."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import nocs.focus.autofocus
from nocs.api.schemas import AutofocusState
from nocs.devices import DeviceError, FrameType
from nocs.equipment import Role
from nocs.equipment.profiles import FocusSweep
from nocs.focus.autofocus import AutofocusOptions, AutofocusService
from nocs.focus.curve import Hyperbola
from nocs.focus.focusers import FocuserConfig
from nocs.focus.sweep import Direction
from nocs.imaging import Shot, StarMetrics
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, StateStore
from nocs.storage import FocusRun

CURVE = Hyperbola(a=2.0, b=300, c=10000)


@pytest.fixture(autouse=True)
def quick_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nocs.focus.autofocus, "SETTLE_INTERVAL", 0.01)


class FakeFocuser:
    """Positions as reported; the optics lag ``backlash`` steps after a move inward."""

    def __init__(self, position: int, backlash: int = 0, maximum: int = 60000) -> None:
        self._position = position
        self.backlash = backlash
        self.lagging = False
        self.moves: list[int] = []
        self.maximum = maximum

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

    async def abort(self) -> None:
        pass


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


class Rig:
    def __init__(self, start: int, backlash: int = 0, focuser: FakeFocuser | None = None) -> None:
        self.store = StateStore()
        self.jobs = JobManager(self.store)
        self.focuser = focuser or FakeFocuser(start, backlash)
        self.camera = FakeCamera(self.focuser, self.jobs)
        self.focusers = FakeFocusers(self.focuser)
        self.sweep: FocusSweep | None = None
        self.runs: list[FocusRun] = []

        async def record(run: FocusRun) -> None:
            self.runs.append(run)

        self.service = AutofocusService(
            self.store,
            self.jobs,
            self.focusers,
            self.camera,
            sweep=lambda: self.sweep,
            profile=lambda: "lab",
            record=record,
        )

    async def focus(self, **options: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run to the end; returns the job and the autofocus state."""
        job_id = self.service.start(replace(AutofocusOptions(step=200), **options))
        await self.jobs.wait(job_id)
        return self.job(job_id), self.state()

    def job(self, job_id: str) -> dict[str, Any]:
        value = self.store.get(("jobs", job_id))
        assert isinstance(value, dict)
        return value

    def state(self) -> dict[str, Any]:
        value = self.store.get(("autofocus",))
        assert isinstance(value, dict)
        AutofocusState.model_validate(value)
        return value


async def test_focus_is_found_and_checked() -> None:
    rig = Rig(start=10150)
    job, state = await rig.focus()
    assert job["state"] == "succeeded", job
    assert state["state"] == "succeeded"
    assert state["position"] == pytest.approx(10000, abs=10)
    assert rig.focuser.position == state["position"]
    assert state["hfr"] == pytest.approx(2.0, abs=0.01)
    assert state["start_hfr"] == pytest.approx(CURVE(10150), abs=0.01)
    assert state["fit"]["r_squared"] > 0.99
    assert [p["position"] for p in state["points"]] == list(range(9350, 10951, 200))
    assert state["temperature"] == 4.5
    assert state["phase"] is None
    assert state["suggested_step"] == pytest.approx(CURVE.distance_for(5.0) / 4, abs=1)
    assert job["result"] == state


async def test_every_position_is_reached_moving_outward() -> None:
    rig = Rig(start=10150, backlash=120)
    _, state = await rig.focus(overshoot=300)
    # To the first point: past it inward, then out; the sweep outward; to the best
    # focus: past it, then out again.
    moves = rig.focuser.moves
    assert moves[:3] == [9050, 9350, 9550]
    assert moves[-2:] == [state["position"] - 300, state["position"]]
    # So the optics were never lagging when a frame was taken.
    assert rig.camera.taken[1:] == [p["position"] for p in state["points"]] + [state["position"]]


async def test_without_an_overshoot_backlash_spoils_the_sweep() -> None:
    rig = Rig(start=10150, backlash=120)
    await rig.focus(overshoot=0)
    first = rig.camera.taken[1]
    assert first == 9350 + 120  # the gears had not caught up yet


async def test_the_sweep_is_extended_until_the_curve_turns() -> None:
    rig = Rig(start=10700)
    job, state = await rig.focus()
    assert job["state"] == "succeeded", job
    positions = [p["position"] for p in state["points"]]
    assert positions[:2] == [9500, 9700]  # added below the planned 9900
    assert state["position"] == pytest.approx(10000, abs=10)


async def test_no_stars_fails_without_moving() -> None:
    rig = Rig(start=10150)
    rig.camera.stars = lambda _: 3
    job, state = await rig.focus()
    assert job["state"] == "failed"
    assert job["error"] == "3 stars where the focuser is (10 needed)"
    assert (state["state"], state["problem"]) == ("failed", "no_stars")
    assert rig.focuser.moves == [10150]  # only the move back, to where it already was
    assert rig.focuser.position == 10150


async def test_a_curve_that_never_turns_fails_and_goes_back() -> None:
    rig = Rig(start=14000)
    job, state = await rig.focus(step=100, extension=2)
    assert job["state"] == "failed"
    assert state["problem"] == "not_turning"
    assert len(state["points"]) == 11
    assert rig.focuser.position == 14000


async def test_too_few_stars_in_the_sweep() -> None:
    rig = Rig(start=10150)
    rig.camera.stars = lambda p: 40 if abs(p - 10150) < 300 else 2
    job, state = await rig.focus()
    assert state["problem"] == "too_few_stars", job
    assert rig.focuser.position == 10150


async def test_a_worse_last_frame_restores_the_start() -> None:
    rig = Rig(start=10150)
    frames = 0

    def seeing_worsens(position: int) -> float:
        nonlocal frames
        frames += 1
        return CURVE(position) * (3 if frames > 10 else 1)

    rig.camera.curve = seeing_worsens
    job, state = await rig.focus()
    assert job["state"] == "failed"
    assert state["problem"] == "worse"
    assert state["detail"].startswith("HFR 6.00 at 10000")
    assert rig.focuser.position == 10150


async def test_cancelling_goes_back_to_the_start() -> None:
    rig = Rig(start=10150)
    rig.camera.gate = gate = asyncio.Event()
    job_id = rig.service.start(AutofocusOptions(step=200))
    for _ in range(4):
        gate.set()
        await asyncio.sleep(0)
        gate.clear()
        await asyncio.sleep(0.01)
    rig.jobs.cancel(job_id)
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["state"] == "cancelled"
    state = rig.state()
    assert state["state"] == "cancelled"
    assert state["problem"] is None
    assert rig.focuser.position == 10150


async def test_cancelling_mid_move_waits_for_the_focuser_to_stop() -> None:
    focuser = EafLikeFocuser(10150)
    rig = Rig(start=10150, focuser=focuser)
    job_id = rig.service.start(AutofocusOptions(step=200))
    await focuser.underway.wait()
    rig.jobs.cancel(job_id)  # in the middle of a move
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["state"] == "cancelled"
    assert focuser.position == 10150
    assert focuser.refused == 0


async def test_run_needs_a_job_holding_the_focuser() -> None:
    rig = Rig(start=10150)

    async def other(context: JobContext) -> Json:
        await rig.service.run(context, AutofocusOptions(step=200))
        return None

    job_id = rig.jobs.start("other", [Role.MAIN_CAMERA.value], other)
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["error"] == f"job {job_id} does not hold the focuser"
    assert rig.focuser.moves == []


async def test_options_are_checked_before_the_job() -> None:
    rig = Rig(start=10150)
    with pytest.raises(ValueError, match="at least 5 points"):
        rig.service.start(AutofocusOptions(step=200, points=3))
    with pytest.raises(ValueError, match="step"):
        rig.service.start(AutofocusOptions(step=0))
    assert rig.store.get(("autofocus",)) is None
    assert rig.store.get(("jobs",)) == {}


def test_options_come_from_the_train_and_the_focuser() -> None:
    rig = Rig(start=10150)
    with pytest.raises(ValueError, match="needs a step"):
        rig.service.options()
    rig.sweep = FocusSweep(step=300, points=7, exposure=3.5)
    rig.focusers.config = FocuserConfig(direction="inward", overshoot=50)
    assert rig.service.options() == AutofocusOptions(
        step=300, points=7, exposure=3.5, frames=1, direction=Direction.INWARD, overshoot=50
    )
    given = rig.service.options(step=120, frames=2, direction=Direction.OUTWARD, overshoot=0)
    assert (given.step, given.points, given.frames, given.direction, given.overshoot) == (
        120,
        7,
        2,
        Direction.OUTWARD,
        0,
    )
    rig.sweep = None
    rig.focusers.config = FocuserConfig()
    assert rig.service.options(step=100) == AutofocusOptions(step=100)


async def test_finished_runs_are_recorded_with_the_conditions() -> None:
    rig = Rig(start=10150)
    rig.store.set(("weather",), {"temperature": 11.5})
    rig.store.set(("filter_wheel",), {"filter": "L"})
    _, state = await rig.focus()
    rig.camera.stars = lambda _: 0
    await rig.focus()
    assert state["ambient"] == 11.5
    assert state["filter"] == "L"
    good, bad = rig.runs
    assert (good.state, good.profile, good.filter) == ("succeeded", "lab", "L")
    assert good.position == 10000
    assert (good.focuser_temperature, good.ambient_temperature) == (4.5, 11.5)
    assert json.loads(good.run) == state
    assert (bad.state, bad.problem, bad.position) == ("failed", "no_stars", None)
