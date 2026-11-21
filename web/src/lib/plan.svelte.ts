// The plan the Plan view edits: a draft of the server's, saved a moment after each
// change. The frames each line has are the server's: they come into the draft in
// place (sheets keep editing the same objects), and a save never sends them back.

import { savePlan } from "./api";
import { copyDone, planShape } from "./plan";
import type { NightPlan } from "./types";

const SAVE_AFTER = 600;

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

  async save(): Promise<void> {
    this.timer = null;
    const draft = this.draft;
    if (!draft || !this.dirty) return;
    const body = $state.snapshot(draft);
    const shape = planShape(body);
    this.saving = true;
    try {
      await savePlan(body);
      this.saved = shape;
      this.error = "";
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
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

export function getPending(): NewPoint | null {
  try {
    const text = sessionStorage.getItem(PENDING);
    if (text) return JSON.parse(text) as NewPoint;
  } catch {
    // Blocked, or not JSON: what this page kept, if anything.
  }
  return pendingPoint;
}
