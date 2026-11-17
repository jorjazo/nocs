// How Explore is laid out on this device (ADR 0054): which panes are open, in each
// orientation, whether the overlays show over the image, and the histogram's scale.
// Choices about this screen, kept in the browser like the other per-device ones.

import { isOpen, parseOpen, TOOLS, type HistogramScale, type OpenSections, type Orientation, type Pane } from "./explore";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked (private mode): fall back to defaults
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Not persisted; the choice still applies until the page reloads.
  }
}

const UPRIGHT = "(orientation: portrait)";

class ExploreLayout {
  orientation: Orientation = $state(matchMedia(UPRIGHT).matches ? "portrait" : "landscape");
  overlays: boolean = $state(read("nocs.explore.overlays") !== "off");
  scale: HistogramScale = $state(read("nocs.explore.scale") === "full" ? "full" : "stretch");
  #open: OpenSections = $state(parseOpen(read("nocs.explore.panes")));

  constructor() {
    matchMedia(UPRIGHT).addEventListener("change", (event) => {
      this.orientation = event.matches ? "portrait" : "landscape";
    });
  }

  open(pane: Pane): boolean {
    return isOpen(this.#open, pane, this.orientation);
  }

  setOpen(pane: Pane, open: boolean): void {
    this.#open = { ...this.#open, [`${this.orientation}.${pane}`]: open };
    write("nocs.explore.panes", JSON.stringify(this.#open));
  }

  // Upright there is room for one tool over the image: opening one folds the others.
  toggle(pane: Pane): void {
    const open = !this.open(pane);
    if (open && this.orientation === "portrait" && TOOLS.includes(pane)) {
      for (const other of TOOLS) if (other !== pane && this.open(other)) this.setOpen(other, false);
    }
    this.setOpen(pane, open);
  }

  toggleOverlays(): void {
    this.overlays = !this.overlays;
    write("nocs.explore.overlays", this.overlays ? "on" : "off");
  }

  setScale(scale: HistogramScale): void {
    this.scale = scale;
    write("nocs.explore.scale", scale);
  }
}

export const exploreLayout = new ExploreLayout();
