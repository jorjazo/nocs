"""Wire schemas shared with the web client (exported as JSON Schema)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nocs.equipment import Role, Site
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


class CameraField(StateModel):
    focal_length: float = Field(description="Effective focal length (with reducer), mm.")
    scale: float = Field(description="Arcseconds per binned pixel.")
    width: float = Field(description="Degrees across a frame (its x axis).")
    height: float = Field(description="Degrees along a frame's y axis.")


class CameraState(StateModel):
    device: str
    exposing: bool
    remaining: float | None = Field(description="Seconds left in the current exposure.")
    temperature: float | None = Field(description="Sensor temperature, °C; None if unknown.")
    can_cool: bool = Field(description="The sensor temperature can be set (a cooled camera).")
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
    field: CameraField | None = Field(
        description="What a frame covers with the current binning and region; None without"
        " the role's optics in the profile or while the sensor is unknown."
    )
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


type NorthSouth = Literal["north", "south"]
type WestEast = Literal["west", "east"]


class MountMotion(StateModel):
    ns: NorthSouth | None
    we: WestEast | None


class MountSite(StateModel):
    latitude: float = Field(description="Degrees, north positive.")
    longitude: float = Field(description="Degrees, east positive (-180..180).")
    elevation: float = Field(description="Metres.")


class AltitudeLimits(StateModel):
    enabled: bool
    lower: float = Field(description="Degrees.")
    upper: float = Field(description="Degrees.")


class MeridianLimits(StateModel):
    flip: bool = Field(description="The mount flips by itself at the limit.")
    limit: float = Field(description="Degrees past the meridian.")


class MountLimits(StateModel):
    """Limits the mount enforces itself, when its driver exposes them (read only)."""

    altitude: AltitudeLimits | None
    meridian: MeridianLimits | None


class MountState(StateModel):
    device: str
    ra: float = Field(description="Apparent (JNow) right ascension, hours.")
    dec: float = Field(description="Apparent (JNow) declination, degrees.")
    ra_j2000: float = Field(description="Hours.")
    dec_j2000: float = Field(description="Degrees.")
    alt: float | None = Field(
        description="Degrees; from the driver, or computed when the site and time are known."
    )
    az: float | None = Field(description="Degrees from north through east.")
    slewing: bool
    tracking: bool
    track_mode: str | None = Field(description="e.g. sidereal, lunar, solar, custom.")
    track_modes: list[str]
    parked: bool
    parking: bool = Field(description="Parking or unparking right now.")
    can_park: bool
    can_home: bool
    homing: bool
    pier_side: Literal["east", "west", "unknown"]
    moving: MountMotion = Field(description="Manual motion (slew pad), axis by axis.")
    moved_by: str | None = Field(description="Paired device whose slew pad holds the mount.")
    slew_rate: str | None = Field(description="Speed of manual motion, a name in slew_rates.")
    slew_rates: list[str] = Field(description="Slowest first, as the driver names them.")
    time: str | None = Field(description="The mount's clock as it last reported it, UTC.")
    site: MountSite | None = Field(description="Where the mount believes it is.")
    site_check: Literal["same", "different", "unknown", "no_profile_site"] = Field(
        description="The mount's site against the active profile's."
    )
    site_sent: bool = Field(description="NOCS sent the site since the mount became ready.")
    time_sent: bool = Field(
        description="NOCS sent the time since the mount became ready; go to waits for both."
    )
    limits: MountLimits


class ClockState(StateModel):
    offset: float | None = Field(
        description="Seconds the clients' clock is ahead of the system clock; None until a"
        " client reports it."
    )
    measured: str | None = Field(description="When it was last reported, UTC.")
    corrected: bool = Field(
        description="The system clock is more than 5 s off: NOCS uses the clients' time for"
        " frame times, nights and the mount."
    )


type OutputKindName = Literal["dc", "dew", "usb", "variable"]


class PowerOutput(StateModel):
    id: str = Field(description="<kind>:<n>, numbered from 1 in the driver's order (ADR 0017).")
    kind: OutputKindName
    label: str = Field(description="The profile's label, else the driver's.")
    on: bool
    current: float | None = Field(description="Amperes, when the box measures this output.")
    duty: float | None = Field(
        description="Dew heaters: power in percent; while off, what it gets when switched on."
    )
    voltage: float | None = Field(description="Variable outputs: volts while on.")
    voltages: list[float] = Field(description="Variable outputs: the voltages it can be set to.")
    feeds: list[Role] = Field(description="Roles the profile says this output powers.")


class PowerInputState(StateModel):
    voltage: float | None
    current: float | None = Field(description="Total current drawn, A.")
    power: float | None = Field(description="W")


class PowerState(StateModel):
    device: str
    outputs: list[PowerOutput]
    auto_dew: bool | None = Field(
        description="The box drives its dew heaters itself; None: it cannot."
    )
    auto_dew_aggression: float | None = Field(description="Percent (Pegasus boxes).")
    input: PowerInputState | None


class WeatherState(StateModel):
    device: str
    temperature: float | None = Field(description="°C")
    humidity: float | None = Field(description="Relative humidity, %.")
    dew_point: float | None = Field(
        description="°C: the sensor's, or computed from temperature and humidity."
    )


class FocuserState(StateModel):
    device: str
    position: int = Field(description="Steps.")
    max_position: int | None = Field(description="Highest position the driver accepts.")
    moving: bool
    target: int | None = Field(description="Where the move NOCS is running goes.")
    temperature: float | None = Field(description="Its probe, °C; None if it has none.")
    can_abort: bool


class FilterWheelState(StateModel):
    device: str
    key: str | None = Field(
        description="The physical wheel: serial:<number> or device:<name>; None while"
        " it is being identified (ADR 0016)."
    )
    label: str = Field(description="The user's name for this wheel; may be empty.")
    slot: int | None = Field(description="1-based; None while unknown.")
    filter: str | None = Field(description="Name of the current slot; None if it has none.")
    names: list[str] = Field(description="One per slot, as the driver has them; empty = none.")
    slots: int
    moving: bool
    confirmed: bool = Field(
        description="The user said what sits in each slot; false for a wheel NOCS has not"
        " seen before, which keeps its driver's names."
    )


class StarDatabase(StateModel):
    name: str = Field(description="As ASTAP calls it, e.g. D50.")
    min_fov: float = Field(description="Smallest frame height it solves, degrees.")
    max_fov: float = Field(description="Largest frame height it solves, degrees.")


class SolutionState(StateModel):
    ra: float = Field(description="Centre of the frame, J2000, hours.")
    dec: float = Field(description="Centre of the frame, J2000, degrees.")
    rotation: float = Field(
        description="Position angle of the top of the image as shown, degrees east of north."
    )
    scale: float = Field(description="Arcseconds per pixel of the solved image.")
    mirrored: bool = Field(description="The image as shown is a mirror view of the sky.")
    fov: list[float] = Field(min_length=2, max_length=2, description="Degrees across x and y.")
    hinted: bool = Field(description="Solved near the hint; false: by searching the whole sky.")
    seconds: float = Field(description="Time ASTAP took.")
    time: str = Field(description="UTC, ISO 8601, when it was solved.")


class SolverState(StateModel):
    available: bool = Field(description="ASTAP is installed.")
    version: str | None
    databases: list[StarDatabase]
    solving: bool
    last: SolutionState | None = Field(description="The most recent solution.")


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
    mount: MountState | None = Field(default=None, description="None: no mount is ready.")
    power: PowerState | None = Field(default=None, description="None: no power box is ready.")
    weather: WeatherState | None = Field(
        default=None, description="None: no weather sensor is ready."
    )
    clock: ClockState | None = None
    focuser: FocuserState | None = Field(default=None, description="None: no focuser is ready.")
    filter_wheel: FilterWheelState | None = Field(
        default=None, description="None: no filter wheel is ready."
    )
    solver: SolverState | None = None


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


class EquatorialGoto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame: Literal["j2000", "jnow"]
    ra: float = Field(ge=0, lt=24, description="Hours.")
    dec: float = Field(ge=-90, le=90, description="Degrees.")
    force: bool = Field(default=False, description="Slew even if the target is below the horizon.")


class HorizontalGoto(BaseModel):
    """Point at a place in the local sky (e.g. the zenith for flats); tracking stops."""

    model_config = ConfigDict(extra="forbid")

    frame: Literal["altaz"]
    alt: float = Field(ge=0, le=90, description="Degrees.")
    az: float = Field(ge=0, lt=360, description="Degrees from north through east.")


type GotoRequest = Annotated[EquatorialGoto | HorizontalGoto, Field(discriminator="frame")]


class TrackingRequest(BaseModel):
    """Only the fields present are changed."""

    model_config = ConfigDict(extra="forbid")

    on: bool | None = None
    mode: str | None = Field(default=None, description="One of the mount's track_modes.")


class OutputRequest(BaseModel):
    """dc and usb outputs take ``on``; dew heaters ``on`` and/or ``duty``; variable
    outputs a ``voltage`` (switching them on) or ``on: false``.

    Switching an output off, or changing its voltage, is refused (409) while a role
    it feeds is busy (any job, when the profile does not say), unless ``force``.
    """

    model_config = ConfigDict(extra="forbid")

    on: bool | None = None
    duty: float | None = Field(default=None, ge=0, le=100, description="Percent.")
    voltage: float | None = Field(default=None, gt=0, description="Volts.")
    force: bool = False


class AutoDewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool


class MountSiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: Site | None = Field(default=None, description="None: the active profile's site.")


class FocuserMoveRequest(BaseModel):
    """Exactly one of ``position`` and ``steps``."""

    model_config = ConfigDict(extra="forbid")

    position: int | None = Field(default=None, ge=0, description="Absolute position, steps.")
    steps: int | None = Field(
        default=None, description="Relative move: positive outward, negative inward."
    )

    @model_validator(mode="after")
    def _one_of(self) -> FocuserMoveRequest:
        if (self.position is None) == (self.steps is None):
            raise ValueError("give either position or steps")
        return self


class FilterSelectRequest(BaseModel):
    """Exactly one of ``slot`` and ``filter``."""

    model_config = ConfigDict(extra="forbid")

    slot: int | None = Field(default=None, ge=1, description="1-based.")
    filter: str | None = Field(default=None, min_length=1, description="A name in names.")

    @model_validator(mode="after")
    def _one_of(self) -> FilterSelectRequest:
        if (self.slot is None) == (self.filter is None):
            raise ValueError("give either slot or filter")
        return self


class FilterNamesRequest(BaseModel):
    """What sits in each slot of the wheel connected now (ADR 0016)."""

    model_config = ConfigDict(extra="forbid")

    filters: list[str] = Field(description="One name per slot, in order; empty = no filter.")
    label: str | None = Field(
        default=None, max_length=80, description="Name for this wheel; None keeps it."
    )


class ClockRequest(BaseModel):
    """The client's clock, sent when it connects."""

    model_config = ConfigDict(extra="forbid")

    utc: datetime = Field(description="ISO 8601 with a time zone, e.g. 2026-10-30T23:10:05.120Z.")
    utc_offset: float | None = Field(
        default=None, ge=-14, le=14, description="The client's time zone, hours east of UTC."
    )


class ClockReport(WireModel):
    offset: float = Field(description="Seconds the client is ahead of the system clock.")
    corrected: bool = Field(description="NOCS now uses the clients' time (offset over 5 s).")


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


# -- Slew pad WebSocket (/api/mount/pad, ADR 0015) -------------------------------


class PadRequest(BaseModel):
    """What the client holds, repeated every 0.25 s while held; all null to let go.

    The mount stops after 1 s without a message, when the socket closes, and on
    any error; after such a stop the client must let go before moving again.
    """

    model_config = ConfigDict(extra="forbid")

    ns: NorthSouth | None = None
    we: WestEast | None = None
    rate: str | None = Field(default=None, description="One of the mount's slew_rates.")


class PadStatusMessage(WireModel):
    type: Literal["pad"] = "pad"
    moving: MountMotion
    rate: str | None
    latched: bool = Field(description="Stopped by NOCS: let go before moving again.")
    message: str | None = Field(description="Why it stopped or refused.")
