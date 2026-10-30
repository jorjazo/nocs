from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """nocsd configuration, read from ``NOCS_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="NOCS_")

    host: str = "127.0.0.1"
    port: int = 8000
    indi_host: str = "localhost"
    indi_port: int = 7624
    web_dir: Path | None = None
    log_level: str = "info"
