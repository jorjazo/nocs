"""The ASTAP command-line plate solver (ADR 0006, ADR 0018).

ASTAP runs as a process per solve. It reads the FITS file where it is and writes
its result (``.ini``, ``.wcs``) under a base name NOCS gives it, in a directory of
its own, so the frame is never copied nor written next to.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import anyio

from nocs.solving.solution import Solution, SolutionError, read_ini, solution_from_ini

log = logging.getLogger(__name__)

SEARCH_PATHS = (Path("/opt/astap/astap_cli"), Path("/usr/local/opt/astap/astap_cli"))
"""Where ASTAP's packages put the command-line solver, when it is not on ``PATH``."""
DATABASE_PATHS = (Path("/opt/astap"), Path("/usr/local/opt/astap"), Path("/usr/share/astap"))

DATABASE_FIELDS: dict[str, tuple[float, float]] = {
    "d80": (0.15, 6.0),
    "d50": (0.2, 6.0),
    "v50": (0.2, 6.0),
    "d20": (0.3, 6.0),
    "d05": (0.6, 6.0),
    "g05": (3.0, 20.0),
    "w08": (20.0, 80.0),
}
"""Fields of view (frame height, degrees) each star database solves, from ASTAP's readme."""
_DATABASE_FILE = re.compile(r"^([a-z]\d\d)_\d{4}\.\w+$")
_VERSION = re.compile(r"version\s+(\S+)")

MAX_DOWNSAMPLE = 3
"""Beyond this ASTAP lost the badly defocused stars (HFR 22 px) of a real frame."""
STAR_DIAMETER = 3.0
"""Pixels a star's half-flux diameter should keep after downsampling. ASTAP detects
stars of a few pixels; its automatic choice (``-z 0``) bins the simulators' sharp
stars (HFR < 1 px) out of existence, so NOCS chooses from the measured HFR."""
ROWS_PER_STEP = 1500
"""Rows a frame needs per step of downsampling: a 1080-row frame of a crowded
globular cluster solved only at full size, a 4176-row one at -z 1 or 2."""


class Failure(StrEnum):
    """Why a frame was not solved, for clients to explain."""

    UNAVAILABLE = "unavailable"
    """ASTAP is not installed."""
    NO_DATABASE = "no_database"
    """No star database is installed for the frame's field."""
    NO_STARS = "no_stars"
    NO_SOLUTION = "no_solution"
    UNREADABLE = "unreadable"
    """ASTAP could not read the image."""
    ERROR = "error"


EXIT_CODES = {
    1: ("no solution found", Failure.NO_SOLUTION),
    2: ("not enough stars detected", Failure.NO_STARS),
    16: ("error reading the image", Failure.UNREADABLE),
    32: ("no star database found", Failure.NO_DATABASE),
    33: ("error reading the star database", Failure.ERROR),
}


class SolveError(Exception):
    """ASTAP did not solve the frame; the message says why, ``reason`` in a word."""

    def __init__(self, message: str, reason: Failure = Failure.ERROR) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Database:
    name: str
    """As ASTAP calls it, e.g. ``D50``."""
    min_fov: float
    max_fov: float
    """Frame heights it solves, degrees."""


@dataclass(frozen=True, slots=True)
class Hint:
    """Where the frame should be: J2000 RA (hours) and Dec (degrees), and how far to search."""

    ra: float
    dec: float
    radius: float = 10.0


def downsample_for(hfr: float | None, height: int, *, bayer: bool = False) -> int:
    """ASTAP's downsampling factor for a frame ``height`` rows high whose stars have a
    median half-flux radius of ``hfr`` pixels (``None``: unknown, no downsampling).

    A raw colour frame (``bayer``) is downsampled at least twice: at full size its
    focused stars are a checkerboard of the colour filters, which ASTAP rejects ("Not
    enough stars", "increase downsampling") while -z 2 solved the same ASI2600MC frame
    in 0.9 s on the Pi."""
    least = 2 if bayer else 1
    if hfr is None or not math.isfinite(hfr):
        return least
    by_stars = math.floor(2 * hfr / STAR_DIAMETER)
    by_size = height // ROWS_PER_STEP
    return max(least, min(MAX_DOWNSAMPLE, by_stars, by_size))


def find_databases(directory: Path) -> list[Database]:
    names = set[str]()
    if directory.is_dir():
        for path in directory.iterdir():
            match = _DATABASE_FILE.match(path.name.lower())
            if match and match.group(1) in DATABASE_FIELDS:
                names.add(match.group(1))
    return [
        Database(name.upper(), *DATABASE_FIELDS[name])
        for name in sorted(names, key=lambda n: DATABASE_FIELDS[n])
    ]


class Astap:
    def __init__(self, executable: Path, database_dir: Path) -> None:
        self.executable = executable
        self.database_dir = database_dir
        self.databases = find_databases(database_dir)

    @classmethod
    def find(cls, executable: Path | None = None, database_dir: Path | None = None) -> Astap | None:
        """ASTAP as configured, or where its packages install it; ``None`` if it is not there."""
        if executable is None:
            on_path = shutil.which("astap_cli")
            candidates = [Path(on_path)] if on_path else []
            executable = next((p for p in [*candidates, *SEARCH_PATHS] if p.is_file()), None)
            if executable is None:
                return None
        elif not executable.is_file():
            log.warning("ASTAP not found at %s", executable)
            return None
        if database_dir is None:
            database_dir = next(
                (d for d in (executable.parent, *DATABASE_PATHS) if find_databases(d)),
                executable.parent,
            )
        return cls(executable, database_dir)

    def database_for(self, fov: float) -> Database | None:
        """A star database that solves frames ``fov`` degrees high, if one is installed."""
        return next((d for d in self.databases if d.min_fov <= fov <= d.max_fov), None)

    async def version(self) -> str | None:
        try:
            with anyio.fail_after(10):
                result = await anyio.run_process(
                    [str(self.executable), "-h"], check=False, stderr=subprocess.STDOUT
                )
        except (OSError, TimeoutError) as error:
            log.warning("cannot run ASTAP at %s: %s", self.executable, error)
            return None
        match = _VERSION.search(result.stdout.decode(errors="replace"))
        return match.group(1) if match else None

    def command(
        self,
        image: Path,
        output: Path,
        *,
        fov: float | None,
        hint: Hint | None,
        downsample: int,
    ) -> list[str]:
        """The command line that solves ``image`` and writes ``output``.ini/.wcs.

        ``fov`` is the frame's height in degrees (``None``: unknown, ASTAP tries
        several); without ``hint`` the whole sky is searched.
        """
        # "slow" overlaps the search steps more. Near a hint it was as fast on every
        # frame tried, and solved a crowded globular cluster (0.36° field), a defocused
        # frame at -z 3 and a sparse simulator frame that the default missed; over the
        # whole sky it takes about twice as long, and found the cluster in 42 s where
        # the default gave up after 27 s.
        command = [
            str(self.executable),
            "-f",
            str(image),
            "-o",
            str(output),
            "-d",
            str(self.database_dir),
            "-z",
            str(downsample),
            "-fov",
            f"{fov:.4f}" if fov else "0",
            "-speed",
            "slow",
        ]
        if hint is None:
            return [*command, "-r", "180"]
        return [
            *command,
            "-ra",
            f"{hint.ra % 24:.6f}",
            "-spd",
            f"{hint.dec + 90:.6f}",
            "-r",
            f"{hint.radius:g}",
        ]

    async def solve(
        self,
        image: Path,
        size: tuple[int, int],
        *,
        fov: float | None,
        hint: Hint | None,
        downsample: int = 1,
        timeout: float,
        bottom_up: bool = False,
    ) -> Solution:
        """Solve ``image`` (``size`` = width, height in pixels); raises SolveError.

        The process is killed when the timeout expires or the caller is cancelled.
        """
        with tempfile.TemporaryDirectory(prefix="nocs-astap-") as tmp:
            output = Path(tmp) / "solution"
            command = self.command(image, output, fov=fov, hint=hint, downsample=downsample)
            log.debug("solving: %s", " ".join(command))
            try:
                with anyio.fail_after(timeout):
                    result = await anyio.run_process(
                        command, check=False, stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT
                    )
            except TimeoutError:
                raise SolveError(f"no solution within {timeout:g} s", Failure.NO_SOLUTION) from None
            except OSError as error:
                raise SolveError(f"cannot run ASTAP: {error}") from error
            ini = output.with_suffix(".ini")
            values = read_ini(ini) if ini.is_file() else {}
            if result.returncode != 0 or values.get("PLTSOLVD") != "T":
                message, reason = EXIT_CODES.get(
                    result.returncode,
                    (f"ASTAP exited with {result.returncode}", Failure.ERROR)
                    if result.returncode
                    else ("no solution found", Failure.NO_SOLUTION),
                )
                error = values.get("ERROR")
                # Too few stars exits with 1 like a failed search: only the .ini tells.
                if error and error.lower().startswith("not enough stars"):
                    reason = Failure.NO_STARS
                raise SolveError(error or message, reason)
            try:
                return solution_from_ini(values, *size, bottom_up=bottom_up)
            except SolutionError as error:
                raise SolveError(str(error)) from error
