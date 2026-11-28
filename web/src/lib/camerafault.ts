// The camera link popup: which jobs just failed because the camera sent no image, and
// what the Raspberry Pi's USB power says about it.

import type { Messages } from "./i18n/en";
import type { JobInfo, UsbPower } from "./types";

type Jobs = Record<string, JobInfo> | null | undefined;

// Jobs that were running in `before` and failed with the camera link fault in `after`:
// failures found already over when the page loads are old news.
export function newCameraFaults(before: Jobs, after: Jobs): string[] {
  if (!before || !after) return [];
  return Object.entries(after)
    .filter(([id, job]) => job.state === "failed" && job.fault === "camera_link" && before[id]?.state === "running")
    .map(([id]) => id);
}

function milliamps(value: number, locale: string): string {
  return value >= 1000 && value % 100 === 0
    ? `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value / 1000)} A`
    : `${new Intl.NumberFormat(locale).format(value)} mA`;
}

// What connecting found on the Pi's limited USB ports, as one sentence.
export function usbPowerText(power: UsbPower, t: Messages, locale: string): string {
  const limit = milliamps(power.limit, locale);
  const supply = power.supply === null ? null : milliamps(power.supply, locale);
  if (power.cameras.length > 0) {
    const cameras = new Intl.ListFormat(locale, { type: "conjunction" }).format(power.cameras);
    return t.usbPower.cameras(limit, supply, cameras);
  }
  return t.usbPower.draw(limit, supply, milliamps(power.draw, locale));
}

// The likely causes, the Pi's limited ports first when they power something at risk.
export function cameraLinkCauses(power: UsbPower | null | undefined, t: Messages, locale: string): string[] {
  const causes = [t.cameraLink.hub, t.cameraLink.cable, t.cameraLink.supply];
  return power ? [t.cameraLink.limited(milliamps(power.limit, locale)), ...causes] : causes;
}
