// Live stacking (ADR 0039) in the client: the look's presets and what the
// stack's state says, in words. Pure functions, tested with node:test.

import type { CurrentStack, StackLook, StackOutcome } from "./types";

// The look is chosen from a few steps, not sliders: big targets, usable with
// gloves in the dark, and each step visibly different (docs/ux.md).
export const BACKGROUNDS = [0.15, 0.25, 0.32, 0.4] as const;
export const SHADOWS = [-4.5, -2.8, -1.5] as const;
export const SATURATIONS = [0, 1, 1.5, 2.2] as const;

// The server fills every field; the schema marks them optional as requests may omit them.
export type Look = Required<StackLook>;

export const DEFAULT_LOOK: Look = { background: 0.25, shadows: -2.8, saturation: 1, linked: false };

export function complete(look: StackLook): Look {
  return { ...DEFAULT_LOOK, ...look };
}

// The step of a preset list nearest a value (a look set by another client may lie between).
export function nearest<T extends number>(steps: readonly T[], value: number): T {
  let best = steps[0] as T;
  for (const step of steps) {
    if (Math.abs(step - value) < Math.abs(best - value)) best = step;
  }
  return best;
}

export type Calibrated = "darksFlats" | "darks" | "flats" | "cosmetic" | "none";

// What the stack's frames are calibrated with, as one word for its chip.
export function calibrated(stack: CurrentStack): Calibrated {
  const { dark, flat, cosmetic } = stack.calibration;
  if (dark && flat) return "darksFlats";
  if (dark) return "darks";
  if (flat) return "flats";
  return cosmetic ? "cosmetic" : "none";
}

// What the calibration is made of, as parts of one line ("20 darks · 15 flats").
export type Part =
  | { kind: "darks" | "bias" | "flats"; count: number }
  | { kind: "noFlats" | "flatsUnused" | "noDarks" };

export function parts(stack: CurrentStack): Part[] {
  const c = stack.calibration;
  const found: Part[] = [];
  if (c.dark_kind === "dark") found.push({ kind: "darks", count: c.dark_frames });
  else if (c.dark_kind === "bias") found.push({ kind: "bias", count: c.dark_frames });
  else found.push({ kind: "noDarks" });
  if (c.flat_frames > 0) found.push({ kind: "flats", count: c.flat_frames });
  else found.push({ kind: c.flats_unused ? "flatsUnused" : "noFlats" });
  return found;
}

export type Outcome =
  | { kind: "accepted"; shift: number; rotation: number }
  | { kind: "left"; cause: StackOutcome["cause"]; reason: string };

// The latest frame: how far it moved onto the stack, or why it was left out.
export function outcome(last: StackOutcome): Outcome {
  if (!last.accepted) return { kind: "left", cause: last.cause, reason: last.reason ?? "" };
  const [x = 0, y = 0] = last.shift ?? [];
  return { kind: "accepted", shift: Math.hypot(x, y), rotation: last.rotation ?? 0 };
}

// Turns of a meridian flip read as ±180°: show how far from the reference
// orientation it is, folded to -180..180.
export function folded(degrees: number): number {
  return ((((degrees + 180) % 360) + 360) % 360) - 180;
}
