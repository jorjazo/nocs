"""nocsd entry point: ``uv run nocsd`` or ``python -m nocs``."""

import logging

import uvicorn

from nocs.api import create_app
from nocs.config import Settings


def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
