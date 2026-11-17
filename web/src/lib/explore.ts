// Explore (ADR 0054) in the client, what can be worked out without the page: which
// of its panes start open, where the mount stands against the meridian, and whether
// the latest plate solution is of the frame on screen.

import { hourAngle } from "./polar.ts";
import { parseOpen, type OpenSections } from "./rigsections.ts";

// Panes that open and close: the histogram over the status bar, the guiding and
// focus widgets on the image, the go to panel at its side, and the panel of actions,
// which is a sheet over the image when the screen stands upright.
export const PANES = ["histogram", "guiding", "focus", "goto", "panel"] as const;
export type Pane = (typeof PANES)[number];
export type Orientation = "portrait" | "landscape";

// The tools over the image.
export const TOOLS: readonly Pane[] = ["guiding", "focus", "goto"];

// Lying down there is room for everything; upright the image comes first, and the
// panes start folded into their icons.
export function isOpen(open: OpenSections, pane: Pane, orientation: Orientation): boolean {
  return open[`${orientation}.${pane}`] ?? orientation === "landscape";
}

export { parseOpen, type OpenSections };

// How the histogram spans its values: the camera's whole scale, or the stretch's.
export type HistogramScale = "full" | "stretch";

// A sidereal hour is this many hours of the clock.
const SIDEREAL = 0.99726957;

// Hours of the clock until a JNow right ascension crosses the meridian at
// `longitude`; negative once it has (a pointing west of it).
export function untilMeridian(ra: number, longitude: number, when: Date): number {
  return -hourAngle(ra, when, longitude) * SIDEREAL;
}

// A plate solution says when its frame was taken (mid-exposure); a preview, when its
// frame arrived. The solution is of the frame on screen when the two agree.
export function solvedShown(
  preview: { time: string; exposure: number } | null,
  solution: { taken?: string | null } | null,
): boolean {
  if (!preview || !solution?.taken) return false;
  const middle = Date.parse(preview.time) - (preview.exposure * 1000) / 2;
  return Math.abs(middle - Date.parse(solution.taken)) < 1500;
}

// The automatic stretch of a channel (ADR 0054): what part of the 16-bit scale (0..1)
// ends up how bright (0..1). Black at `shadows` and below, mid grey at `midtones`.
export function stretched(value: number, stretch: { shadows: number; midtones: number }): number {
  const { shadows, midtones } = stretch;
  const scale = Math.max(1 - shadows, 1e-6);
  const x = Math.min(1, Math.max(0, (value - shadows) / scale));
  const m = Math.min(1 - 1e-6, Math.max(1e-6, (midtones - shadows) / scale));
  const y = ((m - 1) * x) / ((2 * m - 1) * x - m);
  return Math.min(1, Math.max(0, y));
}
