// Typed REST client over the generated wire types. Every failure is an
// ApiError: status 0 means the request never reached nocsd.

import type {
  AuthStatus,
  CameraRoleName,
  CameraSettingsRequest,
  ConnectRequest,
  CoolingRequest,
  Driver,
  ExposeRequest,
  FilterNamesRequest,
  FilterSelectRequest,
  FocuserMoveRequest,
  JobStarted,
  LoopRequest,
  ObserverRequest,
  OutputRequest,
  PairedDevice,
  PairRequest,
  Profile,
  SerialPortInfo,
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
// choice (the main camera saves, the guide camera never does).
export async function expose(role: CameraRoleName, exposure: number, save?: boolean): Promise<string> {
  const body: ExposeRequest = save === undefined ? { exposure } : { exposure, save };
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

// -- Power box (ADR 0017) ------------------------------------------------------

export function setOutput(id: string, change: OutputRequest): Promise<void> {
  return request("PUT", `/api/power/outputs/${encodeURIComponent(id)}`, change);
}

export function setAutoDew(on: boolean): Promise<void> {
  return request("PUT", "/api/power/auto-dew", { on });
}
