"""Wire schemas shared with the web client (exported as JSON Schema)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nocs.equipment import Role
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


type ConnectionName = Literal["disconnected", "connecting", "connected", "disconnecting"]
type DeviceStatusName = Literal["waiting", "connecting", "ready", "error", "disconnected"]


class ProfileSummary(StateModel):
    name: str


class RoleState(StateModel):
    driver: str
    device: str | None = Field(description="INDI device name, once known.")
    status: DeviceStatusName
    error: str | None


class EquipmentState(StateModel):
    profiles: dict[str, ProfileSummary]
    active: str | None = Field(description="Id of the selected profile.")
    connection: ConnectionName
    error: str | None = Field(description="Why the profile cannot be connected right now.")
    devices: dict[Role, RoleState] = Field(description="Roles of the active profile.")


class AppState(StateModel):
    """The whole state tree sent in snapshots and modified by patches."""

    indi: IndiState | None = None
    equipment: EquipmentState | None = None


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


class ConnectRequest(BaseModel):
    profile: str


class Driver(WireModel):
    driver: str = Field(description="Executable, e.g. indi_asi_ccd.")
    name: str
    label: str = Field(description="Device model the entry is for (one driver, many models).")
    manufacturer: str
    group: str


class SerialPortInfo(WireModel):
    path: str = Field(description="Stable /dev/serial/by-id/ name.")
    device: str = Field(description="Device node it points to now.")


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
