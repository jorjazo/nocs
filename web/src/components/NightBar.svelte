<script lang="ts">
  // The night from sunset to sunrise as one bar: daylight and the three
  // twilights shade it, the dark window is the bar's own black, the Moon's time
  // above the horizon runs under it, and a line marks now.
  import { formatTime } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { bands, position } from "../lib/sky/night";
  import type { Almanac } from "../lib/types";

  let { almanac, now }: { almanac: Almanac; now: number } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const start = $derived(Date.parse(almanac.start));
  const end = $derived(Date.parse(almanac.end));
  const span = $derived(Math.max(1, end - start));
  const shades = $derived(bands(almanac.times, almanac.sun_altitude));
  const moon = $derived(
    almanac.moon.up.map((i) => ({
      left: Math.max(0, (Date.parse(i.start) - start) / span),
      right: Math.min(1, (Date.parse(i.end) - start) / span),
    })),
  );
  const at = $derived(position(now, start, end));
  const pct = (fraction: number) => `${(fraction * 100).toFixed(2)}%`;

  // Labels under the bar: sunset, the dark window, sunrise.
  const marks = $derived(
    [
      { time: almanac.sunset, label: t.tonight.sunset },
      { time: almanac.dark?.start ?? null, label: t.tonight.darkFrom },
      { time: almanac.dark?.end ?? null, label: t.tonight.darkUntil },
      { time: almanac.sunrise, label: t.tonight.sunrise },
    ].filter((m): m is { time: string; label: string } => m.time !== null),
  );
</script>

<div class="night" role="img" aria-label={t.tonight.barLabel}>
  <div class="bar">
    {#each shades as band (band.start)}
      <span
        class="band {band.light}"
        style:left={pct((band.start - start) / span)}
        style:width={pct((band.end - band.start) / span)}></span>
    {/each}
    {#if at !== null}<span class="now" style:left={pct(at)}></span>{/if}
  </div>
  <div class="moon" aria-hidden="true">
    {#each moon as up (up.left)}
      <span style:left={pct(up.left)} style:width={pct(up.right - up.left)}></span>
    {/each}
  </div>
  <div class="marks">
    {#each marks as mark (mark.label)}
      <div>
        <span class="label muted">{mark.label}</span>
        <span class="time">{formatTime(mark.time, locale)}</span>
      </div>
    {/each}
  </div>
</div>

<style>
  .night {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .bar {
    position: relative;
    height: 28px;
    border-radius: var(--radius-tile);
    border: 1px solid var(--line);
    background: var(--bg);
    overflow: hidden;
  }
  .band {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--accent);
  }
  .day {
    opacity: 0.55;
  }
  .civil {
    opacity: 0.38;
  }
  .nautical {
    opacity: 0.22;
  }
  .astronomical {
    opacity: 0.1;
  }
  .dark {
    opacity: 0;
  }
  .now {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    margin-left: -1px;
    background: var(--text);
  }
  .moon {
    position: relative;
    height: 4px;
  }
  .moon span {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: var(--radius-full);
    background: var(--muted);
  }
  .marks {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }
  .marks > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .marks > div:last-child {
    text-align: right;
  }
  .label {
    font-size: 12px;
    line-height: 16px;
  }
  .time {
    font-family: var(--font-mono);
  }
</style>
