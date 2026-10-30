"""HTTP and WebSocket API of nocsd."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from nocs import __version__
from nocs.api.schemas import (
    Health,
    Hello,
    PatchMessage,
    ServerMessage,
    SetPropertyRequest,
    SnapshotMessage,
    StateSnapshot,
)
from nocs.config import Settings
from nocs.services.indi_bridge import IndiBridge, NotConnectedError
from nocs.state import Resync, StateStore

log = logging.getLogger(__name__)

_HELLO_TIMEOUT = 5.0


def create_app(settings: Settings, store: StateStore | None = None) -> FastAPI:
    store = store if store is not None else StateStore()
    bridge = IndiBridge(store, settings.indi_host, settings.indi_port)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        task = asyncio.create_task(bridge.run(), name="indi-bridge")
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="NOCS", version=__version__, lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> Health:  # pyright: ignore[reportUnusedFunction]
        return Health(version=__version__, indi_connected=bridge.client is not None)

    @app.get("/api/state")
    async def state() -> StateSnapshot:  # pyright: ignore[reportUnusedFunction]
        return StateSnapshot(version=store.version, state=store.snapshot())

    @app.post("/api/indi/devices/{device}/properties/{name}", status_code=status.HTTP_202_ACCEPTED)
    async def set_property(  # pyright: ignore[reportUnusedFunction]
        device: str, name: str, request: SetPropertyRequest
    ) -> None:
        try:
            await bridge.set_property(device, name, request.values)
        except NotConnectedError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
        except KeyError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e.args[0])) from e
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), _HELLO_TIMEOUT)
            hello = Hello.model_validate_json(raw)
        except (TimeoutError, ValidationError):
            hello = Hello()
        except WebSocketDisconnect:
            return
        since = hello.since if hello.epoch == store.epoch else None
        await _stream_state(websocket, store, since)

    if settings.web_dir is not None and settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app


async def _stream_state(websocket: WebSocket, store: StateStore, since: int | None) -> None:
    """Send the client what it is missing, then every change as it happens."""
    subscription = store.subscribe()

    async def send(message: ServerMessage) -> None:
        await websocket.send_text(message.model_dump_json())

    async def sender() -> None:
        missed = store.patches_since(since) if since is not None else None
        if missed is None:
            last = store.version
            await send(SnapshotMessage(epoch=store.epoch, version=last, state=store.snapshot()))
        else:
            last = since if since is not None else 0
            for patch in missed:
                await send(PatchMessage.from_patch(patch))
                last = patch.version
        while True:
            item = await subscription.get()
            if isinstance(item, Resync):
                last = store.version
                await send(SnapshotMessage(epoch=store.epoch, version=last, state=store.snapshot()))
            elif item.version > last:
                await send(PatchMessage.from_patch(item))
                last = item.version

    async def receiver() -> None:
        # Clients have nothing more to say yet; this only detects disconnection.
        while True:
            await websocket.receive_text()

    # A TaskGroup (not bare tasks) so that cancellation of this handler, e.g. by the
    # server on shutdown, propagates correctly and both halves always stop together.
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(sender())
            group.create_task(receiver())
    except* WebSocketDisconnect:
        pass
    except* Exception as errors:
        log.warning("websocket closed with error: %r", errors.exceptions)
    finally:
        subscription.close()
