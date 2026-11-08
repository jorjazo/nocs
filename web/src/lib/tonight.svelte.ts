// Tonight's almanac at the box's active site (ADR 0038), shared by Tonight and
// Plan. Asked again when the night or the site changes, and at most every few
// minutes otherwise (the server computes it in ~50 ms; the night does not move).

import { ApiError, getTonight } from "./api";
import type { Almanac, SitesState } from "./types";

const FRESH_MS = 10 * 60 * 1000;
// After a failure (no site yet, nocsd unreachable), ask again no sooner than this:
// callers load from effects, which run again as soon as `loading` changes.
const RETRY_MS = 30 * 1000;

class Tonight {
  almanac: Almanac | null = $state(null);
  // No active site (409), or the request failed.
  missingSite = $state(false);
  error: unknown = $state(null);
  loading = $state(false);
  private fetched = 0;
  private site: string | null = null;

  // `site` is `siteKey`'s: another site, or the same one moved, is another night.
  async load(site: string | null, force = false): Promise<void> {
    const stale = Date.now() - this.fetched > FRESH_MS;
    const over = this.almanac !== null && Date.now() > Date.parse(this.almanac.end);
    if (!force && !stale && !over && site === this.site) return;
    if (this.loading) return;
    this.loading = true;
    this.site = site;
    try {
      this.almanac = await getTonight();
      this.missingSite = false;
      this.error = null;
      this.fetched = Date.now();
    } catch (e) {
      this.fetched = Date.now() - FRESH_MS + RETRY_MS;
      this.almanac = null;
      this.missingSite = e instanceof ApiError && e.status === 409;
      this.error = this.missingSite ? null : e;
    } finally {
      this.loading = false;
    }
  }
}

export const tonight = new Tonight();

// The active site and where it is, to tell when tonight must be asked again.
export function siteKey(sites: SitesState | null | undefined): string | null {
  const id = sites?.active;
  const site = id ? sites.saved[id] : undefined;
  return id && site ? `${id} ${site.latitude} ${site.longitude} ${site.elevation ?? 0}` : null;
}
