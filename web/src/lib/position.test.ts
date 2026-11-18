import assert from "node:assert/strict";
import { test } from "node:test";
import { parseAngle, readPasted, shortLink } from "./position.ts";

function near(actual: number | null, expected: number): void {
  assert.ok(actual !== null && Math.abs(actual - expected) < 1e-6, `${actual} is not ${expected}`);
}

function position(text: string): { latitude: number; longitude: number } {
  const pasted = readPasted(text);
  assert.ok("position" in pasted, `${text}: ${JSON.stringify(pasted)}`);
  return pasted.position;
}

function at(text: string, latitude: number, longitude: number): void {
  const found = position(text);
  near(found.latitude, latitude);
  near(found.longitude, longitude);
}

test("an angle in decimal degrees, or degrees, minutes and seconds", () => {
  near(parseAngle("-33.4372", "latitude"), -33.4372);
  near(parseAngle("-33,4372", "latitude"), -33.4372);
  near(parseAngle("−70.65", "longitude"), -70.65);
  near(parseAngle("33°26'14\"S", "latitude"), -(33 + 26 / 60 + 14 / 3600));
  near(parseAngle("33° 26′ 14.5″ S", "latitude"), -(33 + 26 / 60 + 14.5 / 3600));
  near(parseAngle("S 33 26 14", "latitude"), -(33 + 26 / 60 + 14 / 3600));
  near(parseAngle("33 26.23 s", "latitude"), -(33 + 26.23 / 60));
  near(parseAngle("70°39'02''W", "longitude"), -(70 + 39 / 60 + 2 / 3600));
  near(parseAngle("70 39 2 O", "longitude"), -(70 + 39 / 60 + 2 / 3600));
  near(parseAngle("-70 39 2", "longitude"), -(70 + 39 / 60 + 2 / 3600));
  near(parseAngle("12°E", "longitude"), 12);
});

test("an angle that is not one, names the other axis, or is out of range", () => {
  for (const [text, axis] of [
    ["", "latitude"],
    ["abc", "latitude"],
    ["91", "latitude"],
    ["181", "longitude"],
    ["70°W", "latitude"],
    ["33°S", "longitude"],
    ["-33 S", "latitude"],
    ["33 60 0", "latitude"],
    ["33 26 60", "latitude"],
    ["33.5 26", "latitude"],
    ["N 33 S", "latitude"],
  ] as const) {
    assert.equal(parseAngle(text, axis), null, text);
  }
});

test("pasted coordinates, as Maps copies them or typed with hemispheres", () => {
  at("-33.437272, -70.650579", -33.437272, -70.650579);
  at("-33.437272 -70.650579", -33.437272, -70.650579);
  at("-33,437272; -70,650579", -33.437272, -70.650579);
  at("-33,437272 -70,650579", -33.437272, -70.650579);
  at(`33°26'14.2"S 70°39'02.1"W`, -(33 + 26 / 60 + 14.2 / 3600), -(70 + 39 / 60 + 2.1 / 3600));
  at(`33°26'14.2"S, 70°39'02.1"W`, -(33 + 26 / 60 + 14.2 / 3600), -(70 + 39 / 60 + 2.1 / 3600));
  at("S 33 26 14 O 70 39 2", -(33 + 26 / 60 + 14 / 3600), -(70 + 39 / 60 + 2 / 3600));
  // Longitude first is fine when the hemispheres say so, or when only that order fits.
  at("70°39'W 33°26'S", -(33 + 26 / 60), -(70 + 39 / 60));
  at("-122.0632, 37.0004", 37.0004, -122.0632);
  // Both orders fit: latitude first.
  at("-33.4372, -70.6506", -33.4372, -70.6506);
  at("10, 20", 10, 20);
});

test("pasted text that is not a position, or reads two ways", () => {
  for (const text of ["", "Santiago", "-33.43", "33°S 20°N", "100, 100", "200, 20", "1 2 3 4 5 6 7"]) {
    assert.deepEqual(readPasted(text), { problem: "unreadable" }, text);
  }
});

test("Google Maps links, the pin before the view", () => {
  at("https://www.google.com/maps/search/-31.591678,+-71.071358?entry=tts&g_ep=EgoyMDI2", -31.591678, -71.071358);
  at("https://www.google.com/maps/@-33.4372,-70.6506,15z?entry=ttu", -33.4372, -70.6506);
  at(
    "https://www.google.com/maps/place/Observatorio+Mamalluca/@-29.98,-70.69,15z/data=!3m1!4b1!4m6!3m5!1s0x0:0x1!8m2!3d-29.9859!4d-70.6862",
    -29.9859,
    -70.6862,
  );
  at(
    "https://www.google.com/maps/place/33%C2%B026'14.2%22S+70%C2%B039'02.1%22W/@-33.4372,-70.6506,17z/data=!3m1!4b1!4m4!3m3!8m2!3d-33.437277!4d-70.650583",
    -33.437277,
    -70.650583,
  );
  at("https://maps.google.com/?q=-33.4372,-70.6506", -33.4372, -70.6506);
  at("https://www.google.com/maps?q=loc:-33.4372,-70.6506&z=15", -33.4372, -70.6506);
  at("google.com/maps/@-33.4372,-70.6506,15z", -33.4372, -70.6506);
  // The view's longitude keeps counting past the antimeridian.
  at("https://www.google.com/maps/@-41.2,-185.3,10z", -41.2, 174.7);
  at("https://www.google.com/maps/@-41.2,534.7,10z", -41.2, 174.7);
  // A link with a latitude out of range has no position.
  assert.deepEqual(readPasted("https://www.google.com/maps/@95.2,-70.6,10z"), { problem: "noPosition" });
  assert.deepEqual(readPasted("https://www.google.com/maps/place/Mamalluca/data=!4m2!3m1!1s0x0:0x1"), {
    problem: "noPosition",
  });
  assert.deepEqual(readPasted("https://www.google.com/maps?q=Observatorio+Mamalluca&ftid=0x0:0x1"), {
    problem: "noPosition",
  });
});

test("the link in what Maps' Share gives, after the place's name", () => {
  assert.deepEqual(readPasted("Observatorio Mamalluca\nhttps://maps.app.goo.gl/AbC123xyz"), {
    short: "https://maps.app.goo.gl/AbC123xyz",
  });
  assert.deepEqual(readPasted("Dropped pin https://maps.app.goo.gl/AbC123xyz?g_st=ic"), {
    short: "https://maps.app.goo.gl/AbC123xyz?g_st=ic",
  });
  at("Dropped pin\nNear Vicuña\nhttps://www.google.com/maps/search/-30.0277,+-70.6733", -30.0277, -70.6733);
});

test("short links go to the box, only Google Maps ones", () => {
  assert.equal(shortLink("https://maps.app.goo.gl/AbC123xyz"), "https://maps.app.goo.gl/AbC123xyz");
  assert.equal(shortLink("maps.app.goo.gl/AbC123xyz"), "https://maps.app.goo.gl/AbC123xyz");
  assert.equal(shortLink(" https://goo.gl/maps/AbC123 "), "https://goo.gl/maps/AbC123");
  assert.deepEqual(readPasted("https://maps.app.goo.gl/AbC123xyz?g_st=ic"), {
    short: "https://maps.app.goo.gl/AbC123xyz?g_st=ic",
  });
  for (const text of ["https://maps.app.goo.gl/", "https://goo.gl/AbC", "https://example.com/maps.app.goo.gl/x", "-33, -70"]) {
    assert.equal(shortLink(text), null, text);
  }
});
