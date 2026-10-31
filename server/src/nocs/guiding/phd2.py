"""Async client for PHD2's event server: JSON-RPC calls and events over one TCP connection.

PHD2 writes one JSON object per line. Objects with ``jsonrpc`` and an ``id`` answer
a call; every other object is an event, named by its ``Event`` field. The first
events after connecting describe PHD2's current state (``Version``, ``AppState``…).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from nocs.state import Json

log = logging.getLogger(__name__)

DEFAULT_PORT = 4400
CALL_TIMEOUT = 15.0
_LINE_LIMIT = 1 << 20
"""Events are small; ``get_star_image`` answers with a base64 image of ~10 KB."""


class Phd2Error(Exception):
    """PHD2 answered a call with an error."""

    def __init__(self, method: str, code: int | None, message: str) -> None:
        super().__init__(f"{method}: {message}")
        self.method = method
        self.code = code


class Phd2ConnectionError(ConnectionError):
    """The connection to PHD2 is closed, or closed while waiting for an answer."""


@dataclass(frozen=True, slots=True)
class Phd2Event:
    name: str
    data: dict[str, Json]


@dataclass(frozen=True, slots=True)
class Phd2Closed:
    reason: str


type Phd2Message = Phd2Event | Phd2Closed
type Listener = Callable[[Phd2Message], None]


class Phd2Client:
    def __init__(self, host: str = "localhost", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._listeners: list[Listener] = []
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Json]]] = {}
        self._next_id = 1
        self._write_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self, timeout: float = 5.0) -> None:
        reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, limit=_LINE_LIMIT), timeout
        )
        self._read_task = asyncio.create_task(self._read_loop(reader), name="phd2-read")

    async def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await self._writer.wait_closed()
            self._writer = None
        self._fail_pending("connection closed")

    async def __aenter__(self) -> Phd2Client:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def call(
        self,
        method: str,
        params: list[Json] | dict[str, Json] | None = None,
        timeout: float = CALL_TIMEOUT,
    ) -> Json:
        """Call a method and return its result; raises ``Phd2Error`` for an error answer."""
        if self._writer is None or self._writer.is_closing():
            raise Phd2ConnectionError("not connected to PHD2")
        call_id = self._next_id
        self._next_id += 1
        request: dict[str, Json] = {"method": method, "id": call_id}
        if params is not None:
            request["params"] = params
        future: asyncio.Future[dict[str, Json]] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        try:
            async with self._write_lock:
                self._writer.write(json.dumps(request).encode() + b"\r\n")
                await self._writer.drain()
            response = await asyncio.wait_for(future, timeout)
        except (ConnectionError, OSError) as e:
            raise Phd2ConnectionError(f"{method}: {e}") from e
        finally:
            self._pending.pop(call_id, None)
        error = response.get("error")
        if error is not None:
            code, message = None, str(error)
            if isinstance(error, dict):
                raw_code = error.get("code")
                code = raw_code if isinstance(raw_code, int) else None
                message = str(error.get("message", error))
            raise Phd2Error(method, code, message)
        return response.get("result")

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        reason = "connection closed by PHD2"
        try:
            while line := await reader.readline():
                self._handle(line)
        except (ConnectionError, OSError, ValueError) as e:  # ValueError: line over the limit
            reason = f"connection error: {e}"
        if self._writer is not None:
            self._writer.close()
        self._fail_pending(reason)
        self._emit(Phd2Closed(reason))

    def _handle(self, line: bytes) -> None:
        try:
            decoded: object = json.loads(line)
        except ValueError:
            log.warning("PHD2 sent something that is not JSON: %r", line[:200])
            return
        if not isinstance(decoded, dict):
            return
        message = cast(dict[str, Json], decoded)
        if "jsonrpc" in message:
            call_id = message.get("id")
            future = self._pending.get(call_id) if isinstance(call_id, int) else None
            if future is not None and not future.done():
                future.set_result(message)
            return
        name = message.get("Event")
        if isinstance(name, str):
            self._emit(Phd2Event(name, message))

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(Phd2ConnectionError(reason))
        self._pending.clear()

    def _emit(self, message: Phd2Message) -> None:
        for listener in list(self._listeners):
            try:
                listener(message)
            except Exception:
                log.exception("PHD2 listener failed")
