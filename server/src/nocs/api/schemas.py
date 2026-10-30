"""Wire schemas shared with the web client (exported as JSON Schema)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from nocs.state import Patch


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    indi_connected: bool


class StateSnapshot(BaseModel):
    version: int
    state: dict[str, Any]


class SetPropertyRequest(BaseModel):
    values: dict[str, str | float | bool] = Field(min_length=1)


# -- WebSocket ---------------------------------------------------------------


class Hello(BaseModel):
    """First client message: the state epoch and version the client already holds, if any."""

    type: Literal["hello"] = "hello"
    epoch: str | None = None
    since: int | None = None


class PatchOp(BaseModel):
    op: Literal["set", "delete"]
    path: list[str]
    value: Any = None


class SnapshotMessage(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    epoch: str
    version: int
    state: dict[str, Any]


class PatchMessage(BaseModel):
    type: Literal["patch"] = "patch"
    version: int
    ops: list[PatchOp]

    @classmethod
    def from_patch(cls, patch: Patch) -> PatchMessage:
        return cls(
            version=patch.version,
            ops=[PatchOp(op=op.op, path=list(op.path), value=op.value) for op in patch.ops],
        )


type ServerMessage = SnapshotMessage | PatchMessage
