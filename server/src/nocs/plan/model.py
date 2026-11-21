"""The plan: the targets to take over one night or many, in priority, each with its
lines of lights, and what happens around them.

The plan runs as a sequence (``expand``) whose ``schedule`` takes the targets from
the ``PlanService``: the first in priority that is up with frames left. Each line
keeps the frames it has (``done``) across nights, so a plan goes on where it was.
"""

from __future__ import annotations

import re
from typing import Self

from pydantic import Field, model_validator

from nocs.equipment.profiles import OutputId
from nocs.sequence.model import (
    MAX_EXPOSURE,
    Actions,
    Center,
    Condition,
    Container,
    Cool,
    Guide,
    Name,
    Node,
    Outputs,
    Schedule,
    Sequence,
    SequenceModel,
    Slew,
    Unpark,
    UntilDawn,
    Wait,
    WhileAbove,
)
from nocs.sequence.template import end_steps, focus_at_start, triggers

PLAN_ID = "plan"
"""The sequence a plan runs as: kept among the sequences, never listed with them."""
PLAN_NAME = "Plan"
ITEM_ID = re.compile(r"^[a-z0-9]{1,16}$")


class PlanLine(SequenceModel):
    """Lights of a target taken alike."""

    id: str = Field(pattern=ITEM_ID.pattern, description="Chosen by the client; kept.")
    filter: Name | None = Field(default=None, description="None: whatever the wheel holds.")
    exposure: float = Field(gt=0, le=MAX_EXPOSURE, description="Seconds.")
    gain: float | None = None
    offset: float | None = None
    count: int = Field(ge=1, le=10000)
    done: int = Field(
        default=0,
        ge=0,
        description="Frames kept, over every night; the server counts them (a client's "
        "value is ignored).",
    )

    @property
    def left(self) -> int:
        return max(0, self.count - self.done)


class PlanTarget(SequenceModel):
    """Where to point (the frame's centre, which may be off the object), and its lines."""

    id: str = Field(pattern=ITEM_ID.pattern, description="Chosen by the client; kept.")
    name: Name = Field(description="Frames carry it, and their folder.")
    object: str | None = Field(
        default=None, max_length=50, description="Catalog id (NGC 292), when it is one."
    )
    ra: float = Field(ge=0, lt=24, description="J2000 hours where the frame points.")
    dec: float = Field(ge=-90, le=90, description="J2000 degrees where the frame points.")
    rotation: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="Wanted angle of the frame's top, degrees east of north; None: any.",
    )
    lines: list[PlanLine] = Field(default_factory=list[PlanLine])

    @property
    def left(self) -> int:
        return sum(line.left for line in self.lines)


def _actions() -> Actions:
    # A plan goes from target to target: centring each one is what makes it work.
    return Actions(center=True, recenter_every=10)


class NightPlan(SequenceModel):
    """What the Plan view edits."""

    targets: list[PlanTarget] = Field(
        default_factory=list[PlanTarget], description="In priority, the first first."
    )
    actions: Actions = Field(default_factory=_actions)
    start_outputs: list[OutputId] = Field(
        default_factory=list[OutputId],
        description="Power outputs to switch on when it starts (dew heaters).",
    )

    @model_validator(mode="after")
    def _fits(self) -> Self:
        if self.actions.cooling == "group":
            raise ValueError("a plan cools to one temperature, or not at all")
        targets = [target.id for target in self.targets]
        if len(set(targets)) != len(targets):
            raise ValueError("two targets share an id")
        lines = [line.id for target in self.targets for line in target.lines]
        if len(set(lines)) != len(lines):
            raise ValueError("two lines share an id")
        return self

    def target(self, target_id: str) -> PlanTarget | None:
        return next((t for t in self.targets if t.id == target_id), None)

    @property
    def left(self) -> int:
        return sum(target.left for target in self.targets)


def expand(plan: NightPlan) -> Sequence:
    """The sequence a plan runs as::

        start:   outputs on · cool · unpark
        targets: until dawn: wait for dusk · schedule (each target: while above the
                 minimum: centre or go · guide · focus the first one · its lines)
        end:     stop guiding · park · warm · outputs off

    Its targets are not in it: the schedule asks the plan, so that editing them while
    it runs changes what it takes next, not the sequence.
    """
    actions = plan.actions
    start: list[Node] = []
    if plan.start_outputs:
        start.append(Outputs(outputs=plan.start_outputs, on=True))
    if actions.cooling == "global" and actions.temperature is not None:
        start.append(Cool(temperature=actions.temperature, ramp=actions.cooling_ramp))
    start.append(Unpark())

    steps: list[Node] = [Center() if actions.center else Slew()]
    if actions.guide:
        steps.append(Guide(on=True))
    # Above the horizon at least: a target is chosen only while it is.
    up: list[Condition] = [WhileAbove(altitude=actions.min_altitude or 0)]
    each = Container(conditions=up, triggers=triggers(actions), children=steps)
    children: list[Node] = []
    if actions.start_at_dusk:
        children.append(Wait(dusk=actions.darkness))
    children.append(Schedule(each=each, focus_first=focus_at_start(actions)))
    night: list[Condition] = [UntilDawn(darkness=actions.darkness)] if actions.until_dawn else []

    return Sequence(
        name=PLAN_NAME,
        start=Container(children=start),
        targets=Container(name=PLAN_NAME, conditions=night, children=children),
        end=Container(children=end_steps(actions, lights=True)),
        recovery=actions.recovery,
    )
