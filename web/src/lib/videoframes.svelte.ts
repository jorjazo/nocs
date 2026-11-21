// The Video view's previews: fetched one after another while the stream runs, each
// as soon as the server has a newer one, so a slow phone simply gets fewer. They
// become object URLs for the viewer; the one before is released once replaced.

import { nextVideoFrame } from "./api";

const RETRY_MS = 1000;

export class VideoFrames {
  url: string | null = $state(null);
  #controller: AbortController | null = null;
  #seq = 0;

  // Fetch while `on`; stopping keeps the last image on screen.
  run(on: boolean): void {
    if (on && !this.#controller) {
      const controller = new AbortController();
      this.#controller = controller;
      void this.#loop(controller.signal);
    } else if (!on && this.#controller) {
      this.#controller.abort();
      this.#controller = null;
    }
  }

  // The server's latest frame number, from the state: below the one held here, the
  // server started counting again (it restarted) and waiting for a newer one would
  // last until it caught up.
  resync(seq: number | null): void {
    if (seq !== null && seq < this.#seq) this.#seq = 0;
  }

  close(): void {
    this.run(false);
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
  }

  async #loop(signal: AbortSignal): Promise<void> {
    while (!signal.aborted) {
      try {
        const next = await nextVideoFrame(this.#seq, signal);
        if (!next || signal.aborted) continue;
        // A restarted server counts from zero again.
        this.#seq = next.seq;
        const previous = this.url;
        this.url = URL.createObjectURL(next.image);
        // The viewer draws the new image once loaded: free the old one after that.
        if (previous) setTimeout(() => URL.revokeObjectURL(previous), 2000);
      } catch {
        this.#seq = 0;
        await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
      }
    }
  }
}
