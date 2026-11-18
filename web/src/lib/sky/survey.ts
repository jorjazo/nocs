// The framing chart's survey image: DSS2 in colour, drawn from the HiPS tiles the
// browser fetches from one of the survey's mirrors (IRSA, ESA, CDS), or a DSS2
// red image from NASA SkyView when no mirror answers. The browser fetches them
// itself, so this is per device; nothing here touches nocsd.

import { type Tile, tileKey, tilePath } from "./hips.ts";
import type { View } from "./projection.ts";

// The mirrors of CDS's DSS2 colour HiPS (the same tiles, byte for byte), in the
// order tried by default; all allow CORS.
export type Mirror = "irsa" | "esa" | "cds";
export type Source = Mirror | "skyview";
const DEFAULT: Mirror = "irsa";
export const MIRRORS: readonly Mirror[] = [DEFAULT, "esa", "cds"];
export const HIPS: Record<Mirror, string> = {
  irsa: "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color",
  esa: "https://skies.esac.esa.int/DSSColor",
  cds: "https://alasky.cds.unistra.fr/DSS/DSSColor",
};
// The survey's deepest order: ~1″ per pixel.
export const DEEPEST = 9;

export const ORIGIN: Record<Source, string> = {
  irsa: "https://irsa.ipac.caltech.edu",
  esa: "https://skies.esac.esa.int",
  cds: "https://alasky.cds.unistra.fr",
  skyview: "https://skyview.gsfc.nasa.gov",
};

// A tile takes a second or two when the mirror is up. SkyView makes its image
// from the DSS plates, slower the wider the field (measured in ADR 0020).
export const TILE_TIMEOUT = 10_000;
export const SKYVIEW_TIMEOUT = 30_000;
// A mirror that failed a tile is not asked again for this long.
export const DOWN_MS = 5 * 60_000;
// Tiles kept in memory: a few views' worth (a view needs 4–40).
export const KEPT_TILES = 160;

// Asked after a miss, to tell a service that answers from one that does not.
export const PROBE_TIMEOUT = 5_000;

// Why a service gave no image:
// - unreachable: a probe of its host fails at once (no internet, DNS, refused);
// - silent: a probe gets no answer in time either;
// - slow: no image in time, but the service answers a probe;
// - error: it answered the image with an error (an HTTP error, or not an image).
// An <img> says neither the HTTP status nor why it failed, and SkyView allows no
// CORS, so the probe is a no-cors fetch: it resolves on any answer and rejects
// when nothing reached the host.
export type Miss = "unreachable" | "silent" | "slow" | "error";
export type Probe = "answered" | "failed" | "timeout";

// What the image request ended in, and what the probe after it got.
export function classify(outcome: "error" | "timeout", probe: Probe): Miss {
  if (probe === "answered") return outcome === "timeout" ? "slow" : "error";
  return probe === "timeout" ? "silent" : "unreachable";
}

// -- Which mirror first -----------------------------------------------------------

const KEY = "nocs.surveyMirror";
// A preference for another mirror lasts this long from its first success: the
// next night tries the default first again.
export const FALLBACK_KEPT_MS = 20 * 3600 * 1000;

export type KeyValueStore = { getItem(key: string): string | null; setItem(key: string, value: string): void };

function defaultStore(): KeyValueStore | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null; // storage blocked (private mode)
  }
}

// The mirror that worked last in this browser, tried first next time, across
// charts and reloads. A later success of another one moves it.
export class SourceMemory {
  #store: KeyValueStore | null;
  #now: () => number;
  #last: { source: Mirror; at: number } | null = null;

  constructor(store: KeyValueStore | null = defaultStore(), now: () => number = Date.now) {
    this.#store = store;
    this.#now = now;
    try {
      const saved: unknown = JSON.parse(store?.getItem(KEY) ?? "null");
      if (isSaved(saved)) this.#last = saved;
    } catch {
      // Unreadable: start from the default order.
    }
  }

  // The mirrors in the order to try them.
  order(): Mirror[] {
    const first = this.#preferred() ?? DEFAULT;
    return [first, ...MIRRORS.filter((mirror) => mirror !== first)];
  }

  // The time is that of the first success in a row, so a preference for another
  // mirror runs out the next day even when it kept working all night; a success
  // after it ran out (the default still failing) starts a new one.
  worked(source: Mirror): void {
    if (this.#preferred() === source) return;
    this.#last = { source, at: this.#now() };
    try {
      this.#store?.setItem(KEY, JSON.stringify(this.#last));
    } catch {
      // Not persisted; this page still remembers it.
    }
  }

  // The remembered mirror, while its preference holds.
  #preferred(): Mirror | null {
    const last = this.#last;
    if (!last) return null;
    // A time ahead of the clock (the device's clock was wrong) has run out too.
    const age = this.#now() - last.at;
    return last.source === DEFAULT || (age >= 0 && age < FALLBACK_KEPT_MS) ? last.source : null;
  }
}

function isSaved(value: unknown): value is { source: Mirror; at: number } {
  if (typeof value !== "object" || value === null) return false;
  const { source, at } = value as { source?: unknown; at?: unknown };
  return MIRRORS.some((m) => m === source) && typeof at === "number";
}

// -- The browser's side ------------------------------------------------------------

export type Missed = { source: Source; miss: Miss };

// Apart so the order and the wording can be tested without a browser.
export type Loader<I> = {
  // Rejects with "error" or "timeout" (or "abort" when the signal aborts).
  image(url: string, timeout: number, signal: AbortSignal): Promise<I>;
  probe(origin: string, signal: AbortSignal): Promise<Probe>;
  online(): boolean;
};

// -- Tiles ----------------------------------------------------------------------

// The tiles of the views asked for, from the first mirror that answers. A mirror
// that fails a tile is skipped for DOWN_MS, its tiles asked of the next one;
// when every mirror is down the chart falls back to SkyView. `changed` is called
// whenever a tile arrives or a mirror goes down or is told apart by its probe.
export class SurveyTiles<I> {
  #memory: SourceMemory;
  #loader: Loader<I>;
  #changed: () => void;
  #now: () => number;
  // Loaded tiles by key, least recently wanted first.
  #images = new Map<string, I>();
  #pending = new Map<string, AbortController>();
  #down = new Map<Mirror, { until: number; miss: Miss | null }>();
  #stopped = new AbortController();
  // The mirror the last tile came from, for the credit.
  last: Mirror | null = null;

  constructor(memory: SourceMemory, loader: Loader<I>, changed: () => void, now: () => number = Date.now) {
    this.#memory = memory;
    this.#loader = loader;
    this.#changed = changed;
    this.#now = now;
  }

  image(tile: Tile): I | undefined {
    return this.#images.get(tileKey(tile));
  }

  // The mirrors to ask now, in order.
  mirrors(): Mirror[] {
    const now = this.#now();
    return this.#memory.order().filter((m) => (this.#down.get(m)?.until ?? 0) <= now);
  }

  allDown(): boolean {
    return this.mirrors().length === 0;
  }

  // The mirror being asked for tiles, while any is on its way.
  asking(): Mirror | null {
    return this.#pending.size ? (this.mirrors()[0] ?? null) : null;
  }

  // Why each mirror is down, in the order they are tried; null while a probe
  // has not answered yet.
  misses(): Missed[] | null {
    const misses: Missed[] = [];
    for (const source of this.#memory.order()) {
      const miss = this.#down.get(source)?.miss;
      if (!miss) return null;
      misses.push({ source, miss });
    }
    return misses;
  }

  // The tiles a view needs: asked for when missing, and those on their way for
  // an earlier view and no longer needed are dropped.
  want(tiles: Tile[]): void {
    const keys = new Set(tiles.map(tileKey));
    for (const [key, controller] of this.#pending) {
      if (keys.has(key)) continue;
      controller.abort();
      this.#pending.delete(key);
    }
    if (!this.#loader.online()) return;
    for (const tile of tiles) {
      const key = tileKey(tile);
      const image = this.#images.get(key);
      if (image !== undefined) {
        // Wanted again: the last to be dropped.
        this.#images.delete(key);
        this.#images.set(key, image);
      } else if (!this.#pending.has(key) && !this.allDown()) {
        void this.#load(tile, key);
      }
    }
  }

  // Back online: every mirror may be asked again.
  reset(): void {
    this.#down.clear();
  }

  stop(): void {
    this.#stopped.abort();
    for (const controller of this.#pending.values()) controller.abort();
    this.#pending.clear();
  }

  async #load(tile: Tile, key: string): Promise<void> {
    const controller = new AbortController();
    this.#pending.set(key, controller);
    for (;;) {
      const mirror = this.mirrors()[0];
      if (!mirror) break;
      try {
        const image = await this.#loader.image(`${HIPS[mirror]}/${tilePath(tile)}`, TILE_TIMEOUT, controller.signal);
        if (controller.signal.aborted) return;
        this.#pending.delete(key);
        this.#images.set(key, image);
        while (this.#images.size > KEPT_TILES) {
          const oldest = this.#images.keys().next().value;
          if (oldest === undefined) break;
          this.#images.delete(oldest);
        }
        this.#down.delete(mirror);
        this.#memory.worked(mirror);
        this.last = mirror;
        this.#changed();
        return;
      } catch (outcome) {
        if (controller.signal.aborted) return;
        this.#fail(mirror, outcome === "timeout" ? "timeout" : "error");
      }
    }
    if (this.#pending.get(key) === controller) this.#pending.delete(key);
    this.#changed();
  }

  #fail(mirror: Mirror, outcome: "error" | "timeout"): void {
    const now = this.#now();
    if ((this.#down.get(mirror)?.until ?? 0) > now) return; // another tile told already
    const entry: { until: number; miss: Miss | null } = { until: now + DOWN_MS, miss: null };
    this.#down.set(mirror, entry);
    this.#changed();
    void this.#loader.probe(ORIGIN[mirror], this.#stopped.signal).then((probe) => {
      entry.miss = classify(outcome, probe);
      this.#changed();
    });
  }
}

// -- SkyView, when no mirror answers ---------------------------------------------

// SkyView's time grows with the field's area, hardly with its pixels (ADR 0020):
// a view wider than this gets an image of its middle, where the frame is.
export const MAX_FIELD = 5;
// The longer side's pixels; a phone's, capped (the services are free, be kind).
export const MAX_PIXELS = 800;

export type SurveyRequest = {
  ra: number;
  dec: number;
  // Degrees across the image's width, and its pixels.
  fov: number;
  width: number;
  height: number;
};

export function surveyRequest(v: View, pixelRatio: number): SurveyRequest {
  const rad = Math.PI / 180;
  const long = Math.max(v.width, v.height);
  const longDegrees = long / v.scale / rad;
  // The part of the view asked for, in screen pixels: all of it, or its middle.
  const shrink = Math.min(1, MAX_FIELD / longDegrees);
  const w = v.width * shrink;
  const h = v.height * shrink;
  const pixels = Math.min(MAX_PIXELS, Math.round(long * shrink * Math.min(2, pixelRatio || 1)));
  return {
    ra: v.center.ra,
    dec: v.center.dec,
    fov: w / v.scale / rad,
    width: Math.max(1, Math.round((pixels * w) / (long * shrink))),
    height: Math.max(1, Math.round((pixels * h) / (long * shrink))),
  };
}

// An image (shown or on its way) still serves a request: about the same place and
// size, and sharp enough. Past MAX_FIELD every view asks for the same field, with
// the pixels it covers on screen: zooming in from a wide view needs more of them.
export function serves(
  image: { fov: number; width: number },
  wanted: SurveyRequest,
  separation: number,
): boolean {
  const sharp = image.width / image.fov >= 0.7 * (wanted.width / wanted.fov);
  return separation < wanted.fov * 0.25 && Math.abs(image.fov / wanted.fov - 1) < 0.3 && sharp;
}

export function skyViewUrl(r: SurveyRequest): string {
  const params = new URLSearchParams({
    Survey: "DSS2 Red",
    Position: `${(r.ra * 15).toFixed(5)},${r.dec.toFixed(5)}`,
    Size: `${r.fov.toFixed(4)},${((r.fov * r.height) / r.width).toFixed(4)}`,
    Pixels: `${r.width},${r.height}`,
    Projection: "Tan",
    Coordinates: "J2000",
    Return: "JPEG",
  });
  return `${ORIGIN.skyview}/current/cgi/runquery.pl?${params}`;
}

// SkyView's image, or why there is none; null when aborted.
export async function fetchSkyView<I>(
  request: SurveyRequest,
  loader: Loader<I>,
  signal: AbortSignal,
): Promise<{ image: I } | { miss: Miss } | null> {
  try {
    const image = await loader.image(skyViewUrl(request), SKYVIEW_TIMEOUT, signal);
    return signal.aborted ? null : { image };
  } catch (outcome) {
    if (signal.aborted) return null;
    const probe = await loader.probe(ORIGIN.skyview, signal);
    if (signal.aborted) return null;
    return { miss: classify(outcome === "timeout" ? "timeout" : "error", probe) };
  }
}

function onAbort(signal: AbortSignal, run: () => void): () => void {
  signal.addEventListener("abort", run);
  return () => signal.removeEventListener("abort", run);
}

export const browserLoader: Loader<HTMLImageElement> = {
  image(url, timeout, signal) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      // The mirrors allow CORS; asking with it keeps the chart's canvas clean.
      if (!url.startsWith(ORIGIN.skyview)) image.crossOrigin = "anonymous";
      const done = (result: "load" | "error" | "timeout" | "abort"): void => {
        clearTimeout(timer);
        stop();
        image.onload = image.onerror = null;
        if (result === "load") return resolve(image);
        image.src = ""; // stop the download
        reject(result);
      };
      const timer = setTimeout(() => done("timeout"), timeout);
      const stop = onAbort(signal, () => done("abort"));
      image.onload = () => done("load");
      image.onerror = () => done("error");
      image.src = url;
    });
  },
  async probe(origin, signal) {
    const controller = new AbortController();
    let late = false;
    const timer = setTimeout(() => {
      late = true;
      controller.abort();
    }, PROBE_TIMEOUT);
    const stop = onAbort(signal, () => controller.abort());
    try {
      // Opaque, but it resolves only when the host answered something.
      await fetch(`${origin}/favicon.ico`, { mode: "no-cors", cache: "no-store", signal: controller.signal });
      return "answered";
    } catch {
      return late ? "timeout" : "failed";
    } finally {
      clearTimeout(timer);
      stop();
    }
  },
  online: () => navigator.onLine,
};

// The services' names as the chart says them.
export const SERVICE: Record<Source, string> = { irsa: "IRSA", esa: "ESA", cds: "CDS", skyview: "SkyView" };

// One per page, shared by every chart.
export const surveyMemory = new SourceMemory();
