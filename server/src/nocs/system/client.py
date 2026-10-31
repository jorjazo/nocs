"""nocsd's side of the socket: one connection per call (ADR 0027)."""

from __future__ import annotations

from pathlib import Path

import anyio
from anyio.streams.buffered import BufferedByteReceiveStream

from nocs.system.protocol import MAX_LINE, SOCKET, HelperError, Message, decode, encode


class HelperUnavailableError(Exception):
    """nocs-system is not running, or does not answer this user."""


async def call(
    op: str, args: Message | None = None, *, socket: Path = SOCKET, timeout: float = 10.0
) -> Message:
    """Perform ``op``; its result, or ``HelperError`` with the reason it was refused."""
    try:
        with anyio.fail_after(timeout):
            line = await _exchange(socket, encode({"id": 1, "op": op, "args": args or {}}))
    except TimeoutError as e:
        raise HelperUnavailableError(f"nocs-system did not answer within {timeout:g} s") from e
    reply = decode(line)
    error = reply.get("error")
    if isinstance(error, dict):
        code = error.get("code")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        message = error.get("message")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if code in ("invalid", "unknown", "disabled", "failed") and isinstance(message, str):
            raise HelperError(code, message)
    result = reply.get("result")
    if not isinstance(result, dict):
        raise HelperUnavailableError(f"nocs-system sent a reply NOCS cannot read: {reply}")
    return result  # pyright: ignore[reportUnknownVariableType]


async def _exchange(socket: Path, request: bytes) -> bytes:
    try:
        stream = await anyio.connect_unix(socket)
    except OSError as e:
        raise HelperUnavailableError(f"nocs-system is not running ({e.strerror})") from e
    async with stream:
        try:
            await stream.send(request)
            return await BufferedByteReceiveStream(stream).receive_until(b"\n", MAX_LINE)
        except (
            anyio.EndOfStream,
            anyio.IncompleteRead,
            anyio.DelimiterNotFound,
            anyio.BrokenResourceError,
        ) as e:
            # It hangs up without a word on a user it does not serve.
            raise HelperUnavailableError(
                "nocs-system closed the connection: does it allow the user nocsd runs as?"
            ) from e
