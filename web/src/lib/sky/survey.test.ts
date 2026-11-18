import assert from "node:assert/strict";
import { test } from "node:test";
import { en } from "../i18n/en.ts";
import { es } from "../i18n/es.ts";
import { type Tile, tileKey } from "./hips.ts";
import {
  classify,
  DOWN_MS,
  FALLBACK_KEPT_MS,
  fetchSkyView,
  KEPT_TILES,
  type KeyValueStore,
  type Loader,
  MAX_FIELD,
  MAX_PIXELS,
  type Mirror,
  type Probe,
  type Source,
  SourceMemory,
  SurveyTiles,
  serves,
  surveyRequest,
} from "./survey.ts";

function store(initial: Record<string, string> = {}): KeyValueStore & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => data[key] ?? null,
    setItem: (key, value) => void (data[key] = value),
  };
}

type Outcome = "load" | "error" | "timeout";

// A loader whose services answer as told (an outcome, or a promise to settle
// later); records what was asked, by service and URL.
function loader(
  images: Partial<Record<Source, Outcome>>,
  probes: Partial<Record<Source, Probe>> = {},
  online = true,
): Loader<string> & { asked: Source[]; urls: string[]; setOnline(on: boolean): void } {
  const asked: Source[] = [];
  const urls: string[] = [];
  const source = (url: string): Source =>
    url.includes("skyview") ? "skyview" : url.includes("irsa") ? "irsa" : url.includes("esac") ? "esa" : "cds";
  return {
    asked,
    urls,
    setOnline: (on) => void (online = on),
    image: (url, _timeout, signal) => {
      const s = source(url);
      asked.push(s);
      urls.push(url);
      const outcome = images[s] ?? "error";
      if (signal.aborted) return Promise.reject("abort");
      return outcome === "load" ? Promise.resolve(`${url}`) : Promise.reject(outcome);
    },
    probe: (origin) => Promise.resolve(probes[source(origin)] ?? "failed"),
    online: () => online,
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const tile = (ix: number, iy = 0): Tile => ({ order: 7, face: 9, ix, iy });

function tilesWith(images: Partial<Record<Source, Outcome>>, probes: Partial<Record<Source, Probe>> = {}, memory = new SourceMemory(store())) {
  let now = 1_000_000;
  let changes = 0;
  const services = loader(images, probes);
  const tiles = new SurveyTiles(memory, services, () => (changes += 1), () => now);
  return {
    tiles,
    services,
    memory,
    changes: () => changes,
    later: (ms: number) => void (now += ms),
  };
}

test("tiles come from IRSA first, as HiPS paths", async () => {
  const { tiles, services } = tilesWith({ irsa: "load" });
  tiles.want([tile(1), tile(2)]);
  assert.equal(tiles.asking(), "irsa");
  await settle();
  assert.deepEqual(services.asked, ["irsa", "irsa"]);
  assert.ok(services.urls[0]?.startsWith("https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color/Norder7/Dir"));
  assert.ok(tiles.image(tile(1)));
  assert.equal(tiles.asking(), null);
  assert.equal(tiles.last, "irsa");
  // Wanted again: not asked again.
  tiles.want([tile(1), tile(2)]);
  await settle();
  assert.equal(services.asked.length, 2);
});

test("a mirror that fails a tile is skipped, and the next one gives it", async () => {
  const { tiles, services, memory } = tilesWith({ irsa: "timeout", esa: "load" });
  tiles.want([tile(1), tile(2), tile(3)]);
  await settle();
  // Every tile asked of IRSA at once; each goes on to ESA; later ones skip IRSA.
  assert.ok(tiles.image(tile(1)) && tiles.image(tile(3)));
  assert.equal(tiles.last, "esa");
  assert.deepEqual(memory.order(), ["esa", "irsa", "cds"]);
  services.asked.length = 0;
  tiles.want([tile(4)]);
  await settle();
  assert.deepEqual(services.asked, ["esa"]);
});

test("a mirror is asked again once its down time is over", async () => {
  const { tiles, services, later } = tilesWith({ irsa: "error", esa: "error", cds: "error" });
  tiles.want([tile(1)]);
  await settle();
  assert.ok(tiles.allDown());
  services.asked.length = 0;
  tiles.want([tile(2)]);
  await settle();
  assert.deepEqual(services.asked, []);
  later(DOWN_MS + 1);
  assert.ok(!tiles.allDown());
  tiles.want([tile(2)]);
  await settle();
  assert.deepEqual(services.asked, ["irsa", "esa", "cds"]);
});

test("when every mirror is down, each says why, in the order tried", async () => {
  const { tiles } = tilesWith({ irsa: "timeout", esa: "error", cds: "timeout" }, { irsa: "answered", esa: "answered", cds: "timeout" });
  tiles.want([tile(1)]);
  await settle();
  assert.ok(tiles.allDown());
  assert.deepEqual(tiles.misses(), [
    { source: "irsa", miss: "slow" },
    { source: "esa", miss: "error" },
    { source: "cds", miss: "silent" },
  ]);
  // Back online: all of them may be asked again.
  tiles.reset();
  assert.ok(!tiles.allDown());
});

test("tiles no longer wanted are dropped on their way, and an offline device asks nothing", async () => {
  const pending: string[] = [];
  const services: Loader<string> = {
    image: (url, _t, signal) =>
      new Promise((_resolve, reject) => {
        pending.push(url);
        signal.addEventListener("abort", () => reject("abort"));
      }),
    probe: () => Promise.resolve("answered"),
    online: () => true,
  };
  let changes = 0;
  const tiles = new SurveyTiles(new SourceMemory(store()), services, () => (changes += 1));
  tiles.want([tile(1), tile(2)]);
  tiles.want([tile(2)]);
  await settle();
  // tile(1) was aborted: no mirror marked down for it.
  assert.ok(!tiles.allDown());
  assert.equal(tiles.asking(), "irsa");
  assert.equal(pending.length, 2);
  tiles.stop();
  assert.equal(tiles.asking(), null);

  const offline = tilesWith({ irsa: "load" });
  offline.services.setOnline(false);
  offline.tiles.want([tile(1)]);
  assert.deepEqual(offline.services.asked, []);
});

test("only so many tiles are kept, the least recently wanted dropped first", async () => {
  const { tiles } = tilesWith({ irsa: "load" });
  const many = Array.from({ length: KEPT_TILES }, (_, i) => tile(i % 128, Math.floor(i / 128)));
  tiles.want(many);
  await settle();
  // The first wanted again, then one more: the second goes.
  tiles.want([many[0] as Tile]);
  tiles.want([tile(0, 100)]);
  await settle();
  assert.ok(tiles.image(many[0] as Tile));
  assert.equal(tiles.image(many[1] as Tile), undefined);
  assert.ok(tiles.image(tile(0, 100)));
  assert.equal(new Set(many.map(tileKey)).size, KEPT_TILES);
});

test("SkyView gives its image, or why not", async () => {
  const signal = new AbortController().signal;
  const request = { ra: 5.6, dec: -69, fov: 2, width: 800, height: 600 };
  const ok = loader({ skyview: "load" });
  const image = await fetchSkyView(request, ok, signal);
  assert.ok(image && "image" in image && image.image.includes("skyview.gsfc.nasa.gov") && image.image.includes("DSS2+Red"));
  assert.deepEqual(await fetchSkyView(request, loader({ skyview: "timeout" }, { skyview: "answered" }), signal), { miss: "slow" });
  assert.deepEqual(await fetchSkyView(request, loader({ skyview: "error" }, { skyview: "failed" }), signal), {
    miss: "unreachable",
  });
  const controller = new AbortController();
  controller.abort();
  assert.equal(await fetchSkyView(request, loader({ skyview: "timeout" }), controller.signal), null);
});

test("the mirror that worked is asked first next time, across charts and reloads", () => {
  const saved = store();
  const memory = new SourceMemory(saved);
  assert.deepEqual(memory.order(), ["irsa", "esa", "cds"]);
  memory.worked("esa");
  // A new memory reads what the last one saved: a reload, or another chart's.
  assert.deepEqual(new SourceMemory(saved).order(), ["esa", "irsa", "cds"]);
  // A later success of the default moves the preference back.
  memory.worked("irsa");
  assert.deepEqual(new SourceMemory(saved).order(), ["irsa", "esa", "cds"]);
});

test("another mirror is preferred for a night, then IRSA is tried first again", () => {
  let now = 1_000_000;
  const saved = store();
  new SourceMemory(saved, () => now).worked("esa");
  now += FALLBACK_KEPT_MS - 1;
  assert.deepEqual(new SourceMemory(saved, () => now).order(), ["esa", "irsa", "cds"]);
  now += 2;
  assert.deepEqual(new SourceMemory(saved, () => now).order(), ["irsa", "esa", "cds"]);
});

test("a mirror that keeps working still gives way to IRSA the next night", () => {
  let now = 1_000_000;
  const saved = store();
  const memory = new SourceMemory(saved, () => now);
  memory.worked("esa");
  // Every chart of the night got its tiles from ESA, the last one 18 h before the next night.
  now += 2 * 3600 * 1000;
  memory.worked("esa");
  now += 18 * 3600 * 1000;
  assert.deepEqual(new SourceMemory(saved, () => now).order(), ["irsa", "esa", "cds"]);
});

test("while IRSA stays down, ESA is preferred again each night", async () => {
  let now = 1_000_000;
  const saved = store();
  new SourceMemory(saved, () => now).worked("esa");
  // The next night: IRSA first, still not answering, and ESA gives the tile.
  now += 24 * 3600 * 1000;
  const memory = new SourceMemory(saved, () => now);
  const services = loader({ irsa: "timeout", esa: "load" });
  const tiles = new SurveyTiles(memory, services, () => {}, () => now);
  tiles.want([tile(1)]);
  await settle();
  assert.deepEqual(services.asked, ["irsa", "esa"]);
  // The night's next charts, and a reload, ask ESA first.
  now += 3600 * 1000;
  assert.deepEqual(memory.order(), ["esa", "irsa", "cds"]);
  assert.deepEqual(new SourceMemory(saved, () => now).order(), ["esa", "irsa", "cds"]);
});

test("a preference saved with the clock ahead runs out", () => {
  const saved = store();
  new SourceMemory(saved, () => 5e12).worked("esa");
  assert.deepEqual(new SourceMemory(saved, () => 1e12).order(), ["irsa", "esa", "cds"]);
});

test("unreadable or blocked storage falls back to the default order", () => {
  assert.deepEqual(new SourceMemory(store({ "nocs.surveyMirror": "{bad" })).order(), ["irsa", "esa", "cds"]);
  assert.deepEqual(new SourceMemory(store({ "nocs.surveyMirror": '{"source":"x","at":1}' })).order(), ["irsa", "esa", "cds"]);
  const throwing: KeyValueStore = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  const memory = new SourceMemory(throwing);
  memory.worked("esa");
  assert.deepEqual(memory.order(), ["esa", "irsa", "cds"]);
  assert.deepEqual(new SourceMemory(null).order(), ["irsa", "esa", "cds"]);
});

test("a miss is told apart by its probe", () => {
  assert.equal(classify("timeout", "answered"), "slow");
  assert.equal(classify("error", "answered"), "error");
  assert.equal(classify("timeout", "timeout"), "silent");
  assert.equal(classify("error", "timeout"), "silent");
  assert.equal(classify("error", "failed"), "unreachable");
  assert.equal(classify("timeout", "failed"), "unreachable");
});

test("the failure says what failed, in both languages", () => {
  const cds = { service: "CDS", miss: "silent" as const };
  const skyview = { service: "SkyView", miss: "slow" as const };
  assert.equal(en.chart.surveyFailed([cds, skyview]), "No survey image: CDS not answering · SkyView too slow for this view");
  assert.equal(es.chart.surveyFailed([cds, skyview]), "Sin imagen del survey: CDS no responde · SkyView tarda demasiado para esta vista");
  const unreachable = [
    { service: "CDS", miss: "unreachable" as const },
    { service: "SkyView", miss: "unreachable" as const },
  ];
  assert.equal(en.chart.surveyFailed(unreachable), "No survey image: CDS and SkyView cannot be reached. No internet on this device?");
  assert.equal(en.chart.surveyFailed([{ service: "SkyView", miss: "error" }]), "No survey image: SkyView answered with an error");
  assert.equal(
    en.chart.surveyFailed([
      { service: "CDS", miss: "silent" },
      { service: "SkyView", miss: "silent" },
    ]),
    "No survey image: CDS and SkyView are not answering",
  );
  assert.ok(!en.chart.surveyOffline.includes("?"));
});

// A 4:3 view, `degrees` across its width.
function view(degrees: number, width = 800, height = 600) {
  return { center: { ra: 5.6, dec: -69 }, scale: width / (degrees * (Math.PI / 180)), width, height };
}

test("a narrow view is asked for whole, in the screen's pixels", () => {
  const r = surveyRequest(view(2, 400, 300), 2);
  assert.ok(Math.abs(r.fov - 2) < 1e-9);
  assert.deepEqual([r.width, r.height], [MAX_PIXELS, 600]);
  const small = surveyRequest(view(1, 300, 200), 1);
  assert.deepEqual([small.width, small.height], [300, 200]);
});

test("a wide view is asked for only its middle", () => {
  const r = surveyRequest(view(10.4), 1);
  // The longer side is capped, the shape kept.
  assert.ok(Math.abs(r.fov - MAX_FIELD) < 1e-9);
  assert.ok(Math.abs(r.width / r.height - 4 / 3) < 0.01);
  assert.ok(r.width <= MAX_PIXELS);
  // A portrait phone: the cap is on its height.
  const tall = surveyRequest(view(5, 400, 800), 1);
  assert.ok(Math.abs((tall.fov * 800) / 400 - MAX_FIELD) < 1e-9);
  assert.deepEqual([tall.width, tall.height], [200, 400]);
});

test("an image serves views about its own place and size", () => {
  const wanted = surveyRequest(view(2), 1);
  assert.ok(serves({ ...wanted }, wanted, 0));
  assert.ok(serves({ ...wanted, fov: 2.4 }, wanted, 0.4));
  assert.ok(!serves({ ...wanted, fov: 3 }, wanted, 0));
  assert.ok(!serves({ ...wanted }, wanted, 0.6));
  // Zooming out past the cap asks for nothing new.
  assert.ok(serves(surveyRequest(view(8), 1), surveyRequest(view(12), 1), 0));
});

test("zooming in from a wide view asks again for a sharper image", () => {
  // Past the cap every view asks for the same field, with fewer pixels the wider it is.
  const wide = surveyRequest(view(20), 1);
  assert.deepEqual([wide.fov, wide.width], [MAX_FIELD, 200]);
  for (const degrees of [8, 6, 5, 4]) {
    const wanted = surveyRequest(view(degrees), 1);
    assert.ok(!serves(wide, wanted, 0), `${degrees}°`);
  }
  // A little closer is still sharp enough.
  assert.ok(serves(surveyRequest(view(12), 1), surveyRequest(view(10), 1), 0));
});
