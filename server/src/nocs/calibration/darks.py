"""The darks and bias the library lacks, as a sequence to leave running.

Groups per sensor temperature, coldest first: the bias, then the darks from the
shortest exposure to the longest, each cooled to its temperature. The end warms the
camera when asked. Nothing moves the mount, the focuser or the wheel.
"""

from __future__ import annotations

from nocs.calibration.library import Need
from nocs.sequence.model import EndPlan, Group, Template
from nocs.sequence.template import estimate

SEQUENCE_ID = "calibration"


def darks_template(
    needs: list[Need],
    *,
    camera: str,
    sensor: tuple[int, int],
    warm: bool,
    name: str,
) -> tuple[Template | None, list[Need]]:
    """The groups for the needs of ``camera`` (None when it needs none), and the needs it
    leaves out.

    Left out: flats, other cameras' darks, and frame sizes other than the full
    sensor (a region is not part of a sequence's groups). The run asks for the camera
    to be covered first.
    """
    taken = [
        n
        for n in needs
        if n.kind in ("dark", "bias") and n.setup.camera == camera and full_frame(n, sensor)
    ]
    left = [n for n in needs if n not in taken and n.kind != "flat"]
    if not taken:
        return None, left
    template = Template(
        name=name,
        groups=dark_groups(taken),
        cooling="group" if any(n.temperature is not None for n in taken) else "off",
        start_at_dusk=False,
        until_dawn=False,
        min_altitude=None,
        focus=None,
        flip=False,
        end=EndPlan(park=False, warm=warm),
    )
    return template, left


def dark_groups(needs: list[Need]) -> list[Group]:
    """Darks and bias as groups: coldest first; bias, then darks, shortest first."""
    by_temperature: dict[float | None, list[Need]] = {}
    for need in needs:
        if need.kind not in ("dark", "bias"):
            continue
        temperature = round(need.temperature) if need.temperature is not None else None
        by_temperature.setdefault(temperature, []).append(need)
    groups: list[Group] = []
    for temperature in sorted(by_temperature, key=lambda t: (t is None, t or 0)):
        found = by_temperature[temperature]
        bias = [n for n in found if n.kind == "bias"]
        darks = sorted((n for n in found if n.kind == "dark"), key=lambda n: n.exposure or 0)
        for need in [*bias, *darks]:
            groups.append(_group(need, temperature))
    return groups


def flat_groups(needs: list[Need]) -> list[Group]:
    """Flats as groups, one per filter, each exposure found."""
    return [
        Group(
            frame_type="flat",
            filter=need.filter,
            count=min(need.count, 200),
            gain=need.setup.gain,
            offset=need.setup.offset,
            binning=need.setup.binning,
        )
        for need in needs
        if need.kind == "flat"
    ]


def _group(need: Need, temperature: float | None) -> Group:
    return Group(
        frame_type=need.kind,
        exposure=need.exposure if need.kind == "dark" else None,
        count=need.count,
        gain=need.setup.gain,
        offset=need.setup.offset,
        binning=need.setup.binning,
        temperature=temperature,
    )


def full_frame(need: Need, sensor: tuple[int, int]) -> bool:
    setup = need.setup
    if setup.width is None or setup.height is None:
        return True
    binning = setup.binning or 1
    width, height = sensor[0] // binning, sensor[1] // binning
    return abs(setup.width - width) <= 1 and abs(setup.height - height) <= 1


def frames(template: Template | None) -> int:
    """Frames the groups take."""
    return estimate(template).frames if template is not None else 0


def duration(template: Template | None) -> float:
    """Seconds their frames take, with their overhead each; cooling not included."""
    return estimate(template).duration if template is not None else 0.0
