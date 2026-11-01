"""Updates of the box from apt, only when the owner asks (ADR 0025).

Checking runs ``apt-get update`` and lists what would be upgraded. Installing and
rolling back run in a transient systemd unit of their own (``nocs-update``): an
upgrade of the ``nocs`` package restarts nocs-system and nocsd, and must not kill
the apt or dpkg that is doing it. Their progress and result are read back from that
unit and its journal, so they survive the restarts they cause.

Before installing, the installed version of ``nocs`` is kept; rolling back installs
it again from apt's cache with dpkg.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import anyio

from nocs.system.protocol import HelperError, Message

log = logging.getLogger("nocs.system")

UNIT = "nocs-update"
CHECK_TIMEOUT = 600.0
LOG_LINES = 40
_UPGRADABLE = re.compile(r"^(\S+)/\S+\s+(\S+)\s+\S+\s+\[upgradable from: (\S+)\]")

type Task = Literal["check", "install", "rollback"]


@dataclass(frozen=True, slots=True)
class UpdatePaths:
    state: Path = Path("/var/lib/nocs-system/updates.json")
    archives: Path = Path("/var/cache/apt/archives")


class Updates:
    def __init__(self, paths: UpdatePaths | None = None) -> None:
        self._paths = paths or UpdatePaths()
        self._saved = self._load()
        self._checking = False
        self._error: str | None = None
        self._pending: Task | None = None
        self._wake = anyio.Event()

    # -- operations --------------------------------------------------------------

    async def status(self, _: Message) -> Message:
        unit = await self._unit()
        if self._checking or self._pending == "check":
            state = "checking"
        elif unit in ("active", "activating") or self._pending in ("install", "rollback"):
            state = "installing"
        elif unit == "failed":
            state = "failed"
        elif unit == "inactive" and self._saved.get("task") in ("install", "rollback"):
            state = "succeeded"
        else:
            state = "idle"
        return {
            "state": state,
            "task": self._saved.get("task"),
            "upgradable": self._saved.get("upgradable", []),
            "checked": self._saved.get("checked"),
            "installed": await _nocs_version(),
            "previous": self._saved.get("previous"),
            "error": self._error,
            "log": await self._log() if self._saved.get("task") in ("install", "rollback") else [],
        }

    async def check(self, args: Message) -> Message:
        return self._ask("check", args)

    async def install(self, args: Message) -> Message:
        return self._ask("install", args)

    async def rollback(self, args: Message) -> Message:
        if not self._saved.get("previous"):
            raise HelperError("invalid", "no earlier version of NOCS to go back to")
        return self._ask("rollback", args)

    def _ask(self, task: Task, args: Message) -> Message:
        if args:
            raise HelperError("invalid", f"unexpected arguments: {', '.join(sorted(args))}")
        if self._pending is not None or self._checking:
            raise HelperError("invalid", "an update is already being checked or installed")
        self._pending = task
        self._wake.set()
        return {"accepted": True}

    # -- the actor ---------------------------------------------------------------

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake = anyio.Event()
            task, self._error = self._pending, None
            try:
                if task == "check":
                    await self._check()
                elif task == "install":
                    await self._install()
                elif task == "rollback":
                    await self._rollback()
            except HelperError as e:
                log.warning("update %s: %s", task, e)
                self._error = str(e)
            except Exception as e:  # the actor must outlive any one failure
                log.exception("update %s failed", task)
                self._error = str(e)
            finally:
                self._pending = None

    async def _check(self) -> None:
        self._checking, self._pending = True, None
        self._saved["task"] = None  # what was installed last is old news after a new look
        try:
            with anyio.fail_after(CHECK_TIMEOUT):
                await _run("apt-get", "update")
                listing = await _run("apt", "list", "--upgradable")
        except TimeoutError as e:
            raise HelperError("failed", "apt did not finish checking within 10 minutes") from e
        finally:
            self._checking = False
        upgradable = [
            {"name": m[1], "to": m[2], "from": m[3]}
            for line in listing.splitlines()
            if (m := _UPGRADABLE.match(line))
        ]
        self._saved |= {"upgradable": upgradable, "checked": time.time()}
        self._save()

    async def _install(self) -> None:
        if await self._unit() in ("active", "activating"):
            raise HelperError("invalid", "an update is already being installed")
        self._saved |= {"task": "install", "previous": await _nocs_version()}
        self._save()
        await self._start(
            "apt-get", "-y", "-o", "Dpkg::Options::=--force-confold", "upgrade", "--with-new-pkgs"
        )

    async def _rollback(self) -> None:
        previous = str(self._saved["previous"])
        debs = sorted(self._paths.archives.glob(f"nocs_{previous.replace(':', '%3a')}_*.deb"))
        if not debs:
            raise HelperError("failed", f"NOCS {previous} is no longer in apt's cache")
        self._saved |= {"task": "rollback"}
        self._save()
        await self._start("dpkg", "-i", str(debs[0]))

    async def _start(self, *argv: str) -> None:
        """Run ``argv`` as the ``nocs-update`` unit, outside nocs-system's own cgroup."""
        await _run("systemctl", "reset-failed", f"{UNIT}.service", check=False)
        await _run(
            "systemd-run",
            f"--unit={UNIT}",
            "--description=NOCS update",
            "--setenv=DEBIAN_FRONTEND=noninteractive",
            "--setenv=NEEDRESTART_MODE=l",
            *argv,
        )
        log.info("update started: %s", " ".join(argv))

    async def _unit(self) -> str:
        state = await _run(
            "systemctl", "show", "--property=ActiveState", "--value", f"{UNIT}.service", check=False
        )
        return state.strip() or "inactive"

    async def _log(self) -> list[str]:
        output = await _run(
            "journalctl", "--unit", f"{UNIT}.service", "--output", "cat", "--no-pager",
            "--lines", str(LOG_LINES), "--boot", check=False,
        )  # fmt: skip
        return output.splitlines()[-LOG_LINES:]

    def _load(self) -> dict[str, object]:
        try:
            data = json.loads(self._paths.state.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}  # pyright: ignore[reportUnknownVariableType]

    def _save(self) -> None:
        self._paths.state.parent.mkdir(parents=True, exist_ok=True)
        new = self._paths.state.with_name(f".{self._paths.state.name}.new")
        new.write_text(json.dumps(self._saved, indent=2) + "\n")
        new.replace(self._paths.state)


async def _nocs_version() -> str | None:
    version = await _run("dpkg-query", "--show", "--showformat=${Version}", "nocs", check=False)
    return version.strip() or None


async def _run(*argv: str, check: bool = True) -> str:
    try:
        result = await anyio.run_process(list(argv), check=False)
    except FileNotFoundError as e:
        if check:
            raise HelperError("failed", f"{argv[0]} is not installed") from e
        return ""
    if check and result.returncode != 0:
        lines = result.stderr.decode(errors="replace").strip().splitlines()
        detail = lines[-1] if lines else f"exit status {result.returncode}"
        raise HelperError("failed", f"{argv[0]}: {detail}")
    return result.stdout.decode(errors="replace")
