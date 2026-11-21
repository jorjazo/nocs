// What lies around where the mount points, asked of the server as the mount moves
// (Tonight's Pointing card, the Visitors view): the Sun or the Moon, catalog objects.

import { getSkyPointing } from "./api";
import { movedFrom, type Sky } from "./tonightcards";
import type { SkyPointing } from "./types";

// The Sun and the Moon move: what is around the mount is asked again now and then.
const REASK = 5 * 60_000;

export class AroundMount {
  around: SkyPointing | null = $state(null);
  private asked: Sky | null = null;
  private askedAt = 0;

  // Ask again when the mount moved a quarter of the frame, or after a while; not while
  // it slews.
  look(at: Sky | null, radius: number, now: number, slewing: boolean): void {
    if (!at || slewing) return;
    const moved = movedFrom(this.asked, at, radius);
    if (!moved && now - this.askedAt < REASK) return;
    const here = at;
    // What was around the last field is not around this one.
    if (moved) this.around = null;
    this.asked = here;
    this.askedAt = now;
    getSkyPointing(here.ra, here.dec, radius)
      .then((found) => {
        if (this.asked === here) this.around = found;
      })
      .catch(() => {
        // Asked again in a minute; what is shown stays while the mount stays.
        if (this.asked === here) this.askedAt = Date.now() - REASK + 60_000;
      });
  }
}
