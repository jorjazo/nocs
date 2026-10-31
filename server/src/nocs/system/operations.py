"""The operations nocs-system performs (ADR 0027).

Each one validates its arguments, then runs the OS's own command-line tool with an
argument list, never through a shell, so no value can become a command.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import anyio
import anyio.to_thread

from nocs.system.protocol import HelperError, Message, validate_hostname


@dataclass(frozen=True, slots=True)
class Context:
    """Files operations change, replaced in tests."""

    hosts: Path = Path("/etc/hosts")


type Operation = Callable[[Context, Message], Awaitable[Message]]


async def run(*argv: str) -> str:
    """Run a tool; its standard output, or ``HelperError("failed")`` with its message."""
    try:
        result = await anyio.run_process(list(argv), check=False)
    except FileNotFoundError as e:
        raise HelperError("failed", f"{argv[0]} is not installed") from e
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise HelperError("failed", f"{argv[0]}: {detail or f'exit status {result.returncode}'}")
    return result.stdout.decode(errors="replace")


def _no_args(args: Message) -> None:
    if args:
        raise HelperError("invalid", f"unexpected arguments: {', '.join(sorted(args))}")


async def reboot(_: Context, args: Message) -> Message:
    _no_args(args)
    await run("systemctl", "reboot")
    return {}


async def power_off(_: Context, args: Message) -> Message:
    _no_args(args)
    await run("systemctl", "poweroff")
    return {}


async def set_hostname(context: Context, args: Message) -> Message:
    name = args.get("name")
    if not isinstance(name, str) or set(args) != {"name"}:
        raise HelperError("invalid", "the arguments are {name: <host name>}")
    name = validate_hostname(name)
    await run("hostnamectl", "set-hostname", name)
    await anyio.to_thread.run_sync(update_hosts, context.hosts, name)
    return {"name": name}


def update_hosts(path: Path, name: str) -> None:
    """Point ``127.0.1.1`` at the new name, as Ubuntu sets it up, so that sudo and
    other tools that look up their own host name keep finding it."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    entry = f"127.0.1.1\t{name}"
    updated = [entry if line.split()[:1] == ["127.0.1.1"] else line for line in lines]
    if entry not in updated:
        loopback = next((i for i, line in enumerate(updated) if line.startswith("127.0.0.1")), -1)
        updated.insert(loopback + 1, entry)
    new = path.with_name(f".{path.name}.nocs-system")
    new.write_text("\n".join(updated) + "\n")
    os.chmod(new, 0o644)
    new.replace(path)


OPERATIONS: dict[str, Operation] = {
    "power.reboot": reboot,
    "power.poweroff": power_off,
    "hostname.set": set_hostname,
}
