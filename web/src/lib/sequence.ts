// Sequence templates in the client (phase 5.13). A target has one sequence,
// saved under an id made from its name.

import type { PlannedTarget, PlanRow, SequenceRun, Template } from "./types";

export const DEFAULT_EXPOSURE = 120;
export const DEFAULT_COUNT = 20;

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

// What frames are named after (folder, OBJECT): a catalog target's label ("M 42"),
// not its display name, which is in the language of whoever chose it (Plan names
// it "M 42 · Gran Nebulosa de Orión"); typed coordinates keep their name.
export function frameName(target: PlannedTarget): string {
  return target.id ? (target.name.split(" · ")[0] ?? target.name) : target.name;
}

export function newTemplate(
  target: PlannedTarget,
  filter: string | null,
  guide: boolean,
  solver = false,
): Template {
  return {
    name: target.name,
    target: { name: frameName(target), ra: target.ra, dec: target.dec },
    rows: [{ filter, exposure: DEFAULT_EXPOSURE, count: DEFAULT_COUNT }],
    order: "batches",
    batch: 5,
    start_at_dusk: true,
    darkness: "astronomical",
    until_dawn: true,
    min_altitude: 30,
    cooling: null,
    cooling_ramp: null,
    focus: { at_start: true, filter_change: false, temperature_change: 1, hfr_increase: null, minutes: null },
    guide,
    dither_every: guide ? 3 : null,
    dither_pixels: 5,
    center: solver,
    recenter_every: solver ? 10 : null,
    recenter_drift: 2,
    end: { park: true, warm: true, outputs: [] },
    recovery: {},
  };
}

// The next filter for a new row: the first of the wheel's that no row uses yet.
export function nextFilter(rows: PlanRow[], names: string[]): string | null {
  const used = new Set(rows.map((row) => row.filter));
  return names.find((name) => name && !used.has(name)) ?? names[0] ?? null;
}

export function rowSeconds(row: PlanRow): number {
  return row.exposure * row.count;
}

// A run that still holds the rig (anything but finished).
export function isActive(run: SequenceRun | null | undefined): run is SequenceRun {
  return !!run && run.state !== "finished";
}

export type RowProgress = { filter: string | null; exposure: number; count: number; done: number };

// How far a run is: its frames done and in all, the time its frames still take
// (with `overhead` seconds each), and its rows, by filter in the order of the plans.
export function runProgress(
  run: SequenceRun,
  overhead = 3,
): { done: number; total: number; left: number; rows: RowProgress[] } {
  const rows = Object.values(run.plans).flatMap((plan) => plan.rows);
  let done = 0;
  let total = 0;
  let left = 0;
  for (const row of rows) {
    done += Math.min(row.done, row.count);
    total += row.count;
    left += Math.max(0, row.count - row.done) * (row.exposure + overhead);
  }
  return { done, total, left, rows };
}

// The row a frame in progress belongs to: the plan's row with the wheel's filter
// that still has frames left, else its first unfinished one.
export function currentRow(run: SequenceRun, filter: string | null): RowProgress | null {
  const plan = run.current ? run.plans[run.current] : undefined;
  if (!plan) return null;
  const open = plan.rows.filter((row) => row.done < row.count);
  return open.find((row) => row.filter === filter) ?? open[0] ?? null;
}
