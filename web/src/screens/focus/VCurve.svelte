<script lang="ts">
  // The V-curve of an autofocus run: each point's HFR against the focuser
  // position, the fitted hyperbola once the run has one, where the focuser is
  // now (dotted) and the best focus (dashed). Points without enough stars sit
  // on the axis as rings. Series differ in shape and line style, not only in
  // color (docs/ux.md §3).
  import { formatDecimal, formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { AutofocusFit, AutofocusPoint } from "../../lib/types";

  let {
    points,
    fit,
    position,
    best,
    expected = null,
  }: {
    points: AutofocusPoint[];
    fit: AutofocusFit | null;
    // Where the focuser is now; null to leave it out.
    position: number | null;
    best: number | null;
    // Positions the sweep is about to cover, so the axis does not jump while
    // the first points arrive.
    expected?: [number, number] | null;
  } = $props();

  const WIDTH = 320;
  const HEIGHT = 200;
  const LEFT = 30;
  const RIGHT = 8;
  const TOP = 14;
  const BOTTOM = 22;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const measured = $derived(points.filter((p) => p.hfr !== null));
  const domain = $derived.by((): [number, number] => {
    const xs = [...points.map((p) => p.position), ...(best !== null ? [best] : [])];
    if (position !== null) xs.push(position);
    if (expected) xs.push(...expected);
    if (xs.length === 0) return [0, 1];
    let low = Math.min(...xs);
    let high = Math.max(...xs);
    if (high - low < 1) {
      low -= 50;
      high += 50;
    }
    const margin = (high - low) * 0.06;
    return [low - margin, high + margin];
  });
  const top = $derived.by(() => {
    const highest = Math.max(1, ...measured.map((p) => p.hfr ?? 0));
    return niceCeiling(highest * 1.1);
  });
  const ticks = $derived([0, top / 2, top]);

  function niceCeiling(value: number): number {
    const magnitude = 10 ** Math.floor(Math.log10(value));
    const step = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= value) ?? 10;
    return step * magnitude;
  }

  function x(steps: number): number {
    const [low, high] = domain;
    return LEFT + ((steps - low) / (high - low)) * (WIDTH - LEFT - RIGHT);
  }

  function y(hfr: number): number {
    return HEIGHT - BOTTOM - (Math.min(hfr, top) / top) * (HEIGHT - TOP - BOTTOM);
  }

  const curve = $derived.by(() => {
    if (!fit) return "";
    const [low, high] = domain;
    const samples = 64;
    const parts: string[] = [];
    for (let i = 0; i <= samples; i++) {
      const steps = low + ((high - low) * i) / samples;
      const hfr = fit.a * Math.sqrt(1 + ((steps - fit.c) / fit.b) ** 2);
      parts.push(`${x(steps).toFixed(1)} ${y(hfr).toFixed(1)}`);
    }
    return `M${parts.join("L")}`;
  });

  const label = $derived(
    t.autofocus.chart(points.length) + (best !== null ? t.autofocus.chartFit(formatPlain(best, locale)) : ""),
  );
</script>

<figure class="vcurve">
  <svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label={label}>
    <defs>
      <clipPath id="vcurve-plot">
        <rect x={LEFT} y={TOP} width={WIDTH - LEFT - RIGHT} height={HEIGHT - TOP - BOTTOM} />
      </clipPath>
    </defs>
    {#each ticks as tick (tick)}
      <line class="grid" x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} />
      <text class="tick" x={LEFT - 4} y={y(tick) + 3} text-anchor="end">{formatDecimal(tick, locale, 1)}</text>
    {/each}
    <text class="tick" x={LEFT} y={HEIGHT - 6}>{formatPlain(Math.round(domain[0]), locale)}</text>
    <text class="tick" x={WIDTH - RIGHT} y={HEIGHT - 6} text-anchor="end">
      {formatPlain(Math.round(domain[1]), locale)}
    </text>

    {#if curve}<path class="fit" d={curve} clip-path="url(#vcurve-plot)" />{/if}
    {#if best !== null}
      <line class="best" x1={x(best)} x2={x(best)} y1={TOP} y2={HEIGHT - BOTTOM} />
    {/if}
    {#if position !== null}
      <line class="now" x1={x(position)} x2={x(position)} y1={TOP} y2={HEIGHT - BOTTOM} />
    {/if}
    {#each points as point (point.position)}
      {#if point.hfr === null}
        <circle class="empty" cx={x(point.position)} cy={HEIGHT - BOTTOM} r="3.5" />
      {:else}
        <circle class="point" cx={x(point.position)} cy={y(point.hfr)} r="4" />
      {/if}
    {/each}
  </svg>
</figure>

<style>
  .vcurve {
    margin: 0;
    padding: var(--space-2) var(--space-2) 0;
    border: 1px solid var(--line);
    border-radius: var(--radius-card);
    background: var(--surface);
  }
  svg {
    display: block;
    width: 100%;
    height: auto;
    max-height: 46dvh;
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
  .fit {
    fill: none;
    stroke: var(--muted);
    stroke-width: 1.5;
  }
  .best {
    stroke: var(--ok);
    stroke-width: 1.5;
    stroke-dasharray: 6 4;
  }
  .now {
    stroke: var(--accent);
    stroke-width: 1.5;
    stroke-dasharray: 2 3;
  }
  .point {
    fill: var(--accent);
    stroke: var(--surface);
    stroke-width: 1.5;
  }
  .empty {
    fill: none;
    stroke: var(--muted);
    stroke-width: 1.5;
  }
</style>
