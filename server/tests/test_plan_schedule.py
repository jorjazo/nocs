"""A schedule in the runner: a plan's targets in priority, as they are up (fake rig)."""

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from test_sequence import START, Rig, frames

from nocs.sequence import Container, EventKind, Outcome, Runner, Sequence, StepError, Target
from nocs.sequence.model import (
    Park,
    PlanRow,
    Schedule,
    Slew,
    UntilTime,
    Warm,
)
from nocs.sequence.runner import Choice, Event
from nocs.state import Json


@dataclass
class Line:
    id: str
    filter: str | None
    count: int
    exposure: float = 60
    done: int = 0


@dataclass
class Aim:
    id: str
    lines: list[Line]
    up: Callable[[datetime], bool] = lambda _: True
    ra: float = 5.588
    dec: float = -5.39

    @property
    def left(self) -> int:
        return sum(max(0, line.count - line.done) for line in self.lines)


@dataclass
class Plan:
    """A scheduler over fake targets: ``up`` says when each is up."""

    targets: list[Aim]
    chosen: list[str] = field(default_factory=list[str])

    def choose(self, now: datetime, skipped: Collection[str]) -> Choice | None:
        for aim in self.targets:
            if aim.id in skipped or aim.left == 0 or not aim.up(now):
                continue
            lines = [line for line in aim.lines if line.done < line.count]
            return Choice(
                key=aim.id,
                target=Target(name=aim.id.upper(), ra=aim.ra, dec=aim.dec),
                rows=[
                    PlanRow(
                        filter=line.filter, exposure=line.exposure, count=line.count - line.done
                    )
                    for line in lines
                ],
                lines=[line.id for line in lines],
                done=[line.done for line in lines],
                revision=",".join(f"{line.id}:{line.count}:{line.exposure}" for line in aim.lines),
            )
        return None

    def pending(self) -> bool:
        return any(aim.left for aim in self.targets)

    async def taken(self, choice: Choice, row: int) -> None:
        for aim in self.targets:
            for line in aim.lines:
                if line.id == choice.lines[row]:
                    line.done += 1


def plan_night(every: float = 10, hours: float = 8) -> Sequence:
    """The targets until a time (dawn, in a real plan), each gone to before its frames."""
    return Sequence(
        name="Plan",
        targets=Container(
            conditions=[UntilTime(time=START + timedelta(hours=hours))],
            children=[Schedule(every=every, each=Container(children=[Slew()]))],
        ),
        end=Container(children=[Park(), Warm()]),
    )


def runner(rig: Rig, plan: Plan, sequence: Sequence | None = None) -> tuple[Runner, list[Event]]:
    events: list[Event] = []
    run = Runner(
        sequence or plan_night(),
        rig,
        now=rig.now,
        sleep=rig.sleep,
        scheduler=plan,
        on_event=events.append,
    )
    return run, events


def targets_taken(events: list[Event]) -> list[tuple[str | None, str]]:
    return [
        (e.data.get("target"), str(e.data.get("why")))  # type: ignore[arg-type]
        for e in events
        if e.kind is EventKind.TARGET
    ]


async def test_targets_are_taken_in_priority_each_to_its_end() -> None:
    rig = Rig()
    plan = Plan(
        [Aim("m42", [Line("a", "L", 2), Line("b", "R", 1)]), Aim("m8", [Line("c", "L", 2)])]
    )
    run, events = runner(rig, plan)
    assert await run.run() is Outcome.COMPLETED
    assert rig.calls == [
        "slew M42",
        "filter L",
        "L 60",
        "L 60",
        "filter R",
        "R 60",
        "slew M8",
        "filter L",
        "L 60",
        "L 60",
        "park",
        "warm",
    ]
    assert targets_taken(events) == [("m42", "start"), ("m8", "next")]
    assert [line.done for aim in plan.targets for line in aim.lines] == [2, 1, 2]


async def test_a_target_first_in_priority_takes_over_once_it_is_up() -> None:
    rig = Rig()
    rises = START + timedelta(minutes=20)
    first = Aim("m42", [Line("a", "L", 3)], up=lambda now: now >= rises)
    second = Aim("m8", [Line("b", "L", 100)])
    plan = Plan([first, second])
    run, events = runner(rig, plan)
    assert await run.run() is Outcome.COMPLETED
    taken = frames(rig)
    # m8 until a look every 10 minutes finds m42 up (at 20 min), between two frames.
    assert rig.calls[: rig.calls.index("slew M42")].count("L 60") == 20
    assert targets_taken(events)[:3] == [("m8", "start"), ("m42", "priority"), ("m8", "next")]
    assert first.lines[0].done == 3
    assert second.lines[0].done == len(taken) - 3


async def test_the_end_of_a_line_looks_again() -> None:
    rig = Rig()
    rises = START + timedelta(minutes=2)
    first = Aim("m42", [Line("a", "L", 1)], up=lambda now: now >= rises)
    second = Aim("m8", [Line("b", "R", 3), Line("c", "G", 3)])
    plan = Plan([first, second])
    run, events = runner(rig, plan)
    await run.run()
    # m8's R ends at 3 min: m42 is up by then and comes first, before m8's G.
    assert frames(rig) == ["R 60"] * 3 + ["L 60"] + ["G 60"] * 3
    assert targets_taken(events) == [("m8", "start"), ("m42", "priority"), ("m8", "next")]


async def test_a_target_taken_again_takes_what_is_left() -> None:
    rig = Rig()
    plan = Plan([Aim("m42", [Line("a", "L", 5, done=3)])])
    run, events = runner(rig, plan)
    await run.run()
    assert frames(rig) == ["L 60", "L 60"]
    # Its frames are the line's, other nights' included.
    labels = [e.message for e in events if e.kind is EventKind.FRAME]
    assert labels == ["L 60 s 4/5", "L 60 s 5/5"]


async def test_a_target_given_up_waits_while_the_others_are_taken() -> None:
    rig = Rig()
    rig.errors["slew"] = [StepError("solve", "no solution"), StepError("solve", "no solution")]
    plan = Plan([Aim("m42", [Line("a", "L", 1)]), Aim("m8", [Line("b", "L", 2)])])
    run, events = runner(rig, plan)
    assert await run.run() is Outcome.COMPLETED
    # m42 is left out for 15 minutes; m8's frames take 2: then nothing is up but m42,
    # which is waited for, and taken again.
    assert targets_taken(events) == [
        ("m42", "start"),
        ("m8", "next"),
        (None, "none"),
        ("m42", "next"),
    ]
    assert frames(rig) == ["L 60", "L 60", "L 60"]
    assert rig.time >= START + timedelta(minutes=15)


async def test_with_nothing_up_it_waits_until_the_night_ends() -> None:
    rig = Rig()
    plan = Plan([Aim("m42", [Line("a", "L", 1)], up=lambda _: False)])
    run, events = runner(rig, plan, plan_night(hours=1))
    assert await run.run() is Outcome.COMPLETED
    assert frames(rig) == []
    assert rig.calls == ["park", "warm"]
    assert targets_taken(events) == [(None, "none")]


async def test_a_target_changed_while_it_is_taken_is_taken_afresh() -> None:
    rig = Rig()
    aim = Aim("m42", [Line("a", "L", 30)])
    plan = Plan([aim])

    def edit(n: int) -> None:
        if n == 2:
            aim.lines[0].exposure = 120  # the user changed it
            aim.lines[0].count = 14

    rig.on_frame = edit
    run, events = runner(rig, plan)
    await run.run()
    # From the next look on, 10 minutes in.
    assert frames(rig) == ["L 60"] * 10 + ["L 120"] * 4
    assert targets_taken(events)[:2] == [("m42", "start"), ("m42", "changed")]


async def test_the_status_shows_the_target_and_its_lines() -> None:
    rig = Rig()
    plan = Plan([Aim("m42", [Line("a", "L", 4, done=1)])])
    run, _ = runner(rig, plan)
    seen: list[dict[str, Json]] = []

    def look(n: int) -> None:
        if n == 1:
            seen.append(run.status())

    rig.on_frame = look
    await run.run()
    [status] = seen
    assert status["target"] == "m42"
    current = status["current"]
    assert isinstance(current, str)
    assert current.startswith("targets.0.m42.")
    plans = status["plans"]
    assert isinstance(plans, dict)
    shown = plans[current]
    assert isinstance(shown, dict)
    assert shown["target"] == "M42"
    assert shown["rows"] == [{"filter": "L", "exposure": 60, "count": 4, "done": 1}]
    assert status["step"] == {"kind": "expose", "frame_type": "light"}
    assert run.status()["target"] is None


async def test_a_pause_and_a_stop_keep_the_frames_counted() -> None:
    rig = Rig()
    plan = Plan([Aim("m42", [Line("a", "L", 10)])])
    run, _ = runner(rig, plan)

    def stop(n: int) -> None:
        if n == 3:
            run.stop(run_end=False)

    rig.on_frame = stop
    assert await run.run() is Outcome.STOPPED
    assert plan.targets[0].lines[0].done == 3
    assert "park" not in rig.calls
