"""Wire schemas shared with the web client (exported as JSON Schema)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nocs.state import Patch

# -- State -------------------------------------------------------------------
# These models document the shape of the state tree for clients (and generate the
# TypeScript types). The server builds the tree as plain JSON for speed; tests
# check that what it builds validates against these models.


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlobInfo(StateModel):
    format: str
    size: int


class IndiNumberElement(StateModel):
    label: str
    value: float
    format: str
    min: float
    max: float
    step: float


class IndiValueElement(StateModel):
    """Text (string), switch (bool), light (state name) or BLOB (metadata only)."""

    label: str
    value: str | bool | BlobInfo


type PropertyStateName = Literal["Idle", "Ok", "Busy", "Alert"]


class IndiProperty(StateModel):
    type: Literal["text", "number", "switch", "light", "blob"]
    label: str
    group: str
    state: PropertyStateName
    perm: Literal["ro", "wo", "rw"]
    rule: Literal["OneOfMany", "AtMostOne", "AnyOfMany"] | None
    timestamp: str | None
    message: str | None
    elements: dict[str, IndiNumberElement | IndiValueElement]


class IndiDevice(StateModel):
    interfaces: list[str] = Field(
        default_factory=list[str], description="Present once DRIVER_INFO is defined."
    )
    properties: dict[str, IndiProperty] = Field(default_factory=dict[str, IndiProperty])


class IndiServer(StateModel):
    host: str
    port: int
    connected: bool
    error: str | None


class IndiMessage(StateModel):
    device: str | None
    timestamp: str | None
    text: str


class IndiState(StateModel):
    server: IndiServer | None = None
    devices: dict[str, IndiDevice] = Field(default_factory=dict[str, IndiDevice])
    messages: list[IndiMessage] = Field(default_factory=list[IndiMessage])


class AppState(StateModel):
    """The whole state tree sent in snapshots and modified by patches."""

    indi: IndiState | None = None


# -- HTTP --------------------------------------------------------------------


class WireModel(BaseModel):
    """Messages the server sends: every field is always present on the wire."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class Health(WireModel):
    status: Literal["ok"] = "ok"
    version: str
    indi_connected: bool


class StateSnapshot(WireModel):
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


class PatchOp(WireModel):
    op: Literal["set", "delete"]
    path: list[str]
    value: Any = None


class SnapshotMessage(WireModel):
    type: Literal["snapshot"] = "snapshot"
    epoch: str
    version: int
    state: dict[str, Any]


class PatchMessage(WireModel):
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
