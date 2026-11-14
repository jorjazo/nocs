"""Focuser calibration against the fake rig: focusers with a dead band, a V-curve camera."""

from collections.abc import Callable
from typing import Any

import pytest
from focusrig import CURVE, FakeCamera, FakeFocuser, FakeFocusers, SlackFocuser

import nocs.focus.autofocus
from nocs.api.schemas import FocusCalibrationState, FocuserCalibrationRecord
from nocs.focus.autofocus import AutofocusService
from nocs.focus.backlash import Ruler, focus_zone, microns_per_step, overshoot_for, round_up
from nocs.focus.calibration import FocuserCalibrationService, Scale
from nocs.jobs import JobManager
from nocs.state import StateStore

STEP = 200


@pytest.fixture(autouse=True)
def quick_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nocs.focus.autofocus, "SETTLE_INTERVAL", 0.01)


class VaryingSlack(SlackFocuser):
    """A dead band whose width ``slack_now`` says, move by move."""

    def __init__(self, position: int, slack_now: Callable[[], int]) -> None:
        super().__init__(position, slack=slack_now())
        self.slack_now = slack_now

    async def move_to(self, position: int) -> None:
        self.slack = self.slack_now()
        await super().move_to(position)


class Rig:
    def __init__(self, focuser: FakeFocuser) -> None:
        self.store = StateStore()
        self.jobs = JobManager(self.store)
        self.focuser = focuser
        self.camera = FakeCamera(focuser, self.jobs)
        self.focusers = FakeFocusers(focuser)
        self.autofocus = AutofocusService(self.store, self.jobs, self.focusers, self.camera)
        self.service = FocuserCalibrationService(
            self.store,
            self.jobs,
            self.focusers,
            self.camera,
            self.autofocus,
            scale=lambda: Scale(focal_ratio=4.74, pixel_size=3.76),
            profile=lambda: "william",
        )

    async def calibrate(self) -> tuple[dict[str, Any], dict[str, Any]]:
        job_id = self.service.start(self.service.options(step=STEP))
        await self.jobs.wait(job_id)
        job = self.store.get(("jobs", job_id))
        state = self.store.get(("focus_calibration",))
        assert isinstance(job, dict)
        assert isinstance(state, dict)
        FocusCalibrationState.model_validate(state)
        return job, state

    def phase(self) -> object:
        state = self.store.get(("focus_calibration",))
        return state.get("phase") if isinstance(state, dict) else None


async def test_a_focuser_without_backlash() -> None:
    rig = Rig(FakeFocuser(10150))
    job, state = await rig.calibrate()
    assert job["state"] == "succeeded", job
    assert state["best"]["position"] == pytest.approx(10000, abs=10)
    assert [r["towards"] for r in state["reversals"]] == ["inward", "outward"] * 2
    assert all(abs(r["lost"]) < 30 and not r["slip"] for r in state["reversals"])
    assert state["overshoot"] == STEP  # nothing to take up: one sweep step
    assert [t["ok"] for t in state["trips"]] == [True] * 3
    assert rig.focuser.position == state["best"]["position"]
    assert state["hfr"] == pytest.approx(2.0, abs=0.05)
    calibration = rig.focusers.config.calibration
    assert calibration is not None
    assert (calibration.profile, calibration.overshoot) == ("william", STEP)
    assert rig.focusers.config.overshoot == STEP
    assert len(calibration.inward) == len(calibration.outward) == 2
    # The curve's asymptote: 2 px per 300 steps at f/4.74 and 3.76 µm.
    microns = calibration.microns_per_step
    assert microns == pytest.approx(microns_per_step(2.0, 300, 4.74, 3.76), rel=0.05)
    assert microns is not None
    assert calibration.focus_zone == focus_zone(4.74, microns)
    FocuserCalibrationRecord.model_validate(calibration.model_dump(mode="json"))


async def test_a_dead_band_is_measured_both_ways() -> None:
    rig = Rig(SlackFocuser(10150, slack=780))
    job, state = await rig.calibrate()
    assert job["state"] == "succeeded", job
    lost = [r["lost"] for r in state["reversals"]]
    assert lost == pytest.approx([780] * 4, abs=25)
    assert state["overshoot"] == overshoot_for(lost, STEP)
    assert state["overshoot"] >= 1000
    assert all(t["ok"] for t in state["trips"])
    # Back at the best focus with the gears pushing the optics there.
    assert rig.focuser.optical == rig.focuser.position == state["best"]["position"]
    assert rig.focusers.config.overshoot == state["overshoot"]


async def test_a_backlash_that_grows_is_not_repeatable() -> None:
    # 300 steps while measured, 1500 in the round trips: every overshoot falls short.
    rig = Rig(FakeFocuser(0))
    rig.focuser = rig.camera.focuser = rig.focusers.device = VaryingSlack(
        10150, lambda: 1500 if rig.phase() in ("round_trips", "restoring") else 300
    )
    job, state = await rig.calibrate()
    assert job["state"] == "failed"
    assert state["problem"] == "not_repeatable", state["detail"]
    tried = [t["overshoot"] for t in state["trips"] if not t["ok"]]
    assert len(tried) == 3
    assert 390 <= tried[0] <= 450  # 1.3 times the ~300 measured
    assert tried[1:] == [round_up(tried[0] * 1.5), round_up(round_up(tried[0] * 1.5) * 1.5)]
    assert rig.focusers.config.calibration is None
    # Going back with twice the last overshoot takes the 1500 steps up.
    assert rig.focuser.position == state["best"]["position"]
    assert rig.focuser.optical == rig.focuser.position


async def test_a_failed_autofocus_fails_the_calibration() -> None:
    rig = Rig(FakeFocuser(10150))
    rig.camera.stars = lambda _: 3
    job, state = await rig.calibrate()
    assert job["state"] == "failed"
    assert state["problem"] == "autofocus"
    assert state["detail"] == "autofocus: 3 stars where the focuser is (10 needed)"
    assert state["best"] is None
    assert rig.focuser.position == 10150


async def test_driver_compensation_is_turned_off_and_the_calibration_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    focuser = FakeFocuser(10150)
    focuser.driver_backlash = 120
    rig = Rig(focuser)
    job, state = await rig.calibrate()
    assert job["state"] == "succeeded", job
    assert focuser.driver_backlash is None
    assert state["driver_backlash"] == 120
    assert "compensated 120 steps" in caplog.text


def test_the_autofocus_overshoot_is_large() -> None:
    rig = Rig(FakeFocuser(10150))
    assert rig.service.options(step=STEP).overshoot == 2000
    rig.focusers.config = rig.focusers.config.model_copy(update={"overshoot": 900})
    assert rig.service.options(step=STEP).overshoot == 2700


def test_ruler_reads_positions_on_an_arm() -> None:
    positions = [10360, 10588, 10816, 11044, 11272, 11500]
    ruler = Ruler.fit(positions, [CURVE(p) for p in positions])
    assert ruler.noise < 5
    assert ruler.position(CURVE(10700)) == pytest.approx(10700, abs=5)


def test_round_up() -> None:
    assert [round_up(v) for v in (0, 87, 1014, 1035, 99.2)] == [0, 87, 1100, 1100, 100]


def test_the_scale_of_the_gt81() -> None:
    # rc5's night: a 1.52, b 36 steps at f/4.74 with 3.76 µm pixels.
    microns = microns_per_step(1.52, 36.3, 4.74, 3.76)
    assert microns == pytest.approx(2.1, abs=0.1)
    assert focus_zone(4.74, microns) == pytest.approx(28, abs=2)
