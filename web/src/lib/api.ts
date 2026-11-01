// Typed REST client over the generated wire types. Every failure is an
// ApiError: status 0 means the request never reached nocsd.

import type {
  AccessPointRequest,
  AuthStatus,
  AutofocusRequest,
  AutofocusRun,
  CameraRoleName,
  CameraSettingsRequest,
  CenterRequest,
  ClockReport,
  ClockRequest,
  ConnectRequest,
  CoolingRequest,
  DitherNowRequest,
  DitherRequest,
  Driver,
  EjectRequest,
  EquatorialGoto,
  ExposeRequest,
  FilterNamesRequest,
  FilterSelectRequest,
  FocuserBacklashRequest,
  FocuserMoveRequest,
  GuideRequest,
  GuideSteps,
  HorizontalGoto,
  HostnameRequest,
  JobStarted,
  LoopRequest,
  MountSiteRequest,
  NetworkForgetRequest,
  NetworkJoinRequest,
  NetworkModeRequest,
  ObserverRequest,
  OutputRequest,
  PairedDevice,
  PairRequest,
  Profile,
  SerialPortInfo,
  ShutdownRequest,
  Site,
  SolveRequest,
  TrackingRequest,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    // Seconds, from Retry-After (throttled passphrase attempts).
    readonly retryAfter: number | null = null,
  ) {
    super(message);
  }

  get network(): boolean {
    return this.status === 0;
  }
}

type Unauthorized = () => void;
let onUnauthorized: Unauthorized = () => {};

// Called on any 401: this device is no longer (or not yet) paired.
export function setUnauthorizedHandler(handler: Unauthorized): void {
  onUnauthorized = handler;
}

// FastAPI puts a string in `detail`, or a list of validation errors.
function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item: unknown) =>
      typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : String(item),
    );
    return messages.join("; ");
  }
  return fallback;
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : String(e));
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: unknown };
    const retry = Number(response.headers.get("Retry-After"));
    const error = new ApiError(
      response.status,
      detailText(payload.detail, response.statusText),
      Number.isFinite(retry) && retry > 0 ? retry : null,
    );
    if (response.status === 401) onUnauthorized();
    throw error;
  }
  if (response.status === 204 || response.headers.get("Content-Length") === "0") {
    return undefined as T;
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// -- Authentication (ADR 0014) ------------------------------------------------

export function getAuth(): Promise<AuthStatus> {
  return request("GET", "/api/auth");
}

// Setting up the passphrase also pairs this device.
export function setUp(body: PairRequest): Promise<PairedDevice> {
  return request("POST", "/api/auth/setup", body);
}

export function pair(body: PairRequest): Promise<PairedDevice> {
  return request("POST", "/api/auth/pair", body);
}

export function listDevices(): Promise<PairedDevice[]> {
  return request("GET", "/api/auth/devices");
}

export function revokeDevice(id: string): Promise<void> {
  return request("DELETE", `/api/auth/devices/${encodeURIComponent(id)}`);
}

export function setObserver(enabled: boolean): Promise<void> {
  return request("PUT", "/api/auth/observer", { enabled } satisfies ObserverRequest);
}

// -- This computer, through nocs-system (ADR 0027) -----------------------------

// Unmounts a USB drive and powers it off; refused (409) while a frame is being
// saved to it, and while a job runs unless forced.
export function ejectDrive(id: string, force = false): Promise<void> {
  return request("POST", `/api/storage/destinations/${encodeURIComponent(id)}/eject`, {
    force,
  } satisfies EjectRequest);
}

// Refused (409) while a job runs, unless forced.
export function reboot(force = false): Promise<void> {
  return request("POST", "/api/system/reboot", { force } satisfies ShutdownRequest);
}

export function powerOff(force = false): Promise<void> {
  return request("POST", "/api/system/poweroff", { force } satisfies ShutdownRequest);
}

// Restarting indiserver drops every device; refused (409) while a job runs, unless forced.
export function restartService(service: "indiserver" | "phd2", force = false): Promise<void> {
  return request("POST", `/api/system/services/${service}/restart`, { force } satisfies ShutdownRequest);
}

export function setHostname(name: string): Promise<void> {
  return request("PUT", "/api/system/hostname", { name } satisfies HostnameRequest);
}

// The GPS's position becomes the active profile's site, and the mount's (ADR 0029).
export function useGpsSite(): Promise<Site> {
  return request("POST", "/api/gps/site");
}

// The box leaves its access point to join in a moment (202): the phone must follow it.
export function joinNetwork(ssid: string, password: string | null): Promise<void> {
  return request("POST", "/api/system/network/join", { ssid, password } satisfies NetworkJoinRequest);
}

export function forgetNetwork(ssid: string): Promise<void> {
  return request("POST", "/api/system/network/forget", { ssid } satisfies NetworkForgetRequest);
}

// Applied at once when the box is an access point: phones on it must join it again.
export function setAccessPoint(body: AccessPointRequest): Promise<void> {
  return request("PUT", "/api/system/network/access-point", body);
}

export function setNetworkMode(pin: NetworkModeRequest["pin"]): Promise<void> {
  return request("PUT", "/api/system/network/mode", { pin } satisfies NetworkModeRequest);
}

// A zip for bug reports: versions, the state and the last day of logs.
export const DIAGNOSTICS_URL = "/api/system/diagnostics";

// -- Equipment ----------------------------------------------------------------

export function getProfile(id: string): Promise<Profile> {
  return request("GET", `/api/profiles/${encodeURIComponent(id)}`);
}

export function putProfile(id: string, profile: Profile): Promise<void> {
  return request("PUT", `/api/profiles/${encodeURIComponent(id)}`, profile);
}

export function deleteProfile(id: string): Promise<void> {
  return request("DELETE", `/api/profiles/${encodeURIComponent(id)}`);
}

export function listDrivers(): Promise<Driver[]> {
  return request("GET", "/api/indi/drivers");
}

export function listSerialPorts(): Promise<SerialPortInfo[]> {
  return request("GET", "/api/system/serial-ports");
}

export function connectProfile(profile: string): Promise<void> {
  return request("POST", "/api/equipment/connect", { profile } satisfies ConnectRequest);
}

export function disconnectEquipment(): Promise<void> {
  return request("POST", "/api/equipment/disconnect");
}

export function setIndiProperty(
  device: string,
  name: string,
  values: Record<string, string | number | boolean>,
): Promise<void> {
  const url = `/api/indi/devices/${encodeURIComponent(device)}/properties/${encodeURIComponent(name)}`;
  return request("POST", url, { values });
}

// -- Focuser and filter wheel --------------------------------------------------

export async function moveFocuser(body: FocuserMoveRequest): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/focuser/move", body);
  return started.job;
}

export function abortFocuser(): Promise<void> {
  return request("POST", "/api/focuser/abort");
}

export function setFocuserBacklash(body: FocuserBacklashRequest): Promise<void> {
  return request("PUT", "/api/focuser/backlash", body);
}

// -- Autofocus (ADR 0021) ---------------------------------------------------------

// What the request leaves out comes from the imaging train's sweep and the
// focuser's backlash.
export async function startAutofocus(body: AutofocusRequest): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/autofocus", body);
  return started.job;
}

// Finished runs, newest first.
export function autofocusRuns(limit = 1): Promise<AutofocusRun[]> {
  return request("GET", `/api/autofocus/runs?limit=${limit}`);
}

export async function selectFilter(body: FilterSelectRequest): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/filter-wheel/select", body);
  return started.job;
}

export function setFilterNames(body: FilterNamesRequest): Promise<void> {
  return request("PUT", "/api/filter-wheel/names", body);
}

// -- Cameras and jobs -----------------------------------------------------------

export function setCameraSettings(role: CameraRoleName, body: CameraSettingsRequest): Promise<void> {
  return request("POST", `/api/cameras/${role}/settings`, body);
}

export function setCooling(role: CameraRoleName, body: CoolingRequest): Promise<void> {
  return request("POST", `/api/cameras/${role}/cooling`, body);
}

// The frame type is the camera's current one; `save` defaults to the server's
// choice (the main camera saves, the guide camera never does). A series of the
// main camera may dither between its frames while PHD2 guides (ADR 0024).
export async function expose(
  role: CameraRoleName,
  exposure: number,
  save?: boolean,
  series?: { count: number; dither: DitherRequest | null },
): Promise<string> {
  const body: ExposeRequest = save === undefined ? { exposure } : { exposure, save };
  if (series && series.count > 1) {
    body.count = series.count;
    body.dither = series.dither;
  }
  const started = await request<JobStarted>("POST", `/api/cameras/${role}/expose`, body);
  return started.job;
}

export async function loop(role: CameraRoleName, exposure: number): Promise<string> {
  const body: LoopRequest = { exposure };
  const started = await request<JobStarted>("POST", `/api/cameras/${role}/loop`, body);
  return started.job;
}

export function cancelJob(job: string): Promise<void> {
  return request("POST", `/api/jobs/${job}/cancel`);
}

// -- Guiding with PHD2 (ADR 0022–0024) ---------------------------------------------

export function connectGuiding(): Promise<void> {
  return request("POST", "/api/guiding/connect");
}

export function disconnectGuiding(): Promise<void> {
  return request("POST", "/api/guiding/disconnect");
}

export function loopGuiding(exposure?: number): Promise<void> {
  return request("POST", "/api/guiding/loop", exposure === undefined ? {} : { exposure });
}

export function setGuidingExposure(exposure: number): Promise<void> {
  return request("PUT", "/api/guiding/exposure", { exposure });
}

// Starting to guide is a job: it ends once PHD2 has settled; guiding goes on.
export async function startGuiding(body: GuideRequest = {}): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/guiding/guide", body);
  return started.job;
}

export function stopGuiding(): Promise<void> {
  return request("POST", "/api/guiding/stop");
}

// Up to `pixels` of the main camera; the job ends once PHD2 has settled.
export async function ditherNow(body: DitherNowRequest): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/guiding/dither", body);
  return started.job;
}

// The guiding run's graph: entries numbered above `after`, oldest first.
export function guideSteps(after = 0): Promise<GuideSteps> {
  return request("GET", `/api/guiding/steps?after=${after}`);
}

// -- Power box (ADR 0017) ------------------------------------------------------

export function setOutput(id: string, change: OutputRequest): Promise<void> {
  return request("PUT", `/api/power/outputs/${encodeURIComponent(id)}`, change);
}

export function setAutoDew(on: boolean): Promise<void> {
  return request("PUT", "/api/power/auto-dew", { on });
}

// -- Mount and clock (ADR 0015) --------------------------------------------------

// This client's clock and time zone, reported whenever it connects: the server
// corrects its own timestamps when the system clock is off, and sets the mount's.
export function reportClock(): Promise<ClockReport> {
  const body: ClockRequest = {
    utc: new Date().toISOString(),
    utc_offset: -new Date().getTimezoneOffset() / 60,
  };
  return request("POST", "/api/clock", body);
}

export async function gotoMount(body: EquatorialGoto | HorizontalGoto): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/mount/goto", body);
  return started.job;
}

export function abortMount(): Promise<void> {
  return request("POST", "/api/mount/abort");
}

export function setTracking(body: TrackingRequest): Promise<void> {
  return request("PUT", "/api/mount/tracking", body);
}

export async function parkMount(): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/mount/park");
  return started.job;
}

export function unparkMount(): Promise<void> {
  return request("POST", "/api/mount/unpark");
}

export async function homeMount(): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/mount/home");
  return started.job;
}

export function sendMountTime(): Promise<void> {
  return request("POST", "/api/mount/time");
}

// Without a site, the active profile's.
export function sendMountSite(body: MountSiteRequest = {}): Promise<void> {
  return request("PUT", "/api/mount/site", body);
}

// -- Plate solving (ADR 0018) ---------------------------------------------------

// A frame of the main camera, solved; with `sync`, the mount is synced to it.
export async function solve(body: SolveRequest = {}): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/solver/solve", body);
  return started.job;
}

// Syncs the mount to the last solution, if it has not moved since that frame.
export function syncToSolution(): Promise<void> {
  return request("POST", "/api/solver/sync");
}

// Goes to a J2000 target and centres it in the main camera's frame (stage 3.3).
export async function centerOn(body: CenterRequest): Promise<string> {
  const started = await request<JobStarted>("POST", "/api/solver/center", body);
  return started.job;
}
