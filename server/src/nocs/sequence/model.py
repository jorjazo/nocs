"""What a sequence is: containers, instructions, conditions and triggers (ADR 0031).

A sequence has three containers: *start*, *targets* and *end*. A container runs
its children in order, ``repeat`` times, while its conditions hold; triggers
attached to it apply to everything inside it. Instructions are the leaves: an
action is one step, an exposure plan takes frames one at a time.

These models are what is stored (``<config dir>/sequences/<id>.json``) and what
the API takes. Every node has a ``kind``; new kinds can be added without breaking
stored sequences.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from nocs.equipment.profiles import OutputId
from nocs.storage import layout

VERSION = 1

SEQUENCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
"""Sequence ids are file names, like profile ids."""

MAX_EXPOSURE = 7200.0
"""Seconds; the capture service's own limit."""

HFR_MEMORY = 10
"""HFRs kept per filter at each end of the frames since the last autofocus."""

type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class SequenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(SequenceModel):
    name: Name = Field(description="Object name: frames carry it, and their folder.")
    ra: float | None = Field(default=None, ge=0, lt=24, description="J2000 right ascension, hours.")
    dec: float | None = Field(
        default=None, ge=-90, le=90, description="J2000 declination, degrees."
    )

    @model_validator(mode="after")
    def _both_or_neither(self) -> Self:
        if not layout.clean(self.name):
            raise ValueError("the target name needs letters or digits")
        if (self.ra is None) != (self.dec is None):
            raise ValueError("a target needs both RA and Dec, or neither")
        return self


# -- actions ------------------------------------------------------------------------


class Cool(SequenceModel):
    kind: Literal["cool"] = "cool"
    temperature: float = Field(ge=-60, le=40, description="Target sensor temperature, °C.")
    ramp: float | None = Field(
        default=None, ge=0, description="At most this many °C per minute; 0: as fast as it can."
    )
    wait: bool = Field(default=True, description="Wait until the sensor gets there.")


class Warm(SequenceModel):
    kind: Literal["warm"] = "warm"
    ramp: float | None = Field(
        default=None, ge=0, description="At most this many °C per minute; 0: as fast as it can."
    )


class Unpark(SequenceModel):
    kind: Literal["unpark"] = "unpark"


class Park(SequenceModel):
    kind: Literal["park"] = "park"


class Slew(SequenceModel):
    """Go to the target of the enclosing container."""

    kind: Literal["slew"] = "slew"


class Center(SequenceModel):
    """Go to the target of the enclosing container and centre it by plate solving."""

    kind: Literal["center"] = "center"
    tolerance: float = Field(default=1.0, gt=0, le=60, description="Arcminutes.")
    attempts: int = Field(default=5, ge=1, le=10)
    exposure: float | None = Field(
        default=None, gt=0, le=120, description="Seconds; the camera's current one when None."
    )
    binning: int | None = Field(default=None, ge=1, le=8)


class Recenter(SequenceModel):
    """Solve a frame where the mount is; centre again when it drifted past ``drift``."""

    kind: Literal["recenter"] = "recenter"
    drift: float = Field(default=2.0, gt=0, le=60, description="Arcminutes.")
    center: Center = Field(default_factory=Center)


class Flip(SequenceModel):
    """Go to the container's target again once it is past the meridian, so the mount
    changes sides (ADR 0033); centre it when ``center`` is set."""

    kind: Literal["flip"] = "flip"
    center: Center | None = None


class SelectFilter(SequenceModel):
    kind: Literal["filter"] = "filter"
    filter: Name


class Autofocus(SequenceModel):
    """Focus with the settings of the profile's imaging train (ADR 0021)."""

    kind: Literal["autofocus"] = "autofocus"


class Guide(SequenceModel):
    kind: Literal["guide"] = "guide"
    on: bool


class Dither(SequenceModel):
    """Move the guiding lock position a little and wait until PHD2 settles (ADR 0024).

    Only while the sequence guides; otherwise there is nothing to dither.
    """

    kind: Literal["dither"] = "dither"
    pixels: float = Field(
        default=5, gt=0, le=50, description="Main camera pixels, at most this far."
    )
    settle_pixels: float = Field(default=1.5, gt=0, le=20, description="Settled within this…")
    settle_time: float = Field(default=10, ge=0, le=300, description="…for this long, seconds…")
    settle_timeout: float = Field(default=60, gt=0, le=600, description="…or give up after this.")
    ra_only: bool = False


class Outputs(SequenceModel):
    kind: Literal["outputs"] = "outputs"
    outputs: list[OutputId] = Field(min_length=1)
    on: bool


type Action = Annotated[
    Cool
    | Warm
    | Unpark
    | Park
    | Slew
    | Center
    | Recenter
    | Flip
    | SelectFilter
    | Autofocus
    | Guide
    | Dither
    | Outputs,
    Field(discriminator="kind"),
]

# -- exposure plans -----------------------------------------------------------------

type FrameKind = Literal["light", "dark", "flat", "bias"]
type Darkness = Literal["civil", "nautical", "astronomical"]
"""Which twilight ends the night (as in ``nocs.sky``)."""


class PlanRow(SequenceModel):
    filter: Name | None = Field(default=None, description="None: whatever the wheel holds.")
    exposure: float = Field(gt=0, le=MAX_EXPOSURE, description="Seconds.")
    count: int = Field(ge=1, le=10000)
    gain: float | None = None
    offset: float | None = None
    binning: int | None = Field(default=None, ge=1, le=8)


class ExposurePlan(SequenceModel):
    kind: Literal["expose"] = "expose"
    rows: list[PlanRow] = Field(min_length=1)
    order: Literal["batches", "in_turn"] = Field(
        default="batches",
        description="batches: up to `batch` frames of a row, then the next row with frames "
        "left; in_turn: each row to its end.",
    )
    batch: int = Field(default=5, ge=1, le=1000)
    frame_type: FrameKind = "light"


class Wait(SequenceModel):
    """Wait for a time, for the night to get dark, or for the target to rise.

    The runner itself waits, letting stops, pauses and conditions take effect.
    """

    kind: Literal["wait"] = "wait"
    time: AwareDatetime | None = None
    dusk: Darkness | None = Field(
        default=None, description="Until the Sun is below this twilight's end."
    )
    altitude: float | None = Field(
        default=None,
        ge=0,
        le=90,
        description="Until the target is this high (degrees) and above the horizon profile.",
    )

    @model_validator(mode="after")
    def _one_reason(self) -> Self:
        if sum(x is not None for x in (self.time, self.dusk, self.altitude)) != 1:
            raise ValueError("a wait needs one of time, dusk or altitude")
        return self


type Instruction = Annotated[
    Cool
    | Warm
    | Unpark
    | Park
    | Slew
    | Center
    | Recenter
    | Flip
    | SelectFilter
    | Autofocus
    | Guide
    | Dither
    | Outputs
    | Wait
    | ExposurePlan,
    Field(discriminator="kind"),
]

# -- conditions ---------------------------------------------------------------------


class UntilTime(SequenceModel):
    kind: Literal["until_time"] = "until_time"
    time: AwareDatetime

    def holds(self, now: datetime) -> bool:
        return now < self.time


class UntilDawn(SequenceModel):
    """Until the night ends: the end of this twilight (needs the site)."""

    kind: Literal["until_dawn"] = "until_dawn"
    darkness: Darkness = "astronomical"


class WhileAbove(SequenceModel):
    """While the container's target is this high and above the horizon profile."""

    kind: Literal["while_above"] = "while_above"
    altitude: float = Field(default=30, ge=0, le=90, description="Degrees, apparent.")


type Condition = Annotated[UntilTime | UntilDawn | WhileAbove, Field(discriminator="kind")]

# -- triggers -----------------------------------------------------------------------


class FocusMemory(SequenceModel):
    """What the autofocus triggers remember about the last run, kept in the checkpoint."""

    time: AwareDatetime | None = None
    filter: str | None = None
    temperature: float | None = None
    frames: int = 0
    hfr: dict[str, list[float]] = Field(default_factory=dict[str, list[float]])
    """Per filter (``""`` without one): HFRs since the run, the first and last ``HFR_MEMORY``."""

    def add_hfr(self, filter: str | None, hfr: float) -> None:
        values = self.hfr.setdefault(filter or "", [])
        if len(values) >= 2 * HFR_MEMORY:
            del values[HFR_MEMORY]
        values.append(hfr)


class AutofocusTrigger(SequenceModel):
    """Focus before a frame when one of the set reasons applies."""

    kind: Literal["autofocus"] = "autofocus"
    filter_change: bool = Field(default=False, description="The filter is not the last run's.")
    temperature_change: float | None = Field(
        default=None, gt=0, description="°C the focuser's temperature moved since the last run."
    )
    hfr_increase: float | None = Field(
        default=None,
        gt=0,
        description="Fraction the median HFR of a filter's last frames grew over its first "
        "frames after the last run.",
    )
    hfr_frames: int = Field(default=3, ge=1, le=HFR_MEMORY)
    minutes: float | None = Field(default=None, gt=0, description="Time since the last run.")
    frames: int | None = Field(default=None, ge=1, description="Frames since the last run.")

    @model_validator(mode="after")
    def _some_reason(self) -> Self:
        if not (
            self.filter_change
            or self.temperature_change
            or self.hfr_increase
            or self.minutes
            or self.frames
        ):
            raise ValueError("an autofocus trigger needs at least one reason")
        return self

    def due(
        self,
        memory: FocusMemory,
        *,
        filter: str | None,
        temperature: float | None,
        now: datetime,
        started: datetime,
    ) -> str | None:
        """Why focusing is due now, or ``None``."""
        if self.filter_change and filter is not None and filter != memory.filter:
            return f"filter {filter}"
        if (
            self.temperature_change is not None
            and temperature is not None
            and memory.temperature is not None
            and abs(temperature - memory.temperature) >= self.temperature_change
        ):
            return f"temperature {temperature - memory.temperature:+.1f} °C"
        if self.minutes is not None:
            since = (now - (memory.time or started)).total_seconds() / 60
            if since >= self.minutes:
                return f"{since:.0f} min"
        if self.frames is not None and memory.frames >= self.frames:
            return f"{memory.frames} frames"
        if self.hfr_increase is not None:
            values = memory.hfr.get(filter or "", [])
            n = self.hfr_frames
            if len(values) >= 2 * n:
                first, last = statistics.median(values[:n]), statistics.median(values[-n:])
                if first > 0 and last > first * (1 + self.hfr_increase):
                    return f"HFR {last / first - 1:+.0%}"
        return None


class DitherTrigger(SequenceModel):
    """Dither before a frame once ``every`` frames were taken since the last dither."""

    kind: Literal["dither"] = "dither"
    every: int = Field(default=1, ge=1, le=1000)
    dither: Dither = Field(default_factory=Dither)

    def due(self, frames: int) -> str | None:
        return f"{frames} frames" if frames >= self.every else None


class RecenterTrigger(SequenceModel):
    """Check the pointing once ``every`` frames were taken since the last check."""

    kind: Literal["recenter"] = "recenter"
    every: int = Field(default=10, ge=1, le=1000)
    recenter: Recenter = Field(default_factory=Recenter)

    def due(self, frames: int) -> str | None:
        return f"{frames} frames" if frames >= self.every else None


class FlipTrigger(SequenceModel):
    """Flip the mount when its target crosses the meridian (ADR 0033).

    Before each frame: a frame that would end past the flip point waits for it, or
    flips first once the target is past the meridian.
    """

    kind: Literal["flip"] = "flip"
    after: float = Field(
        default=5, ge=0, le=60, description="Minutes past the meridian at which to flip."
    )
    flip: Flip = Field(default_factory=Flip)


type Trigger = Annotated[
    AutofocusTrigger | DitherTrigger | RecenterTrigger | FlipTrigger, Field(discriminator="kind")
]

# -- containers and sequences -------------------------------------------------------


class Container(SequenceModel):
    kind: Literal["container"] = "container"
    name: str = Field(default="", max_length=80)
    target: Target | None = Field(
        default=None,
        description="What instructions inside aim at, unless a nested one names another.",
    )
    repeat: int | None = Field(
        default=1, ge=1, description="Times to run the children; None: until a condition ends it."
    )
    conditions: list[Condition] = Field(default_factory=list[Condition])
    triggers: list[Trigger] = Field(default_factory=list[Trigger])
    children: list[Node] = Field(default_factory=list["Node"])

    @model_validator(mode="after")
    def _repeat_ends(self) -> Self:
        if self.repeat is None and not self.conditions:
            raise ValueError("a container repeated without a limit needs a condition")
        if self.repeat != 1 and not self.children:
            raise ValueError("an empty container cannot repeat")
        return self


type Node = Annotated[
    Cool
    | Warm
    | Unpark
    | Park
    | Slew
    | Center
    | Recenter
    | Flip
    | SelectFilter
    | Autofocus
    | Guide
    | Dither
    | Outputs
    | Wait
    | ExposurePlan
    | Container,
    Field(discriminator="kind"),
]

Container.model_rebuild()


# -- recovery (ADR 0032) ------------------------------------------------------------

type FailureKind = Literal[
    "device", "clouds", "guiding", "focus", "solve", "flip", "storage", "other"
]


class Policy(SequenceModel):
    """What to do when a step fails with one kind of failure."""

    retries: int | None = Field(
        default=0, ge=0, description="Tries after the first; None: while the conditions hold."
    )
    wait: float = Field(default=0, ge=0, le=3600, description="Seconds before each retry.")
    then: Literal["skip", "skip_target", "pause", "end"] = Field(
        default="end",
        description="When the retries run out: skip the step, skip the target, pause for "
        "the user, or end the session (run *end*).",
    )


DEFAULT_POLICIES: dict[FailureKind, Policy] = {
    "clouds": Policy(retries=None, wait=300),
    "guiding": Policy(retries=3, wait=10),
    "device": Policy(retries=2, wait=60),
    "focus": Policy(then="skip"),
    "solve": Policy(retries=1, then="skip_target"),
    "flip": Policy(retries=1, wait=10),
    "storage": Policy(),
    "other": Policy(),
}


def needs_site(sequence: Sequence) -> bool:
    """Whether the sequence asks about the sky: the site must be known to run it."""

    def asks(container: Container) -> bool:
        if any(not isinstance(c, UntilTime) for c in container.conditions):
            return True
        if any(isinstance(t, FlipTrigger) for t in container.triggers):
            return True
        for child in container.children:
            if isinstance(child, Container) and asks(child):
                return True
            if isinstance(child, Wait) and child.time is None:
                return True
        return False

    return any(asks(part) for part in (sequence.start, sequence.targets, sequence.end))


# -- templates (phase 5.10) ---------------------------------------------------------


class FocusPlan(SequenceModel):
    """When a template's sequence focuses: at the start, and on these reasons."""

    at_start: bool = True
    filter_change: bool = False
    temperature_change: float | None = Field(default=1.0, gt=0)
    hfr_increase: float | None = Field(default=None, gt=0)
    minutes: float | None = Field(default=None, gt=0)


class EndPlan(SequenceModel):
    park: bool = True
    warm: bool = True
    outputs: list[OutputId] = Field(
        default_factory=list[OutputId], description="Power outputs to switch off."
    )


class Template(SequenceModel):
    """This target, these filters, tonight: what the builder edits (phase 5.10)."""

    name: Name
    target: Target
    rows: list[PlanRow] = Field(min_length=1)
    order: Literal["batches", "in_turn"] = "batches"
    batch: int = Field(default=5, ge=1, le=1000)
    start_at_dusk: bool = Field(
        default=True, description="Wait until dark first; otherwise start at once."
    )
    darkness: Darkness = Field(
        default="astronomical", description="The twilight that starts and ends the night."
    )
    until_dawn: bool = True
    min_altitude: float | None = Field(
        default=30, ge=0, le=90, description="Image the target only above this (and the horizon)."
    )
    cooling: float | None = Field(default=None, ge=-60, le=40, description="Sensor °C.")
    cooling_ramp: float | None = Field(default=None, ge=0)
    focus: FocusPlan | None = Field(default_factory=FocusPlan)
    guide: bool = False
    dither_every: int | None = Field(
        default=None, ge=1, le=1000, description="Dither every so many frames while guiding."
    )
    dither_pixels: float = Field(default=5, gt=0, le=50, description="Main camera pixels.")
    center: bool = Field(
        default=False, description="Centre the target by plate solving instead of only going."
    )
    recenter_every: int | None = Field(
        default=None, ge=1, le=1000, description="Check the pointing every so many frames."
    )
    recenter_drift: float = Field(default=2.0, gt=0, le=60, description="Arcminutes.")
    flip: bool = Field(default=True, description="Flip the mount at the meridian (ADR 0033).")
    flip_after: float = Field(default=5, ge=0, le=60, description="Minutes past the meridian.")
    end: EndPlan = Field(default_factory=EndPlan)
    recovery: dict[FailureKind, Policy] = Field(default_factory=dict[FailureKind, Policy])

    @model_validator(mode="after")
    def _target_with_coordinates(self) -> Self:
        if self.target.ra is None:
            raise ValueError("a template's target needs its coordinates")
        return self


class Sequence(SequenceModel):
    version: Literal[1] = VERSION
    name: Name
    start: Container = Field(default_factory=Container)
    targets: Container = Field(default_factory=Container)
    end: Container = Field(default_factory=Container, description="Always runs, once.")
    recovery: dict[FailureKind, Policy] = Field(
        default_factory=dict[FailureKind, Policy],
        description="Policies that replace the defaults, by kind of failure (ADR 0032).",
    )
    template: Template | None = Field(
        default=None, description="What the sequence was built from: the builder edits that."
    )

    def policy(self, kind: FailureKind) -> Policy:
        return self.recovery.get(kind) or DEFAULT_POLICIES[kind]

    @model_validator(mode="after")
    def _end_runs_once(self) -> Self:
        if self.end.repeat != 1 or self.end.conditions:
            raise ValueError("the end container runs once, without conditions")
        return self

    def digest(self) -> str:
        """Identifies this definition, so a checkpoint is never resumed on another one."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


type PathKey = str
"""A node's place in the tree: ``start``, ``targets.0.2``…"""


def key(path: tuple[str, ...]) -> PathKey:
    return ".".join(path)


def plans(sequence: Sequence) -> Iterator[tuple[PathKey, ExposurePlan, Target | None]]:
    """Every exposure plan, with its place and target, in the order of the tree."""

    def walk(
        container: Container, path: tuple[str, ...], target: Target | None
    ) -> Iterator[tuple[PathKey, ExposurePlan, Target | None]]:
        target = container.target or target
        for i, child in enumerate(container.children):
            child_path = (*path, str(i))
            if isinstance(child, Container):
                yield from walk(child, child_path, target)
            elif isinstance(child, ExposurePlan):
                yield key(child_path), child, target

    for part in ("start", "targets", "end"):
        yield from walk(getattr(sequence, part), (part,), None)
