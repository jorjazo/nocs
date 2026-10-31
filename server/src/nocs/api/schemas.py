"""Wire schemas shared with the web client (exported as JSON Schema)."""

from __future__ import annotations

from datetime import datetime
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


type CameraRoleName = Literal["main_camera", "guide_camera"]
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


type FrameTypeName = Literal["light", "dark", "bias", "flat"]
type JobStateName = Literal["running", "succeeded", "failed", "cancelled"]


class ValueRange(StateModel):
    min: float
    max: float


class Region(StateModel):
    """Part of the sensor, in unbinned pixels."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class SensorInfo(StateModel):
    width: int
    height: int
    pixel_size: float = Field(description="Micrometres.")
    bits: int


class FrameInfo(StateModel):
    exposure: float
    frame_type: FrameTypeName
    format: str = Field(description="File extension sent by the driver, e.g. .fits.")
    size: int = Field(description="Bytes.")
    time: str = Field(description="UTC, ISO 8601, when the image arrived.")
    id: int | None = Field(description="Catalog id of the saved frame; None if it was not saved.")
    path: str | None = Field(description="Where it was saved, below <destination>/NOCS/.")
    destination: str | None = Field(description="Id of the destination it was saved to.")


class Preview(StateModel):
    url: str = Field(description="JPEG, at most 1920 px wide; immutable.")
    width: int
    height: int
    color: bool
    stars: int
    hfr: float | None = Field(description="Median half-flux radius, unbinned pixels.")
    histogram: list[int] = Field(
        description="256 equal bins of the linear data (sampled), over where most of it is."
    )
    histogram_start: int = Field(description="ADU at the lower edge of the first bin.")
    histogram_step: int = Field(description="ADU per bin.")
    minimum: int = Field(description="Darkest sampled value, ADU; may be below the bins.")
    maximum: int = Field(description="Brightest sampled value, ADU; may be above the bins.")
    exposure: float
    frame_type: FrameTypeName
    time: str = Field(description="UTC, ISO 8601, when the frame arrived.")
    seconds: float = Field(description="Time the worker took.")


class CameraState(StateModel):
    device: str
    exposing: bool
    remaining: float | None = Field(description="Seconds left in the current exposure.")
    temperature: float | None = Field(description="Sensor temperature, °C; None if unknown.")
    cooler: bool | None = Field(description="Cooler on; None if the camera has none.")
    cooler_power: float | None = Field(description="As reported by the driver; units vary.")
    target: float | None = Field(description="Cooling target set through NOCS, °C.")
    ramp: float | None = Field(description="Cooling rate limit, °C/min; 0 = unlimited.")
    exposure: float = Field(
        description="Seconds; the last one set or used through NOCS (INDI keeps none)."
    )
    gain: float | None
    gain_range: ValueRange | None
    offset: float | None
    offset_range: ValueRange | None
    binning: list[int] = Field(min_length=2, max_length=2)
    max_binning: int
    region: Region
    frame_type: FrameTypeName
    sensor: SensorInfo
    bayer: str | None = Field(description="Color filter pattern (e.g. RGGB); None for mono.")
    last_frame: FrameInfo | None
    preview: Preview | None = Field(description="Latest preview, from any exposure or loop.")


class JobInfo(StateModel):
    kind: str
    resources: list[str] = Field(description="Equipment roles the job locks.")
    state: JobStateName
    progress: float | None = Field(description="0 to 1; None while unknown.")
    message: str | None
    error: str | None
    result: Any = Field(description="Kind-specific; for exposures, a FrameInfo.")
    started: str
    finished: str | None


class StorageDestination(StateModel):
    id: str = Field(description='"internal", or the volume\'s filesystem UUID (or mount:<path>).')
    label: str
    path: str = Field(description="Directory frames are saved below, as NOCS/….")
    fs: str = Field(description="Filesystem type, e.g. ext4 or exfat.")
    total: int = Field(description="Bytes.")
    free: int = Field(description="Bytes available to nocsd.")
    writable: bool
    system: bool = Field(description="On the same disk as the operating system.")
    sd: bool = Field(description="On an SD card (slower, wears out sooner; still supported).")
    internal: bool


class StorageState(StateModel):
    destinations: list[StorageDestination] = Field(description="Internal, then mounted drives.")
    choice: str = Field(description='"auto" (an external drive if any, else internal) or an id.')
    destination: str | None = Field(description="Where the next frame would go; None if nowhere.")
    error: str | None = Field(description="Why frames cannot be saved right now.")
    target: str | None = Field(description="Target name for lights.")
    template: str = Field(description="File name template.")


class AppState(StateModel):
    """The whole state tree sent in snapshots and modified by patches."""

    indi: IndiState | None = None
    equipment: EquipmentState | None = None
    cameras: dict[CameraRoleName, CameraState] | None = Field(
        default=None, description="Connected camera roles."
    )
    jobs: dict[str, JobInfo] | None = Field(
        default=None, description="Running jobs and the most recent finished ones."
    )
    storage: StorageState | None = None


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


class CameraSettingsRequest(BaseModel):
    """Only the fields present are changed."""

    model_config = ConfigDict(extra="forbid")

    exposure: float | None = Field(default=None, ge=0, le=7200, description="Seconds.")
    gain: float | None = None
    offset: float | None = None
    binning: int | None = Field(default=None, ge=1)
    region: Region | Literal["full"] | None = Field(
        default=None, description='A readout region, or "full" for the whole sensor.'
    )
    frame_type: FrameTypeName | None = None


class CoolingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool
    target: float | None = Field(default=None, ge=-60, le=40, description="°C; needed to cool.")
    ramp: float | None = Field(default=None, ge=0, description="°C/min; 0 = unlimited.")


class ExposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exposure: float = Field(ge=0, le=7200, description="Seconds.")
    frame_type: FrameTypeName | None = Field(
        default=None, description="Defaults to the camera's current frame type."
    )
    save: bool | None = Field(
        default=None,
        description="Defaults to true for the main camera; the guide camera never saves.",
    )


class LoopRequest(BaseModel):
    """Expose repeatedly for previews (nothing is saved) until the job is cancelled."""

    model_config = ConfigDict(extra="forbid")

    exposure: float = Field(ge=0, le=600, description="Seconds.")
    frame_type: FrameTypeName | None = None


class DestinationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str = Field(
        min_length=1, description='"auto", "internal" or the id of a mounted destination.'
    )


class TargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str | None = Field(max_length=80, description="None to clear it.")


class TemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str = Field(
        min_length=1,
        max_length=200,
        description="Fields: {target} {night} {type} {filter} {exposure} {gain} {offset} "
        "{temperature} {binning} {camera} {datetime} {seq}.",
    )


class NightGroup(WireModel):
    frame_type: FrameTypeName
    target: str | None
    filter: str | None
    frames: int
    size: int = Field(description="Bytes.")
    exposure: float = Field(description="Total exposure, seconds.")


class NightInfo(WireModel):
    id: int
    night: str = Field(description="YYYY-MM-DD, the date at the start of the night.")
    site: str | None
    first_frame: str = Field(description="UTC, ISO 8601, exposure start.")
    last_frame: str
    frames: int
    size: int = Field(description="Bytes.")
    groups: list[NightGroup] = Field(description="Frames by type, target and filter.")
    zip_url: str = Field(description="All its frames as one zip (add ?type=&target=&filter=).")


class FrameRecord(WireModel):
    id: int
    night: str
    target: str | None
    frame_type: FrameTypeName
    filter: str | None
    exposure: float
    started: str = Field(description="UTC, ISO 8601, exposure start.")
    size: int
    path: str = Field(description="Below <destination>/NOCS/.")
    volume: str = Field(description="Label of the drive it is on.")
    available: bool = Field(description="Its drive is mounted now.")
    url: str = Field(description="Download URL.")
    camera: str
    profile: str | None
    gain: float | None
    offset: float | None
    binning: int | None
    temperature: float | None
    width: int | None
    height: int | None
    stars: int | None
    hfr: float | None


class JobStarted(WireModel):
    job: str


class Driver(WireModel):
    driver: str = Field(description="Executable, e.g. indi_asi_ccd.")
    name: str
    label: str = Field(description="Device model the entry is for (one driver, many models).")
    manufacturer: str
    group: str


class SerialPortInfo(WireModel):
    path: str = Field(description="Stable /dev/serial/by-id/ name.")
    device: str = Field(description="Device node it points to now.")


# -- Authentication (ADR 0014) ---------------------------------------------------

type ClientRole = Literal["owner", "observer"]


class PairRequest(BaseModel):
    """Set up the owner passphrase (``/api/auth/setup``) or pair with it (``/api/auth/pair``)."""

    model_config = ConfigDict(extra="forbid")

    passphrase: str = Field(description="At least 8 characters.")
    name: str = Field(description='What the device is, e.g. "Pixel 8".')


class PassphraseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: str
    new: str = Field(description="At least 8 characters.")


class ObserverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class PairedDevice(WireModel):
    id: str
    name: str
    created: datetime
    last_used: datetime = Field(description="To the hour.")
    current: bool = Field(description="The device making the request.")


class AuthStatus(WireModel):
    setup_required: bool = Field(description="No owner passphrase yet: set one up first.")
    role: ClientRole | None = Field(description="None: pair to do anything.")
    device: PairedDevice | None = Field(description="This client's device, when paired.")
    observer: bool = Field(description="Whether unpaired clients may watch (read only).")


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
