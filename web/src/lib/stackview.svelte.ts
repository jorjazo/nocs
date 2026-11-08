// Whether this device shows the latest frame or the live stack (ADR 0040): a
// choice about this screen, kept in the browser like the other per-device ones.

export type StackView = "frame" | "stack";

const KEY = "nocs.stackView";

function read(): StackView {
  try {
    return localStorage.getItem(KEY) === "frame" ? "frame" : "stack";
  } catch {
    return "stack"; // storage blocked (private mode)
  }
}

class StackViewPref {
  view: StackView = $state(read());

  set(view: StackView): void {
    this.view = view;
    try {
      localStorage.setItem(KEY, view);
    } catch {
      // Not persisted; the choice still applies until the page reloads.
    }
  }
}

export const stackView = new StackViewPref();
