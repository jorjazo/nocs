"""Autofocus runs against a fake rig: a focuser with backlash and a camera whose stars
follow a known V-curve."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from focusrig import CURVE, EafLikeFocuser, FakeCamera, FakeFocuser, FakeFocusers, SlackFocuser

import nocs.focus.autofocus
from nocs.api.schemas import AutofocusState
from nocs.equipment import Role
from nocs.equipment.profiles import FocusSweep
from nocs.focus.autofocus import AutofocusOptions, AutofocusService
from nocs.focus.curve import Hyperbola
from nocs.focus.focusers import FocuserConfig
from nocs.focus.sweep import Direction
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, StateStore
from nocs.storage import FocusRun


@pytest.fixture(autouse=True)
def quick_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nocs.focus.autofocus, "SETTLE_INTERVAL", 0.01)


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


def seeing_worsens(by: float, after: int) -> Callable[[int], float]:
    """The curve, with every frame after the first ``after`` ``by`` times larger."""
    frames = 0

    def curve(position: int) -> float:
        nonlocal frames
        frames += 1
        return CURVE(position) * (by if frames > after else 1)

    return curve


async def test_a_worse_last_frame_restores_the_start() -> None:
    rig = Rig(start=10150)
    rig.camera.curve = seeing_worsens(1.4, after=10)  # the first frame and the sweep's 9
    job, state = await rig.focus()
    assert job["state"] == "failed"
    assert state["problem"] == "worse"
    assert state["detail"].startswith("HFR 2.80 at 10000")
    assert rig.focuser.position == 10150


async def test_a_missed_focus_is_approached_again_with_twice_the_overshoot() -> None:
    # As on the GT81 (2026-11-12): the move to the best focus falls short of the backlash
    # and leaves the optics 150 steps out. In a dead band the sweep starts with the same
    # shortfall: two points, too few to fail as backlash.
    rig = Rig(start=10150, focuser=SlackFocuser(10150, slack=550))
    rig.camera.curve = Hyperbola(a=2.0, b=100, c=10000)
    job, state = await rig.focus(step=100, overshoot=400)
    assert job["state"] == "succeeded", job
    best = state["position"]
    assert rig.focuser.moves[-4:] == [best - 400, best, best - 800, best]
    assert rig.focuser.optical == best  # the gears push the optics there at last
    assert best == pytest.approx(10000, abs=80)  # the sweep's two short points skew the fit
    assert state["hfr"] < 1.5 * state["fit"]["a"]
    assert state["suggested_overshoot"] == 800
    assert rig.runs[-1].hfr == state["hfr"]


async def test_a_focus_missed_twice_fails_and_goes_back() -> None:
    rig = Rig(start=10150)
    rig.camera.curve = seeing_worsens(3, after=10)
    job, state = await rig.focus()
    assert job["state"] == "failed"
    assert state["problem"] == "missed"
    assert state["detail"] == (
        "HFR 6.00 at 10000 against 2.00 at the curve's best, also after approaching it"
        " again past 400 steps"
    )
    assert state["suggested_overshoot"] is None
    assert rig.focuser.position == 10150


async def test_a_failed_run_goes_back_past_its_backlash() -> None:
    rig = Rig(start=10150, focuser=SlackFocuser(10150, slack=780))
    rig.camera.stars = lambda p: 40 if abs(p - 10150) < 300 else 2
    _, state = await rig.focus(overshoot=400)
    assert state["problem"] == "too_few_stars"
    assert rig.focuser.position == 10150
    assert rig.focuser.optical == 10150  # twice the overshoot: the gears pushed it there


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
