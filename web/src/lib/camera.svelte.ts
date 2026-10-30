// What the Live view reads from the state besides the camera itself: the job a
// camera is busy with, the filter wheel, and this device's capture choices.

import { setIndiProperty } from "./api";
import type { AppState, CameraRoleName, JobInfo } from "./types";

export const CAMERA_ROLES: readonly CameraRoleName[] = ["main_camera", "guide_camera"];

// Server limits (ExposeRequest, LoopRequest).
export const MAX_EXPOSURE = 7200;
export const MAX_LOOP_EXPOSURE = 600;

// -- Jobs -----------------------------------------------------------------------

export type CameraJob = { id: string; info: JobInfo };

// The job running on a camera, if any, and the latest one started on it
// (running or finished): its outcome is what the screen reports.
export function cameraJobs(
  jobs: Record<string, JobInfo> | null | undefined,
  role: CameraRoleName,
): { running: CameraJob | null; latest: CameraJob | null } {
  let running: CameraJob | null = null;
  let latest: CameraJob | null = null;
  for (const [id, info] of Object.entries(jobs ?? {})) {
    if (!info.resources.includes(role)) continue;
    if (info.state === "running") running = { id, info };
    if (!latest || info.started > latest.info.started) latest = { id, info };
  }
  return { running, latest };
}

// -- Filter wheel ---------------------------------------------------------------
// Read from the raw INDI properties until stage 2.8 gives the wheel a typed
// state and endpoint; selectFilter() is the only place that writes to it.

export interface FilterWheelState {
  device: string;
  // 1-based, as INDI counts slots; null while unknown.
  slot: number | null;
  // One name per slot; empty when the driver has no names for a slot.
  names: string[];
  moving: boolean;
}

export function filterWheel(app: AppState): FilterWheelState | null {
  const role = app.equipment?.devices.filter_wheel;
  if (!role?.device || role.status !== "ready") return null;
  const properties = app.indi?.devices?.[role.device]?.properties;
  const slotProperty = properties?.FILTER_SLOT;
  const element = slotProperty?.elements.FILTER_SLOT_VALUE;
  if (!slotProperty || !element || !("max" in element)) return null;
  const names = Object.values(properties.FILTER_NAME?.elements ?? {}).map((name) =>
    typeof name.value === "string" ? name.value.trim() : "",
  );
  const count = names.length || Math.max(0, Math.round(element.max));
  return {
    device: role.device,
    slot: Math.round(element.value) || null,
    names: names.length ? names : Array.from({ length: count }, () => ""),
    moving: slotProperty.state === "Busy",
  };
}

export function selectFilter(wheel: FilterWheelState, slot: number): Promise<void> {
  return setIndiProperty(wheel.device, "FILTER_SLOT", { FILTER_SLOT_VALUE: slot });
}

// -- Capture choices ------------------------------------------------------------
// Per device, like the theme: the exposure time is not part of the camera's
// state, and whether to save is a choice made before each frame.

const EXPOSURE_DEFAULT = 2;

function readNumber(key: string): number | null {
  try {
    const value = Number(localStorage.getItem(key));
    return localStorage.getItem(key) !== null && Number.isFinite(value) ? value : null;
  } catch {
    return null; // storage blocked (private mode): fall back to defaults
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Not persisted; the choice still applies until the page reloads.
  }
}

class CapturePrefs {
  role: CameraRoleName = $state("main_camera");
  exposure: Record<CameraRoleName, number> = $state({
    main_camera: readNumber("nocs.exposure.main_camera") ?? EXPOSURE_DEFAULT,
    guide_camera: readNumber("nocs.exposure.guide_camera") ?? EXPOSURE_DEFAULT,
  });
  save: boolean = $state(readNumber("nocs.save") !== 0);
  // Exposure time of the jobs this device started, to show "74 / 120 s".
  started: Record<string, number> = $state({});

  setExposure(role: CameraRoleName, seconds: number): void {
    this.exposure[role] = seconds;
    write(`nocs.exposure.${role}`, String(seconds));
  }

  setSave(save: boolean): void {
    this.save = save;
    write("nocs.save", save ? "1" : "0");
  }
}

export const capture = new CapturePrefs();
