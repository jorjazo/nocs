import assert from "node:assert/strict";
import { test } from "node:test";
import { formatTime, hourOf, nextWholeHour, setTimeZone, timeZone } from "./format.ts";

test("times show in the site's time zone, else the browser's", () => {
  try {
    setTimeZone("America/Santiago");
    assert.equal(timeZone(), "America/Santiago");
    // UTC−3 in November (summer time).
    assert.equal(formatTime("2026-11-16T03:00:00Z", "en-GB"), "00:00");
    assert.equal(hourOf(Date.parse("2026-11-16T03:00:00Z")), 0);
    assert.equal(nextWholeHour(Date.parse("2026-11-16T03:10:00Z")), Date.parse("2026-11-16T04:00:00Z"));
    // Kolkata is UTC+5:30: its hours start at half past the UTC hour.
    setTimeZone("Asia/Kolkata");
    assert.equal(nextWholeHour(Date.parse("2026-11-16T03:10:00Z")), Date.parse("2026-11-16T03:30:00Z"));
    assert.equal(hourOf(Date.parse("2026-11-16T03:30:00Z")), 9);
    setTimeZone("Mars/Olympus_Mons");
    assert.equal(timeZone(), undefined);
    setTimeZone(null);
    assert.equal(timeZone(), undefined);
  } finally {
    setTimeZone(null);
  }
});
