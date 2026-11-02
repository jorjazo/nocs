"""nocs-system: the privileged helper's daemon and a command line to call it (ADR 0027).

    nocs-system                       serve on the socket (run by nocs-system.service)
    nocs-system call <op> [<json>]    perform one operation, as nocsd would

Configuration in ``/etc/nocs/system.conf`` (``NOCS_SYSTEM_CONFIG``), then the files
in ``/etc/nocs/system.conf.d/``::

    [helper]
    user = nocs                 # the only user served, besides root
    [operations]
    enabled = power hostname storage    # groups of operations to perform

The socket is ``/run/nocs-system/socket`` (``NOCS_SYSTEM_SOCKET``), mode 0660 with
the served user's group. A connection from any other user is closed unanswered.
"""

from __future__ import annotations

import argparse
import configparser
import functools
import json
import logging
import os
import pwd
import socket
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import anyio
from anyio.abc import SocketAttribute, SocketStream, TaskStatus
from anyio.streams.buffered import BufferedByteReceiveStream

from nocs.system import client
from nocs.system.network import Network
from nocs.system.operations import OPERATIONS, Context
from nocs.system.protocol import (
    GROUPS,
    HELLO,
    MAX_LINE,
    SOCKET,
    VERSION,
    HelperError,
    Message,
    decode,
    encode,
    redact,
)
from nocs.system.updates import Updates

log = logging.getLogger("nocs.system")

CONFIG = Path("/etc/nocs/system.conf")


@dataclass(frozen=True, slots=True)
class Config:
    uid: int
    """The user served (besides root)."""
    gid: int
    """Its group, which owns the socket."""
    enabled: frozenset[str] = frozenset()
    """Groups of operations switched on."""
    socket: Path = SOCKET
    context: Context = field(default_factory=Context)


def load_config(path: Path, socket_path: Path = SOCKET) -> Config:
    """Read ``path``, then ``<path>.d/*.conf`` in order, later settings winning (the
    appliance switches its operations on there); none serves ``nocs`` with every
    operation off."""
    parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
    parser.read([path, *sorted(path.with_name(f"{path.name}.d").glob("*.conf"))])
    user = pwd.getpwnam(parser.get("helper", "user", fallback="nocs"))
    groups = parser.get("operations", "enabled", fallback="").replace(",", " ").split()
    known = set(GROUPS.values())
    for group in sorted(set(groups) - known):
        log.warning("%s: unknown group of operations %r", path, group)
    enabled = frozenset(groups) & known
    return Config(
        uid=user.pw_uid,
        gid=user.pw_gid,
        enabled=enabled,
        socket=socket_path,
        context=Context(
            owner=user.pw_name,
            network=Network() if "network" in enabled else None,
            updates=Updates() if "update" in enabled else None,
        ),
    )


class Helper:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = anyio.Lock()
        """One operation at a time, whoever asks."""

    def operations(self) -> list[str]:
        return [op for op, group in GROUPS.items() if group in self._config.enabled]

    async def serve(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        path = self._config.socket
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        listener = await anyio.create_unix_listener(path)
        os.chmod(path, 0o660)
        if os.geteuid() == 0:
            os.chown(path, 0, self._config.gid)
        log.info("serving %s, operations: %s", path, ", ".join(self.operations()) or "none")
        task_status.started()
        async with anyio.create_task_group() as tg:
            if self._config.context.network is not None:
                tg.start_soon(self._config.context.network.run)
            if self._config.context.updates is not None:
                tg.start_soon(self._config.context.updates.run)
            await listener.serve(self._connection)

    async def reply(self, line: bytes) -> Message:
        request_id: object = None
        try:
            request = decode(line)
            request_id = request.get("id")
            op, args = request.get("op"), request.get("args", {})
            if not isinstance(op, str) or not isinstance(args, dict):
                raise HelperError("invalid", 'a request is {"id", "op": <name>, "args": {…}}')
            if op == HELLO:
                hello = {"version": VERSION, "operations": self.operations()}
                return {"id": request_id, "result": hello}
            group = GROUPS.get(op)
            if group is None:
                raise HelperError("unknown", f"no operation {op!r}")
            if group not in self._config.enabled:
                raise HelperError("disabled", f"{op} is switched off (group {group!r} in {CONFIG})")
            async with self._lock:
                log.info("%s %s", op, json.dumps(redact(args)))  # pyright: ignore[reportUnknownArgumentType]
                result = await OPERATIONS[op](self._config.context, args)  # pyright: ignore[reportUnknownArgumentType]
        except HelperError as e:
            log.info("%s: %s", e.code, e)
            return {"id": request_id, "error": {"code": e.code, "message": str(e)}}
        except Exception as e:
            log.exception("operation failed")
            return {"id": request_id, "error": {"code": "failed", "message": str(e)}}
        return {"id": request_id, "result": result}

    async def _connection(self, stream: SocketStream) -> None:
        """One client; whatever it does, the helper serves the next one."""
        try:
            async with stream:
                await self._converse(stream)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError, ConnectionError):
            log.info("a client left before its reply")
        except Exception:
            log.exception("connection failed")

    async def _converse(self, stream: SocketStream) -> None:
        uid = peer_uid(stream)
        if uid not in (self._config.uid, 0):
            log.warning("refused a connection from uid %d", uid)
            return
        receive = BufferedByteReceiveStream(stream)
        while True:
            try:
                line = await receive.receive_until(b"\n", MAX_LINE)
            except (anyio.EndOfStream, anyio.IncompleteRead):
                return
            except anyio.DelimiterNotFound:
                error = {"code": "invalid", "message": f"a message is at most {MAX_LINE} bytes"}
                await stream.send(encode({"id": None, "error": error}))
                return
            await stream.send(encode(await self.reply(line)))


def peer_uid(stream: SocketStream) -> int:
    raw = stream.extra(SocketAttribute.raw_socket)
    credentials = raw.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", credentials)
    return uid


def main() -> None:
    parser = argparse.ArgumentParser(prog="nocs-system", description="NOCS's privileged helper.")
    commands = parser.add_subparsers(dest="command")
    call = commands.add_parser("call", help="perform one operation and print its result")
    call.add_argument("op")
    call.add_argument("args", nargs="?", default="{}", help="JSON object")
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    socket_path = Path(os.environ.get("NOCS_SYSTEM_SOCKET", SOCKET))
    if options.command == "call":
        try:
            args = json.loads(options.args)
            result = anyio.run(functools.partial(client.call, options.op, args, socket=socket_path))
        except (HelperError, client.HelperUnavailableError, json.JSONDecodeError) as e:
            sys.exit(f"nocs-system: {e}")
        print(json.dumps(result))
        return
    config = load_config(Path(os.environ.get("NOCS_SYSTEM_CONFIG", CONFIG)), socket_path)
    anyio.run(Helper(config).serve)


if __name__ == "__main__":
    main()
