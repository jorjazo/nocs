// What Tonight's cards work out from the state (docs/ux.md §1): what the mount
// points at, when the camera's cooler is off its target, how the power box's input
// stands, and which forecast hours to show. Pure functions, tested with `pnpm test`.

import { separation } from "./sky/projection.ts";
import type { ForecastHour, PlannedTarget, SkyPointing } from "./types.ts";

// -- Pointing -------------------------------------------------------------------------

export interface Sky {
  ra: number; // J2000 hours
  dec: number; // J2000 degrees
}

export type Pointed =
  | { kind: "planned"; target: PlannedTarget }
  | { kind: "body"; body: "sun" | "moon" }
  | { kind: "catalog"; object: SkyPointing["objects"][number] }
  | { kind: "none" };

// Without the camera's field, a frame is taken to reach this far from its centre.
export const DEFAULT_RADIUS = 0.5;

// Degrees from a frame's centre to its corner.
export function frameRadius(field: { width: number; height: number } | null | undefined): number {
  return field ? Math.hypot(field.width, field.height) / 2 : DEFAULT_RADIUS;
}

// What the mount points at: tonight's target when it is in the frame, else the Sun
// or the Moon, else the nearest catalog object the server found there.
export function pointedAt(
  mount: Sky,
  radius: number,
  planned: PlannedTarget | null,
  around: SkyPointing | null,
): Pointed {
  if (planned && separation(mount, planned) <= radius) return { kind: "planned", target: planned };
  if (around?.body) return { kind: "body", body: around.body };
  const object = around?.objects[0];
  return object ? { kind: "catalog", object } : { kind: "none" };
}

// Whether the mount moved far enough from where the server was last asked to ask again.
export function movedFrom(asked: Sky | null, now: Sky, radius: number): boolean {
  return asked === null || separation(asked, now) > radius / 4;
}

// -- The camera's cooler ----------------------------------------------------------------

// Degrees the sensor may stay from its target once the ramp had time to get there.
export const COOLER_TOLERANCE = 1;
// Minutes allowed without a ramp limit (the cooler's own pace), and on top of a ramp's.
export const COOLER_SETTLE = 5;

export interface CoolerStart {
  at: number; // ms, when this target was first seen with the cooler on
  temperature: number; // °C then
  target: number;
}

// When the sensor should have reached its target (ms).
export function settledBy(start: CoolerStart, ramp: number | null): number {
  const minutes = ramp && ramp > 0 ? Math.abs(start.temperature - start.target) / ramp : 0;
  return start.at + (minutes + COOLER_SETTLE) * 60_000;
}

export function coolerOffTarget(
  start: CoolerStart | null,
  temperature: number | null,
  ramp: number | null,
  now: number,
): boolean {
  if (!start || temperature === null) return false;
  return now >= settledBy(start, ramp) && Math.abs(temperature - start.target) > COOLER_TOLERANCE;
}

// -- The power box's input ----------------------------------------------------------------

// A 12 V battery: worth a look under 12.0 V, nearly empty under 11.5 V.
export const LOW_VOLTAGE = 12.0;
export const EMPTY_VOLTAGE = 11.5;

export function inputAttention(voltage: number | null | undefined): "problem" | "warning" | null {
  if (voltage === null || voltage === undefined || voltage <= 0) return null;
  if (voltage < EMPTY_VOLTAGE) return "problem";
  return voltage < LOW_VOLTAGE ? "warning" : null;
}

// -- The forecast -------------------------------------------------------------------------

// The hours from the current one until `until` (ms; the end of the dark window).
export function forecastHours(hours: readonly ForecastHour[], now: number, until: number): ForecastHour[] {
  const hour = Math.floor(now / 3600_000) * 3600_000;
  return hours.filter((h) => {
    const t = Date.parse(h.time);
    return t >= hour && t < Math.max(until, hour + 3600_000);
  });
}
