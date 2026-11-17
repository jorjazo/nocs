// What Explore reads from the state besides the camera itself: the job a
// camera is busy with, the focuser and filter wheel, and this device's choices.

import type { Messages } from "./i18n";
import type { CameraRoleName, FilterWheelState, JobInfo, Role } from "./types";

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
    // A paused sequence lends its devices (ADR 0031): it holds nothing meanwhile.
    if (!info.resources.includes(role) || info.suspended) continue;
    if (info.state === "running") running = { id, info };
    if (!latest || info.started > latest.info.started) latest = { id, info };
  }
  return { running, latest };
}

// -- Focuser and filter wheel ---------------------------------------------------

// The running job that locks a device: its own move, or a main camera exposure
// (which locks both, so a frame is never spoiled; loops lock only the camera).
export function holder(jobs: Record<string, JobInfo> | null | undefined, resource: Role): CameraJob | null {
  for (const [id, info] of Object.entries(jobs ?? {})) {
    if (info.state === "running" && !info.suspended && info.resources.includes(resource)) return { id, info };
  }
  return null;
}

// Steps the focuser moves per tap; the choice is kept per device.
export const FOCUS_STEPS: readonly number[] = [10, 50, 100, 500, 1000];

// Explore's focuser speeds (ADR 0054): half, once or twice the step set.
export const FOCUS_SPEEDS: readonly number[] = [0.5, 1, 2];

export function speedStep(step: number, speed: number): number {
  return Math.max(1, Math.round(step * speed));
}

// How far "Dither now" dithers, on the guiding screen.
export const DITHER_PIXELS = 5;
export const MAX_SERIES = 1000;

// Offered first when naming filters, so every wheel names a filter the same way
// (frames are grouped by these names, ADR 0016).
export const COMMON_FILTERS: readonly string[] = ["L", "R", "G", "B", "Ha", "OIII", "SII"];

// The name of a slot to show: its filter, or "Slot 3" when it has none.
export function slotLabel(wheel: FilterWheelState, slot: number, t: Messages): string {
  return wheel.names[slot - 1] || t.live.slot(slot);
}

// -- Capture choices ------------------------------------------------------------
// Per device, like the theme: the camera shown, the focuser's step and Explore's speed
// of it, how many frames a capture takes (a short stack, ADR 0054), and how far
// "Dither now" dithers. The exposure time is in the camera's state.

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

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

function readRole(): CameraRoleName {
  try {
    const value = localStorage.getItem("nocs.camera");
    return CAMERA_ROLES.find((role) => role === value) ?? "main_camera";
  } catch {
    return "main_camera";
  }
}

class CapturePrefs {
  role: CameraRoleName = $state(readRole());
  focusStep: number = $state(FOCUS_STEPS.find((step) => step === readNumber("nocs.focusStep")) ?? 100);
  focusSpeed: number = $state(FOCUS_SPEEDS.find((speed) => speed === readNumber("nocs.focusSpeed")) ?? 1);
  count: number = $state(clamp(readNumber("nocs.frames") ?? 1, 1, MAX_SERIES));
  ditherPixels: number = $state(clamp(readNumber("nocs.ditherPixels") ?? DITHER_PIXELS, 1, 100));

  setRole(role: CameraRoleName): void {
    this.role = role;
    write("nocs.camera", role);
  }

  setFocusStep(step: number): void {
    this.focusStep = step;
    write("nocs.focusStep", String(step));
  }

  setFocusSpeed(speed: number): void {
    this.focusSpeed = speed;
    write("nocs.focusSpeed", String(speed));
  }

  setCount(count: number): void {
    this.count = clamp(Math.round(count), 1, MAX_SERIES);
    write("nocs.frames", String(this.count));
  }

  setDitherPixels(pixels: number): void {
    this.ditherPixels = clamp(pixels, 1, 100);
    write("nocs.ditherPixels", String(this.ditherPixels));
  }
}

export const capture = new CapturePrefs();
