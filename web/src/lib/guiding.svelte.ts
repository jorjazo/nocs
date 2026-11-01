// Guiding as the screens read it: whether PHD2 moves the mount, and the graph's
// entries. The server keeps the guiding run's steps (ADR 0024 stage 4.4); this
// cache fetches them once, then appends each new one as the state announces it
// (`guiding.stats.last`), and asks for what it missed after a gap.

import { guideSteps } from "./api";
import type { GuideEntry, GuidingState, GuidingStats } from "./types";

// PHD2 states in which it moves the mount: NOCS holds the mount meanwhile.
export const GUIDING_STATES: ReadonlySet<string> = new Set(["Calibrating", "Guiding", "LostLock"]);
// States in which PHD2 exposes without guiding ("Selected": looping, a star picked).
export const LOOPING_STATES: ReadonlySet<string> = new Set(["Looping", "Selected"]);

export function guidingActive(guiding: GuidingState | null | undefined): boolean {
  return !!guiding?.app_state && GUIDING_STATES.has(guiding.app_state);
}

// Entries kept here; the graph shows the most recent ones.
const KEEP = 400;

class GuideGraph {
  entries: GuideEntry[] = $state([]);
  private seq = 0;
  private fetching = false;
  private started = false;

  // Fetch the run's entries when a screen first shows the graph.
  start(): void {
    if (this.started) return;
    this.started = true;
    void this.fetch(0, true);
  }

  // Follow the state: called whenever `guiding.stats` changes.
  follow(stats: GuidingStats | null | undefined): void {
    if (!this.started) return;
    if (!stats) return;
    if (stats.steps === 0 && stats.last === null) {
      // A new guiding run: its graph starts empty.
      this.entries = [];
      this.seq = stats.seq;
      return;
    }
    const last = stats.last;
    if (!last || last.seq <= this.seq) return;
    if (last.seq === this.seq + 1) {
      this.entries = [...this.entries.slice(-(KEEP - 1)), last];
      this.seq = last.seq;
    } else {
      void this.fetch(this.seq, false);
    }
  }

  private async fetch(after: number, replace: boolean): Promise<void> {
    if (this.fetching) return;
    this.fetching = true;
    try {
      const { steps } = await guideSteps(after);
      const merged = replace ? steps : [...this.entries, ...steps.filter((e) => e.seq > this.seq)];
      this.entries = merged.slice(-KEEP);
      this.seq = this.entries.at(-1)?.seq ?? this.seq;
    } catch {
      // Offline or not allowed: the next state change tries again.
      if (replace) this.started = false;
    } finally {
      this.fetching = false;
    }
  }
}

export const guideGraph = new GuideGraph();
