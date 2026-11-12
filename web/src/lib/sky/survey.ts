// The framing chart's survey image (ADR 0020): which service to ask, how much
// to ask for, and how to say why there is none. The browser fetches it itself,
// so this is per device; nothing here touches nocsd.

import type { View } from "./projection.ts";

export type Source = "cds" | "skyview";
// CDS first by default: its image is in colour.
const DEFAULT: Source = "cds";
export const SOURCES: readonly Source[] = [DEFAULT, "skyview"];

// CDS answers in a second or two when it is up; SkyView makes the image from the
// DSS plates, slower the wider the field (measured in ADR 0020).
export const TIMEOUT: Record<Source, number> = { cds: 12_000, skyview: 30_000 };

// Asked after a miss, to tell a service that answers from one that does not.
export const PROBE_TIMEOUT = 5_000;
export const ORIGIN: Record<Source, string> = {
  cds: "https://alasky.cds.unistra.fr",
  skyview: "https://skyview.gsfc.nasa.gov",
};

// Why a service gave no image:
// - unreachable: a probe of its host fails at once (no internet, DNS, refused);
// - silent: a probe gets no answer in time either;
// - slow: no image in time, but the service answers a probe;
// - error: it answered the image with an error (an HTTP error, or not an image).
// An <img> says neither the HTTP status nor why it failed, and the services do
// not all allow CORS (SkyView does not), so the probe is a no-cors fetch: it
// resolves on any answer and rejects when nothing reached the host.
export type Miss = "unreachable" | "silent" | "slow" | "error";
export type Probe = "answered" | "failed" | "timeout";

// What the image request ended in, and what the probe after it got.
export function classify(outcome: "error" | "timeout", probe: Probe): Miss {
  if (probe === "answered") return outcome === "timeout" ? "slow" : "error";
  return probe === "timeout" ? "silent" : "unreachable";
}

// -- Which service first ----------------------------------------------------------

const KEY = "nocs.surveySource";
// A preference for the fallback lasts this long from its first success: the next
// night tries CDS (colour) first again.
export const FALLBACK_KEPT_MS = 20 * 3600 * 1000;

export type KeyValueStore = { getItem(key: string): string | null; setItem(key: string, value: string): void };

function defaultStore(): KeyValueStore | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null; // storage blocked (private mode)
  }
}

// The service that worked last in this browser, tried first next time, across
// charts and reloads. A later success of the other one moves it.
export class SourceMemory {
  #store: KeyValueStore | null;
  #now: () => number;
  #last: { source: Source; at: number } | null = null;

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

  // The services in the order to try them.
  order(): Source[] {
    const first = this.#preferred() ?? DEFAULT;
    return [first, ...SOURCES.filter((source) => source !== first)];
  }

  // The time is that of the first success in a row, so a preference for the
  // fallback runs out the next day even when it kept working all night; a
  // success after it ran out (CDS still failing) starts a new one.
  worked(source: Source): void {
    if (this.#preferred() === source) return;
    this.#last = { source, at: this.#now() };
    try {
      this.#store?.setItem(KEY, JSON.stringify(this.#last));
    } catch {
      // Not persisted; this page still remembers it.
    }
  }

  // The remembered service, while its preference holds.
  #preferred(): Source | null {
    const last = this.#last;
    if (!last) return null;
    // A time ahead of the clock (the device's clock was wrong) has run out too.
    const age = this.#now() - last.at;
    return last.source === DEFAULT || (age >= 0 && age < FALLBACK_KEPT_MS) ? last.source : null;
  }
}

function isSaved(value: unknown): value is { source: Source; at: number } {
  if (typeof value !== "object" || value === null) return false;
  const { source, at } = value as { source?: unknown; at?: unknown };
  return SOURCES.some((s) => s === source) && typeof at === "number";
}

// -- How much to ask for ----------------------------------------------------------

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

export function surveyUrl(source: Source, r: SurveyRequest): string {
  const ra = (r.ra * 15).toFixed(5);
  const dec = r.dec.toFixed(5);
  if (source === "cds") {
    const params = new URLSearchParams({
      hips: "CDS/P/DSS2/color",
      width: String(r.width),
      height: String(r.height),
      fov: r.fov.toFixed(4),
      projection: "TAN",
      coordsys: "icrs",
      ra,
      dec,
      format: "jpg",
    });
    return `${ORIGIN.cds}/hips-image-services/hips2fits?${params}`;
  }
  const params = new URLSearchParams({
    Survey: "DSS2 Red",
    Position: `${ra},${dec}`,
    Size: `${r.fov.toFixed(4)},${((r.fov * r.height) / r.width).toFixed(4)}`,
    Pixels: `${r.width},${r.height}`,
    Projection: "Tan",
    Coordinates: "J2000",
    Return: "JPEG",
  });
  return `${ORIGIN.skyview}/current/cgi/runquery.pl?${params}`;
}

// -- Fetching ---------------------------------------------------------------------

export type Missed = { source: Source; miss: Miss };
export type SurveyResult<I> = { image: I; source: Source } | { offline: boolean; misses: Missed[] };

// The browser's side, apart so the order and the wording can be tested without one.
export type Loader<I> = {
  // Rejects with "error" or "timeout".
  image(url: string, timeout: number, signal: AbortSignal): Promise<I>;
  probe(origin: string, signal: AbortSignal): Promise<Probe>;
  online(): boolean;
};

// Tries the services in the remembered order; null when aborted. A miss's probe
// runs while the next service is asked, so it costs time only when all fail.
export async function fetchSurvey<I>(
  request: SurveyRequest,
  memory: SourceMemory,
  loader: Loader<I>,
  signal: AbortSignal,
  asking: (source: Source) => void = () => {},
): Promise<SurveyResult<I> | null> {
  if (!loader.online()) return { offline: true, misses: [] };
  const probes: Promise<Missed>[] = [];
  for (const source of memory.order()) {
    if (signal.aborted) return null;
    asking(source);
    try {
      const image = await loader.image(surveyUrl(source, request), TIMEOUT[source], signal);
      if (signal.aborted) return null;
      memory.worked(source);
      return { image, source };
    } catch (outcome) {
      if (signal.aborted) return null;
      const kind = outcome === "timeout" ? "timeout" : "error";
      probes.push(loader.probe(ORIGIN[source], signal).then((probe) => ({ source, miss: classify(kind, probe) })));
    }
  }
  const misses = await Promise.all(probes);
  if (signal.aborted) return null;
  // Offline by now, or every host failed at once: most likely no internet here.
  return { offline: !loader.online(), misses };
}

function onAbort(signal: AbortSignal, run: () => void): () => void {
  signal.addEventListener("abort", run);
  return () => signal.removeEventListener("abort", run);
}

export const browserLoader: Loader<HTMLImageElement> = {
  image(url, timeout, signal) {
    return new Promise((resolve, reject) => {
      const image = new Image();
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
export const SERVICE: Record<Source, string> = { cds: "CDS", skyview: "SkyView" };

// One per page, shared by every chart.
export const surveyMemory = new SourceMemory();
