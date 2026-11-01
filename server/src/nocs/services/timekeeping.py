"""The system clock: what keeps it, and setting it from a client when nothing does
(ADR 0029).

chrony is the only thing that disciplines the clock on the appliance: a GPS (a
reference clock, through gpsd) or NTP servers when the box is online. When neither
is selected and a client's clock says the system's is more than 5 s off, NOCS asks
nocs-system to step it to the client's time; never while a job runs, so a clock
does not jump in the middle of an exposure. ``nocs.clock`` keeps correcting NOCS's
own timestamps until then, and wherever nocs-system cannot (a PC).

Reading the source needs no privileges: ``chronyc -c sources`` (or timedatectl).
Having set the clock is remembered for the rest of the boot, across restarts of
nocsd, by writing the boot's id to a file: the clock stays known (phase 5.12 resumes
a sequence only once it is).
"""

from __future__ import annotations

import logging
from pathlib import Path

import anyio

from nocs.clock import Clock
from nocs.jobs import JobManager
from nocs.storage.service import SystemHelper

log = logging.getLogger(__name__)

CHECK = 30.0
"""Seconds between looks at the clock's source."""
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


async def clock_source() -> str:
    """``gps`` (a reference clock), ``ntp`` or ``none``."""
    sources = await _output("chronyc", "-c", "sources")
    if sources is not None:
        for line in sources.splitlines():
            fields = line.split(",")
            # Mode (^ server, = peer, # reference clock), then state (* selected).
            if len(fields) >= 2 and fields[1] == "*":
                return "gps" if fields[0] == "#" else "ntp"
        return "none"
    synced = await _output("timedatectl", "show", "--property=NTPSynchronized", "--value")
    return "ntp" if synced is not None and synced.strip() == "yes" else "none"


async def _output(*argv: str) -> str | None:
    try:
        result = await anyio.run_process(list(argv), check=False)
    except OSError:
        return None
    return result.stdout.decode(errors="replace") if result.returncode == 0 else None


class TimeKeeper:
    def __init__(
        self,
        clock: Clock,
        jobs: JobManager,
        helper: SystemHelper,
        *,
        memory: Path | None = None,
        boot_id: Path = BOOT_ID,
    ) -> None:
        """``memory``: where to remember that the clock was set from a client this boot."""
        self._clock = clock
        self._jobs = jobs
        self._helper = helper
        self._memory = memory
        self._boot = _read(boot_id)
        self._set_from_client = (
            memory is not None and self._boot is not None and _read(memory) == self._boot
        )
        self._reported = anyio.Event()
        clock.add_listener(lambda: self._reported.set())

    async def run(self) -> None:
        """Look every ``CHECK`` seconds, and as soon as a client reports its clock."""
        while True:
            await self.check()
            with anyio.move_on_after(CHECK):
                await self._reported.wait()
            self._reported = anyio.Event()

    async def check(self) -> None:
        source = await clock_source()
        if source == "none" and self._clock.corrected and await self._set():
            self._set_from_client = True
            self._remember()
        self._clock.set_source("client" if source == "none" and self._set_from_client else source)

    async def _set(self) -> bool:
        if not self._helper.offers("time.set") or self._jobs.active():
            return False
        offset = self._clock.offset
        try:
            await self._helper.perform("time.set", {"utc": self._clock.now().timestamp()})
        except Exception as e:  # nocs-system refused or failed: keep correcting timestamps
            log.warning("cannot set the system clock from the client's: %s", e)
            return False
        log.warning("set the system clock from a client's, %.1f s off before", offset or 0.0)
        self._clock.refresh()
        return True

    def _remember(self) -> None:
        if self._memory is None or self._boot is None:
            return
        try:
            self._memory.parent.mkdir(parents=True, exist_ok=True)
            self._memory.write_text(self._boot + "\n")
        except OSError as e:
            log.warning("cannot remember that the clock was set: %s", e)


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except OSError:
        return None
