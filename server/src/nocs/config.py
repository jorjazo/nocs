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
