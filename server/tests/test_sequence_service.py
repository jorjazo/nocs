# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A sequence as a job: its locks, pausing, its state, its checkpoint (ADR 0031)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import anyio.lowlevel
import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api.app import create_app
from nocs.clock import Clock
from nocs.config import Settings
from nocs.devices import Coordinates, DeviceError, FrameType
from nocs.equipment import Role
from nocs.focus.autofocus import AutofocusOptions
from nocs.imaging.capture import CameraSettings, Captured
from nocs.jobs import JobContext, JobManager, ResourceBusyError
from nocs.sequence import CheckpointFile, Container, ExposurePlan, PlanRow, Sequence, SequenceStore
from nocs.sequence.model import Autofocus, Cool, Guide, Outputs, Park, Slew, Target, Unpark, Warm
from nocs.sequence.rig import Parts
from nocs.sequence.service import SequenceBusyError, SequenceService
from nocs.state import Json, StateStore

M42 = Target(name="M 42", ra=5.588, dec=-5.39)


class Camera:
    can_cool = True
    gain: float | None = 100
    offset: float | None = 10
    binning = (1, 1)

    def __init__(self) -> None:
        self.temperature: float | None = 20.0


class Rig:
    """Every service a sequence drives, recording what it is asked."""

    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs
        self.calls: list[str] = []
        self.sensor = Camera()
        self.gate: anyio.Event | None = None
        self.guiding = False
        self.under: list[str | None] = []
        self.fail_park = False

    # capture
    def camera(self, role: Role) -> Camera:
        return self.sensor

    async def configure(
        self, role: Role, settings: CameraSettings, *, job: str | None = None
    ) -> None:
        self.calls.append(f"configure gain={settings.gain}")

    async def set_cooling(
        self, role: Role, on: bool, target: float | None = None, ramp: float | None = None
    ) -> None:
        self.calls.append(f"cooling {on} {target}")
        if on and target is not None:
            self.sensor.temperature = target

    async def capture(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        *,
        save: bool,
        target: str | None = None,
    ) -> Captured:
        assert self.jobs.holder(role.value) == context.id
        if self.gate is not None:
            await self.gate.wait()
        await anyio.lowlevel.checkpoint()
        self.calls.append(f"frame {target} {seconds:g}")
        return Captured({}, 40, 2.1)

    # filters
    async def select_in(self, context: JobContext, filter: int | str) -> Json:
        self.calls.append(f"filter {filter}")
        return None

    # focus
    def options(self) -> AutofocusOptions:
        return AutofocusOptions(step=100)

    async def run(self, context: JobContext, options: AutofocusOptions) -> dict[str, Json]:
        self.calls.append("autofocus")
        return {}

    # mount
    async def unpark(self, *, job: str | None = None) -> None:
        self.calls.append("unpark")

    async def park_in(self, context: JobContext) -> None:
        if self.fail_park:
            raise DeviceError("cannot park")
        self.calls.append("park")

    async def set_tracking(
        self, on: bool | None, mode: str | None = None, *, job: str | None = None
    ) -> None:
        self.calls.append(f"tracking {on}")

    async def slew(
        self, context: JobContext, ra: float, dec: float, *, force: bool = False
    ) -> Coordinates:
        self.calls.append(f"slew {ra:g} {dec:g}")
        return Coordinates(ra, dec)

    # guiding
    async def start(self, context: JobContext) -> Json:
        self.calls.append("guide")
        self.guiding = True
        return None

    async def stop(self) -> None:
        self.calls.append("stop guiding")
        self.guiding = False

    def guide_under(self, job_id: str | None) -> None:
        self.under.append(job_id)

    # power
    async def set_output(
        self, output_id: str, *, on: bool | None = None, job: str | None = None
    ) -> None:
        self.calls.append(f"output {output_id} {on}")

    def parts(self) -> Parts:
        return Parts(capture=self, filters=self, focus=self, mount=self, guiding=self, power=self)


def lrgb(**end: object) -> Sequence:
    plan = ExposurePlan(rows=[PlanRow(filter="L", exposure=1, count=2)])
    return Sequence(
        name="tonight",
        start=Container(children=[Cool(temperature=-10), Unpark(), Guide(on=True)]),
        targets=Container(children=[Container(target=M42, children=[Slew(), Autofocus(), plan])]),
        end=Container(
            children=[Guide(on=False), Park(), Warm(), Outputs(outputs=["dc:1"], on=False)]
        ),
        **end,  # pyright: ignore[reportArgumentType]
    )


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(5000):
        if condition():
            return
        await anyio.sleep(0.001)
    raise AssertionError("never happened")


@pytest.fixture
def setup(tmp_path: Path) -> tuple[SequenceService, Rig, StateStore, JobManager, CheckpointFile]:
    store = StateStore()
    jobs = JobManager(store)
    rig = Rig(jobs)
    checkpoint = CheckpointFile(tmp_path / "data" / "sequence" / "run.json")
    service = SequenceService(
        store,
        jobs,
        SequenceStore(tmp_path),
        checkpoint,
        Clock(store),
        rig.parts,
    )
    return service, rig, store, jobs, checkpoint


async def test_a_sequence_runs_as_one_job_holding_the_rig(setup: Any) -> None:
    service, rig, store, jobs, checkpoint = setup
    service.put("m42", lrgb())
    job = service.start("m42")
    assert {jobs.holder(r) for r in ("main_camera", "filter_wheel", "focuser", "mount")} == {job}
    with pytest.raises(SequenceBusyError):
        service.start("m42")
    with pytest.raises(SequenceBusyError):
        service.put("m42", lrgb())
    with pytest.raises(ResourceBusyError, match=r"mount is busy \(sequence"):
        jobs.check_free(["mount"])
    await jobs.wait(job)

    assert rig.calls == [
        "cooling True -10.0",
        "unpark",
        "guide",
        "stop guiding",  # before the slew
        "slew 5.588 -5.39",
        "autofocus",
        "filter L",
        "frame M 42 1",
        "frame M 42 1",
        "stop guiding",
        "park",
        "cooling True 15.0",
        "cooling False None",
        "output dc:1 False",
    ]
    state = store.get(("jobs", job))
    assert state["state"] == "succeeded"
    sequence = store.get(("sequence",))
    assert sequence["run"]["outcome"] == "completed"
    assert sequence["run"]["plans"]["targets.0.2"]["rows"][0]["done"] == 2
    assert [e["kind"] for e in sequence["events"]][:2] == ["started", "action"]
    assert sequence["events"][-1]["kind"] == "ended"
    assert checkpoint.load() is None
    assert jobs.holder("mount") is None
    assert rig.under[-1] is None


async def test_a_paused_sequence_lends_the_rig_back(setup: Any) -> None:
    service, rig, store, jobs, checkpoint = setup
    service.put("m42", lrgb())
    rig.gate = anyio.Event()
    job = service.start("m42")
    await until(lambda: bool(rig.calls) and rig.calls[-1] == "filter L")
    service.pause()
    assert store.get(("sequence", "run", "state")) == "pausing"
    rig.gate.set()
    await until(lambda: store.get(("sequence", "run", "state")) == "paused")
    assert jobs.holder("mount") is None
    assert rig.under[-1] is None  # guiding's own hold while paused
    saved = checkpoint.load()
    assert saved is not None
    # Paused at the safe point after the filter, or after the frame that was starting.
    assert saved.plans["targets.0.2"].done[0] <= 1

    token = jobs.reserve("move", ["mount"])  # someone uses the pad meanwhile
    with pytest.raises(ResourceBusyError):
        service.resume()
    jobs.release(token)
    service.resume()
    assert jobs.holder("mount") == job
    assert rig.under[-1] == job
    await jobs.wait(job)
    assert rig.calls.count("filter L") == 2  # selected again after the pause
    assert rig.calls.count("frame M 42 1") == 2
    assert store.get(("sequence", "run", "outcome")) == "completed"


async def test_stopping_a_paused_sequence_takes_the_rig_back_for_the_end(setup: Any) -> None:
    service, rig, store, jobs, _ = setup
    service.put("m42", lrgb())
    rig.gate = anyio.Event()
    job = service.start("m42")
    await until(lambda: bool(rig.calls) and rig.calls[-1] == "filter L")
    service.pause(now=True)
    await until(lambda: store.get(("sequence", "run", "state")) == "paused")
    service.stop()
    await jobs.wait(job)
    assert not any(c.startswith("frame") for c in rig.calls)
    assert rig.calls[-4:] == [
        "park",
        "cooling True 15.0",
        "cooling False None",
        "output dc:1 False",
    ]
    assert store.get(("sequence", "run", "outcome")) == "stopped"


async def test_a_failed_sequence_ends_and_fails_its_job(setup: Any) -> None:
    service, rig, store, jobs, _ = setup
    service.put("m42", lrgb())
    rig.fail_park = True

    async def broken(context: JobContext, ra: float, dec: float, *, force: bool = False) -> Any:
        raise ValueError("the target is below the horizon")

    rig.slew = broken  # pyright: ignore[reportAttributeAccessIssue]
    job = service.start("m42")
    await jobs.wait(job)
    assert store.get(("jobs", job, "state")) == "failed"
    assert store.get(("jobs", job, "error")) == "the target is below the horizon"
    assert "tracking False" in rig.calls  # it could not park: at least it stopped
    with pytest.raises(SequenceBusyError):
        service.pause()


async def test_cooling_waits_for_the_sensor(setup: Any) -> None:
    _, rig, _, jobs, _ = setup
    temperatures = iter([5.0, -5.0, -9.5])

    async def slow_cooling(
        role: Role, on: bool, target: float | None = None, ramp: float | None = None
    ) -> None:
        rig.calls.append(f"cooling {on} {target}")

    rig.set_cooling = slow_cooling  # pyright: ignore[reportAttributeAccessIssue]
    rig.sensor.temperature = 20.0
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        rig.sensor.temperature = next(temperatures)

    from nocs.sequence import rig as rig_module

    executor = rig_module.RigExecutor(
        JobContext(jobs, "job"), jobs, StateStore(), rig.parts(), sleep=sleep
    )
    await executor.action(Cool(temperature=-10), None)
    assert sleeps == [5.0, 5.0, 5.0]


def test_the_api_keeps_and_starts_sequences(tmp_path: Path) -> None:
    settings = Settings(
        indi_host="127.0.0.1",
        indi_port=1,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        body = lrgb().model_dump(mode="json")
        assert client.put("/api/sequences/m42", json=body).status_code == 204
        assert client.put("/api/sequences/Bad Id", json=body).status_code == 422
        assert client.put("/api/sequences/x", json={"name": ""}).status_code == 422
        assert client.get("/api/sequences").json() == {"m42": body}
        assert client.get("/api/sequences/m42").json() == body
        assert client.get("/api/sequences/nope").status_code == 404
        # No camera: refused at once, not in a job.
        assert client.post("/api/sequences/m42/start").status_code == 503
        assert client.post("/api/sequences/nope/start").status_code == 404
        assert client.post("/api/sequence/pause", json={}).status_code == 409
        state = client.get("/api/state").json()["state"]
        assert state["sequence"] == {"run": None, "events": []}
        assert client.delete("/api/sequences/m42").status_code == 204
        assert client.delete("/api/sequences/m42").status_code == 404
