"""The time NOCS trusts: the system clock, or the clients' when it is wrong.

In the field the Pi has no network time, and without a battery its clock starts
wherever it stopped. Clients report their own clock when they connect; when the
system clock is more than ``THRESHOLD`` seconds off, NOCS keeps time from the
client's report (advanced with the monotonic clock, which a later correction of
the system clock does not move) for what it timestamps itself: frame start times
and nights (ADR 0015), the mount's clock, and the horizon check. Where nocs-system
can, ``nocs.services.timekeeping`` also sets the system clock from the client's
report when nothing else keeps it (ADR 0029); this correction then drops to zero.

State under ``("clock",)``: ``{offset, measured, corrected, source}``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from nocs.state import Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("clock",)
TRUSTED_SOURCES = frozenset({"ntp", "gps", "client"})
"""System time sources that make the time known without a client reporting it now:
``client`` is a system clock a client's time set earlier this boot (ADR 0029)."""
THRESHOLD = 5.0
"""Seconds the system clock may be off before NOCS stops trusting it."""


class Clock:
    def __init__(
        self,
        store: StateStore,
        *,
        system: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._system = system
        self._monotonic = monotonic
        self._reference: tuple[datetime, float] | None = None
        """A client's time and the monotonic clock when it was reported."""
        self._utc_offset: float | None = None
        self._listeners: list[Callable[[], None]] = []
        self._source: str | None = None
        store.set(ROOT, {"offset": None, "measured": None, "corrected": False, "source": None})

    @property
    def known(self) -> bool:
        """Whether the time is known: a client confirmed (or corrected) it since nocsd
        started, NTP or a GPS keeps the system clock, or a client's time set it this
        boot (ADR 0029)."""
        return self._reference is not None or self._source in TRUSTED_SOURCES

    @property
    def offset(self) -> float | None:
        """Seconds the client clock is ahead of the system clock; ``None`` until reported."""
        if self._reference is None:
            return None
        return (self._client_now(self._reference) - self._system()).total_seconds()

    @property
    def corrected(self) -> bool:
        offset = self.offset
        return offset is not None and abs(offset) > THRESHOLD

    @property
    def correction(self) -> float:
        """Seconds to add to a time from the system clock (0 when it is trusted)."""
        offset = self.offset
        return offset if offset is not None and abs(offset) > THRESHOLD else 0.0

    @property
    def utc_offset(self) -> float | None:
        """The client's time zone, hours east of UTC, as last reported."""
        return self._utc_offset

    def now(self) -> datetime:
        if self._reference is not None and self.corrected:
            return self._client_now(self._reference)
        return self._system()

    def report(self, client: datetime, utc_offset: float | None = None) -> float:
        """A client's clock reading (and time zone); returns the offset in seconds."""
        if client.tzinfo is None:
            raise ValueError("the client time must carry its time zone (UTC)")
        self._reference = (client.astimezone(UTC), self._monotonic())
        if utc_offset is not None:
            self._utc_offset = utc_offset
        offset = self.offset
        assert offset is not None
        if abs(offset) > THRESHOLD:
            log.warning("system clock is %.1f s off the client's; using the client's", -offset)
        self.refresh()
        for listener in list(self._listeners):
            listener()
        return offset

    def refresh(self) -> None:
        """Publish the offset again: after the system clock was set, it is close to zero."""
        offset = self.offset
        if offset is None:
            return
        with self._store.transaction():
            self._store.set((*ROOT, "offset"), round(offset, 3))
            self._store.set((*ROOT, "measured"), self.now().isoformat(timespec="seconds"))
            self._store.set((*ROOT, "corrected"), abs(offset) > THRESHOLD)

    def set_source(self, source: str | None) -> None:
        """Where the system time comes from: gps, ntp, client or none (ADR 0029)."""
        if source != self._source:
            was_known = self.known
            self._source = source
            self._store.set((*ROOT, "source"), source)
            if self.known and not was_known:
                for listener in list(self._listeners):
                    listener()

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` after every client report, and when the time becomes known."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _client_now(self, reference: tuple[datetime, float]) -> datetime:
        client, monotonic = reference
        return client + timedelta(seconds=self._monotonic() - monotonic)
