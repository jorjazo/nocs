"""Plate solving for the rest of NOCS: one solve at a time, hinted first, then blind.

State under ``("solver",)``::

    {available, version, databases, solving, last}

``last`` is the most recent solution, whoever asked for it. Workflows (solve and
sync, centring, polar alignment, re-centring) call ``SolverService.solve`` with a
frame on disk and what they know about it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

from nocs.solving.astap import Astap, Database, Hint, SolveError, downsample_for
from nocs.solving.solution import Solution
from nocs.state import Json, StateStore

log = logging.getLogger(__name__)

ROOT = ("solver",)
HINTED_TIMEOUT = 30.0
"""Seconds for a solve near the hint; ~1.3 s on the Pi 5 with D50 (spike)."""
BLIND_TIMEOUT = 120.0
"""Seconds for a search of the whole sky; ~4 s on the Pi 5 with a known field."""

_fits: Any = fits  # untyped library; see nocs.imaging.pipeline


@dataclass(frozen=True, slots=True)
class SolveResult:
    solution: Solution
    hinted: bool
    """Solved near the hint (``False``: by searching the whole sky)."""
    downsample: int
    seconds: float


@dataclass(frozen=True, slots=True)
class ImageInfo:
    width: int
    height: int
    bottom_up: bool


def image_info(path: Path) -> ImageInfo:
    header = _fits.getheader(path)
    row_order = str(header.get("ROWORDER", "TOP-DOWN")).strip().upper()
    return ImageInfo(int(header["NAXIS1"]), int(header["NAXIS2"]), row_order == "BOTTOM-UP")


class SolverService:
    def __init__(self, store: StateStore, astap: Astap | None) -> None:
        self._store = store
        self._astap = astap
        self._lock = anyio.Lock()
        self._version: str | None = None
        self._solving = False
        self._last: dict[str, Json] | None = None
        self._publish()

    @property
    def available(self) -> bool:
        return self._astap is not None

    async def start(self) -> None:
        if self._astap is not None:
            self._version = await self._astap.version()
            log.info(
                "ASTAP %s at %s, databases: %s",
                self._version,
                self._astap.executable,
                ", ".join(d.name for d in self._astap.databases) or "none found",
            )
            self._publish()

    async def solve(
        self,
        image: Path,
        *,
        fov: float | None,
        hint: Hint | None,
        hfr: float | None = None,
        blind: bool = True,
    ) -> SolveResult:
        """Solve a FITS frame; raises SolveError.

        ``fov`` is the frame's height in degrees, ``hfr`` its stars' median half-flux
        radius in pixels (to choose ASTAP's downsampling). With a ``hint``, the sky
        around it is searched first, then, if ``blind``, the whole sky.
        """
        astap = self._astap
        if astap is None:
            raise SolveError("ASTAP is not installed")
        if fov is not None and astap.databases and astap.database_for(fov) is None:
            raise SolveError(
                f"no star database for a {fov:.2g}° field (installed: "
                f"{', '.join(_describe(d) for d in astap.databases)})"
            )
        info = await anyio.to_thread.run_sync(image_info, image)
        downsample = downsample_for(hfr, info.height)
        attempts = [hint, None] if hint is not None and blind else [hint]
        async with self._lock:
            self._solving = True
            self._publish()
            try:
                for attempt in attempts:
                    start = time.monotonic()
                    try:
                        solution = await astap.solve(
                            image,
                            (info.width, info.height),
                            fov=fov,
                            hint=attempt,
                            downsample=downsample,
                            timeout=HINTED_TIMEOUT if attempt is not None else BLIND_TIMEOUT,
                            bottom_up=info.bottom_up,
                        )
                    except SolveError as error:
                        if attempt is attempts[-1]:
                            raise
                        log.info("no solution near the hint (%s); searching the whole sky", error)
                        continue
                    result = SolveResult(
                        solution,
                        hinted=attempt is not None,
                        downsample=downsample,
                        seconds=round(time.monotonic() - start, 2),
                    )
                    self._last = _summary(result)
                    return result
                raise AssertionError("unreachable")
            finally:
                self._solving = False
                self._publish()

    def _publish(self) -> None:
        astap = self._astap
        self._store.set(
            ROOT,
            {
                "available": astap is not None,
                "version": self._version,
                "databases": [
                    {"name": d.name, "min_fov": d.min_fov, "max_fov": d.max_fov}
                    for d in (astap.databases if astap else [])
                ],
                "solving": self._solving,
                "last": self._last,
            },
        )


def _describe(database: Database) -> str:
    return f"{database.name} {database.min_fov:g} to {database.max_fov:g}°"


def _summary(result: SolveResult) -> dict[str, Json]:
    solution = result.solution
    width, height = solution.fov
    return {
        "ra": solution.ra,
        "dec": solution.dec,
        "rotation": solution.rotation,
        "scale": solution.scale,
        "mirrored": solution.mirrored,
        "fov": [width, height],
        "hinted": result.hinted,
        "seconds": result.seconds,
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
    }
