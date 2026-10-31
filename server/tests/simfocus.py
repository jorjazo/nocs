"""The INDI simulators as a rig to focus (ADR 0021).

The CCD Simulator draws its stars with the FWHM the Focuser Simulator computes
from its position, a parabola: ``seeing + 0.5625 · ((x - best) / 5000)²``
arcseconds. At the dev profile's 250 mm the stars stay under 2 px HFR; at
``FOCAL_LENGTH`` the curve is clear (1.7 px at focus, 5.4 px 20000 steps away).
"""

from nocs.devices import Focuser
from nocs.indi import IndiClient

FOCUSER = "Focuser Simulator"
FOCAL_LENGTH = 1000
APERTURE = 150
ORION = (5.6, -5.4)
"""JNow RA (hours) and Dec of a field with ~50 stars at ``FOCAL_LENGTH``."""


def fwhm(client: IndiClient) -> float:
    prop = client.get_property(FOCUSER, "FWHM")
    assert prop is not None
    return prop.number("SIM_FWHM")


async def best_focus(client: IndiClient) -> float:
    """Where the simulated stars are smallest, from the FWHM at three positions.

    The simulator updates its FWHM before it reports the new position.
    """
    focuser = Focuser(client, FOCUSER)
    start = focuser.position
    samples: list[tuple[float, float]] = []
    for position in (20000, 40000, 60000):
        await focuser.move_to(position)
        samples.append((position, fwhm(client)))
    await focuser.move_to(start)
    (x0, y0), (x1, y1), (x2, y2) = samples
    # Vertex of the parabola through the three points.
    numerator = (x1 - x0) ** 2 * (y1 - y2) - (x1 - x2) ** 2 * (y1 - y0)
    denominator = (x1 - x0) * (y1 - y2) - (x1 - x2) * (y1 - y0)
    return x1 - numerator / (2 * denominator)
