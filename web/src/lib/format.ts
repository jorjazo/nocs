// Formatting of INDI numbers according to their printf-style format, including
// the INDI-specific sexagesimal "%<w>.<p>m" form (e.g. %010.6m -> hh:mm:ss.s).

const FORMAT = /%[-+ 0#]*(\d*)(?:\.(\d+))?([a-zA-Z])/;

function sexagesimal(value: number, precision: number): string {
  const sign = value < 0 ? "-" : "";
  let rest = Math.abs(value);
  const fractionDigits = { 9: 3, 8: 2, 6: 1 }[precision] ?? 0;
  const withSeconds = precision >= 5;
  const scale = withSeconds ? 3600 * 10 ** fractionDigits : 60;
  rest = Math.round(rest * scale) / scale;
  const degrees = Math.floor(rest);
  const minutesTotal = (rest - degrees) * 60;
  if (!withSeconds) {
    return `${sign}${degrees}:${String(Math.round(minutesTotal)).padStart(2, "0")}`;
  }
  const minutes = Math.floor(minutesTotal + 1e-9);
  const seconds = (minutesTotal - minutes) * 60;
  const secondsText = seconds.toFixed(fractionDigits).padStart(fractionDigits ? fractionDigits + 3 : 2, "0");
  return `${sign}${degrees}:${String(minutes).padStart(2, "0")}:${secondsText}`;
}

export function formatNumber(value: number, format = "%g"): string {
  const match = FORMAT.exec(format);
  if (!match) return String(value);
  const precision = match[2] === undefined ? undefined : Number(match[2]);
  switch (match[3]) {
    case "m":
      return sexagesimal(value, precision ?? 6);
    case "f":
      return value.toFixed(precision ?? 6);
    case "e":
      return value.toExponential(precision ?? 6);
    case "d":
    case "i":
      return Math.round(value).toString();
    default:
      return Number(value.toPrecision(precision || 6)).toString();
  }
}

// Locale-aware formatting for the interface (INDI's own formats stay above).

const MINUS = "−";

export function formatDecimal(value: number, locale: string, digits = 1): string {
  const text = new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
  return text.replace("-", MINUS);
}

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"] as const;

// Decimal units, as drives are sold: 1 TB = 10^12 bytes.
export function formatBytes(bytes: number, locale: string): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: BYTE_UNITS[unit],
    maximumFractionDigits: value < 10 && unit > 0 ? 1 : 0,
  }).format(value);
}

export function formatDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function formatTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { timeStyle: "short" }).format(new Date(iso));
}

// Plain numbers in the interface (gain, offset, ranges), without grouping.
export function formatPlain(value: number, locale: string, maxDigits = 3): string {
  const text = new Intl.NumberFormat(locale, { maximumFractionDigits: maxDigits, useGrouping: false }).format(value);
  return text.replace("-", MINUS);
}

// Exposure times as typed: "0.5 s", "120 s", never "120.0 s".
export function formatSeconds(seconds: number, locale: string): string {
  return `${formatPlain(seconds, locale)} s`;
}

export function formatTemperature(celsius: number, locale: string, digits = 1): string {
  return `${formatDecimal(celsius, locale, digits)} °C`;
}

// How far apart two clocks are, roughly: "45 s", "3 min", "2 h 5 min", "3 d 4 h".
export function formatDuration(seconds: number): string {
  const s = Math.round(Math.abs(seconds));
  if (s < 60) return `${s} s`;
  const minutes = Math.floor(s / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `${days} d ${hours % 24} h` : `${days} d`;
}

// Numbers typed by hand, with either decimal separator; null if not a number.
export function parseNumber(text: string): number | null {
  const cleaned = text.trim().replace(",", ".").replace(MINUS, "-");
  if (cleaned === "") return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}
