"""The sequence model and its runner, with a fake rig and a fake clock (ADR 0031)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import anyio.lowlevel
import pytest
from pydantic import ValidationError

from nocs.devices import Location
from nocs.sequence import (
    Checkpoint,
    CheckpointFile,
    Container,
    Event,
    EventKind,
    ExposurePlan,
    FrameResult,
    Outcome,
    PlanRow,
    Runner,
    RunState,
    Sequence,
    SequenceError,
    SequenceStore,
    StepError,
    Target,
    sky,
)
from nocs.sequence.model import (
    Action,
    Autofocus,
    AutofocusTrigger,
    Cool,
    Park,
    Policy,
    SelectFilter,
    Slew,
    Unpark,
    UntilDawn,
    UntilTime,
    Wait,
    Warm,
    WhileAbove,
    needs_site,
)
from nocs.sequence.runner import PlanProgress, count_frame, next_row
from nocs.sequence.sky import Place

START = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
M42 = Target(name="M 42", ra=5.588, dec=-5.39)


class Rig:
    """Records what the runner asks for; a frame advances the clock by its exposure."""

    def __init__(self) -> None:
        self.time = START
        self.calls: list[str] = []
        self.temperature: float | None = 10.0
        self.hfr: Callable[[int], float | None] = lambda _: 2.0
        self.fail: set[str] = set()
        self.on_frame: Callable[[int], None] = lambda _: None
        self.gate: anyio.Event | None = None
        """When set, frames wait for it (to be dropped by a pause or stop ``now``)."""
        self.pauses = 0
        self.frames = 0
        self.stars: Callable[[int], int | None] = lambda _: 50
        self.errors: dict[str, list[StepError]] = {}
        """Failures to raise, in turn, for an action kind or ``frame``."""
        self.slept = 0.0

    async def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.time += timedelta(seconds=seconds)
        await anyio.lowlevel.checkpoint()

    def _raise(self, what: str) -> None:
        if errors := self.errors.get(what):
            raise errors.pop(0)

    def now(self) -> datetime:
        return self.time

    async def action(self, action: Action, target: Target | None) -> None:
        name = action.kind
        if action.kind == "filter":
            name = f"filter {action.filter}"
        elif action.kind == "slew" and target is not None:
            name = f"slew {target.name}"
        self.calls.append(name)
        await anyio.lowlevel.checkpoint()
        if action.kind in self.fail:
            raise RuntimeError(f"{action.kind} failed")
        self._raise(action.kind)
        if action.kind == "autofocus":
            self.time += timedelta(minutes=3)

    async def frame(self, plan: ExposurePlan, row: PlanRow, target: Target | None) -> FrameResult:
        if self.gate is not None:
            await self.gate.wait()
        await anyio.lowlevel.checkpoint()
        if "frame" in self.fail:
            raise RuntimeError("the camera timed out")
        self._raise("frame")
        self.frames += 1
        self.time += timedelta(seconds=row.exposure)
        self.calls.append(f"{row.filter or '-'} {row.exposure:g}")
        hfr = self.hfr(self.frames)
        self.on_frame(self.frames)
        return FrameResult(stars=self.stars(self.frames), hfr=hfr, frame=self.frames)

    async def paused(self) -> None:
        self.pauses += 1
        self.calls.append("paused")

    async def resumed(self) -> None:
        self.calls.append("resumed")

    def focuser_temperature(self) -> float | None:
        return self.temperature


def target(*rows: PlanRow, batch: int = 5, **container: object) -> Container:
    plan = ExposurePlan(rows=list(rows), batch=batch)
    return Container.model_validate(
        {"name": "M 42", "target": M42, "children": [Slew(), plan], **container}
    )


def night(*targets: Container, **parts: object) -> Sequence:
    return Sequence.model_validate(
        {
            "name": "tonight",
            "start": Container(children=[Cool(temperature=-10), Unpark()]),
            "targets": Container(children=list(targets)),
            "end": Container(children=[Park(), Warm()]),
            **parts,
        }
    )


def row(filter: str | None, count: int, exposure: float = 60) -> PlanRow:
    return PlanRow(filter=filter, exposure=exposure, count=count)


def frames(rig: Rig) -> list[str]:
    return [c for c in rig.calls if c[0].isupper() or c[0] == "-"]


# -- the model ----------------------------------------------------------------------


def test_a_target_needs_both_coordinates() -> None:
    with pytest.raises(ValidationError):
        Target(name="M 42", ra=5.5)
    assert Target(name="somewhere").ra is None


def test_containers_and_sequences_are_checked() -> None:
    with pytest.raises(ValidationError, match="needs a condition"):
        Container(repeat=None, children=[Slew()])
    with pytest.raises(ValidationError, match="cannot repeat"):
        Container(repeat=2)
    with pytest.raises(ValidationError, match="runs once"):
        Sequence(name="x", end=Container(repeat=2, children=[Park()]))
    with pytest.raises(ValidationError, match="at least one reason"):
        AutofocusTrigger()
    with pytest.raises(ValidationError):
        Container.model_validate({"children": [{"kind": "teleport"}]})


def test_a_sequence_survives_json_and_its_digest_follows_it() -> None:
    sequence = night(
        target(
            row("L", 10),
            row("R", 5),
            triggers=[AutofocusTrigger(filter_change=True, temperature_change=1)],
            conditions=[UntilTime(time=START + timedelta(hours=6))],
        )
    )
    again = Sequence.model_validate_json(sequence.model_dump_json())
    assert again == sequence
    assert again.digest() == sequence.digest()
    changed = sequence.model_copy(update={"name": "tomorrow"})
    assert changed.digest() != sequence.digest()


def test_sequences_are_kept_as_files(tmp_path: Path) -> None:
    store = SequenceStore(tmp_path)
    assert store.load_all() == {}
    sequence = night(target(row("L", 10)))
    store.put("m42-lrgb", sequence)
    assert store.get("m42-lrgb") == sequence
    assert list(store.load_all()) == ["m42-lrgb"]
    (tmp_path / "sequences" / "broken.json").write_text("{")
    assert list(store.load_all()) == ["m42-lrgb"]
    assert store.delete("m42-lrgb")
    assert not store.delete("m42-lrgb")
    assert store.get("m42-lrgb") is None
    with pytest.raises(SequenceError):
        store.get("../profiles/x")


# -- plans --------------------------------------------------------------------------


def order(plan: ExposurePlan) -> list[int]:
    progress = PlanProgress(done=[0] * len(plan.rows))
    taken: list[int] = []
    while (index := next_row(plan, progress)) is not None:
        count_frame(plan, progress, index)
        taken.append(index)
    return taken


def test_batches_go_round_the_rows_until_each_is_done() -> None:
    plan = ExposurePlan(rows=[row("L", 7), row("R", 2), row("G", 4)], batch=3)
    assert order(plan) == [0, 0, 0, 1, 1, 2, 2, 2, 0, 0, 0, 2, 0]


def test_in_turn_takes_each_row_to_its_end() -> None:
    plan = ExposurePlan(rows=[row("L", 3), row("R", 2)], order="in_turn")
    assert order(plan) == [0, 0, 0, 1, 1]


# -- running ------------------------------------------------------------------------


async def test_a_night_runs_start_targets_and_end_in_order() -> None:
    rig = Rig()
    events: list[Event] = []
    sequence = night(target(row("L", 2), row("R", 1), batch=1))
    runner = Runner(sequence, rig, now=rig.now, on_event=events.append)
    assert await runner.run() is Outcome.COMPLETED
    assert rig.calls == [
        "cool",
        "unpark",
        "slew M 42",
        "filter L",
        "L 60",
        "filter R",
        "R 60",
        "filter L",
        "L 60",
        "park",
        "warm",
    ]
    assert runner.state is RunState.FINISHED
    assert events[0].kind is EventKind.STARTED
    assert events[-1].kind is EventKind.ENDED
    assert [e.data["row"] for e in events if e.kind is EventKind.FRAME] == [0, 1, 0]
    status = runner.status()
    assert status["outcome"] == "completed"
    assert status["plans"] == {
        "targets.0.1": {
            "target": "M 42",
            "rows": [
                {"filter": "L", "exposure": 60, "count": 2, "done": 2},
                {"filter": "R", "exposure": 60, "count": 1, "done": 1},
            ],
        }
    }


async def test_a_repeated_container_takes_its_plan_again() -> None:
    rig = Rig()
    sequence = night(target(row("L", 2), repeat=3))
    assert await Runner(sequence, rig, now=rig.now).run() is Outcome.COMPLETED
    assert rig.calls.count("slew M 42") == 3
    assert len(frames(rig)) == 6


async def test_a_condition_ends_its_container_after_the_frame_in_progress() -> None:
    rig = Rig()
    until = UntilTime(time=START + timedelta(minutes=5))
    events: list[Event] = []
    sequence = night(target(row("L", 100), conditions=[until]))
    assert await Runner(sequence, rig, now=rig.now, on_event=events.append).run() is (
        Outcome.COMPLETED
    )
    assert len(frames(rig)) == 5  # 60 s each: the fifth ends at 00:05
    assert rig.calls[-2:] == ["park", "warm"]
    assert any(e.kind is EventKind.CONDITION and e.path == "targets.0" for e in events)


async def test_an_outer_condition_ends_the_containers_inside_it() -> None:
    rig = Rig()
    sequence = night(
        targets=Container(
            conditions=[UntilTime(time=START + timedelta(minutes=3))],
            children=[target(row("L", 100)), target(row("R", 100))],
        ),
    )
    assert await Runner(sequence, rig, now=rig.now).run() is Outcome.COMPLETED
    assert frames(rig) == ["L 60"] * 3
    assert rig.calls.count("slew M 42") == 1


# -- triggers -----------------------------------------------------------------------


async def test_autofocus_follows_the_filter() -> None:
    rig = Rig()
    sequence = night(
        target(
            row("L", 2),
            row("R", 2),
            batch=2,
            triggers=[AutofocusTrigger(filter_change=True)],
        )
    )
    await Runner(sequence, rig, now=rig.now).run()
    assert rig.calls[2:-2] == [
        "slew M 42",
        "filter L",
        "autofocus",
        "L 60",
        "L 60",
        "filter R",
        "autofocus",
        "R 60",
        "R 60",
    ]


async def test_an_autofocus_instruction_counts_for_the_triggers() -> None:
    rig = Rig()
    plan = ExposurePlan(rows=[row("L", 2)])
    focused = Container(
        target=M42,
        triggers=[AutofocusTrigger(filter_change=True)],
        children=[Slew(), SelectFilter(filter="L"), Autofocus(), plan],
    )
    await Runner(night(focused), rig, now=rig.now).run()
    assert rig.calls[2:-2] == ["slew M 42", "filter L", "autofocus", "L 60", "L 60"]


async def test_autofocus_on_temperature_frames_and_time() -> None:
    rig = Rig()

    def cooler(frame: int) -> None:
        if frame == 2:
            rig.temperature = 8.5

    rig.on_frame = cooler
    trigger = AutofocusTrigger(filter_change=True, temperature_change=1)
    await Runner(night(target(row("L", 4), triggers=[trigger])), rig, now=rig.now).run()
    assert frames_between_focus(rig) == [2, 2]

    rig = Rig()
    trigger = AutofocusTrigger(filter_change=True, frames=3)
    await Runner(night(target(row("L", 7), triggers=[trigger])), rig, now=rig.now).run()
    assert frames_between_focus(rig) == [3, 3, 1]

    rig = Rig()
    trigger = AutofocusTrigger(filter_change=True, minutes=10)
    plan = row("L", 6, exposure=300)
    await Runner(night(target(plan, triggers=[trigger])), rig, now=rig.now).run()
    assert frames_between_focus(rig) == [2, 2, 2]


async def test_autofocus_when_the_stars_grow() -> None:
    rig = Rig()
    rig.hfr = lambda n: 2.0 if n <= 5 else 2.5
    trigger = AutofocusTrigger(filter_change=True, hfr_increase=0.15, hfr_frames=3)
    await Runner(night(target(row("L", 12), triggers=[trigger])), rig, now=rig.now).run()
    # Two frames at 2.5 after five at 2.0: the median of the last three grew by 25 %.
    assert frames_between_focus(rig) == [7, 5]


def frames_between_focus(rig: Rig) -> list[int]:
    counts: list[int] = []
    for call in rig.calls:
        if call == "autofocus":
            counts.append(0)
        elif counts and (call[0].isupper() or call[0] == "-"):
            counts[-1] += 1
    return counts


# -- pausing and stopping -----------------------------------------------------------


async def test_a_pause_waits_for_the_frame_lends_the_rig_and_selects_the_filter_again() -> None:
    rig = Rig()
    runner = Runner(night(target(row("L", 4))), rig, now=rig.now)
    rig.on_frame = lambda n: runner.pause() if n == 2 else None
    async with anyio.create_task_group() as tg:
        tg.start_soon(runner.run)
        while runner.state is not RunState.PAUSED:
            await anyio.lowlevel.checkpoint()
        assert len(frames(rig)) == 2
        assert rig.pauses == 1
        runner.resume()
    assert runner.state is RunState.FINISHED
    assert rig.calls[3:10] == ["filter L", "L 60", "L 60", "paused", "resumed", "filter L", "L 60"]
    assert len(frames(rig)) == 4


async def test_a_pause_now_drops_the_frame_and_takes_it_again() -> None:
    rig = Rig()
    rig.gate = anyio.Event()
    runner = Runner(night(target(row("L", 2))), rig, now=rig.now)
    async with anyio.create_task_group() as tg:
        tg.start_soon(runner.run)
        while runner.status()["current"] != "targets.0.1" or rig.calls[-1] != "filter L":
            await anyio.lowlevel.checkpoint()
        await anyio.lowlevel.checkpoint()
        runner.pause(now=True)
        while runner.state is not RunState.PAUSED:
            await anyio.lowlevel.checkpoint()
        assert frames(rig) == []
        rig.gate.set()
        runner.resume()
    assert frames(rig) == ["L 60", "L 60"]


async def test_resuming_before_the_pause_takes_effect_cancels_it() -> None:
    rig = Rig()
    runner = Runner(night(target(row("L", 3))), rig, now=rig.now)

    def flip(n: int) -> None:
        if n == 1:
            runner.pause()
            runner.resume()

    rig.on_frame = flip
    assert await runner.run() is Outcome.COMPLETED
    assert rig.pauses == 0


async def test_a_stop_runs_the_end_unless_told_not_to() -> None:
    rig = Rig()
    runner = Runner(night(target(row("L", 10))), rig, now=rig.now)
    rig.on_frame = lambda n: runner.stop() if n == 3 else None
    assert await runner.run() is Outcome.STOPPED
    assert len(frames(rig)) == 3
    assert rig.calls[-2:] == ["park", "warm"]

    rig = Rig()
    runner = Runner(night(target(row("L", 10))), rig, now=rig.now)
    rig.on_frame = lambda n: runner.stop(run_end=False) if n == 3 else None
    assert await runner.run() is Outcome.STOPPED
    assert rig.calls[-1] == "L 60"


async def test_a_paused_run_can_be_stopped() -> None:
    rig = Rig()
    runner = Runner(night(target(row("L", 10))), rig, now=rig.now)
    rig.on_frame = lambda n: runner.pause() if n == 1 else None
    async with anyio.create_task_group() as tg:

        async def run() -> None:
            assert await runner.run() is Outcome.STOPPED

        tg.start_soon(run)
        while runner.state is not RunState.PAUSED:
            await anyio.lowlevel.checkpoint()
        runner.stop()
    assert rig.calls[-4:] == ["paused", "resumed", "park", "warm"]


async def test_a_failure_runs_the_end_and_every_end_step_is_tried() -> None:
    rig = Rig()
    rig.fail = {"slew", "park"}
    events: list[Event] = []
    runner = Runner(night(target(row("L", 10))), rig, now=rig.now, on_event=events.append)
    assert await runner.run() is Outcome.FAILED
    assert rig.calls[-3:] == ["slew M 42", "park", "warm"]
    failed = [(e.path, e.message) for e in events if e.kind is EventKind.FAILED]
    assert failed == [("targets.0.0", "slew failed"), ("end.0", "park failed")]
    assert runner.status()["error"] == "slew failed"


async def test_cancelling_the_run_skips_the_end() -> None:
    rig = Rig()
    rig.gate = anyio.Event()
    runner = Runner(night(target(row("L", 10))), rig, now=rig.now)
    with anyio.move_on_after(0.05):
        await runner.run()
    assert "park" not in rig.calls


# -- checkpoints --------------------------------------------------------------------


async def test_a_run_resumes_from_its_checkpoint_repeating_actions_not_frames() -> None:
    rig = Rig()
    saved: list[Checkpoint] = []

    async def save(checkpoint: Checkpoint) -> None:
        saved.append(checkpoint.model_copy(deep=True))

    first = target(row("L", 2))
    sequence = night(first, target(row("L", 2), row("R", 3), batch=2))
    runner = Runner(sequence, rig, now=rig.now, save=save)
    crashed = anyio.Event()

    def crash(n: int) -> None:
        if n == 5:
            crashed.set()
            rig.gate = anyio.Event()  # the next frame never ends

    rig.on_frame = crash
    async with anyio.create_task_group() as tg:
        tg.start_soon(runner.run)
        await crashed.wait()
        await anyio.sleep(0.01)
        tg.cancel_scope.cancel()

    checkpoint = saved[-1]
    assert checkpoint.finished == ["start", "targets.0"]
    assert checkpoint.plans["targets.1.1"].done == [2, 1]

    rig = Rig()
    events: list[Event] = []
    resumed = Runner(sequence, rig, now=rig.now, checkpoint=checkpoint, on_event=events.append)
    assert await resumed.run() is Outcome.COMPLETED
    assert rig.calls == [
        "cool",
        "unpark",
        "slew M 42",
        "filter R",
        "R 60",
        "R 60",
        "park",
        "warm",
    ]
    assert resumed.checkpoint.restarts == 1
    assert events[0].kind is EventKind.RESUMED_AFTER_RESTART
    with pytest.raises(ValueError, match="ended"):
        Runner(sequence, rig, now=rig.now, checkpoint=resumed.checkpoint)


async def test_a_run_that_was_ending_resumes_with_the_end() -> None:
    rig = Rig()
    sequence = night(target(row("L", 2)))
    checkpoint = Checkpoint(run="r", digest=sequence.digest(), started=START, ending=True)
    assert await Runner(sequence, rig, now=rig.now, checkpoint=checkpoint).run() is (
        Outcome.COMPLETED
    )
    assert rig.calls == ["park", "warm"]


def test_a_checkpoint_is_not_resumed_on_another_sequence() -> None:
    rig = Rig()
    sequence = night(target(row("L", 2)))
    checkpoint = Checkpoint(run="r", digest=sequence.digest(), started=START)
    other = night(target(row("L", 3)))
    with pytest.raises(ValueError, match="another version"):
        Runner(other, rig, now=rig.now, checkpoint=checkpoint)


async def test_the_checkpoint_file(tmp_path: Path) -> None:
    file = CheckpointFile(tmp_path / "sequence" / "run.json")
    assert file.load() is None
    checkpoint = Checkpoint(run="r", digest="d", started=START, finished=["start"])
    checkpoint.focus.add_hfr("L", 2.0)
    await file.save(checkpoint)
    assert file.load() == checkpoint
    (tmp_path / "sequence" / "run.json").write_text("{")
    assert file.load() is None
    file.clear()
    file.clear()
    assert file.load() is None


# -- recovery (ADR 0032) ------------------------------------------------------------


def run(sequence: Sequence, rig: Rig, events: list[Event] | None = None) -> Runner:
    return Runner(
        sequence,
        rig,
        now=rig.now,
        sleep=rig.sleep,
        on_event=(events.append if events is not None else None),
    )


def failures(events: list[Event]) -> list[tuple[str | None, Any, Any]]:
    return [
        (e.path, e.data.get("kind"), e.data.get("then"))
        for e in events
        if e.kind is EventKind.FAILED
    ]


async def test_frames_under_clouds_are_taken_again_after_a_wait() -> None:
    rig = Rig()
    rig.stars = lambda n: 2 if n in (3, 4) else 50  # a cloud passes over frames 3 and 4
    events: list[Event] = []
    assert await run(night(target(row("L", 4))), rig, events).run() is Outcome.COMPLETED
    assert len(frames(rig)) == 6
    assert rig.slept == 600
    assert failures(events) == [("targets.0.1", "clouds", "retry")] * 2
    counted = [e.data["id"] for e in events if e.kind is EventKind.FRAME]
    assert counted == [1, 2, 5, 6]


async def test_clouds_until_the_condition_ends_the_target() -> None:
    rig = Rig()
    rig.stars = lambda n: 50 if n == 1 else 0
    until = UntilTime(time=START + timedelta(hours=1))
    events: list[Event] = []
    sequence = night(target(row("L", 100), conditions=[until]))
    assert await run(sequence, rig, events).run() is Outcome.COMPLETED
    assert rig.now() >= until.time
    assert any(e.kind is EventKind.CONDITION for e in events)
    assert rig.calls[-2:] == ["park", "warm"]


async def test_a_device_that_keeps_failing_ends_the_session_parked() -> None:
    rig = Rig()
    rig.errors["frame"] = [StepError("device", "the camera timed out")] * 3
    events: list[Event] = []
    runner = run(night(target(row("L", 4))), rig, events)
    assert await runner.run() is Outcome.FAILED
    assert failures(events) == [
        ("targets.0.1", "device", "retry"),
        ("targets.0.1", "device", "retry"),
        ("targets.0.1", "device", "end"),
    ]
    assert rig.slept == 120
    assert rig.calls[-2:] == ["park", "warm"]
    assert runner.status()["error"] == "the camera timed out"


async def test_a_failed_autofocus_is_skipped_and_waits_for_the_next_reason() -> None:
    rig = Rig()
    rig.errors["autofocus"] = [StepError("focus", "a bad fit")]
    events: list[Event] = []
    trigger = AutofocusTrigger(filter_change=True, frames=3)
    await run(night(target(row("L", 6), triggers=[trigger])), rig, events).run()
    assert [e.message for e in events if e.kind is EventKind.SKIPPED] == ["autofocus"]
    assert frames_between_focus(rig) == [3, 3]


async def test_a_target_the_solver_cannot_find_is_skipped() -> None:
    rig = Rig()
    rig.errors["slew"] = [StepError("solve", "no solution")] * 2
    other = Container(
        target=Target(name="NGC 253", ra=0.79, dec=-25.29),
        children=[Slew(), ExposurePlan(rows=[row("R", 1)])],
    )
    events: list[Event] = []
    assert await run(night(target(row("L", 2)), other), rig, events).run() is Outcome.COMPLETED
    assert [e.message for e in events if e.kind is EventKind.SKIPPED] == ["target M 42"]
    assert frames(rig) == ["R 60"]


async def test_a_policy_may_pause_for_the_user() -> None:
    rig = Rig()
    rig.errors["frame"] = [StepError("storage", "the drive is full")]
    sequence = night(target(row("L", 2)), recovery={"storage": Policy(then="pause")})
    runner = run(sequence, rig)
    async with anyio.create_task_group() as tg:
        tg.start_soon(runner.run)
        for _ in range(1000):
            if runner.state is RunState.PAUSED:
                break
            await anyio.lowlevel.checkpoint()
        assert runner.state is RunState.PAUSED
        runner.resume()
    assert runner.status()["outcome"] == "completed"
    assert len(frames(rig)) == 2


async def test_a_stop_takes_effect_while_waiting_for_the_sky() -> None:
    rig = Rig()
    rig.stars = lambda n: 0
    runner = run(night(target(row("L", 2))), rig)

    async def sleep(seconds: float) -> None:
        await rig.sleep(seconds)
        if rig.slept >= 60:
            runner.stop()

    runner._sleep = sleep  # pyright: ignore[reportPrivateUsage]
    assert await runner.run() is Outcome.STOPPED
    assert rig.slept == 60
    assert rig.calls[-2:] == ["park", "warm"]


# -- the night's sky (phase 5.9) ----------------------------------------------------

DIAGUITAS = Place(Location(-30.0277, -70.6733, 700))
NGC_253 = Target(name="NGC 253", ra=0.7927, dec=-25.288)


def at_site(sequence: Sequence, rig: Rig, events: list[Event] | None = None) -> Runner:
    return Runner(
        sequence,
        rig,
        now=rig.now,
        sleep=rig.sleep,
        place=lambda: DIAGUITAS,
        on_event=(events.append if events is not None else None),
    )


async def test_until_dawn_ends_the_night() -> None:
    rig = Rig()
    rig.time = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)  # 03:00 at the site
    dawn = sky.dawn(DIAGUITAS, rig.time, "astronomical")
    plan = ExposurePlan(rows=[row("L", 100, exposure=300)])
    tonight = Container(target=NGC_253, conditions=[UntilDawn()], children=[plan])
    events: list[Event] = []
    assert await at_site(night(tonight), rig, events).run() is Outcome.COMPLETED
    taken = len(frames(rig))
    assert taken == math.ceil(
        (dawn - datetime(2026, 11, 1, 6, 0, tzinfo=UTC)).total_seconds() / 300
    )
    assert rig.time >= dawn
    assert any(e.kind is EventKind.CONDITION for e in events)


async def test_waiting_for_dusk() -> None:
    rig = Rig()
    rig.time = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)  # 17:00, the Sun is up
    events: list[Event] = []
    sequence = night(
        Container(
            target=NGC_253, children=[Wait(dusk="astronomical"), ExposurePlan(rows=[row("L", 1)])]
        )
    )
    await at_site(sequence, rig, events).run()
    [waited] = [e for e in events if e.message == "wait"]
    first = rig.time - timedelta(seconds=60)  # when the frame started
    assert sky.dark(DIAGUITAS, first, "astronomical")
    assert not sky.dark(DIAGUITAS, first - timedelta(seconds=31), "astronomical")
    assert isinstance(waited.data["waited"], int)
    assert waited.data["waited"] > 3 * 3600


async def test_a_target_is_imaged_while_it_is_high_enough() -> None:
    rig = Rig()
    # NGC 253 sets through the night of 2026-11-01 at the site; wait until it rises
    # above 60° first, then image it while above 40°.
    rig.time = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    plan = ExposurePlan(rows=[row("L", 1000, exposure=300)])
    tonight = Container(
        target=NGC_253,
        conditions=[WhileAbove(altitude=40)],
        children=[Wait(altitude=60), plan],
    )
    await at_site(night(tonight), rig).run()
    assert frames(rig)
    altitude, _ = sky.altitude(DIAGUITAS, NGC_253.ra or 0, NGC_253.dec or 0, rig.time)
    assert 38 < altitude < 40.5  # it set below 40° during the last frame


async def test_the_sky_needs_the_site() -> None:
    rig = Rig()
    sequence = night(Container(target=NGC_253, conditions=[UntilDawn()], children=[Slew()]))
    assert needs_site(sequence)
    assert not needs_site(night(target(row("L", 1))))
    runner = Runner(sequence, rig, now=rig.now)
    assert await runner.run() is Outcome.FAILED
    assert "site is unknown" in str(runner.status()["error"])
