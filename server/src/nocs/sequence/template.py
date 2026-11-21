"""Templates: groups of frames of what the camera has framed, made into a sequence.

Groups run in their order, cut into **segments**: light groups in a row (at the same
temperature, when cooling is per group) are one segment, whose rows run one after
another, each to its end; every other group is a segment of its own. The tree::

    start:   cool (global cooling)
    targets: the framed target (found by the first ``aim``)
               for each segment, in order:
                 lights:   prompt (after darks or flats) · cool (per group)
                           until dawn: wait for dusk · aim · wait until high enough ·
                             while above it, with the autofocus, re-centring, flip and
                             dither triggers: centre · guide · autofocus · the plan
                 darks, bias, flats:
                           stop guiding · prompt (a new kind) · cool (per group) ·
                           the plan (flats whose exposure is found: ``flats``)
    end:     stop guiding · park · warm · outputs off

A prompt stops the run until the user says the rig is ready: before the first group
when it is not lights, and whenever the kind of frames changes between lights,
darks and bias (covered), and flats (a panel). The night's conditions and the
guiding, focusing and pointing apply to lights only.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from nocs.sequence import sky
from nocs.sequence.model import (
    Aim,
    Autofocus,
    AutofocusTrigger,
    Center,
    Condition,
    Container,
    Cool,
    Dither,
    DitherTrigger,
    ExposurePlan,
    Flats,
    Flip,
    FlipTrigger,
    FrameClass,
    Group,
    Guide,
    Node,
    Outputs,
    Park,
    PlanRow,
    Prompt,
    Recenter,
    RecenterTrigger,
    Sequence,
    Slew,
    Template,
    Trigger,
    Unpark,
    UntilDawn,
    Wait,
    Warm,
    WhileAbove,
    frame_class,
)
from nocs.sky import night, tonight

FRAME_OVERHEAD = 3.0
"""Seconds a frame costs beyond its exposure (download, save), for estimates."""
HEADER_BYTES = 20_000
FLAT_EXPOSURE = 2.0
"""Seconds a flat whose exposure is found is reckoned at, for estimates."""
BIAS_EXPOSURE = 0.001


@dataclass(frozen=True, slots=True)
class Segment:
    groups: list[Group]

    @property
    def frame_class(self) -> FrameClass:
        return frame_class(self.groups[0].frame_type)

    @property
    def temperature(self) -> float | None:
        return self.groups[0].temperature


def segments(template: Template) -> Iterator[Segment]:
    """The groups, with light groups in a row (at one temperature) put together."""
    current: list[Group] = []
    for group in template.groups:
        if (
            current
            and group.frame_type == "light"
            and current[-1].frame_type == "light"
            and (template.cooling != "group" or group.temperature == current[-1].temperature)
        ):
            current.append(group)
            continue
        if current:
            yield Segment(current)
        current = [group]
    if current:
        yield Segment(current)


def row(group: Group) -> PlanRow:
    return PlanRow(
        filter=group.filter,
        exposure=group.exposure,
        count=group.count,
        gain=group.gain,
        offset=group.offset,
        binning=group.binning,
    )


def expand(template: Template) -> Sequence:
    start: list[Node] = []
    if template.cooling == "global" and template.temperature is not None:
        start.append(Cool(temperature=template.temperature, ramp=template.cooling_ramp))
    if template.lights:
        start.append(Unpark())

    children: list[Node] = []
    previous: FrameClass = "light"
    for i, segment in enumerate(segments(template)):
        kind = segment.frame_class
        steps: list[Node] = []
        if kind != "light" and template.guide and i > 0 and previous == "light":
            steps.append(Guide(on=False))
        if kind != previous:
            steps.append(Prompt(frame_type=kind))
        if template.cooling == "group" and segment.temperature is not None:
            steps.append(Cool(temperature=segment.temperature, ramp=template.cooling_ramp))
        if kind == "light":
            # After darks or flats the mount may have moved (to the panel): back to
            # what was framed, unless centring does it.
            steps.extend(_lights(template, segment, back=i > 0 and not template.center))
            conditions: list[Condition] = []
            if template.until_dawn:
                conditions.append(UntilDawn(darkness=template.darkness))
            children.append(Container(name="lights", conditions=conditions, children=steps))
        else:
            steps.extend(_calibration(segment))
            children.append(Container(name=segment.groups[0].frame_type, children=steps))
        previous = kind

    end: list[Node] = []
    if template.guide and template.lights:
        end.append(Guide(on=False))
    if template.end.park:
        end.append(Park())
    if template.end.warm:
        end.append(Warm(ramp=template.cooling_ramp))
    if template.end.outputs:
        end.append(Outputs(outputs=template.end.outputs, on=False))

    return Sequence(
        name=template.name,
        start=Container(children=start),
        targets=Container(name=template.name, children=children),
        end=Container(children=end),
        recovery=template.recovery,
        template=template,
    )


def _lights(template: Template, segment: Segment, *, back: bool) -> list[Node]:
    steps: list[Node] = []
    if template.start_at_dusk:
        steps.append(Wait(dusk=template.darkness))
    steps.append(Aim())
    if back:
        steps.append(Slew())
    if template.min_altitude is not None:
        steps.append(Wait(altitude=template.min_altitude))

    imaging: list[Node] = []
    if template.center:
        imaging.append(Center())
    if template.guide:
        imaging.append(Guide(on=True))
    triggers: list[Trigger] = []
    focus = template.focus
    if focus is not None:
        # On a filter change the trigger focuses before the first frame anyway.
        if focus.at_start and not focus.filter_change:
            imaging.append(Autofocus())
        if focus.filter_change or focus.temperature_change or focus.hfr_increase or focus.minutes:
            triggers.append(
                AutofocusTrigger(
                    filter_change=focus.filter_change,
                    temperature_change=focus.temperature_change,
                    hfr_increase=focus.hfr_increase,
                    minutes=focus.minutes,
                )
            )
    if template.flip:
        center = Center() if template.center else None
        triggers.append(FlipTrigger(after=template.flip_after, flip=Flip(center=center)))
    if template.center and template.recenter_every is not None:
        recenter = Recenter(drift=template.recenter_drift)
        triggers.append(RecenterTrigger(every=template.recenter_every, recenter=recenter))
    if template.guide and template.dither_every is not None:
        dither = Dither(pixels=template.dither_pixels)
        triggers.append(DitherTrigger(every=template.dither_every, dither=dither))
    imaging.append(
        ExposurePlan(
            rows=[row(group) for group in segment.groups],
            order="in_turn",
        )
    )
    above: list[Condition] = []
    if template.min_altitude is not None:
        above.append(WhileAbove(altitude=template.min_altitude))
    steps.append(Container(name="imaging", conditions=above, triggers=triggers, children=imaging))
    return steps


def _calibration(segment: Segment) -> list[Node]:
    [group] = segment.groups
    if group.frame_type == "flat" and group.exposure is None:
        return [
            Flats(
                filter=group.filter,
                count=group.count,
                gain=group.gain,
                offset=group.offset,
                binning=group.binning,
            )
        ]
    return [ExposurePlan(rows=[row(group)], order="in_turn", frame_type=group.frame_type)]


def group_exposure(group: Group) -> float:
    """Seconds one frame of the group is reckoned at."""
    if group.exposure is not None:
        return group.exposure
    return FLAT_EXPOSURE if group.frame_type == "flat" else BIAS_EXPOSURE


@dataclass(frozen=True, slots=True)
class Estimate:
    frames: int
    integration: float
    """Seconds of exposure."""
    duration: float
    """Seconds the frames take, with ``FRAME_OVERHEAD`` each (no focusing, cooling or
    waiting for the user)."""
    bytes: int | None
    """On disk, when the camera's sensor is known."""
    starts: datetime | None = None
    """When it would start: now, or at dusk when its first group is lights that wait for
    it (when the site is known)."""
    ends: datetime | None = None
    """When its frames would be done."""


def estimate(
    template: Template,
    *,
    sensor: tuple[int, int] | None = None,
    place: sky.Place | None = None,
    now: datetime | None = None,
) -> Estimate:
    """What the groups cost."""
    groups = template.groups
    frames = sum(group.count for group in groups)
    integration = sum(group.count * group_exposure(group) for group in groups)
    duration = integration + frames * FRAME_OVERHEAD
    size = None
    if sensor is not None:
        width, height = sensor
        size = sum(
            group.count * (width * height * 2 // (group.binning or 1) ** 2 + HEADER_BYTES)
            for group in groups
        )
    when = now or datetime.now(UTC)
    starts = when
    if (
        place is not None
        and template.start_at_dusk
        and groups[0].frame_type == "light"
        and not sky.dark(place, when, template.darkness)
    ):
        span = night(place.site, tonight(place.site, when)).twilights[template.darkness]
        if span is not None and span.start > when.timestamp():
            starts = datetime.fromtimestamp(span.start, UTC)
    ends = datetime.fromtimestamp(starts.timestamp() + duration, UTC)
    return Estimate(frames, integration, duration, size, starts, ends)
