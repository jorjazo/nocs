"""Tonight's target, as the Plan screen chose it (stage 3.6).

One target at a time, kept in ``<config dir>/plan.json`` so it survives a restart
and published as ``plan.target`` so every client (Tonight, Plan, later the
sequence builder) shows the same one.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nocs.equipment.profiles import write_atomic
from nocs.state import StateStore

log = logging.getLogger(__name__)

FILE_NAME = "plan.json"
STATE: tuple[str, ...] = ("plan",)


class PlannedTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None, max_length=50, description="Catalog id (e.g. NGC 292); None: coordinates."
    )
    name: str = Field(min_length=1, max_length=100, description="What to call it.")
    ra: float = Field(ge=0, lt=24, description="J2000 hours where the frame points.")
    dec: float = Field(ge=-90, le=90, description="J2000 degrees where the frame points.")
    rotation: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="Wanted angle of the frame's top, degrees east of north; None: any.",
    )


class PlanService:
    def __init__(self, store: StateStore, config_dir: Path) -> None:
        self._store = store
        self._path = config_dir / FILE_NAME
        self.target = self._load()
        self._publish()

    def set(self, target: PlannedTarget | None) -> None:
        if target is None:
            self._path.unlink(missing_ok=True)
        else:
            write_atomic(self._path, target.model_dump_json(indent=2) + "\n")
        self.target = target
        self._publish()

    def _load(self) -> PlannedTarget | None:
        try:
            return PlannedTarget.model_validate_json(self._path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._path, e)
            return None

    def _publish(self) -> None:
        target = self.target.model_dump() if self.target else None
        self._store.set(STATE, {"target": target})
