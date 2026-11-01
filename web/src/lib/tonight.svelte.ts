// Tonight's almanac at the active profile's site, shared by Tonight and Plan.
// Asked again when the night or the profile changes, and at most every few
// minutes otherwise (the server computes it in ~50 ms; the night does not move).

import { ApiError, getTonight } from "./api";
import type { Almanac } from "./types";

const FRESH_MS = 10 * 60 * 1000;

class Tonight {
  almanac: Almanac | null = $state(null);
  // No site in the active profile (409), or the request failed.
  missingSite = $state(false);
  error: unknown = $state(null);
  loading = $state(false);
  private fetched = 0;
  private profile: string | null = null;

  async load(profile: string | null, force = false): Promise<void> {
    const stale = Date.now() - this.fetched > FRESH_MS;
    const over = this.almanac !== null && Date.now() > Date.parse(this.almanac.end);
    if (!force && !stale && !over && profile === this.profile) return;
    if (this.loading) return;
    this.loading = true;
    this.profile = profile;
    try {
      this.almanac = await getTonight();
      this.missingSite = false;
      this.error = null;
      this.fetched = Date.now();
    } catch (e) {
      this.almanac = null;
      this.missingSite = e instanceof ApiError && e.status === 409;
      this.error = this.missingSite ? null : e;
    } finally {
      this.loading = false;
    }
  }
}

export const tonight = new Tonight();
