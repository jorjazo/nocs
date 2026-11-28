import assert from "node:assert/strict";
import { test } from "node:test";
import { cameraLinkCauses, newCameraFaults, usbPowerText } from "./camerafault.ts";
import { en } from "./i18n/en.ts";
import type { JobInfo } from "./types.ts";

function job(state: JobInfo["state"], fault: JobInfo["fault"] = null): JobInfo {
  return {
    kind: "expose",
    resources: ["main_camera"],
    state,
    progress: null,
    message: null,
    error: state === "failed" ? "ZWO CCD ASI432MM exposure failed" : null,
    fault,
    result: {},
    started: "2026-11-28T14:39:40.000Z",
    finished: null,
  };
}

test("the popup shows jobs it saw fail for the camera's link", () => {
  const before = { a: job("running"), b: job("running"), c: job("failed", "camera_link") };
  const after = { a: job("failed", "camera_link"), b: job("failed"), c: job("failed", "camera_link") };
  assert.deepEqual(newCameraFaults(before, after), ["a"]);
  // Failures already over when the page loads are old news.
  assert.deepEqual(newCameraFaults(null, { a: job("failed", "camera_link") }), []);
});

test("the USB notice names the cameras the Pi powers", () => {
  const text = usbPowerText({ limit: 600, supply: 3000, draw: 500, cameras: ["ASI432MM"] }, en, "en");
  assert.ok(/limits its USB ports to 600 mA in all \(its supply offered 3 A\), and ASI432MM takes/.test(text));
});

test("without a camera, the USB notice says what the Pi powers asks for", () => {
  const text = usbPowerText({ limit: 600, supply: null, draw: 1250, cameras: [] }, en, "en");
  assert.ok(!/supply offered/.test(text));
  assert.ok(/asks for 1,250 mA/.test(text));
});

test("the Pi's limited ports come first among the causes", () => {
  const power = { limit: 600, supply: 3000, draw: 500, cameras: ["ASI432MM"] };
  assert.ok(/600 mA/.test(cameraLinkCauses(power, en, "en")[0] ?? ""));
  assert.equal(cameraLinkCauses(null, en, "en").length, 3);
});
