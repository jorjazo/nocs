import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "nocs"


class Settings(BaseSettings):
    """nocsd configuration, read from ``NOCS_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="NOCS_")

    host: str = "127.0.0.1"
    port: int = 8000
    indi_host: str = "localhost"
    indi_port: int = 7624
    indi_fifo: Path | None = None
    """indiserver's driver FIFO (``indiserver -f``); without it, drivers cannot be started."""
    indi_drivers_dir: Path = Path("/usr/share/indi")
    """Where the INDI driver catalog (``drivers.xml`` and third-party XML files) lives."""
    config_dir: Path = Field(default_factory=_default_config_dir)
    web_dir: Path | None = None
    log_level: str = "info"
