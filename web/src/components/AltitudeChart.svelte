<script lang="ts">
  // A target's altitude through the night (stage 3.6): twilight shades behind,
  // the site's horizon profile under the target as a filled ground, the minimum
  // altitude dashed, the Moon faint, and a line at now.
  import { i18n } from "../lib/i18n";
  import { bands } from "../lib/sky/night";

  let {
    times,
    sunAltitude,
    altitude,
    horizon,
    moon = null,
    minAltitude,
    now,
  }: {
    times: string[];
    sunAltitude: number[];
    altitude: number[];
    // The horizon's altitude under the target at each time.
    horizon: number[];
    moon?: number[] | null;
    minAltitude: number;
    now: number;
  } = $props();

  const HEIGHT = 180;
  const LEFT = 30;
  const BOTTOM = 20;
  const TOP = 6;
  const RIGHT = 6;

  const locale = $derived(i18n.locale);
  let width = $state(320);
  const ms = $derived(times.map((time) => Date.parse(time)));
  const start = $derived(ms[0] ?? 0);
  const end = $derived(ms.at(-1) ?? 0);
  const x = (time: number) => LEFT + ((time - start) / Math.max(1, end - start)) * (width - LEFT - RIGHT);
  const y = (degrees: number) => TOP + (1 - Math.max(0, Math.min(90, degrees)) / 90) * (HEIGHT - TOP - BOTTOM);
  const base = $derived(y(0));

  const shades = $derived(bands(times, sunAltitude));
  const ground = $derived(
    `M${x(start)},${base} ` + ms.map((t, i) => `L${x(t)},${y(horizon[i] ?? 0)}`).join(" ") + ` L${x(end)},${base} Z`,
  );
  // A line broken where it is below the horizon line (0°).
  function path(values: number[]): string {
    let d = "";
    let drawing = false;
    values.forEach((v, i) => {
      if (v < 0) {
        drawing = false;
        return;
      }
      d += `${drawing ? "L" : "M"}${x(ms[i] ?? start).toFixed(1)},${y(v).toFixed(1)} `;
      drawing = true;
    });
    return d;
  }
  const target = $derived(path(altitude));
  const moonPath = $derived(moon ? path(moon) : "");
  const nowX = $derived(now >= start && now <= end ? x(now) : null);
  // Every other whole hour along the bottom.
  const hours = $derived.by(() => {
    const result: { x: number; label: string }[] = [];
    const first = new Date(start);
    first.setMinutes(0, 0, 0);
    const format = new Intl.DateTimeFormat(locale, { hour: "numeric" });
    for (let t = first.getTime() + 3600_000; t < end; t += 3600_000) {
      if (new Date(t).getHours() % 2 === 0) result.push({ x: x(t), label: format.format(t) });
    }
    return result;
  });
</script>

<div class="chart" bind:clientWidth={width}>
  <svg viewBox="0 0 {width} {HEIGHT}" width={width} height={HEIGHT} role="img" aria-label={i18n.t.plan.altitudeLabel}>
    {#each shades as band (band.start)}
      <rect class="band {band.light}" x={x(band.start)} y={TOP} width={Math.max(0, x(band.end) - x(band.start))} height={base - TOP} />
    {/each}
    {#each [30, 60, 90] as degrees (degrees)}
      <line class="grid" x1={LEFT} x2={width - RIGHT} y1={y(degrees)} y2={y(degrees)} />
      <text class="axis" x={LEFT - 4} y={y(degrees) + 4} text-anchor="end">{degrees}°</text>
    {/each}
    <path class="ground" d={ground} />
    <line class="minimum" x1={LEFT} x2={width - RIGHT} y1={y(minAltitude)} y2={y(minAltitude)} />
    {#if moonPath}<path class="moon" d={moonPath} />{/if}
    <path class="target" d={target} />
    <line class="base" x1={LEFT} x2={width - RIGHT} y1={base} y2={base} />
    {#each hours as hour (hour.x)}
      <text class="axis" x={hour.x} y={HEIGHT - 4} text-anchor="middle">{hour.label}</text>
    {/each}
    {#if nowX !== null}<line class="now" x1={nowX} x2={nowX} y1={TOP} y2={base} />{/if}
  </svg>
</div>

<style>
  .chart {
    width: 100%;
  }
  svg {
    display: block;
  }
  .band {
    fill: var(--accent);
  }
  .day {
    opacity: 0.4;
  }
  .civil {
    opacity: 0.26;
  }
  .nautical {
    opacity: 0.14;
  }
  .astronomical {
    opacity: 0.06;
  }
  .dark {
    opacity: 0;
  }
  .grid {
    stroke: var(--line);
    stroke-width: 1;
  }
  .axis {
    fill: var(--muted);
    font-size: 11px;
    font-family: var(--font-mono);
  }
  .ground {
    fill: var(--muted);
    opacity: 0.28;
  }
  .minimum {
    stroke: var(--warning);
    stroke-width: 1;
    stroke-dasharray: 4 4;
  }
  .moon {
    fill: none;
    stroke: var(--muted);
    stroke-width: 1.5;
    stroke-dasharray: 2 3;
  }
  .target {
    fill: none;
    stroke: var(--accent);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
  .base {
    stroke: var(--line);
  }
  .now {
    stroke: var(--text);
    stroke-width: 1.5;
  }
</style>
