# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The plan: kept, published, counted, chosen from by the sky, run as a sequence."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner
from pydantic import ValidationError
from test_sequence_service import Rig, until

from nocs.api import create_app
from nocs.api.schemas import AppState
from nocs.clock import Clock
from nocs.config import Settings
from nocs.devices import Location
from nocs.jobs import JobManager
from nocs.plan import NightPlan, PlanService, expand
from nocs.sequence import CheckpointFile, SequenceError, SequenceStore
from nocs.sequence.model import (
    Actions,
    Center,
    Cool,
    Guide,
    Outputs,
    Schedule,
    Slew,
    Unpark,
    UntilDawn,
    Wait,
    WhileAbove,
)
from nocs.sequence.service import PLAN_ID, SequenceService
from nocs.sequence.sky import Place
from nocs.state import StateStore

DIAGUITAS = Place(Location(-30.0277, -70.6733, 700))
# 2026-11-01 02:00 UTC, 23:00 local: the SMC is high (47°), Orion has just risen (8°).
NIGHT = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
SMC = {"id": "smc", "name": "NGC 292", "object": "NGC 292", "ra": 0.8762, "dec": -72.8}
ORION = {"id": "m42", "name": "M 42", "object": "NGC 1976", "ra": 5.588, "dec": -5.39}


def line(line_id: str, count: int, done: int = 0, filter: str | None = "L") -> dict[str, Any]:
    return {"id": line_id, "filter": filter, "exposure": 60, "count": count, "done": done}


def plan_of(*targets: dict[str, Any], **actions: Any) -> NightPlan:
    return NightPlan.model_validate({"targets": list(targets), "actions": actions})


def test_a_plan_is_checked() -> None:
    with pytest.raises(ValidationError, match="share an id"):
        plan_of({**SMC, "lines": [line("a", 1)]}, {**ORION, "id": "smc"})
    with pytest.raises(ValidationError, match="share an id"):
        plan_of({**SMC, "lines": [line("a", 1)]}, {**ORION, "lines": [line("a", 1)]})
    with pytest.raises(ValidationError, match="one temperature"):
        plan_of(cooling="group")
    with pytest.raises(ValidationError):
        plan_of({**SMC, "id": "Not An Id"})
    # By default it centres each target, and checks it every 10 frames.
    assert (NightPlan().actions.center, NightPlan().actions.recenter_every) == (True, 10)


async def test_the_plan_is_kept_and_published(tmp_path: Path) -> None:
    store = StateStore()
    service = PlanService(store, tmp_path)
    assert store.snapshot()["plan"] == NightPlan().model_dump(mode="json")
    plan = plan_of({**SMC, "lines": [line("a", 10)]})
    await service.put(plan)
    assert NightPlan.model_validate(store.snapshot()["plan"]) == plan
    AppState.model_validate(store.snapshot())
    assert PlanService(StateStore(), tmp_path).plan == plan


def test_an_unreadable_plan_is_moved_aside(tmp_path: Path) -> None:
    (tmp_path / "plan.json").write_text('{"target": {"name": "SMC"}}')
    assert PlanService(StateStore(), tmp_path).plan == NightPlan()
    assert not (tmp_path / "plan.json").exists()
    assert (tmp_path / "plan.json.unreadable").read_text() == '{"target": {"name": "SMC"}}'


async def test_the_server_counts_the_frames(tmp_path: Path) -> None:
    service = PlanService(StateStore(), tmp_path, place=lambda: DIAGUITAS)
    await service.put(plan_of({**SMC, "lines": [line("a", 3), line("b", 2, filter="R")]}))
    choice = service.choose(NIGHT, ())
    assert choice is not None
    await service.taken(choice, 1)
    assert [ln.done for ln in service.plan.targets[0].lines] == [0, 1]
    # A client's counts are not taken over; a new line starts at none.
    edited = plan_of({**SMC, "lines": [line("a", 3, done=7), line("b", 2), line("c", 1)]})
    await service.put(edited)
    assert [ln.done for ln in service.plan.targets[0].lines] == [0, 1, 0]
    # Read back after a restart, and what is left is what a target is taken for.
    again = PlanService(StateStore(), tmp_path, place=lambda: DIAGUITAS)
    choice = again.choose(NIGHT, ())
    assert choice is not None
    assert [(r.filter, r.count) for r in choice.rows] == [("L", 3), ("L", 1), ("L", 1)]
    assert choice.done == [0, 1, 0]
    await again.reset("smc")
    assert [ln.done for ln in again.plan.targets[0].lines] == [0, 0, 0]
    with pytest.raises(KeyError):
        await again.reset("nope")


async def test_the_first_target_up_with_frames_left_is_chosen(tmp_path: Path) -> None:
    service = PlanService(StateStore(), tmp_path, place=lambda: DIAGUITAS)
    # Orion first in priority, but under 30° at 23:00: the SMC is taken.
    await service.put(plan_of({**ORION, "lines": [line("o", 5)]}, {**SMC, "lines": [line("s", 5)]}))
    assert _chosen(service, NIGHT) == "smc"
    # Later Orion is high: it comes first.
    assert _chosen(service, datetime(2026, 11, 1, 7, 0, tzinfo=UTC)) == "m42"
    assert service.choose(datetime(2026, 11, 1, 7, 0, tzinfo=UTC), {"m42"}) is not None
    # A lower minimum takes Orion at once.
    await service.put(
        plan_of(
            {**ORION, "lines": [line("o", 5)]}, {**SMC, "lines": [line("s", 5)]}, min_altitude=5
        )
    )
    assert _chosen(service, NIGHT) == "m42"
    assert _chosen(service, NIGHT, {"m42"}) == "smc"
    assert _chosen(service, NIGHT, {"m42", "smc"}) is None
    assert service.pending()


async def test_a_target_without_frames_left_is_not_chosen(tmp_path: Path) -> None:
    service = PlanService(StateStore(), tmp_path, place=lambda: DIAGUITAS)
    await service.put(plan_of({**SMC, "lines": [line("a", 1)]}, {**ORION, "lines": []}))
    choice = service.choose(NIGHT, ())
    assert choice is not None
    await service.taken(choice, 0)
    assert service.choose(NIGHT, ()) is None
    assert not service.pending()


def _chosen(service: PlanService, when: datetime, skipped: set[str] | None = None) -> str | None:
    choice = service.choose(when, skipped or set())
    return choice.key if choice is not None else None


async def test_while_it_runs_only_its_targets_change(tmp_path: Path) -> None:
    service = PlanService(StateStore(), tmp_path, place=lambda: DIAGUITAS)
    await service.put(plan_of({**SMC, "lines": [line("a", 1)]}))
    await service.put(plan_of({**SMC, "lines": [line("a", 2)]}, ORION, guide=True), running=True)
    assert [t.id for t in service.plan.targets] == ["smc", "m42"]
    assert not service.plan.actions.guide
    # The target taken is as chosen until it changes, is done or leaves the plan.
    choice = service.choose(NIGHT, ())
    assert choice is not None
    assert service.unchanged(choice)
    await service.put(plan_of({**SMC, "lines": [line("a", 3)]}))
    assert not service.unchanged(choice)
    await service.put(plan_of(ORION))
    assert not service.unchanged(choice)
    with pytest.raises(ValueError, match="site"):
        PlanService(StateStore(), tmp_path).choose(NIGHT, ())


def test_the_plan_runs_as_a_sequence() -> None:
    plan = NightPlan(
        actions=Actions(guide=True, cooling="global", temperature=-10, min_altitude=25),
        start_outputs=["dc:2"],
    )
    sequence = expand(plan)
    assert sequence.start.children == [
        Outputs(outputs=["dc:2"], on=True),
        Cool(temperature=-10),
        Unpark(),
    ]
    assert sequence.targets.conditions == [UntilDawn()]
    wait, schedule = sequence.targets.children
    assert wait == Wait(dusk="astronomical")
    assert isinstance(schedule, Schedule)
    assert (schedule.every, schedule.focus_first) == (10, True)
    assert schedule.each.conditions == [WhileAbove(altitude=25)]
    assert schedule.each.children == [Slew(), Guide(on=True)]
    # Above the horizon at least, without a minimum.
    bare = expand(NightPlan(actions=Actions(min_altitude=None))).targets.children[1]
    assert isinstance(bare, Schedule)
    assert bare.each.conditions == [WhileAbove(altitude=0)]
    assert [t.kind for t in schedule.each.triggers] == ["autofocus", "flip"]
    assert [c.kind for c in sequence.end.children] == ["guide", "park", "warm"]
    centred = expand(NightPlan()).targets.children[1]
    assert isinstance(centred, Schedule)
    assert centred.each.children == [Center()]
    assert [t.kind for t in centred.each.triggers] == ["autofocus", "flip", "recenter"]


# -- on the rig (the sequence service's fakes) ------------------------------------------


def always_up(**actions: Any) -> NightPlan:
    """The SMC never sets at Diaguitas: the plan runs whenever the test does."""
    settings = {
        "start_at_dusk": False,
        "until_dawn": False,
        "min_altitude": None,
        "center": False,
        "flip": False,
        "focus": None,
        **actions,
    }
    return plan_of({**SMC, "lines": [line("a", 2)]}, **settings)


async def service_on(tmp_path: Path) -> tuple[SequenceService, PlanService, Rig, JobManager]:
    store = StateStore()
    jobs = JobManager(store)
    rig = Rig(jobs, store)
    plan = PlanService(store, tmp_path, place=lambda: DIAGUITAS)
    service = SequenceService(
        store,
        jobs,
        SequenceStore(tmp_path),
        CheckpointFile(tmp_path / "data" / "sequence" / "run.json"),
        Clock(store),
        rig.parts,
        place=lambda: DIAGUITAS,
        scheduler=plan,
    )
    return service, plan, rig, jobs


async def test_a_plan_runs_on_the_rig_and_counts_its_frames(tmp_path: Path) -> None:
    service, plan, rig, jobs = await service_on(tmp_path)
    await plan.put(always_up())
    job = service.start_plan(expand(plan.plan))
    assert service.running_plan
    await jobs.wait(job)
    assert [c for c in rig.calls if c.startswith(("slew", "frame", "park"))] == [
        "slew 0.8762 -72.8",
        "frame NGC 292 60",
        "frame NGC 292 60",
        "park",
    ]
    assert plan.plan.targets[0].lines[0].done == 2
    # Kept among the sequences, never listed nor written with them.
    assert PLAN_ID not in service.all()
    assert service.get(PLAN_ID) is None
    with pytest.raises(SequenceError):
        service.put(PLAN_ID, expand(plan.plan))


async def test_a_plan_stopped_leaves_the_rig_as_it_is(tmp_path: Path) -> None:
    service, plan, rig, jobs = await service_on(tmp_path)
    await plan.put(always_up())
    job = service.start_plan(expand(plan.plan))
    await until(lambda: any(c.startswith("frame") for c in rig.calls))
    service.stop()  # even asked to run the end
    await jobs.wait(job)
    assert "park" not in rig.calls


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        indi_host="127.0.0.1",
        indi_port=9,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        yield client


def test_the_api_keeps_and_starts_the_plan(client: TestClient) -> None:
    empty = client.get("/api/plan").json()
    assert empty["targets"] == []
    assert client.post("/api/plan/start").status_code == 422  # nothing to take
    body = plan_of({**SMC, "lines": [line("a", 3, done=9)]}).model_dump(mode="json")
    assert client.put("/api/plan", json=body).status_code == 204
    state = client.get("/api/state").json()["state"]["plan"]
    assert state["targets"][0]["lines"][0]["done"] == 0
    assert client.put("/api/plan", json={"targets": [{"id": "x"}]}).status_code == 422
    assert client.post("/api/plan/targets/smc/reset").status_code == 204
    assert client.post("/api/plan/targets/nope/reset").status_code == 404
    # No site, no camera: refused at once, not in a job.
    assert client.post("/api/plan/start").status_code in (422, 503)
    assert client.get("/api/sequences").json() == {}
    assert client.put("/api/sequences/plan", json={"name": "x"}).status_code == 422
