"""What blocks each step of Tonight's checklist (ADR 0041)."""

import asyncio
from typing import Any

import pytest

from nocs.api.schemas import PreparationState
from nocs.devices import Location
from nocs.equipment import Role
from nocs.preparation import Facts, PreparationService, Reason, Step, blockers
from nocs.solving import Failure, SolveError
from nocs.state import StateStore

SITE = Location(-30.0277, -70.6733, 700)
EVERYTHING = {role: "ready" for role in Role}


def facts(**changes: Any) -> Facts:
    """A rig where every step can run, but for ``changes``."""
    values: dict[str, Any] = {
        "roles": dict(EVERYTHING),
        "connected": True,
        "site": True,
        "solver": None,
        "parked": False,
        "phd2": True,
    }
    return Facts(**(values | changes))


def reasons(step: Step, f: Facts) -> list[tuple[Reason, Role | None]]:
    return [(b.reason, b.role) for b in blockers(step, f)]


@pytest.mark.parametrize("step", list(Step))
def test_every_step_can_run_on_a_ready_rig(step: Step) -> None:
    assert blockers(step, facts()) == []


def test_before_connecting_the_profile_is_the_one_blocker_for_devices() -> None:
    f = facts(roles=dict.fromkeys(EVERYTHING, "disconnected"), connected=False)
    for step in Step:
        assert reasons(step, f) == [(Reason.NOT_CONNECTED, None)]


def test_a_device_not_ready_once_connected_is_named() -> None:
    f = facts(roles=EVERYTHING | {Role.MOUNT: "error"})
    assert reasons(Step.POLAR_ALIGN, f) == [(Reason.NOT_CONNECTED, Role.MOUNT)]
    assert reasons(Step.GUIDE, f) == [(Reason.NOT_CONNECTED, Role.MOUNT)]
    assert reasons(Step.FOCUS, f) == []


def test_polar_alignment_needs_the_site_and_no_other_step_does() -> None:
    f = facts(site=False)
    assert reasons(Step.POLAR_ALIGN, f) == [(Reason.NO_SITE, None)]
    assert "if only roughly" in blockers(Step.POLAR_ALIGN, f)[0].message
    for step in (Step.FOCUS, Step.FRAME, Step.GUIDE):
        assert blockers(step, f) == []


def test_the_site_is_reported_even_before_connecting() -> None:
    f = facts(roles={}, connected=False, site=False)
    assert reasons(Step.POLAR_ALIGN, f) == [(Reason.NOT_CONNECTED, None), (Reason.NO_SITE, None)]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [(Failure.UNAVAILABLE, Reason.NO_SOLVER), (Failure.NO_DATABASE, Reason.NO_DATABASE)],
)
def test_solving_steps_need_the_solver(failure: Failure, reason: Reason) -> None:
    f = facts(solver=SolveError("no", failure))
    assert reasons(Step.POLAR_ALIGN, f) == [(reason, None)]
    assert reasons(Step.FRAME, f) == [(reason, None)]
    assert blockers(Step.FOCUS, f) == []
    assert blockers(Step.GUIDE, f) == []


def test_a_parked_mount_blocks_what_moves_it() -> None:
    f = facts(parked=True)
    assert reasons(Step.POLAR_ALIGN, f) == [(Reason.PARKED, None)]
    assert reasons(Step.FRAME, f) == [(Reason.PARKED, None)]
    assert reasons(Step.GUIDE, f) == [(Reason.PARKED, None)]
    assert blockers(Step.FOCUS, f) == []


def test_guiding_needs_phd2() -> None:
    assert reasons(Step.GUIDE, facts(phd2=False)) == [(Reason.NO_PHD2, None)]


class FakeSolver:
    def __init__(self) -> None:
        self.available = True
        self.covers = (0.2, 3.0)
        self.asked: list[float | None] = []

    def check(self, fov: float | None) -> object:
        self.asked.append(fov)
        if not self.available:
            raise SolveError("ASTAP is not installed", Failure.UNAVAILABLE)
        if fov is not None and not self.covers[0] <= fov <= self.covers[1]:
            raise SolveError(f"no star database for a {fov:.2g}° field", Failure.NO_DATABASE)
        return self


class Box:
    def __init__(self) -> None:
        self.store = StateStore()
        self.solver = FakeSolver()
        self.site: Location | None = SITE
        self.service = PreparationService(self.store, self.solver, lambda: self.site)

    def state(self) -> PreparationState:
        return PreparationState.model_validate(self.store.get(("preparation",)))

    def connect(self, roles: list[Role]) -> None:
        with self.store.transaction():
            self.store.set(("equipment", "connection"), "connected")
            self.store.set(
                ("equipment", "devices"),
                {r.value: {"driver": "d", "device": r.value, "status": "ready"} for r in roles},
            )
            self.store.set(("guiding", "phd2"), {"connected": True})


def test_the_state_before_a_profile() -> None:
    box = Box()
    state = box.state()
    for step in Step:
        s = getattr(state, step.value)
        assert not s.applies
        assert s.blockers[0].reason == "not_connected"


def test_the_state_follows_the_rig() -> None:
    box = Box()
    box.connect([Role.MAIN_CAMERA, Role.MOUNT, Role.FOCUSER])
    box.store.set(("mount", "parked"), False)
    box.service.refresh()
    state = box.state()
    assert state.polar_align.applies
    assert state.polar_align.blockers == []
    assert state.focus.applies
    assert state.focus.blockers == []
    assert not state.guide.applies

    box.store.set(("cameras", "main_camera", "field"), {"height": 5.0})
    box.site = None
    box.service.refresh()
    state = box.state()
    assert [b.reason for b in state.polar_align.blockers] == ["no_site", "no_database"]
    assert [b.reason for b in state.frame.blockers] == ["no_database"]
    assert box.solver.asked[-1] == 5.0


async def test_the_service_follows_the_state_as_it_changes() -> None:
    box = Box()
    box.connect([Role.MAIN_CAMERA, Role.MOUNT])
    task = asyncio.create_task(box.service.run())
    try:
        await asyncio.sleep(0)
        assert box.state().polar_align.blockers == []
        box.store.set(("mount", "parked"), True)
        await asyncio.sleep(0)
        assert [b.reason for b in box.state().polar_align.blockers] == ["parked"]
        # Changes elsewhere leave it alone.
        version = box.store.version
        box.store.set(("mount", "ra"), 1.0)
        await asyncio.sleep(0)
        assert box.store.version == version + 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
