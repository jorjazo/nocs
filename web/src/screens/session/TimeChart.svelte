<script lang="ts" module>
  export type Series = {
    label: string;
    // Seconds since the epoch, and the value.
    points: { t: number; v: number; title?: string }[];
    // Series differ in mark and line style, not only in color (docs/ux.md §3).
    style: "dots" | "solid" | "dashed";
  };
</script>

<script lang="ts">
  // A small chart of values over a session's time: one axis, dots for frames,
  // lines for samples, dashed verticals for events (autofocus runs). Each dot
  // and marker has a native tooltip; the report's tables carry the same data.
  import { formatDecimal, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";

  let {
    label,
    unit,
    series,
    markers = [],
    start,
    end,
    digits = 1,
  }: {
    label: string;
    unit: string;
    series: Series[];
    markers?: { t: number; title: string }[];
    start: number;
    end: number;
    digits?: number;
  } = $props();

  const WIDTH = 320;
  const HEIGHT = 140;
  const LEFT = 34;
  const RIGHT = 8;
  const TOP = 22;
  const BOTTOM = 18;

  const locale = $derived(i18n.locale);
  const values = $derived(series.flatMap((s) => s.points.map((p) => p.v)));
  const range = $derived.by(() => {
    if (!values.length) return { low: 0, high: 1 };
    let low = Math.min(...values);
    let high = Math.max(...values);
    const pad = (high - low) * 0.1 || Math.abs(high) * 0.1 || 1;
    low -= pad;
    high += pad;
    return { low, high };
  });
  const ticks = $derived.by(() => {
    const { low, high } = range;
    return [low, (low + high) / 2, high].map((v) => Number(v.toFixed(digits)));
  });
  const span = $derived(Math.max(1, end - start));

  function x(t: number): number {
    return LEFT + ((t - start) / span) * (WIDTH - LEFT - RIGHT);
  }
  function y(v: number): number {
    const { low, high } = range;
    return HEIGHT - BOTTOM - ((v - low) / (high - low)) * (HEIGHT - TOP - BOTTOM);
  }
  function line(points: Series["points"]): string {
    return points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  }
  const time = (t: number) => formatTime(new Date(t * 1000).toISOString(), locale);
</script>

<figure class="chart">
  <svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label={label}>
    {#each ticks as tick (tick)}
      <line class="grid" x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} />
      <text class="tick" x={LEFT - 4} y={y(tick) + 3} text-anchor="end">{formatDecimal(tick, locale, digits)}</text>
    {/each}
    <text class="tick" x={LEFT - 4} y={TOP - 3} text-anchor="end">{unit}</text>
    <text class="tick" x={LEFT} y={HEIGHT - 4}>{time(start)}</text>
    <text class="tick" x={WIDTH - RIGHT} y={HEIGHT - 4} text-anchor="end">{time(end)}</text>
    {#each markers as marker, i (i)}
      <line class="marker" x1={x(marker.t)} x2={x(marker.t)} y1={TOP} y2={HEIGHT - BOTTOM}><title>{marker.title}</title></line>
    {/each}
    {#each series as s (s.label)}
      {#if s.style === "dots"}
        {#each s.points as p, i (i)}
          <circle class="dot" cx={x(p.t)} cy={y(p.v)} r="4"><title>{p.title ?? formatDecimal(p.v, locale, digits)}</title></circle>
        {/each}
      {:else}
        <path class="line {s.style}" d={line(s.points)} />
      {/if}
    {/each}
  </svg>
  {#if series.length > 1}
    <figcaption class="legend">
      {#each series as s (s.label)}
        <span class="key"><span class="swatch {s.style}"></span>{s.label}</span>
      {/each}
    </figcaption>
  {/if}
</figure>

<style>
  .chart {
    max-width: 640px;
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
  }
  .grid {
    stroke: var(--line);
    stroke-width: 1;
  }
  .tick {
    fill: var(--muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .marker {
    stroke: var(--muted);
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }
  .dot {
    fill: var(--accent);
    stroke: var(--surface);
    stroke-width: 2;
  }
  .line {
    fill: none;
    stroke: var(--accent);
    stroke-width: 2;
    stroke-linejoin: round;
  }
  .line.dashed {
    stroke: var(--muted);
    stroke-dasharray: 5 3;
  }
  .legend {
    display: flex;
    gap: var(--space-4);
    padding: var(--space-1) var(--space-2) 0;
    color: var(--muted);
    font-size: 12px;
  }
  .key {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .swatch {
    width: 16px;
    border-top: 2px solid var(--accent);
  }
  .swatch.dashed {
    border-top: 2px dashed var(--muted);
  }
</style>
