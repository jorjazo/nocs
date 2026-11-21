// The plan the Plan view edits: a draft of the server's, saved a moment after each
// change. The frames each line has are the server's: they come into the draft in
// place (sheets keep editing the same objects), and a save never sends them back.

import { ApiError, savePlan } from "./api";
import { errorText } from "./errors";
import { i18n } from "./i18n";
import { copyDone, planShape } from "./plan";
import type { NightPlan } from "./types";

const SAVE_AFTER = 600;
// A save that failed (no link, say) is tried again this long after.
const RETRY_AFTER = 5000;

class PlanDraft {
  draft: NightPlan | null = $state(null);
  error = $state("");
  saving = $state(false);
  // The last shape saved or loaded, to tell unsaved changes.
  private saved = "";
  private timer: ReturnType<typeof setTimeout> | null = null;

  get dirty(): boolean {
    return this.draft !== null && planShape($state.snapshot(this.draft)) !== this.saved;
  }

  // The server's plan as it arrives: taken as it is unless this draft has changes of
  // its own (then only its counts are taken).
  sync(live: NightPlan | null | undefined): void {
    if (!live) return;
    const shape = planShape(live);
    if (this.draft && (this.dirty || shape === this.saved)) {
      copyDone(this.draft, live);
      return;
    }
    this.draft = $state.snapshot(live);
    this.saved = shape;
  }

  // Called after every change of the draft: saved a moment later.
  changed(): void {
    if (!this.dirty) return;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.save(), SAVE_AFTER);
  }

  // Save now what is waiting.
  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
      void this.save();
    }
  }

  // Save what changed; whether the server has the draft as it is now.
  async save(): Promise<boolean> {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    const draft = this.draft;
    if (!draft || !this.dirty) return true;
    const body = $state.snapshot(draft);
    const shape = planShape(body);
    this.saving = true;
    try {
      await savePlan(body);
      this.saved = shape;
      this.error = "";
      return !this.dirty;
    } catch (e) {
      this.error = errorText(e, i18n.t);
      // No link, or the box busy: tried again by itself, the changes stay in this draft
      // meanwhile. A plan the server refuses stays as it is until it is changed.
      if (!(e instanceof ApiError) || e.status >= 500) this.timer = setTimeout(() => void this.save(), RETRY_AFTER);
      return false;
    } finally {
      this.saving = false;
    }
  }
}

export const plan = new PlanDraft();

// A target from coordinates (typed, or a saved frame's) waiting on its page
// (#/plan/new) to be added: kept for the tab, so a reload does not lose it.
export type NewPoint = { name: string; ra: number; dec: number; rotation: number | null };
const PENDING = "nocs.plan.new";

export function setPending(point: NewPoint): void {
  try {
    sessionStorage.setItem(PENDING, JSON.stringify(point));
  } catch {
    pendingPoint = point; // storage blocked: kept until the page reloads
  }
  pendingPoint = point;
}

let pendingPoint: NewPoint | null = null;

export function clearPending(): void {
  pendingPoint = null;
  try {
    sessionStorage.removeItem(PENDING);
  } catch {
    // Blocked: nothing was kept there.
  }
}

export function getPending(): NewPoint | null {
  try {
    const text = sessionStorage.getItem(PENDING);
    if (text) return JSON.parse(text) as NewPoint;
  } catch {
    // Blocked, or not JSON: what this page kept, if anything.
  }
  return pendingPoint;
}
