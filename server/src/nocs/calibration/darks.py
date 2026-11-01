"""The darks and bias the library lacks, as a sequence to leave running (ADR 0036).

One container per sensor temperature, coldest first: cool and wait, the bias,
then the darks from the shortest exposure to the longest. The end warms the
camera when asked. Nothing moves the mount, the focuser or the wheel.
"""

from __future__ import annotations

from nocs.calibration.library import Need
from nocs.sequence import Sequence
from nocs.sequence.model import Container, Cool, ExposurePlan, Node, PlanRow, Warm

SEQUENCE_ID = "calibration"


def darks_sequence(
    needs: list[Need],
    *,
    camera: str,
    sensor: tuple[int, int],
    bias_exposure: float,
    warm: bool,
    name: str,
) -> tuple[Sequence, list[Need]]:
    """The sequence for the needs of ``camera``, and the needs it leaves out.

    Left out: flats, other cameras' darks, and frame sizes other than the full
    sensor (a region is not part of a sequence's rows).
    """
    taken = [
        n
        for n in needs
        if n.kind in ("dark", "bias") and n.setup.camera == camera and _full_frame(n, sensor)
    ]
    left = [n for n in needs if n not in taken and n.kind != "flat"]
    by_temperature: dict[float | None, list[Need]] = {}
    for need in taken:
        temperature = round(need.temperature) if need.temperature is not None else None
        by_temperature.setdefault(temperature, []).append(need)

    containers: list[Node] = []
    for temperature in sorted(by_temperature, key=lambda t: (t is None, t or 0)):
        group = by_temperature[temperature]
        children: list[Node] = []
        if temperature is not None:
            children.append(Cool(temperature=temperature))
        bias = [_row(n, bias_exposure) for n in group if n.kind == "bias"]
        if bias:
            children.append(ExposurePlan(rows=bias, order="in_turn", frame_type="bias"))
        darks = sorted((n for n in group if n.kind == "dark"), key=lambda n: n.exposure or 0)
        if darks:
            rows = [_row(n, n.exposure or bias_exposure) for n in darks]
            children.append(ExposurePlan(rows=rows, order="in_turn", frame_type="dark"))
        label = f"{temperature:g} °C" if temperature is not None else "Uncooled"
        containers.append(Container(name=label, children=children))

    end: list[Node] = [Warm()] if warm and any(t is not None for t in by_temperature) else []
    sequence = Sequence(
        name=name,
        targets=Container(children=containers),
        end=Container(children=end),
    )
    return sequence, left


def _full_frame(need: Need, sensor: tuple[int, int]) -> bool:
    setup = need.setup
    if setup.width is None or setup.height is None:
        return True
    binning = setup.binning or 1
    width, height = sensor[0] // binning, sensor[1] // binning
    return abs(setup.width - width) <= 1 and abs(setup.height - height) <= 1


def _row(need: Need, exposure: float) -> PlanRow:
    return PlanRow(
        exposure=exposure,
        count=need.count,
        gain=need.setup.gain,
        offset=need.setup.offset,
        binning=need.setup.binning,
    )


def frames(sequence: Sequence) -> int:
    """Frames the sequence takes."""
    total = 0
    for container in sequence.targets.children:
        if isinstance(container, Container):
            for child in container.children:
                if isinstance(child, ExposurePlan):
                    total += sum(row.count for row in child.rows)
    return total
