// Catalog objects in words: the name to show (in this language) and a line of
// what they are (type, constellation, magnitude, size).

import { formatDecimal } from "./format";
import type { Messages } from "./i18n";
import type { CatalogObject } from "./types";

// Its common names in this language, falling back to English.
export function commonNames(object: CatalogObject, locale: string): string[] {
  return locale === "es" && object.names_es.length ? object.names_es : object.names;
}

// "NGC 292 · Small Magellanic Cloud", or the label alone.
export function objectName(object: CatalogObject, locale: string): string {
  const name = commonNames(object, locale)[0];
  return name ? `${object.label} · ${name}` : object.label;
}

// Arcminutes across, as "12′" or "12′ × 5′".
export function objectSize(object: CatalogObject, locale: string): string | null {
  const major = object.major_axis;
  if (major === null) return null;
  const minor = object.minor_axis;
  const text = (value: number) => `${formatDecimal(value, locale, value < 10 ? 1 : 0)}′`;
  return minor !== null && minor !== major ? `${text(major)} × ${text(minor)}` : text(major);
}

// "Galaxy · Tuc · mag 2.3 · 320′ × 185′".
export function objectSummary(object: CatalogObject, t: Messages, locale: string): string {
  const parts = [t.targetTypes[object.type]];
  if (object.constellation) parts.push(object.constellation);
  if (object.magnitude !== null) parts.push(t.plan.magnitude(formatDecimal(object.magnitude, locale, 1)));
  const size = objectSize(object, locale);
  if (size) parts.push(size);
  return parts.join(" · ");
}
