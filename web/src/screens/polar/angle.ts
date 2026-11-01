import { formatDecimal } from "../../lib/format";
import { angleParts } from "../../lib/polar";

// An error in arcminutes, unsigned, in the unit that fits (12′, 4.3′, 36″, 1.2°).
export function formatAngle(arcminutes: number, locale: string): string {
  const { value, unit, digits } = angleParts(arcminutes);
  return `${formatDecimal(value, locale, digits)}${unit}`;
}
