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

export function newTemplate(target: PlannedTarget, filter: string | null, guide: boolean): Template {
  return {
    name: target.name,
    target: { name: target.name, ra: target.ra, dec: target.dec },
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
