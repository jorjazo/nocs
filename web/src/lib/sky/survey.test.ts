import assert from "node:assert/strict";
import { test } from "node:test";
import { en } from "../i18n/en.ts";
import { es } from "../i18n/es.ts";
import {
  classify,
  FALLBACK_KEPT_MS,
  fetchSurvey,
  type KeyValueStore,
  type Loader,
  MAX_FIELD,
  MAX_PIXELS,
  type Probe,
  type Source,
  SourceMemory,
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

// A loader whose services answer as told; records what was asked.
function loader(
  images: Partial<Record<Source, "load" | "error" | "timeout">>,
  probes: Partial<Record<Source, Probe>> = {},
  online = true,
): Loader<string> & { asked: string[] } {
  const asked: string[] = [];
  const source = (url: string): Source => (url.includes("skyview") ? "skyview" : "cds");
  return {
    asked,
    image: (url) => {
      const s = source(url);
      asked.push(s);
      const outcome = images[s] ?? "error";
      return outcome === "load" ? Promise.resolve(`image from ${s}`) : Promise.reject(outcome);
    },
    probe: (origin) => Promise.resolve(probes[source(origin)] ?? "failed"),
    online: () => online,
  };
}

const signal = new AbortController().signal;
const request = { ra: 5.6, dec: -69, fov: 2, width: 800, height: 600 };

test("CDS is asked first, SkyView when it gives nothing", async () => {
  const memory = new SourceMemory(store());
  assert.deepEqual(memory.order(), ["cds", "skyview"]);
  const services = loader({ cds: "timeout", skyview: "load" });
  const result = await fetchSurvey(request, memory, services, signal);
  assert.deepEqual(result, { image: "image from skyview", source: "skyview" });
  assert.deepEqual(services.asked, ["cds", "skyview"]);
});

test("the service that worked is asked first next time, across charts and reloads", async () => {
  const saved = store();
  await fetchSurvey(request, new SourceMemory(saved), loader({ cds: "timeout", skyview: "load" }), signal);
  // A new memory reads what the last one saved: a reload, or another chart's.
  const services = loader({ skyview: "load" });
  await fetchSurvey(request, new SourceMemory(saved), services, signal);
  assert.deepEqual(services.asked, ["skyview"]);
});

test("a later success of the other service moves the preference back", async () => {
  const saved = store();
  const memory = new SourceMemory(saved);
  memory.worked("skyview");
  const back = loader({ skyview: "timeout", cds: "load" });
  assert.deepEqual((await fetchSurvey(request, memory, back, signal)) ?? {}, { image: "image from cds", source: "cds" });
  assert.deepEqual(back.asked, ["skyview", "cds"]);
  assert.deepEqual(new SourceMemory(saved).order(), ["cds", "skyview"]);
});

test("the fallback is preferred for a night, then CDS is tried first again", () => {
  let now = 1_000_000;
  const saved = store();
  new SourceMemory(saved, () => now).worked("skyview");
  now += FALLBACK_KEPT_MS - 1;
  assert.deepEqual(new SourceMemory(saved, () => now).order(), ["skyview", "cds"]);
  now += 2;
  assert.deepEqual(new SourceMemory(saved, () => now).order(), ["cds", "skyview"]);
});

test("unreadable or blocked storage falls back to the default order", () => {
  assert.deepEqual(new SourceMemory(store({ "nocs.surveySource": "{bad" })).order(), ["cds", "skyview"]);
  assert.deepEqual(new SourceMemory(store({ "nocs.surveySource": '{"source":"x","at":1}' })).order(), ["cds", "skyview"]);
  const throwing: KeyValueStore = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  const memory = new SourceMemory(throwing);
  memory.worked("skyview");
  assert.deepEqual(memory.order(), ["skyview", "cds"]);
  assert.deepEqual(new SourceMemory(null).order(), ["cds", "skyview"]);
});

test("a miss is told apart by its probe", () => {
  assert.equal(classify("timeout", "answered"), "slow");
  assert.equal(classify("error", "answered"), "error");
  assert.equal(classify("timeout", "timeout"), "silent");
  assert.equal(classify("error", "timeout"), "silent");
  assert.equal(classify("error", "failed"), "unreachable");
  assert.equal(classify("timeout", "failed"), "unreachable");
});

test("every miss is reported, in the order asked", async () => {
  const memory = new SourceMemory(store());
  const result = await fetchSurvey(
    request,
    memory,
    loader({ cds: "timeout", skyview: "timeout" }, { cds: "timeout", skyview: "answered" }),
    signal,
  );
  assert.deepEqual(result, {
    offline: false,
    misses: [
      { source: "cds", miss: "silent" },
      { source: "skyview", miss: "slow" },
    ],
  });
  // Nothing worked: nothing remembered.
  assert.deepEqual(memory.order(), ["cds", "skyview"]);
});

test("an offline device asks nobody", async () => {
  const services = loader({ cds: "load" }, {}, false);
  assert.deepEqual(await fetchSurvey(request, new SourceMemory(store()), services, signal), { offline: true, misses: [] });
  assert.deepEqual(services.asked, []);
});

test("an aborted request ends in nothing", async () => {
  const controller = new AbortController();
  const services = loader({ cds: "timeout", skyview: "load" });
  const asking: Source[] = [];
  const pending = fetchSurvey(request, new SourceMemory(store()), services, controller.signal, (s) => {
    asking.push(s);
    controller.abort();
  });
  assert.equal(await pending, null);
  assert.deepEqual(asking, ["cds"]);
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
