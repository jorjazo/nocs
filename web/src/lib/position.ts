// A site's position as people paste or type it: a Google Maps link, decimal degrees
// ("-33.4372, -70.6506", what Maps copies) or degrees, minutes and seconds with or
// without a hemisphere ("33°26'14"S 70°39'02"W", "33 26.23 S", "O" for west too).
// A Google Maps short link holds no position: the box expands it (`expandMapsLink`)
// and the long link it leads to is read here.

export type Axis = "latitude" | "longitude";
export type LatLon = { latitude: number; longitude: number };

const LIMIT: Record<Axis, number> = { latitude: 90, longitude: 180 };
const HEMISPHERE: Record<string, { axis: Axis; sign: 1 | -1 }> = {
  N: { axis: "latitude", sign: 1 },
  S: { axis: "latitude", sign: -1 },
  E: { axis: "longitude", sign: 1 },
  W: { axis: "longitude", sign: -1 },
  O: { axis: "longitude", sign: -1 },
};

const NUMBER = String.raw`(\d+(?:[.,]\d+)?)`;
const DEGREES = String.raw`[°º˚]|deg`;
const MINUTES = String.raw`['′’´]`;
const SECONDS = String.raw`["″”]|''|′′|’’`;
// Degrees, then maybe minutes, then maybe seconds, each with its symbol or a space.
const ANGLE = new RegExp(
  String.raw`^([+-])?\s*${NUMBER}\s*(?:${DEGREES})?\s*(?:${NUMBER}\s*(?:${MINUTES})?\s*(?:${NUMBER}\s*(?:${SECONDS})?)?)?$`,
  "i",
);

type Angle = { value: number; axis: Axis | null };

function number(text: string | undefined): number | null {
  if (text === undefined) return null;
  const value = Number(text.replace(",", "."));
  return Number.isFinite(value) ? value : null;
}

function normalize(text: string): string {
  return text.trim().replace(/[−–—]/g, "-");
}

// One angle, signed by its hemisphere letter when it has one (which also names its
// axis), or null when it is not one.
function angle(text: string): Angle | null {
  let rest = normalize(text);
  let hemisphere: { axis: Axis; sign: 1 | -1 } | null = null;
  const leading = /^([NSEWO])\s*/i.exec(rest);
  const trailing = /\s*([NSEWO])\.?$/i.exec(rest);
  if (leading && trailing) return null;
  if (leading) {
    hemisphere = HEMISPHERE[leading[1]!.toUpperCase()] ?? null;
    rest = rest.slice(leading[0].length);
  } else if (trailing) {
    hemisphere = HEMISPHERE[trailing[1]!.toUpperCase()] ?? null;
    rest = rest.slice(0, trailing.index);
  }
  const match = ANGLE.exec(rest);
  if (!match) return null;
  const [, sign, d, m, s] = match;
  const degrees = number(d);
  const minutes = number(m);
  const seconds = number(s);
  if (degrees === null) return null;
  // Only the last part may have decimals, and minutes and seconds stay under 60.
  if (minutes !== null && (!Number.isInteger(degrees) || minutes >= 60)) return null;
  if (seconds !== null && (!Number.isInteger(minutes) || seconds >= 60)) return null;
  // A sign and a hemisphere together would say it twice, maybe differently.
  if (sign && hemisphere) return null;
  const magnitude = degrees + (minutes ?? 0) / 60 + (seconds ?? 0) / 3600;
  const signed = (sign === "-" ? -1 : 1) * (hemisphere?.sign ?? 1) * magnitude;
  return { value: signed, axis: hemisphere?.axis ?? null };
}

function within(value: number, axis: Axis): boolean {
  return Math.abs(value) <= LIMIT[axis];
}

// One latitude or longitude typed in its own field, in any of the forms above; null
// when it is not one, names the other axis (a latitude with E or W), or is out of range.
export function parseAngle(text: string, axis: Axis): number | null {
  const parsed = angle(text);
  if (parsed === null || (parsed.axis !== null && parsed.axis !== axis)) return null;
  return within(parsed.value, axis) ? parsed.value : null;
}

// A latitude and a longitude from two angles, in either order when their hemisphere
// letters say which is which.
function pair(first: Angle, second: Angle): LatLon | null {
  let [latitude, longitude] = [first, second];
  if (first.axis === "longitude" || second.axis === "latitude") [latitude, longitude] = [second, first];
  if (latitude.axis === "longitude" || longitude.axis === "latitude") return null;
  if (!within(latitude.value, "latitude") || !within(longitude.value, "longitude")) return null;
  return { latitude: latitude.value, longitude: longitude.value };
}

// Two angles in plain text: split where both halves read as angles, at a ";", a
// comma, or a space; more than one way to read it is no reading at all.
function coordinates(text: string): LatLon | null {
  const clean = normalize(text);
  const halves = clean.includes(";") ? [clean.split(";")] : splits(clean);
  const found = new Map<string, LatLon>();
  for (const parts of halves) {
    if (parts.length !== 2) continue;
    const [a, b] = parts.map((part) => angle(part.trim().replace(/^,|,$/g, "").trim()));
    const position = a && b ? pair(a, b) : null;
    if (position) found.set(`${position.latitude},${position.longitude}`, position);
  }
  return found.size === 1 ? ([...found.values()][0] ?? null) : null;
}

function splits(text: string): string[][] {
  const result: string[][] = [];
  for (const separator of text.matchAll(/,\s*|\s+/g)) {
    const at = separator.index;
    result.push([text.slice(0, at), text.slice(at + separator[0].length)]);
  }
  return result;
}

const DECIMAL = String.raw`([+-]?\d{1,3}(?:\.\d+)?)`;
// Where a Google Maps link keeps a position, most precise first: the place's own pin
// (`!3d…!4d…`), a query or search (`?q=`, `/search/`, `/place/`, `/dir/`), and last
// the centre of the view (`/@lat,lon,zoom`).
const LINK_PATTERNS = [
  new RegExp(String.raw`!3d${DECIMAL}!4d${DECIMAL}`),
  new RegExp(String.raw`[?&](?:q|query|ll|center|destination|daddr)=(?:loc:)?\s*${DECIMAL}\s*,\s*${DECIMAL}(?![\d.])`),
  new RegExp(String.raw`/(?:search|place|dir)/\s*${DECIMAL}\s*,\s*${DECIMAL}(?![\d.])`),
  new RegExp(String.raw`/@${DECIMAL},${DECIMAL}(?![\d.])`),
];

// A link pasted as text, decoded (`+` is a space in a query); null when it is not one.
function link(text: string): string | null {
  const trimmed = text.trim();
  if (!/^https?:\/\//i.test(trimmed) && !/^(?:www\.)?(?:google\.[a-z.]+\/maps|maps\.google\.|maps\.app\.goo\.gl|goo\.gl\/maps)/i.test(trimmed)) {
    return null;
  }
  let decoded = trimmed.replace(/\+/g, " ");
  for (let i = 0; i < 3; i++) {
    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) break;
      decoded = next;
    } catch {
      break;
    }
  }
  return decoded;
}

function fromLink(decoded: string): LatLon | null {
  for (const pattern of LINK_PATTERNS) {
    const match = pattern.exec(decoded);
    if (!match) continue;
    const position = pair({ value: Number(match[1]), axis: null }, { value: Number(match[2]), axis: null });
    if (position) return position;
  }
  return null;
}

// A Google Maps short link (maps.app.goo.gl, goo.gl/maps), which only the box can
// expand; the link to send it, or null.
export function shortLink(text: string): string | null {
  const trimmed = text.trim();
  const url = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    if (host === "maps.app.goo.gl" && parsed.pathname.length > 1) return parsed.href;
    if (host === "goo.gl" && parsed.pathname.startsWith("/maps/")) return parsed.href;
  } catch {
    return null;
  }
  return null;
}

export type Pasted =
  | { position: LatLon }
  // A short link the box has to expand first.
  | { short: string }
  // A link with no position in it (a place by its name only).
  | { problem: "noPosition" }
  | { problem: "unreadable" };

// What was pasted: a position, a short link to expand, or why it is neither.
export function readPasted(text: string): Pasted {
  if (text.trim() === "") return { problem: "unreadable" };
  const short = shortLink(text);
  if (short !== null) return { short };
  const decoded = link(text);
  if (decoded !== null) {
    const position = fromLink(decoded);
    return position ? { position } : { problem: "noPosition" };
  }
  const position = coordinates(text);
  return position ? { position } : { problem: "unreadable" };
}
