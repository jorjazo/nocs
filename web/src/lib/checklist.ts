// Tonight's checklist (ADR 0041): which step is next, which others can run and which
// are blocked, from what the server says each step needs (the state's `preparation`).
// A step is next only when it can run; a blocked one says why and where to fix it.

import type { Messages } from "./i18n/en";
import type { Route } from "./router.svelte";
import type { PreparationBlocker, PreparationState, Role } from "./types";

export type StepKey = "connect" | "polar" | "focus" | "frame" | "guide";
export type PreparedStep = Exclude<StepKey, "connect">;
export type StepStatus = "done" | "next" | "ready" | "blocked";
export type BlockerReason = PreparationBlocker["reason"];

// Where a blocker is fixed. None where the app cannot fix it (ASTAP and its star
// databases come with the image, or are installed on a PC), or where the step above
// is the fix (connecting).
export type Fix = "rig" | "addSite" | "chooseSite" | "guiding";

export interface Blocker {
  reason: BlockerReason;
  role: Role | null;
  fix: Fix | null;
}

const SERVER_STEP: Record<PreparedStep, keyof PreparationState> = {
  polar: "polar_align",
  focus: "focus",
  frame: "frame",
  guide: "guide",
};

// Whether the active profile has the devices the step uses.
export function applies(preparation: PreparationState | null | undefined, step: PreparedStep): boolean {
  return preparation?.[SERVER_STEP[step]].applies ?? false;
}

// What stops the step now, the most basic first. `savedSites`: how many sites are
// saved, to send the user to add one or to choose one.
export function blockersOf(
  preparation: PreparationState | null | undefined,
  step: PreparedStep,
  savedSites: number,
): Blocker[] {
  return (preparation?.[SERVER_STEP[step]].blockers ?? []).map((b) => ({
    reason: b.reason,
    role: b.role,
    fix: fixFor(b, savedSites),
  }));
}

export function fixFor(blocker: Pick<PreparationBlocker, "reason" | "role">, savedSites: number): Fix | null {
  switch (blocker.reason) {
    case "not_connected":
      return blocker.role === null ? null : "rig";
    case "no_site":
      return savedSites > 0 ? "chooseSite" : "addSite";
    case "parked":
      return "rig";
    case "no_phd2":
      return "guiding";
    case "no_solver":
    case "no_database":
      return null;
  }
}

export function fixRoute(fix: Fix): Route {
  switch (fix) {
    case "addSite":
      return { screen: "site", id: null };
    case "guiding":
      return { screen: "guiding" };
    case "rig":
    case "chooseSite":
      return { screen: "rig" };
  }
}

// Each step's status in order: the first step that is not done and can run is next;
// a later one that can run is ready, one that cannot is blocked.
export function statuses(steps: readonly { done: boolean; blocked: boolean }[]): StepStatus[] {
  let next = false;
  return steps.map((step) => {
    if (step.done) return "done";
    if (step.blocked) return "blocked";
    if (next) return "ready";
    next = true;
    return "next";
  });
}

// What the user reads for a blocker.
export function blockerText(t: Messages, blocker: Pick<Blocker, "reason" | "role">): string {
  if (blocker.reason === "not_connected" && blocker.role !== null) {
    return t.preparation.notReady(t.roles[blocker.role]);
  }
  return t.preparation.blockers[blocker.reason];
}
