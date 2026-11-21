// The plan in the client (docs/ux.md, "Plan"): its targets in priority, each with
// lines of lights, and what can be worked out without the page.

import { DEFAULT_COUNT, DEFAULT_EXPOSURE, FRAME_OVERHEAD, type CameraSettings } from "./sequence.ts";
import type { NightPlan, PlanLine, PlanTarget } from "./types.ts";

export { isPlanRun, PLAN_ID } from "./sequence.ts";

// Ids of targets and lines are the client's: lower-case letters and digits.
export function newId(taken: Iterable<string>, random: () => number = Math.random): string {
  const used = new Set(taken);
  for (;;) {
    const id = Math.floor(random() * 36 ** 8)
      .toString(36)
      .padStart(8, "0");
    if (!used.has(id)) return id;
  }
}

// Every id the plan uses, targets and lines.
export function planIds(plan: NightPlan): string[] {
  return (plan.targets ?? []).flatMap((t) => [t.id, ...(t.lines ?? []).map((l) => l.id)]);
}

// A new line after the last: the next filter of the wheel no line uses, or none
// without a wheel; the last line's exposure, count and settings, else the camera's.
export function newLine(
  lines: PlanLine[],
  filters: string[],
  id: string,
  camera: CameraSettings = { gain: null, offset: null },
): PlanLine {
  const last = lines.at(-1);
  const used = new Set(lines.map((l) => l.filter));
  const filter = filters.length ? (filters.find((name) => name && !used.has(name)) ?? filters[0] ?? null) : null;
  return {
    id,
    filter,
    exposure: last?.exposure ?? DEFAULT_EXPOSURE,
    count: last?.count ?? DEFAULT_COUNT,
    gain: last ? (last.gain ?? null) : camera.gain,
    offset: last ? (last.offset ?? null) : camera.offset,
    done: 0,
  };
}

export function lineLeft(line: PlanLine): number {
  return Math.max(0, line.count - (line.done ?? 0));
}

export function targetLeft(target: PlanTarget): number {
  return (target.lines ?? []).reduce((sum, line) => sum + lineLeft(line), 0);
}

export function targetCount(target: PlanTarget): number {
  return (target.lines ?? []).reduce((sum, line) => sum + line.count, 0);
}

export function targetDone(target: PlanTarget): number {
  return (target.lines ?? []).reduce((sum, line) => sum + Math.min(line.count, line.done ?? 0), 0);
}

// Seconds the frames a target still needs take (with `overhead` seconds each).
export function targetSeconds(target: PlanTarget, overhead = FRAME_OVERHEAD): number {
  return (target.lines ?? []).reduce((sum, line) => sum + lineLeft(line) * (line.exposure + overhead), 0);
}

// Seconds of exposure a target has, over every night.
export function targetIntegration(target: PlanTarget): number {
  return (target.lines ?? []).reduce((sum, line) => sum + Math.min(line.count, line.done ?? 0) * line.exposure, 0);
}

// The list with the item at `index` moved `by` places (up: -1), as a new list.
export function moved<T>(list: readonly T[], index: number, by: number): T[] {
  const to = index + by;
  if (index < 0 || index >= list.length || to < 0 || to >= list.length) return [...list];
  const copy = [...list];
  const [item] = copy.splice(index, 1);
  copy.splice(to, 0, item as T);
  return copy;
}

// What the plan is without what the server counts: two of these that differ are
// changes to save.
export function planShape(plan: NightPlan): string {
  return JSON.stringify({
    ...plan,
    targets: (plan.targets ?? []).map((t) => ({ ...t, lines: (t.lines ?? []).map(({ done: _, ...line }) => line) })),
  });
}

// Copy the frames the server counted into `draft`'s lines, by id, in place.
export function copyDone(draft: NightPlan, live: NightPlan): void {
  const done = new Map((live.targets ?? []).flatMap((t) => (t.lines ?? []).map((l) => [l.id, l.done ?? 0] as const)));
  for (const target of draft.targets ?? []) {
    for (const line of target.lines ?? []) {
      const counted = done.get(line.id);
      if (counted !== undefined && counted !== line.done) line.done = counted;
    }
  }
}

// The frames a line has of its count, from the server (by id): a draft's may lag.
export function lineDone(live: NightPlan | null | undefined, id: string): number {
  for (const target of live?.targets ?? []) {
    for (const line of target.lines ?? []) {
      if (line.id === id) return line.done ?? 0;
    }
  }
  return 0;
}

// Coordinates as typed: decimal ("5.588", "-5.39"), or sexagesimal with spaces,
// colons or units ("05 35 17", "5h35m17s", "-05:23:28", "-5°23′28″"). Right
// ascension in hours, declination in degrees; null when it is not one, or out of range.
function sexagesimal(text: string): number | null {
  const trimmed = text.trim().replace(/,/g, ".");
  if (!trimmed) return null;
  const negative = trimmed.startsWith("-") || trimmed.startsWith("−");
  const parts = trimmed
    .replace(/^[-+−]/, "")
    .split(/[\s:hHmMsSdD°'′"″]+/)
    .filter(Boolean);
  if (!parts.length || parts.length > 3 || parts.some((part) => !/^\d+(\.\d+)?$/.test(part))) return null;
  const [whole = 0, minutes = 0, seconds = 0] = parts.map(Number);
  if (parts.length > 1 && (minutes >= 60 || seconds >= 60)) return null;
  const value = whole + minutes / 60 + seconds / 3600;
  return negative ? -value : value;
}

export function parseRa(text: string): number | null {
  const hours = sexagesimal(text);
  return hours === null || hours < 0 || hours >= 24 ? null : hours;
}

export function parseDec(text: string): number | null {
  const degrees = sexagesimal(text);
  return degrees === null || degrees < -90 || degrees > 90 ? null : degrees;
}
