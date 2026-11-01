# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A sequence as a job: its locks, pausing, its state, its checkpoint (ADR 0031)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import anyio
import anyio.lowlevel
import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api.app import create_app
from nocs.clock import Clock
from nocs.config import Settings
from nocs.devices import Coordinates, DeviceError, FrameType
from nocs.devices.camera import SensorInfo
from nocs.equipment import Role
from nocs.focus.autofocus import AutofocusOptions
from nocs.guiding import Settle
from nocs.imaging.capture import CameraSettings, Captured
from nocs.jobs import JobContext, JobManager, ResourceBusyError
from nocs.pointing import CenterOptions, FrameSolve, SolveOptions
from nocs.sequence import CheckpointFile, Container, ExposurePlan, PlanRow, Sequence, SequenceStore
from nocs.sequence.model import (
    Autofocus,
    Center,
    Cool,
    Dither,
    DitherTrigger,
    Guide,
    Outputs,
    Park,
    Recenter,
    RecenterTrigger,
    Slew,
    Target,
    Unpark,
    UntilDawn,
    Warm,
)
from nocs.sequence.rig import Parts
from nocs.sequence.service import SequenceBusyError, SequenceService
from nocs.state import Json, StateStore
from nocs.storage import Session, SessionEvent

M42 = Target(name="M 42", ra=5.588, dec=-5.39)


class Camera:
    can_cool = True
    sensor = SensorInfo(6248, 4176, 3.76, 3.76, 16)
    gain: float | None = 100
    offset: float | None = 10
    binning = (1, 1)

    def __init__(self) -> None:
        self.temperature: float | None = 20.0


class Rig:
    """Every service a sequence drives, recording what it is asked."""

    def __init__(self, jobs: JobManager, store: StateStore) -> None:
        self.jobs = jobs
        self.store = store
        self.calls: list[str] = []
        self.sensor = Camera()
        self.gate: anyio.Event | None = None
        self.guiding = False
        self.under: list[str | None] = []
        self.fail_park = False
        self.taken = 0
        self.hold_from: int | None = None
        """Frames from this one on never end (nocsd is about to crash)."""
        self.drifts: list[float] = []
        """Arcminutes each pointing check finds the frame off the target."""

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
        self.taken += 1
        if self.hold_from is not None and self.taken >= self.hold_from:
            await anyio.sleep_forever()
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
        self.store.set(("guiding", "app_state"), "Guiding")
        return None

    async def stop(self) -> None:
        self.calls.append("stop guiding")
        self.guiding = False
        self.store.set(("guiding", "app_state"), "Stopped")

    def guide_under(self, job_id: str | None) -> None:
        self.under.append(job_id)

    def guide_pixels(self, main_pixels: float) -> float:
        return main_pixels / 2

    async def dither(
        self,
        context: JobContext,
        pixels: float,
        *,
        settle: Settle | None = None,
        ra_only: bool = False,
    ) -> Json:
        self.calls.append(f"dither {pixels:g}")
        return None

    # power
    async def set_output(
        self, output_id: str, *, on: bool | None = None, job: str | None = None
    ) -> None:
        self.calls.append(f"output {output_id} {on}")

    # recovery
    async def restart_driver(self, role: Role) -> None:
        self.calls.append(f"restart {role.value}")

    async def power_cycle(self, role: Role, *, job: str | None = None) -> None:
        self.calls.append(f"power cycle {role.value} for {job}")

    # centring and solving
    async def center(
        self,
        context: JobContext,
        ra: float,
        dec: float,
        options: CenterOptions,
        role: Role = Role.MAIN_CAMERA,
    ) -> dict[str, Json]:
        self.calls.append(f"center {ra:g} {dec:g} within {options.tolerance:g}'")
        return {"attempts": [{"error": {"angle": 3.0}}, {"error": {"angle": 0.4}}]}

    async def solve_frame(
        self, context: JobContext, options: SolveOptions, role: Role = Role.MAIN_CAMERA
    ) -> FrameSolve:
        drift = self.drifts.pop(0)
        self.calls.append(f"solve (sync {options.sync})")
        # Only what the sequence reads of a solve: where the frame's centre is.
        solution = SimpleNamespace(ra=M42.ra, dec=(M42.dec or 0) + drift / 60)
        return cast(FrameSolve, SimpleNamespace(result=SimpleNamespace(solution=solution)))

    def parts(self) -> Parts:
        return Parts(
            capture=self,
            filters=self,
            focus=self,
            mount=self,
            guiding=self,
            power=self,
            recovery=self,
            centering=self,
            pointing=self,
        )


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
    rig = Rig(jobs, store)
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
        "guide",  # again, after the slew stopped it
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


async def test_a_guided_sequence_dithers_every_n_frames(setup: Any) -> None:
    service, rig, _, jobs, _ = setup
    plan = ExposurePlan(rows=[PlanRow(filter="L", exposure=1, count=5)])
    every = DitherTrigger(every=2, dither=Dither(pixels=8))
    imaging = Container(target=M42, triggers=[every], children=[Slew(), Guide(on=True), plan])
    service.put("dither", Sequence(name="dither", targets=Container(children=[imaging])))
    await jobs.wait(service.start("dither"))
    taken = [c for c in rig.calls if c.startswith(("frame", "dither"))]
    # Before the 3rd and the 5th frame; in guide camera pixels.
    assert taken == ["frame M 42 1"] * 2 + ["dither 4"] + ["frame M 42 1"] * 2 + ["dither 4"] + [
        "frame M 42 1"
    ]

    # Without guiding there is nothing to dither: the step says so and the frames go on.
    unguided = imaging.model_copy(update={"children": [Slew(), plan]})
    service.put("dither", Sequence(name="dither", targets=Container(children=[unguided])))
    rig.calls.clear()
    await jobs.wait(service.start("dither"))
    assert not any(c.startswith("dither") for c in rig.calls)
    events = service_events(setup)
    assert {"skipped": "not guiding"} in [e["data"] for e in events if e["message"] == "dither"]


async def test_a_target_is_centred_and_checked_every_n_frames(setup: Any) -> None:
    service, rig, _, jobs, _ = setup
    rig.drifts = [0.5, 3.0]
    plan = ExposurePlan(rows=[PlanRow(filter="L", exposure=1, count=5)])
    every = RecenterTrigger(every=2, recenter=Recenter(drift=2))
    imaging = Container(target=M42, triggers=[every], children=[Center(tolerance=0.5), plan])
    service.put("centre", Sequence(name="centre", targets=Container(children=[imaging])))
    await jobs.wait(service.start("centre"))
    steps = [c for c in rig.calls if c.startswith(("frame", "center", "solve"))]
    assert steps == [
        "center 5.588 -5.39 within 0.5'",
        "frame M 42 1",
        "frame M 42 1",
        "solve (sync False)",  # 0.5' off: good enough
        "frame M 42 1",
        "frame M 42 1",
        "solve (sync False)",  # 3' off: centred again
        "center 5.588 -5.39 within 1'",
        "frame M 42 1",
    ]
    data = [e["data"] for e in service_events(setup) if e["message"] in ("center", "recenter")]
    assert data[0] == {"centered": True, "attempts": 2, "error": 0.4}
    assert data[1] == {"drift": 0.5}
    assert data[2]["drift"] == pytest.approx(3.0, abs=0.01)
    assert data[2]["centered"] is True


def service_events(setup: Any) -> list[dict[str, Any]]:
    return setup[2].get(("sequence", "events"))


async def test_a_paused_sequence_lends_the_rig_back(setup: Any) -> None:
    service, rig, store, jobs, checkpoint = setup
    service.put("m42", lrgb())
    rig.gate = anyio.Event()
    job = service.start("m42")
    await until(lambda: "filter L" in rig.calls)
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
    await until(lambda: "filter L" in rig.calls)
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


# -- the catalog and restarts (ADR 0032) ---------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.sessions: list[Session] = []
        self.events: list[SessionEvent] = []
        self.ended: list[tuple[int, str, str | None]] = []

    def start_session(self, session: Session) -> int | None:
        self.sessions.append(session)
        return 1

    def end_session(self, session_id: int, ended: str, outcome: str, error: str | None) -> None:
        self.ended.append((session_id, outcome, error))

    def add_session_events(self, session_id: int, events: list[SessionEvent]) -> None:
        self.events.extend(events)


def service_on(
    tmp_path: Path, store: StateStore, jobs: JobManager, rig: Rig, recorder: Recorder
) -> SequenceService:
    return SequenceService(
        store,
        jobs,
        SequenceStore(tmp_path),
        CheckpointFile(tmp_path / "data" / "sequence" / "run.json"),
        Clock(store),
        rig.parts,
        recorder=recorder,
        profile=lambda: "lab",
    )


async def test_a_run_and_its_events_go_to_the_catalog(tmp_path: Path) -> None:
    store = StateStore()
    jobs = JobManager(store)
    rig, recorder = Rig(jobs, store), Recorder()
    service = service_on(tmp_path, store, jobs, rig, recorder)
    service.put("m42", lrgb())
    await jobs.wait(service.start("m42"))
    [session] = recorder.sessions
    assert (session.sequence, session.name, session.profile, session.restarts) == (
        "m42",
        "tonight",
        "lab",
        0,
    )
    assert Sequence.model_validate_json(session.definition) == lrgb()
    kinds = [e.kind for e in recorder.events]
    assert kinds[0] == "started"
    assert kinds[-1] == "ended"
    assert kinds.count("frame") == 2
    assert recorder.ended == [(1, "completed", None)]


async def interrupted(tmp_path: Path, frames: int) -> CheckpointFile:
    """A run of ``lrgb`` cut after ``frames`` frames, as a crash of nocsd would leave it."""
    store = StateStore()
    jobs = JobManager(store)
    rig = Rig(jobs, store)
    service = service_on(tmp_path, store, jobs, rig, Recorder())
    service.put("m42", lrgb())
    rig.hold_from = frames + 1
    job = service.start("m42")
    await until(lambda: rig.taken > frames)
    await anyio.sleep(0.05)  # the last frame's checkpoint is written
    jobs.cancel(job)
    await jobs.wait(job)
    return CheckpointFile(tmp_path / "data" / "sequence" / "run.json")


async def test_a_restarted_nocsd_resumes_the_run(tmp_path: Path) -> None:
    checkpoint = await interrupted(tmp_path, frames=1)
    saved = checkpoint.load()
    assert saved is not None
    assert (saved.sequence, saved.plans["targets.0.2"].done) == ("m42", [1])

    store = StateStore()
    jobs = JobManager(store)
    rig, recorder = Rig(jobs, store), Recorder()
    service = service_on(tmp_path, store, jobs, rig, recorder)
    connected: list[bool] = []
    ready = iter([False, False, True])
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    job = await service.recover(
        lambda: connected.append(True), lambda: next(ready, True), sleep=sleep
    )
    assert job is not None
    assert connected == [True]
    assert len(sleeps) == 2
    await jobs.wait(job)
    assert rig.calls.count("frame M 42 1") == 1  # the one left
    assert rig.calls[:3] == ["cooling True -10.0", "unpark", "guide"]  # *start* again
    assert recorder.sessions[0].restarts == 1
    assert recorder.sessions[0].run == saved.run
    assert recorder.events[0].kind == "resumed_after_restart"
    assert checkpoint.load() is None
    assert await service.recover(lambda: None, lambda: True) is None  # nothing left


async def test_without_the_rig_or_after_three_restarts_only_the_end_runs(
    tmp_path: Path,
) -> None:
    checkpoint = await interrupted(tmp_path, frames=1)
    store = StateStore()
    jobs = JobManager(store)
    rig = Rig(jobs, store)
    service = service_on(tmp_path, store, jobs, rig, Recorder())

    async def sleep(seconds: float) -> None:
        await anyio.lowlevel.checkpoint()

    job = await service.recover(lambda: None, lambda: False, wait=10, poll=2, sleep=sleep)
    assert job is not None
    await jobs.wait(job)
    # A fresh camera is warm already: no ramp, the cooler goes off. PHD2 does not guide,
    # so guiding is left alone.
    assert rig.calls == ["park", "cooling False None", "output dc:1 False"]
    assert checkpoint.load() is None

    checkpoint = await interrupted(tmp_path, frames=1)
    saved = checkpoint.load()
    assert saved is not None
    await checkpoint.save(saved.model_copy(update={"restarts": 3}))
    rig = Rig(jobs, store)
    service = service_on(tmp_path, store, jobs, rig, Recorder())
    job = await service.recover(lambda: None, lambda: True)
    assert job is not None
    await jobs.wait(job)
    assert "frame M 42 1" not in rig.calls
    assert rig.calls[-1] == "output dc:1 False"


async def test_a_run_of_a_deleted_sequence_is_forgotten(tmp_path: Path) -> None:
    checkpoint = await interrupted(tmp_path, frames=1)
    SequenceStore(tmp_path).delete("m42")
    store = StateStore()
    jobs = JobManager(store)
    service = service_on(tmp_path, store, jobs, Rig(jobs, store), Recorder())
    assert await service.recover(lambda: None, lambda: True) is None
    assert checkpoint.load() is None


async def test_a_sequence_that_asks_about_the_sky_needs_the_site(setup: Any) -> None:
    service, *_ = setup
    dark = lrgb()
    dark.targets.conditions.append(UntilDawn())
    service.put("dark", dark)
    with pytest.raises(ValueError, match="set the site"):
        service.start("dark")


async def test_a_failed_device_is_restarted_then_power_cycled(setup: Any) -> None:
    _, rig, _, jobs, _ = setup
    from nocs.sequence import rig as rig_module
    from nocs.sequence.runner import StepError

    executor = rig_module.RigExecutor(JobContext(jobs, "job"), jobs, StateStore(), rig.parts())
    await executor.action(Cool(temperature=-10), None)

    async def stuck(*args: object, **kwargs: object) -> Captured:
        raise TimeoutError("no frame")

    rig.capture = stuck  # pyright: ignore[reportAttributeAccessIssue]
    plan = ExposurePlan(rows=[PlanRow(filter="L", exposure=1, count=1)])
    with pytest.raises(StepError) as failed:
        await executor.frame(plan, plan.rows[0], None)
    assert (failed.value.kind, failed.value.role) == ("device", "main_camera")
    rig.calls.clear()
    assert await executor.recover(failed.value, 1) == "restarted the main_camera's driver"
    assert await executor.recover(failed.value, 2) == "power cycled the main_camera"
    assert await executor.recover(failed.value, 3) is None
    # The restarted camera is asked to cool again.
    assert rig.calls == [
        "restart main_camera",
        "cooling True -10.0",
        "power cycle main_camera for job",
        "cooling True -10.0",
    ]
    mount = StepError("device", "no answer", role="mount")
    assert await executor.recover(mount, 1) == "restarted the mount's driver"
    assert await executor.recover(mount, 2) is None  # never power cycled
