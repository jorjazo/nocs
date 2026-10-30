"""Equipment profiles: which devices make up a rig, their roles, optics and site.

Profiles are stored as one JSON file per profile in ``<config dir>/profiles/``,
named after the profile id, so they can be backed up, exported and edited by hand.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from nocs.indi.drivers import DRIVER_NAME

log = logging.getLogger(__name__)

PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
"""Profile ids are file names: lower-case letters, digits and dashes."""

type DriverName = Annotated[str, StringConstraints(pattern=DRIVER_NAME.pattern)]
"""An INDI driver executable. Restricted because it is written to indiserver's FIFO."""


class Role(StrEnum):
    MAIN_CAMERA = "main_camera"
    GUIDE_CAMERA = "guide_camera"
    MOUNT = "mount"
    FOCUSER = "focuser"
    FILTER_WHEEL = "filter_wheel"
    POWER_BOX = "power_box"


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceConfig(ProfileModel):
    driver: DriverName = Field(description="INDI driver executable, e.g. indi_asi_ccd.")
    device: str | None = Field(
        default=None,
        min_length=1,
        description="INDI device name. When omitted, the device of this driver that offers "
        "the role's interface is used; required when there are several.",
    )
    port: str | None = Field(
        default=None,
        min_length=1,
        description="Serial port for DEVICE_PORT, preferably a /dev/serial/by-id/ path.",
    )


class Optics(ProfileModel):
    focal_length: float = Field(gt=0, description="Native focal length in mm.")
    aperture: float | None = Field(default=None, gt=0, description="Aperture in mm.")
    reducer: float = Field(default=1.0, gt=0, description="Reducer or barlow factor.")


class Site(ProfileModel):
    name: str = ""
    latitude: float = Field(ge=-90, le=90, description="Degrees, north positive.")
    longitude: float = Field(ge=-180, le=180, description="Degrees, east positive.")
    elevation: float = Field(default=0.0, description="Metres above sea level.")


class Profile(ProfileModel):
    name: str = Field(min_length=1, max_length=80)
    devices: dict[Role, DeviceConfig] = Field(default_factory=dict[Role, DeviceConfig])
    imaging: Optics | None = Field(default=None, description="Optics of the imaging train.")
    guiding: Optics | None = Field(
        default=None, description="Optics of the guiding train (guide scope or OAG)."
    )
    site: Site | None = None


class ProfileError(Exception):
    pass


def check_id(profile_id: str) -> str:
    if not PROFILE_ID.fullmatch(profile_id):
        raise ProfileError(
            f"invalid profile id {profile_id!r}: use lower-case letters, digits and dashes"
        )
    return profile_id


class ProfileStore:
    """Profiles on disk, plus the id of the active one."""

    def __init__(self, config_dir: Path) -> None:
        self._dir = config_dir / "profiles"
        self._active_file = config_dir / "active-profile"

    def load_all(self) -> dict[str, Profile]:
        profiles: dict[str, Profile] = {}
        if not self._dir.is_dir():
            return profiles
        for path in sorted(self._dir.glob("*.json")):
            if not PROFILE_ID.fullmatch(path.stem):
                continue
            try:
                profiles[path.stem] = Profile.model_validate_json(path.read_bytes())
            except (OSError, ValidationError) as e:
                log.warning("ignoring unreadable profile %s: %s", path, e)
        return profiles

    def get(self, profile_id: str) -> Profile | None:
        path = self._path(profile_id)
        try:
            return Profile.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            return None

    def put(self, profile_id: str, profile: Profile) -> None:
        data = json.dumps(profile.model_dump(mode="json", exclude_none=True), indent=2) + "\n"
        write_atomic(self._path(profile_id), data)

    def delete(self, profile_id: str) -> bool:
        try:
            self._path(profile_id).unlink()
        except FileNotFoundError:
            return False
        return True

    @property
    def active(self) -> str | None:
        """The profile last connected, kept across restarts."""
        try:
            value = self._active_file.read_text().strip()
        except FileNotFoundError:
            return None
        return value if PROFILE_ID.fullmatch(value) else None

    @active.setter
    def active(self, profile_id: str | None) -> None:
        if profile_id is None:
            self._active_file.unlink(missing_ok=True)
        else:
            write_atomic(self._active_file, check_id(profile_id) + "\n")

    def _path(self, profile_id: str) -> Path:
        return self._dir / f"{check_id(profile_id)}.json"


def write_atomic(path: Path, data: str) -> None:
    """Write through a temporary file, so a crash never leaves half a file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
