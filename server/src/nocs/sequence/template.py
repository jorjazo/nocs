"""Templates: "this target, these filters, tonight", made into a sequence (phase 5.10).

The tree a template makes::

    start:   cool (and wait for it) · unpark · wait for dusk
    targets: the target, until dawn
               wait until it is above the minimum altitude
               while above it, with the autofocus, re-centring and dither triggers:
                 slew (or centre) · guide · autofocus · the exposure plan
    end:     stop guiding · park · warm · outputs off

The wait for the altitude sits outside the container that holds while the target
is above it: otherwise a target still rising would end that container at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nocs.sequence import sky
from nocs.sequence.model import (
    Autofocus,
    AutofocusTrigger,
    Center,
    Condition,
    Container,
    Cool,
    Dither,
    DitherTrigger,
    ExposurePlan,
    Guide,
    Node,
    Outputs,
    Park,
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
)
from nocs.sky import Target as SkyTarget
from nocs.sky import night, tonight, visibility

FRAME_OVERHEAD = 3.0
"""Seconds a frame costs beyond its exposure (download, save), for estimates."""
HEADER_BYTES = 20_000


def expand(template: Template) -> Sequence:
    start: list[Node] = []
    if template.cooling is not None:
        start.append(Cool(temperature=template.cooling, ramp=template.cooling_ramp))
    start.append(Unpark())
    if template.start_at_dusk:
        start.append(Wait(dusk=template.darkness))

    imaging: list[Node] = [Center() if template.center else Slew()]
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
    if template.recenter_every is not None:
        recenter = Recenter(drift=template.recenter_drift)
        triggers.append(RecenterTrigger(every=template.recenter_every, recenter=recenter))
    if template.guide and template.dither_every is not None:
        dither = Dither(pixels=template.dither_pixels)
        triggers.append(DitherTrigger(every=template.dither_every, dither=dither))
    imaging.append(ExposurePlan(rows=template.rows, order=template.order, batch=template.batch))
    above: list[Condition] = []
    if template.min_altitude is not None:
        above.append(WhileAbove(altitude=template.min_altitude))
    inner = Container(name="imaging", conditions=above, triggers=triggers, children=imaging)

    outer: list[Node] = []
    if template.min_altitude is not None:
        outer.append(Wait(altitude=template.min_altitude))
    outer.append(inner)
    night_ends: list[Condition] = []
    if template.until_dawn:
        night_ends.append(UntilDawn(darkness=template.darkness))
    target = Container(
        name=template.target.name, target=template.target, conditions=night_ends, children=outer
    )

    end: list[Node] = []
    if template.guide:
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
        targets=Container(children=[target]),
        end=Container(children=end),
        recovery=template.recovery,
        template=template,
    )


@dataclass(frozen=True, slots=True)
class Estimate:
    frames: int
    integration: float
    """Seconds of exposure."""
    duration: float
    """Seconds the frames take, with ``FRAME_OVERHEAD`` each (no focusing or slewing)."""
    bytes: int | None
    """On disk, when the camera's sensor is known."""
    window: float | None
    """Seconds tonight's dark window keeps the target above the minimum altitude and the
    horizon, when the site is known."""
    starts: datetime | None = None
    """When imaging would start tonight: now, or when the target's window opens."""
    ends: datetime | None = None
    """When it would end: the plan done, or the window closed, whichever comes first."""


def estimate(
    template: Template,
    *,
    sensor: tuple[int, int] | None = None,
    place: sky.Place | None = None,
    now: datetime | None = None,
) -> Estimate:
    """What the plan costs, and how much of tonight it has."""
    frames = sum(row.count for row in template.rows)
    integration = sum(row.count * row.exposure for row in template.rows)
    duration = integration + frames * FRAME_OVERHEAD
    size = None
    if sensor is not None:
        width, height = sensor
        size = sum(
            row.count * (width * height * 2 // (row.binning or 1) ** 2 + HEADER_BYTES)
            for row in template.rows
        )
    window = starts = ends = None
    target = template.target
    if place is not None and target.ra is not None and target.dec is not None:
        when = now or datetime.now(UTC)
        tonight_ = night(place.site, tonight(place.site, when))
        [seen] = visibility(
            tonight_,
            [SkyTarget(target.ra, target.dec)],
            min_altitude=template.min_altitude or 0,
            horizon=place.horizon,
        )
        window = seen.observable
        current = when.timestamp()
        opens = next((w for w in seen.windows if w.end > current), None)
        if opens is not None:
            start = max(current, opens.start)
            starts = datetime.fromtimestamp(start, UTC)
            ends = datetime.fromtimestamp(min(start + duration, opens.end), UTC)
    return Estimate(frames, integration, duration, size, window, starts, ends)
