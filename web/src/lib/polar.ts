// Polar alignment in words and numbers for the #/polar screen (ADR 0034). The
// server measures the axis; this module turns its error into what to do with
// each knob, places it on the target, and suggests where to start.

export interface AxisError {
  altitude: number; // arcminutes, positive: the axis points above the pole
  azimuth: number; // arcminutes on the sky, positive: east of the pole
  total: number;
}

export type AltitudeAdvice = "raise" | "lower" | "ok";
export type AzimuthAdvice = "east" | "west" | "ok";

export interface KnobAdvice {
  altitude: AltitudeAdvice;
  azimuth: AzimuthAdvice;
  altitudeBy: number; // arcminutes to turn, positive
  azimuthBy: number;
}

// What to do with each knob to bring the axis onto the pole. A knob is done
// within tolerance/√2, so both done means the total is within the tolerance.
export function advice(error: AxisError, tolerance: number): KnobAdvice {
  const enough = tolerance / Math.SQRT2;
  return {
    altitude: Math.abs(error.altitude) <= enough ? "ok" : error.altitude > 0 ? "lower" : "raise",
    azimuth: Math.abs(error.azimuth) <= enough ? "ok" : error.azimuth > 0 ? "west" : "east",
    altitudeBy: Math.abs(error.altitude),
    azimuthBy: Math.abs(error.azimuth),
  };
}

// An angle given in arcminutes, as people read it: whole degrees and tenths
// from a degree up, whole arcminutes from 10′, tenths below that, and
// arcseconds under one arcminute.
export function angleParts(arcminutes: number): { value: number; unit: "°" | "′" | "″"; digits: number } {
  const a = Math.abs(arcminutes);
  if (a >= 60) return { value: a / 60, unit: "°", digits: 1 };
  if (a >= 9.95) return { value: a, unit: "′", digits: 0 };
  if (a >= 0.995) return { value: a, unit: "′", digits: 1 };
  return { value: a * 60, unit: "″", digits: 0 };
}

// Radius of the target's outer ring, in arcminutes: the first of these that
// leaves room around every error shown.
const OUTER = [5, 15, 30, 60, 180, 300, 600];

export function outerRing(errors: readonly number[], tolerance: number): number {
  const largest = Math.max(tolerance * 3, ...errors) * 1.15;
  return OUTER.find((ring) => ring >= largest) ?? Math.ceil(largest / 60) * 60;
}

// Rings drawn inside the outer one (arcminutes), the tolerance first.
export function rings(outer: number, tolerance: number): number[] {
  return [tolerance, ...[5, 15, 30, 60, 180].filter((r) => r > tolerance * 1.5 && r < outer * 0.8), outer];
}

// Distance from the centre of the target, 0..1 for 0..outer: logarithmic, so
// both a 3° error and the last arcminute have room.
export function radius(arcminutes: number, outer: number, tolerance: number): number {
  const scale = tolerance / 2;
  return Math.min(1, Math.log1p(Math.abs(arcminutes) / scale) / Math.log1p(outer / scale));
}

// Where an error sits on the target, as x right and y up in -1..1. The target
// is seen from behind the mount, facing the pole: east is to the right in the
// north and to the left in the south.
export function place(error: AxisError, outer: number, tolerance: number, latitude: number): { x: number; y: number } {
  const total = Math.hypot(error.altitude, error.azimuth);
  if (total === 0) return { x: 0, y: 0 };
  const r = radius(total, outer, tolerance);
  const east = latitude >= 0 ? 1 : -1;
  return { x: (r * east * error.azimuth) / total, y: (r * error.altitude) / total };
}

// Greenwich mean sidereal time, hours (good to a second this century).
export function siderealTime(when: Date, longitude: number): number {
  const days = when.getTime() / 86_400_000 + 2_440_587.5 - 2_451_545.0;
  const gmst = 18.697374558 + 24.06570982441908 * days;
  return (((gmst + longitude / 15) % 24) + 24) % 24;
}

// Hour angle of a JNow right ascension, -12..12 h, west positive.
export function hourAngle(ra: number, when: Date, longitude: number): number {
  return ((((siderealTime(when, longitude) - ra + 12) % 24) + 24) % 24) - 12;
}

export const START_HOUR_ANGLE = -0.5;

// The suggested start (JNow): halfway between the zenith and the pole, half
// an hour east of the meridian. The frames read both knobs best near the
// meridian, and off it the mount is on the side the turns away from it keep.
export function suggestedStart(latitude: number, longitude: number, when: Date): { ra: number; dec: number } {
  const pole = latitude >= 0 ? 90 : -90;
  const ra = (((siderealTime(when, longitude) - START_HOUR_ANGLE) % 24) + 24) % 24;
  return { ra, dec: (latitude + pole) / 2 };
}
