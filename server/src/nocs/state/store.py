"""Versioned application state, shared with clients as a snapshot plus patches.

Every commit increments the version and produces a list of operations. Clients
apply them in order; a client that falls behind (or reconnects) either receives
the patches it missed from the recent history or a fresh snapshot.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
type Path = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Op:
    op: Literal["set", "delete"]
    path: Path
    value: Json = None


@dataclass(frozen=True, slots=True)
class Patch:
    version: int
    ops: tuple[Op, ...]


class Resync:
    """Marker delivered to a subscriber that fell too far behind and needs a snapshot."""


RESYNC = Resync()


class Subscription:
    def __init__(self, store: StateStore, maxsize: int) -> None:
        self._store = store
        self._queue: asyncio.Queue[Patch | Resync] = asyncio.Queue(maxsize)

    def _offer(self, patch: Patch) -> None:
        try:
            self._queue.put_nowait(patch)
        except asyncio.QueueFull:
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait(RESYNC)

    async def get(self) -> Patch | Resync:
        return await self._queue.get()

    def close(self) -> None:
        self._store._subscribers.discard(self)  # pyright: ignore[reportPrivateUsage]


class StateStore:
    def __init__(self, history: int = 2000) -> None:
        # Identifies this store instance, so clients never resume across server restarts.
        self.epoch = uuid.uuid4().hex
        self._state: dict[str, Json] = {}
        self._version = 0
        self._history: deque[Patch] = deque(maxlen=history)
        self._subscribers: set[Subscription] = set()
        self._pending: list[Op] | None = None

    @property
    def version(self) -> int:
        return self._version

    def snapshot(self) -> dict[str, Json]:
        return copy.deepcopy(self._state)

    def get(self, path: Path) -> Json:
        node: Json = self._state
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return copy.deepcopy(node)

    def set(self, path: Path, value: Json) -> None:
        self._record(Op("set", path, copy.deepcopy(value)))

    def delete(self, path: Path) -> None:
        self._record(Op("delete", path))

    @contextmanager
    def transaction(self) -> Generator[None]:
        """Group every change made inside the block into a single version."""
        if self._pending is not None:
            yield
            return
        self._pending = []
        try:
            yield
        finally:
            ops, self._pending = self._pending, None
            if ops:
                self._commit(tuple(ops))

    def patches_since(self, version: int) -> list[Patch] | None:
        """Patches after ``version``, or ``None`` if they are no longer in the history."""
        if version == self._version:
            return []
        if version > self._version or not self._history:
            return None
        if self._history[0].version > version + 1:
            return None
        return [p for p in self._history if p.version > version]

    def subscribe(self, maxsize: int = 1000) -> Subscription:
        subscription = Subscription(self, maxsize)
        self._subscribers.add(subscription)
        return subscription

    def _record(self, op: Op) -> None:
        if self._pending is not None:
            self._apply(op)
            self._pending.append(op)
        else:
            self._apply(op)
            self._commit((op,))

    def _commit(self, ops: tuple[Op, ...]) -> None:
        self._version += 1
        patch = Patch(self._version, ops)
        self._history.append(patch)
        for subscriber in list(self._subscribers):
            subscriber._offer(patch)  # pyright: ignore[reportPrivateUsage]

    def _apply(self, op: Op) -> None:
        if not op.path:
            raise ValueError("empty path")
        *parents, last = op.path
        node = self._state
        for key in parents:
            child = node.get(key)
            if not isinstance(child, dict):
                if op.op == "delete":
                    return
                child = {}
                node[key] = child
            node = child
        if op.op == "set":
            node[last] = op.value
        else:
            node.pop(last, None)
