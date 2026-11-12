"""What each step of the night's preparation needs before it can run (ADR 0041).

Tonight's checklist (connect, polar align, focus, frame the target, guide) offers a
step as the next one only when it can run, and shows any other step blocked with what
is missing and where to fix it. This service works that out from the state and the
services, so that the checklist and the steps' own screens agree with what the server
will refuse, and publishes it under ``("preparation",)``::

    {polar_align, focus, frame, guide: {applies, blockers: [{reason, role, message}]}}

``applies``: the active profile has the roles the step uses (a rig without a focuser
has no focusing step). ``blockers``: what stops the step now, the most basic first;
empty when it can run. What a step settles on its own screen is not a blocker: where
the mount points (polar alignment goes to its start), a target to frame (the step
chooses one), another job holding the mount for a while.

Where each precondition is met: the site and the plate solver belong to the box (its
active site, ASTAP and a star database); the devices to Connect, which also sends the
mount the site and the time (``MountService``); the mount being unparked to the mount.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from nocs.devices import Location
from nocs.equipment import Role
from nocs.solving import Failure, SolveError
from nocs.state import Json, Patch, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("preparation",)

WATCHED: tuple[Path, ...] = (
    ("equipment",),
    ("sites",),
    ("solver", "available"),
    ("solver", "databases"),
    ("mount", "parked"),
    ("cameras", Role.MAIN_CAMERA.value, "field"),
    ("guiding", "phd2"),
)
"""The state the blockers follow: a change under (or above) one of these paths."""


class Step(StrEnum):
    POLAR_ALIGN = "polar_align"
    FOCUS = "focus"
    FRAME = "frame"
    GUIDE = "guide"


class Reason(StrEnum):
    NOT_CONNECTED = "not_connected"
    """The profile is not connected (no role), or that role's device is not ready."""
    NO_SITE = "no_site"
    """The box has no active site."""
    NO_SOLVER = "no_solver"
    """ASTAP is not installed."""
    NO_DATABASE = "no_database"
    """No star database solves the main camera's field."""
    PARKED = "parked"
    NO_PHD2 = "no_phd2"
    """NOCS cannot reach PHD2."""


@dataclass(frozen=True, slots=True)
class Blocker:
    reason: Reason
    message: str
    role: Role | None = None

    def summary(self) -> dict[str, Json]:
        return {
            "reason": self.reason.value,
            "role": self.role.value if self.role else None,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class Facts:
    """What the blockers are worked out from."""

    roles: dict[Role, str]
    """The active profile's roles and their devices' status (``ready``…)."""
    connected: bool
    """The profile is connected (some of its devices may still not be ready)."""
    site: bool
    """The box has an active site."""
    solver: SolveError | None
    """What a solve with the main camera would fail on before solving."""
    parked: bool
    """The mount is ready and parked."""
    phd2: bool
    """NOCS reaches PHD2."""


NEEDS: dict[Step, tuple[Role, ...]] = {
    Step.POLAR_ALIGN: (Role.MOUNT, Role.MAIN_CAMERA),
    Step.FOCUS: (Role.FOCUSER, Role.MAIN_CAMERA),
    Step.FRAME: (Role.MOUNT, Role.MAIN_CAMERA),
    Step.GUIDE: (Role.GUIDE_CAMERA, Role.MOUNT),
}
"""The devices each step uses; a profile without one of them has no such step."""


def blockers(step: Step, facts: Facts) -> list[Blocker]:
    """What stops ``step`` now, the most basic first."""
    found = _connection(NEEDS[step], facts)
    if step is Step.POLAR_ALIGN and not facts.site:
        found.append(
            Blocker(
                Reason.NO_SITE,
                "polar alignment needs the site, if only roughly: choose or add one",
            )
        )
    if step in (Step.POLAR_ALIGN, Step.FRAME) and facts.solver is not None:
        unavailable = facts.solver.reason is Failure.UNAVAILABLE
        found.append(
            Blocker(Reason.NO_SOLVER if unavailable else Reason.NO_DATABASE, str(facts.solver))
        )
    if step is not Step.FOCUS and facts.parked:
        found.append(Blocker(Reason.PARKED, "the mount is parked: unpark it"))
    if step is Step.GUIDE and not facts.phd2:
        found.append(Blocker(Reason.NO_PHD2, "NOCS cannot reach PHD2"))
    return found


def assess(facts: Facts) -> dict[str, Json]:
    """The state under ``ROOT``."""
    return {
        step.value: {
            "applies": all(role in facts.roles for role in NEEDS[step]),
            "blockers": [b.summary() for b in blockers(step, facts)],
        }
        for step in Step
    }


def _connection(roles: tuple[Role, ...], facts: Facts) -> list[Blocker]:
    missing = [role for role in roles if facts.roles.get(role) != "ready"]
    if not missing:
        return []
    if not facts.connected:
        return [Blocker(Reason.NOT_CONNECTED, "connect the equipment profile")]
    return [
        Blocker(Reason.NOT_CONNECTED, f"the {role.value.replace('_', ' ')} is not ready", role)
        for role in missing
    ]


class Solver(Protocol):
    """``SolverService``."""

    def check(self, fov: float | None) -> object: ...


class PreparationService:
    def __init__(
        self, store: StateStore, solver: Solver, site: Callable[[], Location | None]
    ) -> None:
        self._store = store
        self._solver = solver
        self._site = site
        self._published: dict[str, Json] | None = None
        self.refresh()

    def refresh(self) -> None:
        """Work the blockers out again and publish them if they changed."""
        summary = assess(self.facts())
        if summary != self._published:
            self._store.set(ROOT, summary)
            self._published = summary

    def facts(self) -> Facts:
        store = self._store
        devices = store.get(("equipment", "devices"))
        roles: dict[Role, str] = {}
        if isinstance(devices, dict):
            for name, device in devices.items():
                if name in Role and isinstance(device, dict):
                    status = device.get("status")
                    roles[Role(name)] = status if isinstance(status, str) else ""
        height = store.get(("cameras", Role.MAIN_CAMERA.value, "field", "height"))
        try:
            self._solver.check(float(height) if isinstance(height, int | float) else None)
            solver = None
        except SolveError as e:
            solver = e
        phd2 = store.get(("guiding", "phd2", "connected"))
        return Facts(
            roles=roles,
            connected=store.get(("equipment", "connection")) == "connected",
            site=self._site() is not None,
            solver=solver,
            parked=store.get(("mount", "parked")) is True,
            phd2=phd2 is True,
        )

    async def run(self) -> None:
        """Follow the state until cancelled."""
        subscription = self._store.subscribe()
        try:
            self._refresh_logged()
            while True:
                patch = await subscription.get()
                if not isinstance(patch, Patch) or any(_watched(op.path) for op in patch.ops):
                    self._refresh_logged()
        finally:
            subscription.close()

    def _refresh_logged(self) -> None:
        """``refresh``, logging a failure instead of ending ``run``: the blockers would
        stay stale until a restart."""
        try:
            self.refresh()
        except Exception:
            log.exception("could not work out what blocks the preparation steps")


def _watched(path: Path) -> bool:
    return any(w[: len(path)] == path or path[: len(w)] == w for w in WATCHED)
