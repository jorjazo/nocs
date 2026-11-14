// A first autofocus step when neither the profile nor an earlier run has one
// (ADR 0021). Focusers do not report their steps' size, so this assumes a full
// travel of 50 mm, and asks the ends of a 9-point sweep (±4 steps) for a blur
// circle of ~100 µm, which takes 100 µm × f-ratio of defocus: 25 µm × f-ratio a
// step. The lab's EAF on f/4.7 gets 110 steps against the 100 that work there; a
// first run then suggests a better one.

const TRAVEL_UM = 50_000;
const UM_PER_FOCAL_RATIO = 25;

export function estimateStep(maxPosition: number | null, focalRatio: number | null): number | null {
  if (!maxPosition || maxPosition <= 0 || !focalRatio || focalRatio <= 0) return null;
  const steps = (UM_PER_FOCAL_RATIO * focalRatio) / (TRAVEL_UM / maxPosition);
  return roundStep(steps);
}

// One or two significant figures: 112 → 110, 3456 → 3500, 7.4 → 7.
export function roundStep(steps: number): number {
  if (steps < 1) return 1;
  const magnitude = 10 ** Math.max(0, Math.floor(Math.log10(steps)) - 1);
  return Math.round(steps / magnitude) * magnitude;
}

// The focuser's calibration (ADR 0044) counts for the profile it was measured with:
// the same focuser on another scope or camera is asked to calibrate again.
export function calibratedFor(
  calibration: { profile: string | null } | null | undefined,
  profile: string | null | undefined,
): boolean {
  return !!calibration && !!profile && calibration.profile === profile;
}

// How far apart a calibration's measurements of one reversal are, in steps.
export function spread(values: readonly number[]): number {
  return values.length < 2 ? 0 : Math.max(...values) - Math.min(...values);
}

// Measurements that disagree by more than a few of the smallest significant steps
// (and by more than a tenth of the backlash): the backlash is not steady.
export function unsteady(values: readonly number[], minStep: number): boolean {
  const largest = Math.max(0, ...values);
  return spread(values) > Math.max(3 * minStep, 0.1 * largest);
}
