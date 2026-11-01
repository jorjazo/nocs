"""Wire schemas shared with the web client (exported as JSON Schema)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nocs.equipment import Role, Site
from nocs.state import Patch
from nocs.targets import TargetType
from nocs.targets.plan import PlannedTarget

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
    responsive: bool = Field(
        description="It answers pings; False while connected to an indiserver that does not"
        " (ADR 0030)."
    )
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


class FrameGuiding(StateModel):
    """How guiding went during a frame (ADR 0024)."""

    rms_ra: float | None = Field(description="Arcseconds; None without the pixel scale.")
    rms_dec: float | None
    rms_total: float | None
    steps: int
    lost: int = Field(description="Guide frames without the star.")


class FrameInfo(StateModel):
    exposure: float
    frame_type: FrameTypeName
    format: str = Field(description="File extension sent by the driver, e.g. .fits.")
    size: int = Field(description="Bytes.")
    time: str = Field(description="UTC, ISO 8601, when the image arrived.")
    id: int | None = Field(description="Catalog id of the saved frame; None if it was not saved.")
    path: str | None = Field(description="Where it was saved, below <destination>/NOCS/.")
    destination: str | None = Field(description="Id of the destination it was saved to.")
    guiding: FrameGuiding | None = Field(description="None: PHD2 did not guide meanwhile.")


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
    used_by: Literal["phd2"] | None = Field(
        description="Another client drives the camera (PHD2, ADR 0023): NOCS shows its frames"
        " and takes none of its own."
    )


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
    removable: bool = Field(description="On a USB drive.")
    ejectable: bool = Field(description="NOCS can eject it here (ADR 0027).")
    internal: bool


class UnmountedDrive(StateModel):
    device: str = Field(description="e.g. /dev/sda1.")
    label: str = Field(description="Its filesystem label, else its UUID.")
    fs: str = Field(description="Filesystem type; empty if unknown.")
    error: str | None = Field(
        description="Why NOCS could not mount it; None while it does not try (not here, or"
        " ejected and still plugged in)."
    )


class StorageState(StateModel):
    destinations: list[StorageDestination] = Field(description="Internal, then mounted drives.")
    unmounted: list[UnmountedDrive] = Field(
        description="USB drives plugged in but not mounted: unplug an ejected one."
    )
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
    slew_rate_labels: list[str] = Field(
        description="What the driver calls each of slew_rates (the AM5's 10x: 1440x)."
    )
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
    source: Literal["gps", "ntp", "client", "none"] | None = Field(
        description="What keeps the system clock: a GPS or NTP servers (through chrony or"
        " systemd-timesyncd), a client's time that NOCS set it to (ADR 0029), or nothing;"
        " None until NOCS has looked."
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


class FocuserBacklash(StateModel):
    """How autofocus takes up this physical focuser's backlash (ADR 0021)."""

    direction: Literal["outward", "inward"] = Field(
        description="Which way every position is reached."
    )
    overshoot: int | None = Field(
        description="Steps past a target when moving the other way; None: one sweep step."
    )


class FocuserState(StateModel):
    device: str
    key: str = Field(description="The physical focuser: serial:<number> or device:<name>.")
    position: int = Field(description="Steps.")
    max_position: int | None = Field(description="Highest position the driver accepts.")
    moving: bool
    target: int | None = Field(description="Where the move NOCS is running goes.")
    temperature: float | None = Field(description="Its probe, °C; None if it has none.")
    can_abort: bool
    backlash: FocuserBacklash


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
    taken: str | None = Field(
        description="UTC, ISO 8601, mid-exposure of the frame; None when the caller did not say."
    )
    mount: SkyPosition | None = Field(
        description="Where the mount said it pointed as the frame started, J2000."
    )
    offset: PointingOffset | None = Field(description="From the mount's position to the solution.")
    synced: bool = Field(description="The mount was synced to this solution.")


class SkyPosition(StateModel):
    ra: float = Field(description="J2000, hours.")
    dec: float = Field(description="J2000, degrees.")


class PointingOffset(StateModel):
    angle: float = Field(description="Arcminutes on the sky.")
    ra: float = Field(description="Arcminutes on the sky along RA (scaled by cos Dec), east +.")
    dec: float = Field(description="Arcminutes, north +.")


type SolveFailureReason = Literal[
    "unavailable", "no_database", "no_stars", "no_solution", "unreadable", "error"
]


class SolveFailure(StateModel):
    reason: SolveFailureReason = Field(
        description="unavailable: ASTAP is not installed; no_database: none for the field;"
        " unreadable: ASTAP could not read the image."
    )
    message: str
    time: str = Field(description="UTC, ISO 8601.")


class SolverState(StateModel):
    available: bool = Field(description="ASTAP is installed.")
    version: str | None
    databases: list[StarDatabase]
    solving: bool
    last: SolutionState | None = Field(description="The most recent solution.")
    failure: SolveFailure | None = Field(
        description="Why the latest attempt failed; None after a solution."
    )


class CenteringFailure(StateModel):
    reason: SolveFailureReason
    message: str


class CenteringAttempt(StateModel):
    aim: SkyPosition = Field(description="Where the mount was sent.")
    solution: SkyPosition | None = Field(description="Centre of the frame; None: not solved.")
    error: PointingOffset | None = Field(description="From the target to the frame's centre.")
    synced: bool = Field(description="The mount was synced to the solution.")
    failure: CenteringFailure | None = Field(description="Why the frame was not solved.")


class PlanState(StateModel):
    """What the Plan screen chose for tonight (stage 3.6)."""

    target: PlannedTarget | None = Field(description="None: no target chosen.")


class CenteringState(StateModel):
    """The running centring, or the most recent one."""

    job: str
    state: Literal["running", "succeeded", "failed", "cancelled"]
    phase: Literal["slewing", "settling", "solving"] | None = Field(description="While running.")
    method: Literal["sync", "offset"] = Field(
        description="sync: the mount is synced to each frame; offset: the next go to aims"
        " off by what the frame missed."
    )
    target: SkyPosition
    tolerance: float = Field(description="Arcminutes.")
    max_attempts: int
    attempts: list[CenteringAttempt]
    error: str | None = Field(description="Why it failed.")
    started: str
    finished: str | None


class AutofocusPoint(StateModel):
    position: int
    hfr: float | None = Field(description="Median HFR, unbinned px; None without enough stars.")
    stars: int


class AutofocusFit(StateModel):
    """The V-curve ``hfr = a·√(1 + ((x - c)/b)²)`` (ADR 0021)."""

    a: float = Field(description="HFR at best focus, px.")
    b: float = Field(description="Steps from best focus at which the HFR is √2·a.")
    c: float = Field(description="Best focus position, steps.")
    r_squared: float


class AutofocusState(StateModel):
    """The running autofocus, or the most recent one."""

    job: str
    state: Literal["running", "succeeded", "failed", "cancelled"]
    phase: Literal["starting", "sweeping", "moving", "checking", "restoring"] | None = Field(
        description="While running."
    )
    started: str
    finished: str | None
    step: int
    start_position: int
    start_hfr: float | None
    start_stars: int | None
    temperature: float | None = Field(description="The focuser's probe at the start, °C.")
    ambient: float | None = Field(description="The weather role's temperature at the start, °C.")
    filter: str | None = Field(description="The filter in place.")
    points: list[AutofocusPoint] = Field(description="Measured so far, by position.")
    fit: AutofocusFit | None
    position: int | None = Field(description="Best focus, once the run checked it.")
    hfr: float | None = Field(description="Of the last frame, at ``position``.")
    stars: int | None
    problem: (
        Literal["no_stars", "too_few_stars", "not_turning", "flat", "bad_fit", "worse", "backlash"]
        | None
    )
    detail: str | None = Field(description="Why it failed.")
    suggested_step: int | None = Field(
        description="A step that would put the sweep's ends at 2.5 times the best HFR."
    )
    suggested_overshoot: int | None = Field(
        default=None, description="For backlash: an overshoot that would take it up."
    )


class Phd2Server(StateModel):
    host: str
    port: int
    connected: bool
    version: str | None
    error: str | None = Field(description="Why NOCS cannot reach PHD2.")


type Phd2AppState = Literal[
    "Stopped", "Selected", "Calibrating", "Guiding", "LostLock", "Paused", "Looping"
]


class GuidingCalibration(StateModel):
    ra_angle: float = Field(description="Of the RA axis on the guide camera, degrees.")
    ra_rate: float = Field(description="Pixels per second of an RA pulse.")
    dec_angle: float
    dec_rate: float
    declination: float | None = Field(description="Where it was calibrated, degrees.")


class GuidingAlert(StateModel):
    message: str
    kind: str = Field(description="PHD2's type: info, question, warning or error.")
    time: str = Field(description="UTC, ISO 8601.")


class GuideEntryModel(StateModel):
    """One entry of the guiding graph (``nocs.guiding.stats``)."""

    seq: int = Field(description="Increasing; ask for entries after the last one seen.")
    kind: Literal["step", "lost", "dither"]
    time: float = Field(description="PHD2's timestamp, Unix seconds.")
    ra: float | None = Field(description="Step: raw RA distance, px; dither: the RA move.")
    dec: float | None
    ra_pulse: int = Field(description="Milliseconds, positive towards west.")
    dec_pulse: int = Field(description="Milliseconds, positive towards north.")
    snr: float | None
    hfd: float | None = Field(description="Pixels.")
    mass: float | None
    settling: bool


class GuidingStats(StateModel):
    """Over the last 100 steps that were not settling; RMS as PHD2's graph (std. dev.)."""

    seq: int = Field(description="Of the newest entry.")
    steps: int
    rms_ra: float | None = Field(description="Arcseconds; None without the pixel scale.")
    rms_dec: float | None
    rms_total: float | None
    rms_ra_px: float | None
    rms_dec_px: float | None
    rms_total_px: float | None
    peak_ra_px: float | None
    peak_dec_px: float | None
    lost: int = Field(description="Frames without the star among the last 100 entries.")
    last: GuideEntryModel | None


class GuidingState(StateModel):
    phd2: Phd2Server
    managed: bool = Field(description="NOCS writes PHD2's settings from the profile (ADR 0022).")
    settings: Literal["none", "pending", "applying", "applied", "failed", "user"] = Field(
        description="none: nothing to apply yet (no profile, or its guide camera or mount not"
        " ready); pending: waiting for PHD2 to stop; applying: PHD2 restarting with them;"
        " user: PHD2 runs the settings its user chose."
    )
    profile: str | None = Field(description="The PHD2 profile in use.")
    app_state: Phd2AppState | None = Field(description="PHD2's state; None while unknown.")
    equipment: bool = Field(
        description="PHD2 is connected to the guide camera and the mount, which is then"
        " PHD2's (ADR 0023)."
    )
    exposure: float | None = Field(description="PHD2's exposure, seconds; None while unknown.")
    calibration: GuidingCalibration | None = Field(description="None: PHD2 is not calibrated.")
    settling: bool = Field(description="PHD2 waits for the star to settle.")
    alert: GuidingAlert | None = Field(description="The last thing PHD2 warned about.")
    pixel_scale: float | None = Field(description="Of the guide camera, arcseconds per pixel.")
    stats: GuidingStats | None = Field(description="None until PHD2 guides.")
    error: str | None = Field(description="Why PHD2 does not run the profile's settings.")


type HealthWarningName = Literal["under_voltage", "throttled", "hot", "memory", "disk"]


class LastJoin(StateModel):
    ssid: str
    ok: bool
    error: str | None
    at: str | None = Field(description="UTC.")


class NetworkState(StateModel):
    """The appliance's network, managed by nocs-system (ADR 0028)."""

    wifi: bool = Field(description="The box has a Wi-Fi device.")
    mode: Literal["ap", "station", "none"]
    ssid: str | None = Field(description="The network joined, as a station.")
    ethernet: bool = Field(description="A cable is connected.")
    pin: Literal["auto", "ap", "station"] = Field(
        description="auto: station when a known network is in range, else access point."
    )
    country: str = Field(description='Regulatory country for the radio; "00" until set.')
    ap_ssid: str = Field(description="The access point's name, NOCS-xxxx by default.")
    ap_default_password: bool = Field(
        description="The access point still has the default password: the first run changes it."
    )
    ap_clients: int = Field(description="Devices on the access point now.")
    known: list[str] = Field(description="Networks the box joins by itself.")
    joining: str | None = Field(description="The network being joined right now.")
    last_join: LastJoin | None


class UpgradablePackage(StateModel):
    name: str
    from_: str = Field(alias="from")
    to: str


class UpdatesState(StateModel):
    """Updates of the appliance from apt, installed only when the owner asks (ADR 0025)."""

    state: Literal["idle", "checking", "installing", "succeeded", "failed"]
    task: Literal["install", "rollback"] | None = Field(description="What ran last.")
    packages: list[UpgradablePackage] = Field(description="What an update would upgrade.")
    checked: str | None = Field(description="When NOCS last looked, UTC.")
    installed: str | None = Field(description="The version of NOCS installed.")
    previous: str | None = Field(description="The version to go back to, if any.")
    error: str | None
    log: list[str] = Field(description="The last lines apt or dpkg wrote, while installing.")


class GpsState(StateModel):
    """A USB GPS through gpsd (ADR 0029); positions to 4 decimals, at most every 10 s."""

    connected: bool = Field(description="gpsd answers (a GPS may still be missing).")
    fix: Literal["none", "2d", "3d"]
    latitude: float | None = Field(description="Degrees, north positive.")
    longitude: float | None = Field(description="Degrees, east positive.")
    elevation: int | None = Field(description="Metres above sea level; 3D fixes only.")
    time: str | None = Field(description="The GPS's time of the fix, UTC.")
    site_differs: bool | None = Field(
        description="A 3D fix more than 0.01° or 50 m from the active profile's site, or a"
        " profile without one: the app offers the GPS's site. None without a 3D fix or profile."
    )


class SystemHealth(StateModel):
    """Read every few seconds; None where the computer does not report it."""

    cpu_temperature: int | None = Field(description="°C.")
    fan: int | None = Field(description="Revolutions per minute, to the nearest 100.")
    under_voltage: bool | None = Field(
        description="The supply is too weak right now (Raspberry Pi only)."
    )
    under_voltage_seen: str | None = Field(
        description="When it was last too weak since nocsd started, UTC."
    )
    throttled: bool | None = Field(
        description="The CPU runs below its top speed: too hot or under-powered."
    )
    memory_used: int | None = Field(description="Percent.")
    disk_free: int | None = Field(description="Bytes free on the system disk, to 100 MB.")
    warnings: list[HealthWarningName] = Field(
        description="Most serious first: hot from 80 °C, memory from 90 %, disk under 2 GB."
    )


class SystemState(StateModel):
    """The box NOCS runs on (ADR 0027)."""

    hostname: str = Field(description="Also its mDNS name, <hostname>.local.")
    helper: bool = Field(description="nocs-system answers.")
    operations: list[str] = Field(
        description="What nocs-system performs here: power.reboot, power.poweroff,"
        " hostname.set. Empty on a PC unless its owner enables them."
    )
    error: str | None = Field(description="Why nocs-system does not answer.")
    health: SystemHealth | None = Field(description="None until the first reading.")


class SequencePlanRow(StateModel):
    filter: str | None
    exposure: float
    count: int
    done: int = Field(description="Frames taken.")


class SequencePlan(StateModel):
    target: str | None
    rows: list[SequencePlanRow]


class SequenceRun(StateModel):
    """A sequence's run in progress, or the last one (ADR 0031)."""

    run: str
    name: str
    state: Literal["running", "pausing", "paused", "stopping", "ending", "finished"]
    started: str = Field(description="UTC, ISO 8601.")
    restarts: int = Field(description="Times it was resumed after nocsd restarted.")
    current: str | None = Field(description="Where in the tree: start, targets.0.1, end.0…")
    plans: dict[str, SequencePlan] = Field(description="Exposure plans by place in the tree.")
    outcome: Literal["completed", "stopped", "failed"] | None
    error: str | None


class SequenceEvent(StateModel):
    time: str = Field(description="UTC, ISO 8601.")
    kind: Literal[
        "started",
        "resumed_after_restart",
        "action",
        "frame",
        "trigger",
        "condition",
        "paused",
        "resumed",
        "failed",
        "skipped",
        "ending",
        "ended",
    ]
    message: str
    path: str | None
    data: dict[str, Any] = Field(
        description="A frame's row, stars and HFR; an autofocus run's position and HFR…"
    )


class SequenceState(StateModel):
    run: SequenceRun | None
    events: list[SequenceEvent] = Field(description="The run's most recent events, oldest first.")


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
    autofocus: AutofocusState | None = Field(default=None, description="None: never run.")
    centering: CenteringState | None = Field(default=None, description="None: never run.")
    plan: PlanState | None = None
    guiding: GuidingState | None = None
    system: SystemState | None = None
    sequence: SequenceState | None = None
    gps: GpsState | None = None
    updates: UpdatesState | None = Field(
        default=None, description="None where NOCS does not install updates (a PC)."
    )
    network: NetworkState | None = Field(
        default=None, description="None where NOCS does not manage the network (a PC)."
    )


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


class GuidingLoopRequest(BaseModel):
    exposure: float | None = Field(
        default=None, ge=0.05, le=60, description="Seconds; PHD2's current one when omitted."
    )


class SettleRequest(BaseModel):
    pixels: float = Field(default=1.5, gt=0, le=20, description="Within this distance, px…")
    time: float = Field(default=10, ge=0, le=300, description="…for this long, seconds…")
    timeout: float = Field(default=60, gt=0, le=600, description="…or give up after this.")


class SequencePauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: bool = Field(default=False, description="Drop the frame in progress instead of waiting.")


class SequenceStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_end: bool = Field(default=True, description="Run the end of the session (park, warm…).")
    now: bool = Field(default=False, description="Drop the frame in progress instead of waiting.")


class GuideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recalibrate: bool = Field(
        default=False,
        description="Calibrate even if PHD2 has a calibration (after rotating the camera).",
    )
    settle: SettleRequest = Field(default_factory=SettleRequest)


class GuideSteps(WireModel):
    steps: list[GuideEntryModel]
    pixel_scale: float | None


class GuidingExposureRequest(BaseModel):
    exposure: float = Field(ge=0.05, le=60, description="Seconds.")


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


class DitherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    every: int = Field(default=1, ge=1, le=100, description="Dither before every n-th frame.")
    pixels: float = Field(
        default=5, gt=0, le=100, description="Up to this far, in main camera pixels."
    )
    ra_only: bool = False
    settle: SettleRequest = Field(default_factory=SettleRequest)


class DitherNowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pixels: float = Field(gt=0, le=100, description="Up to this far, in main camera pixels.")
    ra_only: bool = False
    settle: SettleRequest = Field(default_factory=SettleRequest)


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
    count: int = Field(default=1, ge=1, le=1000, description="Frames in the series.")
    dither: DitherRequest | None = Field(
        default=None, description="Main camera series only: dither between frames (ADR 0024)."
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
    stop_guiding: bool = Field(
        default=False, description="Stop guiding first; refused while guiding otherwise (ADR 0023)."
    )


class HorizontalGoto(BaseModel):
    """Point at a place in the local sky (e.g. the zenith for flats); tracking stops."""

    model_config = ConfigDict(extra="forbid")

    frame: Literal["altaz"]
    alt: float = Field(ge=0, le=90, description="Degrees.")
    az: float = Field(ge=0, lt=360, description="Degrees from north through east.")
    stop_guiding: bool = Field(
        default=False, description="Stop guiding first; refused while guiding otherwise (ADR 0023)."
    )


class MountMoveRequest(BaseModel):
    """Park or home."""

    model_config = ConfigDict(extra="forbid")

    stop_guiding: bool = Field(
        default=False, description="Stop guiding first; refused while guiding otherwise (ADR 0023)."
    )


type GotoRequest = Annotated[EquatorialGoto | HorizontalGoto, Field(discriminator="frame")]


class TrackingRequest(BaseModel):
    """Only the fields present are changed."""

    model_config = ConfigDict(extra="forbid")

    on: bool | None = None
    mode: str | None = Field(default=None, description="One of the mount's track_modes.")


class ShutdownRequest(BaseModel):
    """Refused (409) while a job runs, unless ``force``."""

    model_config = ConfigDict(extra="forbid")

    force: bool = False


class NetworkJoinRequest(BaseModel):
    """Accepted at once (202): the box leaves its access point to join in a moment, and
    comes back as an access point within a minute if it cannot (ADR 0028)."""

    model_config = ConfigDict(extra="forbid")

    ssid: str
    password: str | None = Field(default=None, description="None for an open network.")


class NetworkForgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ssid: str


class AccessPointRequest(BaseModel):
    """Changes apply at once when the box is an access point: phones on it must join
    it again (with the new password)."""

    model_config = ConfigDict(extra="forbid")

    ssid: str | None = None
    password: str | None = Field(default=None, description="8 to 63 characters.")
    country: str | None = Field(default=None, description="Two letters, ISO 3166 (e.g. CL).")


class NetworkSetupRequest(BaseModel):
    """The first run on the appliance (ADR 0028): the access point's country and new
    password, and optionally a network to join. Accepted at once (202): the access
    point restarts with the new password, or the box leaves it to join the network."""

    model_config = ConfigDict(extra="forbid")

    country: str = Field(description="Two letters, ISO 3166 (e.g. CL).")
    password: str = Field(description="The access point's new password, 8 to 63 characters.")
    join: NetworkJoinRequest | None = None


class NetworkModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: Literal["auto", "ap", "station"]


class EjectRequest(BaseModel):
    """Refused (409) while a job runs, unless ``force``; always while a frame is being saved
    to the drive."""

    model_config = ConfigDict(extra="forbid")

    force: bool = False


class HostnameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="One DNS label: letters, digits and hyphens, at most 63.")


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


class AutofocusRequest(BaseModel):
    """What is left out comes from the imaging train's sweep and the focuser's backlash."""

    model_config = ConfigDict(extra="forbid")

    step: int | None = Field(default=None, ge=1, description="Focuser steps between points.")
    points: int | None = Field(default=None, ge=5, le=25)
    exposure: float | None = Field(default=None, gt=0, le=600, description="Seconds.")
    frames: int | None = Field(default=None, ge=1, le=10, description="Frames per point.")
    direction: Literal["outward", "inward"] | None = Field(
        default=None, description="Which way every position is reached (backlash)."
    )
    overshoot: int | None = Field(
        default=None, ge=0, description="Steps past a target moving the other way."
    )


class FocuserBacklashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["outward", "inward"] = "outward"
    overshoot: int | None = Field(
        default=None, ge=0, le=100000, description="None: one sweep step."
    )


class AutofocusRun(WireModel):
    """A finished autofocus run, from the catalog."""

    id: int
    started: str
    finished: str
    profile: str | None
    filter: str | None
    state: Literal["succeeded", "failed", "cancelled"]
    problem: str | None
    start_position: int
    position: int | None
    start_hfr: float | None
    hfr: float | None
    focuser_temperature: float | None
    ambient_temperature: float | None
    run: AutofocusState = Field(description="The run as the state showed it at its end.")


class TemperatureRecord(WireModel):
    time: str = Field(description="UTC, ISO 8601.")
    focuser: float | None = Field(description="The focuser's probe, °C.")
    ambient: float | None = Field(description="The weather role's, °C.")
    humidity: float | None = Field(description="%.")
    dew_point: float | None = Field(description="°C.")


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exposure: float | None = Field(
        default=None, gt=0, le=600, description="Seconds; None: the camera's exposure."
    )
    binning: int | None = Field(default=None, ge=1, description="For this frame only.")
    sync: bool = Field(default=False, description="Sync the mount to the solution.")


class CenterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ra: float = Field(ge=0, lt=24, description="J2000, hours.")
    dec: float = Field(ge=-90, le=90, description="J2000, degrees.")
    tolerance: float = Field(default=1.0, gt=0, le=60, description="Arcminutes.")
    attempts: int = Field(default=5, ge=1, le=20, description="Frames at most.")
    settle: float = Field(default=2.0, ge=0, le=60, description="Seconds after each slew.")
    method: Literal["sync", "offset"] = "sync"
    exposure: float | None = Field(
        default=None, gt=0, le=600, description="Seconds; None: the camera's exposure."
    )
    binning: int | None = Field(default=None, ge=1, description="For the frames only.")
    force: bool = Field(default=False, description="Go below the horizon.")


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
    guiding: FrameGuiding | None = Field(description="None: not guided, or saved before 4.5.")


class JobStarted(WireModel):
    job: str


class SequenceEstimate(WireModel):
    """What a template's plan costs, and how much of tonight it has (phase 5.10)."""

    frames: int
    integration: float = Field(description="Seconds of exposure.")
    duration: float = Field(description="Seconds the frames take, without focusing or slewing.")
    bytes: int | None = Field(description="On disk; None while the camera is unknown.")
    window: float | None = Field(
        description="Seconds tonight's dark window keeps the target above the minimum altitude"
        " and the horizon; None while the site is unknown."
    )


class Driver(WireModel):
    driver: str = Field(description="Executable, e.g. indi_asi_ccd.")
    name: str
    label: str = Field(description="Device model the entry is for (one driver, many models).")
    manufacturer: str
    group: str


class SerialPortInfo(WireModel):
    path: str = Field(description="Stable /dev/serial/by-id/ name.")
    device: str = Field(description="Device node it points to now.")


# -- Target catalog (ADR 0019) ---------------------------------------------------


class CatalogObject(WireModel):
    id: str = Field(description="Designation in its source catalog, e.g. NGC 1976.")
    label: str = Field(description="How people call it: its Messier number, else its id.")
    type: TargetType
    ra: float = Field(description="J2000, hours.")
    dec: float = Field(description="J2000, degrees.")
    constellation: str | None = Field(description="IAU abbreviation, e.g. Ori.")
    magnitude: float | None = Field(description="The brighter of the visual and blue ones.")
    major_axis: float | None = Field(description="Arcminutes.")
    minor_axis: float | None = Field(description="Arcminutes.")
    position_angle: float | None = Field(description="Of the major axis, degrees east of north.")
    aliases: list[str] = Field(description="Other designations, Messier and Caldwell first.")
    names: list[str] = Field(description="Common names in English.")
    names_es: list[str] = Field(description="Common names in Spanish, where they differ.")


class CatalogMatch(WireModel):
    object: CatalogObject
    matched: str = Field(description="The designation or name the query matched.")


class SkyChart(WireModel):
    """What the framing chart draws around a point (ADR 0020)."""

    ra: float = Field(description="Centre, J2000, hours.")
    dec: float = Field(description="Centre, J2000, degrees.")
    radius: float = Field(description="Degrees.")
    magnitude: float = Field(
        description="Faintest magnitude of the stars here: the one asked for, or the bundled"
        " file's own limit if brighter."
    )
    stars: list[list[float]] = Field(
        description="[RA J2000 hours, Dec J2000 degrees, V magnitude], brightest first."
    )
    truncated: bool = Field(description="More stars matched: only the brightest ones are here.")
    star_catalog: bool = Field(
        description="The star file is installed; a commercial distribution may leave it out"
        " (its licence is non-commercial, ADR 0020)."
    )
    objects: list[CatalogObject] = Field(
        description="Deep-sky objects whose extent reaches into the circle, the brightest first."
    )


class CatalogSource(WireModel):
    """Where the bundled catalog comes from; its licence asks to show the attribution."""

    name: str
    version: str
    url: str
    license: str
    license_url: str
    attribution: str


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


# -- Tonight's sky (phase 3.5) ---------------------------------------------------
# Times are UTC, ISO 8601. A night runs from local noon to local noon (local mean
# solar time) and is named after its first date, like the frame catalog's nights.
# Curves are sampled at ``times``, every 10 minutes from sunset to sunrise.

type DarknessName = Literal["civil", "nautical", "astronomical"]


class TimeInterval(WireModel):
    start: str
    end: str


class MoonNight(WireModel):
    rise: str | None = Field(description="The night's moonrise (upper limb), if any.")
    set: str | None
    up: list[TimeInterval] = Field(description="When the Moon is above the horizon.")
    fraction: float = Field(description="Illuminated, 0..1, at the middle of the dark window.")
    phase: float = Field(
        description="Degrees then: 0 new, 90 first quarter, 180 full, 270 last quarter."
    )
    altitude: list[float] = Field(description="Apparent, degrees, at each of times.")
    azimuth: list[float]


class Almanac(WireModel):
    """``GET /api/sky/tonight``: the night at the active profile's site."""

    night: str = Field(description="YYYY-MM-DD, the date at the start of the night.")
    site: Site
    start: str = Field(description="Local noon.")
    end: str = Field(description="The next local noon.")
    sunset: str | None = Field(description="None when the Sun does not set this night.")
    sunrise: str | None
    civil: TimeInterval | None = Field(
        description="The Sun below -6°: dusk to dawn, clipped to the night; None if never."
    )
    nautical: TimeInterval | None = Field(description="Below -12°.")
    astronomical: TimeInterval | None = Field(description="Below -18°.")
    darkness: DarknessName | None = Field(description="The darkest twilight the night reaches.")
    dark: TimeInterval | None = Field(description="The window of that darkness.")
    dark_moonless: list[TimeInterval] = Field(description="The dark window without the Moon.")
    sun_lowest: str
    sun_lowest_altitude: float = Field(description="Degrees, geometric.")
    times: list[str]
    sun_altitude: list[float] = Field(description="Geometric, degrees, at each of times.")
    moon: MoonNight


class TargetVisibility(WireModel):
    target: str = Field(description="As asked.")
    ra: float = Field(description="J2000 hours.")
    dec: float = Field(description="J2000 degrees.")
    altitude: list[float] = Field(description="Apparent, degrees, at each of times.")
    azimuth: list[float]
    horizon: list[float] = Field(description="The horizon profile's altitude at each azimuth.")
    transit: str = Field(description="The upper culmination closest to the middle of the night.")
    transit_altitude: float
    above_minimum: float = Field(description="Seconds of the dark window above min_altitude.")
    above_horizon: float = Field(description="Seconds of the dark window above the horizon.")
    windows: list[TimeInterval] = Field(description="Within the dark window, above both.")
    best: TimeInterval | None = Field(description="The longest of windows.")
    observable: float = Field(description="Seconds of windows.")
    moon_separation: float = Field(
        description="Degrees, at the middle of the best window (or else at transit)."
    )
    moon_separation_min: float | None = Field(description="Over the dark window.")


class SkyVisibility(WireModel):
    """``GET /api/sky/visibility``: targets during a night at the active profile's site."""

    night: str
    min_altitude: float
    darkness: DarknessName | None
    dark: TimeInterval | None
    times: list[str]
    targets: list[TargetVisibility]
