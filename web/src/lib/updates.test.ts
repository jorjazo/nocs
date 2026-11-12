import assert from "node:assert/strict";
import { test } from "node:test";
import type { UpgradablePackage } from "./types.ts";
import { installedCount, isToday, shortVersion, summarize, versions } from "./updates.ts";

function pkg(name: string, kind: UpgradablePackage["kind"], from: string, to: string, extra: Partial<UpgradablePackage> = {}): UpgradablePackage {
  return { name, kind, from, to, security: false, reboot: false, ...extra };
}

// As the rc4 box listed them, cut down.
const listed: UpgradablePackage[] = [
  pkg("libc6", "system", "2.43-2ubuntu2.3", "2.43-2ubuntu2.4", { security: true }),
  pkg("indi-3rdparty-drivers", "indi", "2.2.0+202610040550~ubuntu26.04.1", "2.2.1+202611010550~ubuntu26.04.1"),
  pkg("nocs-appliance", "nocs", "0.1.0~rc4", "0.1.0"),
  pkg("linux-image-raspi", "system", "7.0.0-1017.17", "7.0.0-1023.23", { security: true, reboot: true }),
  pkg("indi-bin", "indi", "2.2.5+202610040455~ubuntu26.04.1", "2.2.6+202611010455~ubuntu26.04.1"),
  pkg("apt", "system", "3.2.0", "3.2.1ubuntu0.1"),
  pkg("nocs", "nocs", "0.1.0~rc4", "0.1.0"),
  pkg("phd2", "phd2", "2.6.14.rev20251216-0ppa1~ubuntu26.04", "2.6.14.rev20260301-0ppa1~ubuntu26.04"),
  pkg("libindi1", "indi", "2.2.5+202610040455~ubuntu26.04.1", "2.2.6+202611010455~ubuntu26.04.1"),
];

test("NOCS first, then INDI and PHD2 by their main package, then the system as counts", () => {
  const summary = summarize(listed);
  assert.equal(summary.total, 9);
  assert.equal(summary.nocs?.name, "nocs");
  assert.deepEqual(summary.components, [
    { kind: "indi", from: "2.2.5", to: "2.2.6", count: 3 },
    { kind: "phd2", from: "2.6.14.rev20251216", to: "2.6.14.rev20260301", count: 1 },
  ]);
  assert.deepEqual(summary.system, { count: 3, security: 2 });
  assert.equal(summary.reboot, true);
  assert.deepEqual(
    summary.groups.map((g) => [g.kind, g.packages.map((p) => p.name)]),
    [
      ["nocs", ["nocs", "nocs-appliance"]],
      ["indi", ["indi-3rdparty-drivers", "indi-bin", "libindi1"]],
      ["phd2", ["phd2"]],
      ["system", ["apt", "libc6", "linux-image-raspi"]],
    ],
  );
});

test("only system updates: no NOCS, no components, no restart", () => {
  const summary = summarize([pkg("curl", "system", "8.18.0-1ubuntu2.4", "8.18.0-1ubuntu2.8", { security: true })]);
  assert.equal(summary.nocs, null);
  assert.deepEqual(summary.components, []);
  assert.deepEqual(summary.system, { count: 1, security: 1 });
  assert.equal(summary.reboot, false);
  assert.deepEqual(summarize([]).groups, []);
});

test("INDI named by any of its packages when indi-bin has no update", () => {
  const summary = summarize([pkg("indi-3rdparty-drivers", "indi", "2.2.0+2026", "2.2.1+2026")]);
  assert.deepEqual(summary.components, [{ kind: "indi", from: "2.2.0", to: "2.2.1", count: 1 }]);
});

test("versions as people know them, whole when shortening hides the change", () => {
  assert.equal(shortVersion("2.2.5+202610040455~ubuntu26.04.1"), "2.2.5");
  assert.equal(shortVersion("1:9.20.24-1ubuntu0.5"), "9.20.24");
  assert.equal(shortVersion("0.1.0~rc4"), "0.1.0~rc4");
  assert.deepEqual(versions("2.2.5+2026a", "2.2.5+2026b"), ["2.2.5+2026a", "2.2.5+2026b"]);
});

test("a check today shows its time only", () => {
  const now = new Date(2026, 10, 12, 22, 0);
  assert.equal(isToday(new Date(2026, 10, 12, 10, 48).toISOString(), now), true);
  assert.equal(isToday(new Date(2026, 10, 11, 23, 59).toISOString(), now), false);
});

test("what apt still lists was not installed", () => {
  const kept = pkg("apt", "system", "3.2.0", "3.2.1ubuntu0.1");
  assert.equal(installedCount(listed, [kept]), listed.length - 1);
  // apt's lists refreshed between the check and the install: still not installed.
  assert.equal(installedCount(listed, [{ ...kept, to: "3.2.2" }]), listed.length - 1);
  assert.equal(installedCount(listed, []), listed.length);
});
