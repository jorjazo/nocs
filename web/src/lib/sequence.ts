// Sequences in the client: groups of frames of what the camera has framed, and how a
// run stands. What can be worked out without the page.

import type { Group, SequencePlan, SequenceRun, Template } from "./types";

export const DEFAULT_EXPOSURE = 120;
export const DEFAULT_COUNT = 20;
// Seconds a flat whose exposure is found, and a bias, are reckoned at (as the server).
export const FLAT_SECONDS = 2;
export const BIAS_SECONDS = 0.001;
export const FRAME_OVERHEAD = 3;

export type FrameKind = NonNullable<Group["frame_type"]>;
export type FrameClass = "light" | "dark" | "flat";

// What the rig must be ready for: open, covered (darks and bias), a panel.
export function frameClass(kind: FrameKind): FrameClass {
  return kind === "bias" ? "dark" : kind;
}

// Sequence ids are file names: lower case letters, digits and dashes.
export function sequenceId(name: string): string {
  const slug = name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/, "");
  return slug || "sequence";
}

// An id for a new sequence named `name` that none of `taken` has.
export function freeId(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const base = sequenceId(name);
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) {
    const id = `${base.slice(0, 60)}-${n}`;
    if (!used.has(id)) return id;
  }
}

// The camera's gain and offset as a new group takes them: written into the group, so
// that a later change in Explore does not change the sequence's frames.
export type CameraSettings = { gain: number | null; offset: number | null };

export function newTemplate(
  name: string,
  filter: string | null,
  guide: boolean,
  solver = false,
  camera: CameraSettings = { gain: null, offset: null },
): Template {
  return {
    name,
    groups: [{ frame_type: "light", filter, exposure: DEFAULT_EXPOSURE, count: DEFAULT_COUNT, gain: camera.gain, offset: camera.offset }],
    start_at_dusk: true,
    darkness: "astronomical",
    until_dawn: true,
    min_altitude: 30,
    cooling: "off",
    temperature: null,
    cooling_ramp: null,
    focus: { at_start: true, filter_change: false, temperature_change: 1, hfr_increase: null, minutes: null },
    guide,
    dither_every: guide ? 3 : null,
    dither_pixels: 5,
    center: solver,
    recenter_every: solver ? 10 : null,
    recenter_drift: 2,
    flip: true,
    flip_after: 5,
    end: { park: true, warm: true, outputs: [] },
    recovery: {},
  };
}

// A new group after the last one: the next light filter no group uses, or another of
// the last group's kind.
export function newGroup(groups: Group[], filters: string[], camera: CameraSettings = { gain: null, offset: null }): Group {
  const last = groups.at(-1);
  const kind = last?.frame_type ?? "light";
  if (kind === "light") {
    return {
      frame_type: "light",
      filter: filters.length ? nextFilter(groups, filters) : null,
      exposure: last?.exposure ?? DEFAULT_EXPOSURE,
      count: last?.count ?? DEFAULT_COUNT,
      gain: last ? (last.gain ?? null) : camera.gain,
      offset: last ? (last.offset ?? null) : camera.offset,
      binning: last?.binning ?? null,
      temperature: last?.temperature ?? null,
    };
  }
  return { ...last, frame_type: kind, count: last?.count ?? DEFAULT_COUNT };
}

// The next filter for a new light group: the first of the wheel's that none uses yet.
export function nextFilter(groups: Group[], names: string[]): string | null {
  const used = new Set(groups.filter((g) => (g.frame_type ?? "light") === "light").map((g) => g.filter));
  return names.find((name) => name && !used.has(name)) ?? names[0] ?? null;
}

// Seconds one frame of a group is reckoned at.
export function groupExposure(group: Group): number {
  if (group.exposure != null) return group.exposure;
  return group.frame_type === "flat" ? FLAT_SECONDS : BIAS_SECONDS;
}

export function groupSeconds(group: Group): number {
  return group.count * (groupExposure(group) + FRAME_OVERHEAD);
}

// Fit a group to its kind as the server does: darks and bias take no filter, bias the
// camera's shortest exposure, lights and darks an exposure.
export function fitGroup(group: Group): Group {
  const kind = group.frame_type ?? "light";
  const fitted: Group = { ...group, frame_type: kind };
  if (kind === "dark" || kind === "bias") fitted.filter = null;
  if (kind === "bias") fitted.exposure = null;
  if ((kind === "light" || kind === "dark") && fitted.exposure == null) fitted.exposure = DEFAULT_EXPOSURE;
  return fitted;
}

// Whether the kinds of frames change between groups: the run asks the user then.
export function prompts(groups: Group[]): FrameClass[] {
  const asked: FrameClass[] = [];
  let previous: FrameClass = "light";
  for (const group of groups) {
    const kind = frameClass(group.frame_type ?? "light");
    if (kind !== previous) asked.push(kind);
    previous = kind;
  }
  return asked;
}

// A run that still holds the rig, or waits on the user (anything but finished).
export function isActive(run: SequenceRun | null | undefined): run is SequenceRun {
  return !!run && run.state !== "finished";
}

export type RowProgress = {
  frameType: SequencePlan["frame_type"];
  filter: string | null;
  exposure: number | null;
  count: number;
  done: number;
  path: string;
};

// How far a run is: its frames done and in all, the time its frames still take
// (with `overhead` seconds each), and its groups in the order of the tree.
export function runProgress(
  run: SequenceRun,
  overhead = FRAME_OVERHEAD,
): { done: number; total: number; left: number; rows: RowProgress[] } {
  const rows = Object.entries(run.plans).flatMap(([path, plan]) =>
    plan.rows.map((row) => ({ frameType: plan.frame_type, filter: row.filter, exposure: row.exposure, count: row.count, done: row.done, path })),
  );
  let done = 0;
  let total = 0;
  let left = 0;
  for (const row of rows) {
    done += Math.min(row.done, row.count);
    total += row.count;
    const seconds = row.exposure ?? (row.frameType === "flat" ? FLAT_SECONDS : BIAS_SECONDS);
    left += Math.max(0, row.count - row.done) * (seconds + overhead);
  }
  return { done, total, left, rows };
}

// The plan the run is in (its path is where the run stands, or above it).
export function currentPlan(run: SequenceRun): string | null {
  const current = run.current;
  if (!current) return null;
  return Object.keys(run.plans).find((path) => current === path || path.startsWith(`${current}.`) || current.startsWith(`${path}.`)) ?? null;
}

// The row a frame in progress belongs to: the current plan's first unfinished row,
// since a sequence's groups are taken in their order, each to its end (a plan in
// batches, only ever built by hand, is shown as if it were too).
export function currentRow(run: SequenceRun): RowProgress | null {
  const path = run.current && run.plans[run.current] ? run.current : null;
  if (!path) return null;
  const plan = run.plans[path];
  const row = plan?.rows.find((r) => r.done < r.count);
  return plan && row ? { frameType: plan.frame_type, filter: row.filter, exposure: row.exposure, count: row.count, done: row.done, path } : null;
}

// Which of a run's rows (runProgress) is being taken in the plan at `plan`: its first
// unfinished one; -1 when none.
export function currentIndex(rows: RowProgress[], plan: string | null): number {
  return plan ? rows.findIndex((r) => r.path === plan && r.done < r.count) : -1;
}

// What a trigger event says (the server's words, "<trigger>: <reason>"): which
// trigger fired, and the frames since its last run for a dither or a recentre.
export type TriggerDue =
  | { kind: "autofocus"; reason: string }
  | { kind: "dither" | "recenter"; frames: number }
  | { kind: "flip"; waiting: number | null }
  | { kind: "other"; message: string };

export function triggerDue(message: string): TriggerDue {
  const at = message.indexOf(": ");
  const kind = at < 0 ? message : message.slice(0, at);
  const reason = at < 0 ? "" : message.slice(at + 2);
  if (kind === "autofocus") return { kind, reason };
  if (kind === "flip") {
    const waiting = /^waiting ([\d.]+) min/.exec(reason);
    return { kind, waiting: waiting ? Number(waiting[1]) : null };
  }
  const frames = /^(\d+) frames?$/.exec(reason);
  if ((kind === "dither" || kind === "recenter") && frames) return { kind, frames: Number(frames[1]) };
  return { kind: "other", message };
}

// Why the runner says an autofocus is due (its words after "autofocus: "): the
// filter it changes to, the focuser's temperature change in °C, the minutes or
// frames since the last run, or how much the stars grew (percent).
export type FocusReason =
  | { why: "filter"; filter: string }
  | { why: "temperature"; change: number }
  | { why: "minutes"; minutes: number }
  | { why: "frames"; frames: number }
  | { why: "hfr"; percent: number }
  | { why: "other"; text: string };

export function focusReason(reason: string): FocusReason {
  let m = /^filter (.+)$/.exec(reason);
  if (m?.[1]) return { why: "filter", filter: m[1] };
  m = /^temperature ([+-]?[\d.]+) °C$/.exec(reason);
  if (m) return { why: "temperature", change: Number(m[1]) };
  m = /^(\d+) min$/.exec(reason);
  if (m) return { why: "minutes", minutes: Number(m[1]) };
  m = /^(\d+) frames?$/.exec(reason);
  if (m) return { why: "frames", frames: Number(m[1]) };
  m = /^HFR ([+-]?\d+)%$/.exec(reason);
  if (m) return { why: "hfr", percent: Number(m[1]) };
  return { why: "other", text: reason };
}

// A frame event's short label for the strip of recent frames: its filter and its
// number in the row ("R 11"), or the number alone ("#11") when the row has no filter.
export function frameLabel(data: Record<string, unknown>): string {
  const filter = typeof data.filter === "string" && data.filter ? data.filter : null;
  const done = typeof data.done === "number" ? data.done : null;
  if (done === null) return filter ?? "";
  return filter ? `${filter} ${done}` : `#${done}`;
}

// Explore and Sequences exclude each other: the one that is working, if either.
// Explore works while it loops or takes frames; Sequences while a run is active.
export type WorkingView = "explore" | "sequence";

export function workingView(
  run: SequenceRun | null | undefined,
  jobs: Record<string, { kind: string; state: string }> | null | undefined,
): WorkingView | null {
  if (isActive(run)) return "sequence";
  for (const job of Object.values(jobs ?? {})) {
    if ((job.kind === "loop" || job.kind === "expose") && job.state === "running") return "explore";
  }
  return null;
}
