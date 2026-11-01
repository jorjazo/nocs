// The night as the Tonight and Plan screens draw it: bands of daylight and
// twilight from the Sun's altitude, the Moon's phase, and where an instant
// falls on the night's time axis. Pure functions, tested with `pnpm test`.

export type Light = "day" | "civil" | "nautical" | "astronomical" | "dark";

export interface Band {
  light: Light;
  // Milliseconds since the epoch.
  start: number;
  end: number;
}

// The Sun's (geometric) altitude in degrees, by the usual twilight limits.
export function light(sunAltitude: number): Light {
  if (sunAltitude >= -0.833) return "day";
  if (sunAltitude >= -6) return "civil";
  if (sunAltitude >= -12) return "nautical";
  if (sunAltitude >= -18) return "astronomical";
  return "dark";
}

// Runs of samples with the same light. Each sample stands for the time up to
// halfway to its neighbours, so bands meet without gaps.
export function bands(times: readonly string[], sunAltitude: readonly number[]): Band[] {
  const ms = times.map((time) => Date.parse(time));
  const result: Band[] = [];
  ms.forEach((t, i) => {
    const before = ms[i - 1];
    const after = ms[i + 1];
    const start = before === undefined ? t : (before + t) / 2;
    const end = after === undefined ? t : (t + after) / 2;
    const kind = light(sunAltitude[i] ?? 0);
    const last = result.at(-1);
    if (last && last.light === kind) last.end = end;
    else result.push({ light: kind, start, end });
  });
  return result.filter((band) => band.end > band.start);
}

// Where `time` falls between `start` and `end`, 0..1; null outside.
export function position(time: number, start: number, end: number): number | null {
  if (end <= start || time < start || time > end) return null;
  return (time - start) / (end - start);
}

export type Phase = "new" | "waxingCrescent" | "firstQuarter" | "waxingGibbous" | "full" | "waningGibbous" | "lastQuarter" | "waningCrescent";

// The Moon's phase angle (0 new, 90 first quarter, 180 full, 270 last quarter)
// by name: the four principal phases take the 45° around them.
export function phase(angle: number): Phase {
  const names: Phase[] = ["new", "waxingCrescent", "firstQuarter", "waxingGibbous", "full", "waningGibbous", "lastQuarter", "waningCrescent"];
  const a = ((angle % 360) + 360) % 360;
  return names[Math.floor((a + 22.5) / 45) % 8] ?? "new";
}

// The sample nearest to `time` (null outside the samples' span).
export function nearest(times: readonly string[], time: number): number | null {
  const first = times[0];
  const last = times.at(-1);
  if (first === undefined || last === undefined) return null;
  if (time < Date.parse(first) || time > Date.parse(last)) return null;
  let best = 0;
  let distance = Infinity;
  times.forEach((t, i) => {
    const d = Math.abs(Date.parse(t) - time);
    if (d < distance) {
      distance = d;
      best = i;
    }
  });
  return best;
}
