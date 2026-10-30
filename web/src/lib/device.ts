// A name for this device to suggest when pairing, e.g. "Firefox on Android".

import type { Messages } from "./i18n";

const SYSTEMS: [RegExp, string][] = [
  [/iPhone/, "iPhone"],
  [/iPad/, "iPad"],
  [/Android/, "Android"],
  [/CrOS/, "ChromeOS"],
  [/Mac OS X|Macintosh/, "macOS"],
  [/Windows/, "Windows"],
  [/Linux/, "Linux"],
];

// Order matters: Edge and Samsung Internet also say Chrome, Chrome says Safari.
const BROWSERS: [RegExp, string][] = [
  [/Edg\//, "Edge"],
  [/SamsungBrowser\//, "Samsung Internet"],
  [/Firefox\/|FxiOS\//, "Firefox"],
  [/Chrome\/|CriOS\//, "Chrome"],
  [/Safari\//, "Safari"],
];

function find(table: [RegExp, string][], agent: string): string | null {
  return table.find(([pattern]) => pattern.test(agent))?.[1] ?? null;
}

export function suggestDeviceName(t: Messages): string {
  const agent = navigator.userAgent;
  const system = find(SYSTEMS, agent);
  const browser = find(BROWSERS, agent);
  if (system && browser) return t.device.suggestion(browser, system);
  return system ?? browser ?? t.device.fallback;
}
