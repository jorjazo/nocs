<script lang="ts">
  // The guiding graph: how far the star was from the lock position at each
  // step, RA solid and Dec dashed (series differ in line style, not only in
  // color: docs/ux.md §3), in arcseconds or guide pixels. Dithers are vertical
  // dashed lines, frames without the star are rings on the axis, and steps
  // taken while settling are paler.
  import { formatDecimal } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { GuideEntry } from "../../lib/types";

  let {
    entries,
    scale,
    units,
    count = 100,
  }: {
    entries: GuideEntry[];
    // Arcseconds per guide pixel; null shows pixels whatever `units` says.
    scale: number | null;
    units: "arcsec" | "px";
    // Most recent entries shown.
    count?: number;
  } = $props();

  const WIDTH = 320;
  const HEIGHT = 180;
  const LEFT = 30;
  const RIGHT = 8;
  const TOP = 18;
  const BOTTOM = 10;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const shown = $derived(entries.slice(-count));
  const factor = $derived(units === "arcsec" && scale ? scale : 1);
  const steps = $derived(shown.filter((e) => e.kind === "step"));
  // The scale follows the steady steps once there are some: the large ones
  // while settling (after starting or a dither) would flatten everything else.
  const scaled = $derived.by(() => {
    const steady = steps.filter((e) => !e.settling);
    return steady.length >= 5 ? steady : steps;
  });
  // Symmetric around zero; at least ±2″ (or ±1 px) so a quiet run looks quiet.
  const limit = $derived.by(() => {
    const floor = factor === 1 ? 1 : 2;
    const peak = Math.max(0, ...scaled.flatMap((e) => [Math.abs(e.ra ?? 0), Math.abs(e.dec ?? 0)])) * factor;
    return niceCeiling(Math.max(floor, peak * 1.1));
  });

  function niceCeiling(value: number): number {
    const magnitude = 10 ** Math.floor(Math.log10(value));
    const step = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= value) ?? 10;
    return step * magnitude;
  }

  function x(index: number): number {
    const span = Math.max(1, count - 1);
    return LEFT + (index / span) * (WIDTH - LEFT - RIGHT);
  }

  function y(value: number): number {
    const clamped = Math.max(-limit, Math.min(limit, value * factor));
    return TOP + ((limit - clamped) / (2 * limit)) * (HEIGHT - TOP - BOTTOM);
  }

  // One path per axis, broken where a dither or a lost frame interrupts it.
  function path(axis: "ra" | "dec", settling: boolean): string {
    let d = "";
    let pen = false;
    shown.forEach((entry, index) => {
      const value = entry[axis];
      if (entry.kind !== "step" || value === null || entry.settling !== settling) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(index).toFixed(1)} ${y(value).toFixed(1)}`;
      pen = true;
    });
    return d;
  }

  const ticks = $derived([limit, limit / 2, 0, -limit / 2, -limit]);
  const unit = $derived(factor === 1 ? t.guiding.pixels : t.guiding.arcsec);
</script>

<figure class="graph">
  <svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label={t.guiding.graph(steps.length)}>
    {#each ticks as tick (tick)}
      <line class="grid" class:zero={tick === 0} x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick / factor)} y2={y(tick / factor)} />
      <text class="tick" x={LEFT - 4} y={y(tick / factor) + 3} text-anchor="end">
        {tick === 0 ? "0" : formatDecimal(tick, locale, limit < 5 ? 1 : 0)}
      </text>
    {/each}
    <text class="tick unit" x={LEFT - 4} y={TOP - 9} text-anchor="end">{unit}</text>
    {#each shown as entry, index (entry.seq)}
      {#if entry.kind === "dither"}
        <line class="dither" x1={x(index)} x2={x(index)} y1={TOP} y2={HEIGHT - BOTTOM} />
      {:else if entry.kind === "lost"}
        <circle class="lost" cx={x(index)} cy={y(0)} r="2.5" />
      {/if}
    {/each}
    <path class="ra settling" d={path("ra", true)} />
    <path class="dec settling" d={path("dec", true)} />
    <path class="ra" d={path("ra", false)} />
    <path class="dec" d={path("dec", false)} />
  </svg>
  <figcaption class="legend caption">
    <span class="key ra-key"><span class="swatch"></span>{t.guiding.ra}</span>
    <span class="key dec-key"><span class="swatch"></span>{t.guiding.dec}</span>
  </figcaption>
</figure>

<style>
  .graph {
    margin: 0;
    padding: var(--space-2) var(--space-2) var(--space-1);
    border: 1px solid var(--line);
    border-radius: var(--radius-card);
    background: var(--surface);
  }
  svg {
    display: block;
    width: 100%;
    height: auto;
    max-height: 40dvh;
  }
  .grid {
    stroke: var(--line);
    stroke-width: 1;
  }
  .grid.zero {
    stroke: var(--muted);
  }
  .tick {
    fill: var(--muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .ra,
  .dec {
    fill: none;
    stroke-width: 1.6;
    stroke-linejoin: round;
  }
  .ra {
    stroke: var(--guide-ra);
  }
  .dec {
    stroke: var(--guide-dec);
    stroke-dasharray: 4 3;
  }
  .settling {
    opacity: 0.4;
  }
  .dither {
    stroke: var(--muted);
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }
  .lost {
    fill: none;
    stroke: var(--error);
    stroke-width: 1.5;
  }
  .legend {
    display: flex;
    gap: var(--space-4);
    padding: var(--space-1) var(--space-2) 0;
    color: var(--muted);
  }
  .key {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .swatch {
    width: 18px;
    height: 0;
    border-top: 2px solid var(--guide-ra);
  }
  .dec-key .swatch {
    border-top: 2px dashed var(--guide-dec);
  }
</style>
