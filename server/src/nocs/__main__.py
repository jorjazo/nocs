"""nocsd entry point: ``uv run nocsd`` or ``python -m nocs``."""

import signal
from types import FrameType

import uvicorn

from nocs.api import create_app
from nocs.config import Settings
from nocs.logs import log_to_thread


def _stop(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(0)


def main() -> None:
    settings = Settings()
    # uvicorn stops on SIGINT and SIGTERM, then raises the signal again under the
    # handler it found. Python's own would end nocsd there and then, before the log
    # thread writes its last records and before multiprocessing's exit handlers
    # unlink the imaging worker's semaphores: this one ends it normally.
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    # uvicorn's loggers get no handlers of their own (log_config=None): their
    # records, the access log's too, reach the root logger's queue.
    with log_to_thread(settings.log_level):
        uvicorn.run(
            create_app(settings),
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
            log_config=None,
            # The client's address is the connection's: Tailscale pairing trusts it, and
            # an X-Forwarded-For from a local process (or a proxy passing one on) must
            # not make it a node of the tailnet.
            proxy_headers=False,
        )


if __name__ == "__main__":
    main()
