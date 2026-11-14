"""Settings per physical focuser, apart from profiles (ADR 0016): its backlash.

``<config dir>/focusers.json`` maps a focuser's key (``Device.key``) to how
autofocus takes up its backlash (ADR 0021): the direction every position is
reached from, and how far a move the other way overshoots its target; and to the
focuser's last calibration (ADR 0044).
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
    calibration: FocuserCalibration | None = Field(
        default=None, description="The last calibration that succeeded."
    )


class FocuserCalibration(BaseModel):
    """What a calibration measured (ADR 0044)."""

    model_config = ConfigDict(extra="forbid")

    measured: str = Field(description="When it finished, UTC ISO 8601.")
    profile: str | None = Field(description="The equipment profile it was measured with.")
    inward: list[int] = Field(description="Motion lost reversing to move inward, steps.")
    outward: list[int] = Field(description="Motion lost reversing to move outward, steps.")
    overshoot: int = Field(ge=0, description="The overshoot that passed the round trips.")
    noise: float = Field(
        ge=0, description="Noise of a frame's position on the arm, steps (standard deviation)."
    )
    min_step: int = Field(ge=1, description="The smallest significant move, steps.")
    microns_per_step: float | None = Field(
        default=None, description="Drawtube travel per step; None without the optics."
    )
    focus_zone: int | None = Field(
        default=None, description="The critical focus zone, steps; None without the optics."
    )
    slip: bool = Field(default=False, description="The optics followed the motor only in part.")


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
