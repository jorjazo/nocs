import os
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _default_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "nocs"


def _default_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "nocs"


class Settings(BaseSettings):
    """nocsd configuration, read from ``NOCS_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="NOCS_")

    host: str = "127.0.0.1"
    port: int = 8000
    hostnames: Annotated[list[str], NoDecode] = Field(default_factory=list[str])
    """Names clients may reach nocsd by besides IP addresses, ``localhost`` and ``*.local``
    (comma-separated in ``NOCS_HOSTNAMES``); any other ``Host`` is refused (ADR 0014)."""
    indi_host: str = "localhost"
    indi_port: int = 7624
    indi_fifo: Path | None = None
    """indiserver's driver FIFO (``indiserver -f``); without it, drivers cannot be started."""
    indi_drivers_dir: Path = Path("/usr/share/indi")
    """Where the INDI driver catalog (``drivers.xml`` and third-party XML files) lives."""
    indi_upload_dir: Path | None = None
    """Where the main camera's driver saves frames itself (UPLOAD_LOCAL), as indiserver
    sees it. Without it, and always for the guide camera, frames arrive as BLOBs (ADR 0012)."""
    indi_upload_dir_local: Path | None = None
    """The same directory as nocsd sees it, when that differs (indiserver in a container)."""
    astap: Path | None = None
    """The ASTAP command-line solver; by default ``astap_cli`` on the PATH or in /opt/astap."""
    astap_db: Path | None = None
    """ASTAP's star databases; by default next to the solver or in /opt/astap."""
    phd2_host: str = "localhost"
    phd2_port: int = 4400
    """PHD2's JSON-RPC event server (ADR 0022)."""
    phd2_settings: Path | None = None
    """The settings file PHD2's service imports at start. nocsd writes it from the active
    profile; without it, nocsd uses PHD2 as the user set it up."""
    phd2_indi_host: str | None = None
    """indiserver as PHD2 reaches it, when that differs from ``indi_host`` (containers)."""
    phd2_indi_port: int | None = None
    system_socket: Path = Path("/run/nocs-system/socket")
    """nocs-system's socket (ADR 0027); without it, NOCS cannot reboot the box or rename it."""
    config_dir: Path = Field(default_factory=_default_config_dir)
    data_dir: Path = Field(default_factory=_default_data_dir)
    """The server's own data: frame catalog, previews, frames on their way."""
    storage_dir: Path | None = None
    """The internal storage destination (ADR 0013); defaults to the data directory."""
    web_dir: Path | None = None
    log_level: str = "info"

    @field_validator("hostnames", mode="before")
    @classmethod
    def _split_hostnames(cls, value: object) -> object:
        if isinstance(value, str):
            return [name.strip() for name in value.split(",") if name.strip()]
        return value
