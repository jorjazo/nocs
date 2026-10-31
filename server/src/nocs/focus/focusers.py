"""Settings per physical focuser, apart from profiles (ADR 0016): its backlash.

``<config dir>/focusers.json`` maps a focuser's key (``Device.key``) to how
autofocus takes up its backlash (ADR 0021): the direction every position is
reached from, and how far a move the other way overshoots its target.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nocs.equipment.profiles import write_atomic

log = logging.getLogger(__name__)

FILE_NAME = "focusers.json"


class FocuserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["outward", "inward"] = Field(
        default="outward", description="Which way every position is reached."
    )
    overshoot: int | None = Field(
        default=None,
        ge=0,
        le=100000,
        description="Steps past a target when moving the other way; None: one sweep step.",
    )


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focusers: dict[str, FocuserConfig] = Field(default_factory=dict[str, FocuserConfig])


class FocuserStore:
    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / FILE_NAME

    def load(self) -> dict[str, FocuserConfig]:
        try:
            return _File.model_validate_json(self._path.read_bytes()).focusers
        except FileNotFoundError:
            return {}
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._path, e)
            return {}

    def get(self, key: str) -> FocuserConfig:
        """The focuser's settings; the defaults for one NOCS has not seen."""
        return self.load().get(key) or FocuserConfig()

    def put(self, key: str, config: FocuserConfig) -> None:
        focusers = self.load()
        focusers[key] = config
        write_atomic(self._path, _File(focusers=focusers).model_dump_json(indent=2) + "\n")
