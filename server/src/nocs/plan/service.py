"""The plan on disk and in the state, and the ``Scheduler`` its run takes targets from.

Kept in ``<config dir>/plan.json`` and published whole under ``("plan",)``: every
client shows the same targets and how far each line is. Lines count their frames
here (``taken``), so a plan goes on where it was on another night; a client's
``done`` is never taken over (``put`` keeps the server's).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Collection
from datetime import datetime
from pathlib import Path

import anyio
from pydantic import ValidationError

from nocs.equipment.profiles import write_atomic
from nocs.plan.model import NightPlan, PlanTarget
from nocs.sequence import sky
from nocs.sequence.model import PlanRow, Target
from nocs.sequence.runner import Choice
from nocs.state import StateStore

log = logging.getLogger(__name__)

FILE_NAME = "plan.json"
STATE: tuple[str, ...] = ("plan",)


class PlanBusyError(Exception):
    """The change cannot be made while the plan runs."""


class PlanService:
    def __init__(
        self,
        store: StateStore,
        config_dir: Path,
        *,
        place: Callable[[], sky.Place | None] = lambda: None,
    ) -> None:
        self._store = store
        self._path = config_dir / FILE_NAME
        self._place = place
        self._lock = anyio.Lock()
        self.plan = self._load()
        self._publish()

    # -- editing ----------------------------------------------------------------------

    async def put(self, plan: NightPlan, *, running: bool = False) -> NightPlan:
        """Keep ``plan``, with the frames each line has here. While it runs, its targets
        and lines change (what it takes next) but not what it does around them."""
        if running and (
            plan.actions != self.plan.actions or plan.start_outputs != self.plan.start_outputs
        ):
            raise PlanBusyError("the plan is running: what it does around its targets is fixed")
        done = {line.id: line.done for target in self.plan.targets for line in target.lines}
        kept = plan.model_copy(deep=True)
        for target in kept.targets:
            for line in target.lines:
                line.done = done.get(line.id, 0)
        self.plan = kept
        await self._save()
        return kept

    async def reset(self, target_id: str) -> None:
        """Forget the frames a target's lines have: it starts again."""
        target = self.plan.target(target_id)
        if target is None:
            raise KeyError(target_id)
        for line in target.lines:
            line.done = 0
        await self._save()

    # -- the scheduler ------------------------------------------------------------------

    def choose(self, now: datetime, skipped: Collection[str]) -> Choice | None:
        place = self._place()
        if place is None:
            return None
        minimum = self.plan.actions.min_altitude or 0.0
        for target in self.plan.targets:
            if target.id in skipped or target.left == 0:
                continue
            altitude, horizon = sky.altitude(place, target.ra, target.dec, now)
            if altitude >= max(minimum, horizon):
                return _choice(target)
        return None

    def pending(self) -> bool:
        return self.plan.left > 0

    async def taken(self, choice: Choice, row: int) -> None:
        line_id = choice.lines[row]
        for target in self.plan.targets:
            for line in target.lines:
                if line.id == line_id:
                    line.done += 1
                    await self._save()
                    return
        log.info("a frame of a line no longer in the plan: %s", line_id)

    # -- storage ------------------------------------------------------------------------

    def _load(self) -> NightPlan:
        try:
            return NightPlan.model_validate_json(self._path.read_bytes())
        except FileNotFoundError:
            return NightPlan()
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._path, e)
            return NightPlan()

    async def _save(self) -> None:
        self._publish()
        async with self._lock:
            # What the plan is when the write starts: a later change writes again.
            data = self.plan.model_dump_json(indent=2) + "\n"
            await anyio.to_thread.run_sync(write_atomic, self._path, data)

    def _publish(self) -> None:
        self._store.set(STATE, self.plan.model_dump(mode="json"))


def _choice(target: PlanTarget) -> Choice:
    lines = [line for line in target.lines if line.left > 0]
    rows = [
        PlanRow(
            filter=line.filter,
            exposure=line.exposure,
            count=line.left,
            gain=line.gain,
            offset=line.offset,
        )
        for line in lines
    ]
    point = Target(name=target.name, ra=target.ra, dec=target.dec)
    # What the run takes: where it points and each line as set (not its count so far).
    revision = hashlib.sha256(
        "|".join(
            [
                f"{target.ra:.6f},{target.dec:.6f},{target.name}",
                *(
                    f"{line.id}:{line.filter}:{line.exposure}:{line.gain}:{line.offset}:{line.count}"
                    for line in target.lines
                ),
            ]
        ).encode()
    ).hexdigest()[:12]
    return Choice(
        key=target.id,
        target=point,
        rows=rows,
        lines=[line.id for line in lines],
        done=[line.done for line in lines],
        revision=revision,
    )
