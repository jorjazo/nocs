from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import PurePosixPath

from nocs.calibration.darks import darks_sequence, frames
from nocs.calibration.library import Light, Setup, Wanted, lights_of, report
from nocs.sequence.model import Container
from nocs.storage import FrameRow

SETUP = Setup("ZWO CCD ASI2600MC Duo", 6248, 4176, 1, 100.0, 50.0)
_ids = iter(range(1, 100000))


def row(
    frame_type: str,
    night: str = "2026-10-31",
    *,
    exposure: float = 300.0,
    filter: str | None = None,
    temperature: float | None = -10.0,
    gain: float | None = 100.0,
    rotation: float | None = None,
) -> FrameRow:
    return FrameRow(
        id=next(_ids),
        night=night,
        target=None,
        volume="v",
        volume_label="v",
        directory=PurePosixPath("."),
        path=PurePosixPath("x.fits"),
        size=1,
        started=f"{night}T23:00:00",
        exposure=exposure,
        frame_type=frame_type,
        filter=filter,
        profile=None,
        camera=SETUP.camera,
        gain=gain,
        offset=50.0,
        binning=1,
        temperature=temperature,
        width=6248,
        height=4176,
        stars=None,
        hfr=None,
        rotation=rotation,
    )


def test_lights_group_by_filter_exposure_and_temperature() -> None:
    lights = lights_of(
        [row("light", filter="L", temperature=t) for t in (-10.1, -9.8, -10.0)]
        + [row("light", filter="L", temperature=0.2)]
        + [row("light", filter="R", exposure=120)]
        + [row("light", filter="L", exposure=300.5, temperature=-10.0)]
    )
    found = report(lights, [], Wanted())
    groups = [(g.filter, g.exposure, g.temperature, g.lights) for g in found.groups]
    assert groups == [("L", 300.0, -10.0, 4), ("L", 300.0, 0.2, 1), ("R", 120, -10.0, 1)]


def test_darks_match_exposure_temperature_and_age() -> None:
    lights = lights_of([row("light", filter="L")])
    darks = [
        row("dark", "2026-09-01", temperature=-11.5),  # 60 days, within 2 °C
        row("dark", temperature=-7.0),  # too warm
        row("dark", exposure=180),  # other exposure
        row("dark", gain=200),  # other gain
        row("dark", "2026-01-01"),  # too old
    ]
    group = report(lights, darks, Wanted()).groups[0]
    assert group.darks.frames == [darks[0].id]
    assert group.darks.nights == {"2026-09-01"}


def test_flats_match_the_same_night_or_the_same_rotation() -> None:
    lights = lights_of([row("light", filter="Ha", rotation=91.5)])
    flats = [
        row("flat", filter="Ha", exposure=2),  # same night
        row("flat", "2026-10-20", filter="Ha", exposure=2, rotation=271.0),  # flipped, within 1°
        row("flat", "2026-10-20", filter="Ha", exposure=2, rotation=95),  # rotated
        row("flat", "2026-10-20", filter="Ha", exposure=2),  # unknown rotation
        row("flat", filter="OIII", exposure=2),  # other filter
        row("flat", "2026-11-01", filter="Ha", exposure=2, gain=0),  # gain does not matter
    ]
    group = report(lights, flats, Wanted()).groups[0]
    assert sorted(group.flats.frames) == [flats[0].id, flats[1].id]


def test_flats_need_their_bias_or_darks_of_their_exposure() -> None:
    lights = lights_of([row("light", filter="Ha")])
    flats = [row("flat", filter="Ha", exposure=2)]
    group = report(lights, flats, Wanted()).groups[0]
    assert group.flat_calibration.frames == []
    dark_flat = row("dark", exposure=2)
    group = report(lights, [*flats, dark_flat], Wanted()).groups[0]
    assert group.flat_calibration.frames == [dark_flat.id]
    bias = row("bias", exposure=0.0001, temperature=-12)
    group = report(lights, [*flats, dark_flat, bias], Wanted()).groups[0]
    assert group.flat_calibration.frames == [bias.id]


def test_needs_merge_darks_across_filters_and_count_what_exists() -> None:
    lights = lights_of(
        [row("light", filter=f) for f in ("R", "G", "B")] + [row("light", filter="L", exposure=60)]
    )
    calibration = [row("dark") for _ in range(5)] + [
        row("flat", filter="R", exposure=1) for _ in range(20)
    ]
    calibration += [row("bias", exposure=0.0001) for _ in range(50)]
    needs = report(lights, calibration, Wanted()).needs
    summary = [(n.kind, n.exposure, n.filter, n.count) for n in needs]
    assert summary == [
        ("dark", 60, None, 20),
        ("dark", 300.0, None, 15),
        ("flat", None, "B", 20),
        ("flat", None, "G", 20),
        ("flat", None, "L", 20),
    ]


def test_planned_lights_need_everything() -> None:
    planned = [Light(SETUP, "Ha", 300, -10, date(2026, 11, 1), count=30)]
    needs = report(planned, [], Wanted(darks=10, bias=30, flats=15)).needs
    assert [(n.kind, n.count, n.temperature) for n in needs] == [
        ("bias", 30, -10),
        ("dark", 10, -10),
        ("flat", 15, None),
    ]


def test_unknown_values_match_only_unknown_ones() -> None:
    lights = lights_of([row("light", temperature=None, gain=None)])
    darks = [row("dark", temperature=None, gain=None), row("dark", gain=None)]
    group = report(lights, darks, Wanted()).groups[0]
    assert group.darks.frames == [darks[0].id]
    assert replace(group.setup, gain=1).gain == 1


def test_darks_sequence_cools_takes_bias_then_darks_and_warms() -> None:
    lights = lights_of(
        [row("light", filter="L", exposure=e) for e in (300, 60)]
        + [row("light", filter="L", exposure=120, temperature=0.0)]
        + [row("light", filter="L", exposure=120, temperature=0.0)]
    )
    needs = report(lights, [], Wanted(darks=10, bias=30)).needs
    other = replace(needs[0], setup=replace(SETUP, camera="Other"))
    region = replace(needs[0], setup=replace(SETUP, width=1000))
    sequence, left = darks_sequence(
        [*needs, other, region],
        camera=SETUP.camera,
        sensor=(6248, 4176),
        bias_exposure=0.0001,
        warm=True,
        name="Darks",
    )
    assert left == [other, region]
    plan = [
        (
            c.name,
            [
                (
                    n.kind,
                    getattr(n, "frame_type", None),
                    [(r.exposure, r.count) for r in getattr(n, "rows", [])],
                )
                for n in c.children
            ],
        )
        for c in sequence.targets.children
        if isinstance(c, Container)
    ]
    assert plan == [
        (
            "-10 °C",
            [
                ("cool", None, []),
                ("expose", "bias", [(0.0001, 30)]),
                ("expose", "dark", [(60, 10), (300, 10)]),
            ],
        ),
        (
            "0 °C",
            [
                ("cool", None, []),
                ("expose", "bias", [(0.0001, 30)]),
                ("expose", "dark", [(120, 10)]),
            ],
        ),
    ]
    assert [n.kind for n in sequence.end.children] == ["warm"]
    assert frames(sequence) == 30 + 20 + 30 + 10
