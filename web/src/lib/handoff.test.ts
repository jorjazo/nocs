import assert from "node:assert/strict";
import { test } from "node:test";
import { handoffUrl, originFor, reachedByName, takeHandoff, waitUntilAnswers } from "./handoff.ts";

test("only a page reached by the box's old .local name hands over", () => {
  assert.equal(reachedByName("nocs.local", "nocs"), true);
  assert.equal(reachedByName("NOCS.local.", "nocs"), true);
  assert.equal(reachedByName("nocs-lab.local", "nocs"), false);
  assert.equal(reachedByName("10.42.0.1", "nocs"), false);
  assert.equal(reachedByName("localhost", "nocs"), false);
  assert.equal(reachedByName("nocs.fritz.box", "nocs"), false);
  assert.equal(reachedByName(".local", ""), false);
});

test("the new origin keeps the page's scheme and port", () => {
  assert.equal(originFor("nocs-lab", { protocol: "http:", port: "" }), "http://nocs-lab.local");
  assert.equal(originFor("Nocs-Lab", { protocol: "http:", port: "8000" }), "http://nocs-lab.local:8000");
  assert.equal(originFor("rig", { protocol: "https:", port: "8443" }), "https://rig.local:8443");
});

test("the token goes in the fragment, after the route", () => {
  const origin = "http://nocs-lab.local";
  assert.equal(handoffUrl(origin, "#/rig", "a-b_c"), "http://nocs-lab.local/#/rig?handoff=a-b_c");
  assert.equal(handoffUrl(origin, "", "t"), "http://nocs-lab.local/#/?handoff=t");
  assert.equal(handoffUrl(origin, "#/rig?handoff=old", "new"), "http://nocs-lab.local/#/rig?handoff=new");
  assert.equal(handoffUrl(origin, "#/plan/NGC%20224", "x/y+z"), "http://nocs-lab.local/#/plan/NGC%20224?handoff=x%2Fy%2Bz");
  const url = new URL(handoffUrl(origin, "#/rig", "secret"));
  assert.equal(url.search, "");
  assert.ok(!url.pathname.includes("secret"));
});

test("the new page takes the token out of the fragment", () => {
  assert.deepEqual(takeHandoff("#/rig?handoff=a-b_c"), { token: "a-b_c", hash: "#/rig" });
  assert.deepEqual(takeHandoff("#/plan/NGC%20224?handoff=x%2Fy%2Bz"), { token: "x/y+z", hash: "#/plan/NGC%20224" });
  assert.deepEqual(takeHandoff("#/rig?handoff=t&other=1"), { token: "t", hash: "#/rig?other=1" });
  assert.deepEqual(takeHandoff("#/rig"), { token: null, hash: "#/rig" });
  assert.deepEqual(takeHandoff(""), { token: null, hash: "" });
  assert.deepEqual(takeHandoff("#/rig?other=1"), { token: null, hash: "#/rig?other=1" });
  assert.deepEqual(takeHandoff("#/rig?handoff="), { token: null, hash: "#/rig" });
});

function fakeTime() {
  const clock = { now: 0 };
  return {
    clock,
    now: () => clock.now,
    sleep: async (ms: number) => {
      clock.now += ms;
    },
  };
}

test("waiting tries the new name's health until it answers", async () => {
  const time = fakeTime();
  const urls: string[] = [];
  const modes: (RequestMode | undefined)[] = [];
  const answers = await waitUntilAnswers("http://nocs-lab.local", {
    ...time,
    timeoutMs: 60_000,
    intervalMs: 2_000,
    fetch: async (url, init) => {
      urls.push(url);
      modes.push(init.mode);
      if (urls.length < 3) throw new TypeError("Failed to fetch");
      return {};
    },
  });
  assert.equal(answers, true);
  assert.equal(urls.length, 3);
  assert.equal(urls[0], "http://nocs-lab.local/api/health");
  assert.deepEqual(modes, ["no-cors", "no-cors", "no-cors"]);
  assert.equal(time.clock.now, 4_000);
});

test("waiting gives up after the time allowed, or when aborted", async () => {
  const time = fakeTime();
  let tries = 0;
  const fail = async () => {
    tries++;
    throw new TypeError("Failed to fetch");
  };
  assert.equal(await waitUntilAnswers("http://x.local", { ...time, timeoutMs: 10_000, intervalMs: 2_000, fetch: fail }), false);
  assert.equal(tries, 5);
  assert.ok(time.clock.now < 10_000);

  const aborted = new AbortController();
  aborted.abort();
  tries = 0;
  assert.equal(await waitUntilAnswers("http://x.local", { ...time, signal: aborted.signal, fetch: fail }), false);
  assert.equal(tries, 0);
});
