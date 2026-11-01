"""nocsd entry point: ``uv run nocsd`` or ``python -m nocs``."""

import uvicorn

from nocs.api import create_app
from nocs.config import Settings
from nocs.logs import log_to_thread


def main() -> None:
    settings = Settings()
    # uvicorn's loggers get no handlers of their own (log_config=None): their
    # records, the access log's too, reach the root logger's queue.
    with log_to_thread(settings.log_level):
        uvicorn.run(
            create_app(settings),
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
            log_config=None,
        )


if __name__ == "__main__":
    main()
